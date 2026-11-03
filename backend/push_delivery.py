"""Local-first outbox, bounded retries, verified receipts and immutable batch history."""
import json,sqlite3,time,uuid,threading
from pathlib import Path
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from contextlib import closing

def stamp():return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
def dump(x):return json.dumps(x,ensure_ascii=False)
def schema(c):
    cols={r[1] for r in c.execute('PRAGMA table_info(result_pushes)')}
    for k,definition in [('payload_json',"TEXT NOT NULL DEFAULT ''"),('phase',"TEXT NOT NULL DEFAULT ''"),('attempts','INTEGER NOT NULL DEFAULT 0'),('next_retry_at','REAL NOT NULL DEFAULT 0'),('verified_at','REAL NOT NULL DEFAULT 0')]:
        if k not in cols:c.execute('ALTER TABLE result_pushes ADD COLUMN '+k+' '+definition)
    c.executescript('''CREATE TABLE IF NOT EXISTS push_batches(id TEXT PRIMARY KEY,target_path TEXT,created_at TEXT,total INTEGER,origin TEXT);
      CREATE TABLE IF NOT EXISTS push_batch_items(batch_id TEXT,ordinal INTEGER,result_id INTEGER,content_hash TEXT,delivery_id TEXT,blocked_reason TEXT DEFAULT '',PRIMARY KEY(batch_id,ordinal));
      CREATE TABLE IF NOT EXISTS push_events(id INTEGER PRIMARY KEY,batch_id TEXT,delivery_id TEXT,action TEXT,message TEXT,created_at TEXT);
      CREATE TABLE IF NOT EXISTS push_meta(key TEXT PRIMARY KEY,value TEXT);
      CREATE INDEX IF NOT EXISTS idx_push_due ON result_pushes(state,phase,next_retry_at);
      CREATE INDEX IF NOT EXISTS idx_push_batch_receipt ON push_batch_items(delivery_id);''')
    if not c.execute("SELECT 1 FROM push_meta WHERE key='legacy_history_v1'").fetchone():
        groups={}
        for r in c.execute('SELECT * FROM result_pushes ORDER BY updated_at,result_id'):
            groups.setdefault((r['target_path'],r['updated_at']),[]).append(dict(r))
        for (target,created),rows in groups.items():
            bid='legacy_'+uuid.uuid5(uuid.NAMESPACE_URL,target+created).hex[:16]
            c.execute('INSERT OR IGNORE INTO push_batches VALUES(?,?,?,?,?)',(bid,target,created,len(rows),'历史回执（时间为最近回执更新时间）'))
            c.executemany('INSERT OR IGNORE INTO push_batch_items VALUES(?,?,?,?,?,?)',[(bid,i,r['result_id'],r['content_hash'],r['delivery_id'],'') for i,r in enumerate(rows)])
        c.execute("INSERT INTO push_meta VALUES('legacy_history_v1','1')")

def event(c,bid,delivery,action,message):c.execute('INSERT INTO push_events(batch_id,delivery_id,action,message,created_at) VALUES(?,?,?,?,?)',(bid,delivery,action,message,stamp()))

def receipt_rows(c,bid=None):
    if bid:return [dict(r) for r in c.execute('SELECT DISTINCT p.* FROM result_pushes p JOIN push_batch_items i ON i.delivery_id=p.delivery_id WHERE i.batch_id=?',(bid,))]
    return [dict(r) for r in c.execute("SELECT * FROM result_pushes WHERE state IN ('pending','failed') AND phase IN ('queued','waiting','retry_wait')")]

def queue(p,entries,blocked=(),origin='手动推送'):
    bid='push_'+uuid.uuid4().hex[:12];target=str(p.db.resolve())
    with p.store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('INSERT INTO push_batches VALUES(?,?,?,?,?)',(bid,target,stamp(),len(entries)+len(blocked),origin))
        for i,(rid,hashed,payload) in enumerate(entries):
            old=c.execute('SELECT * FROM result_pushes WHERE result_id=? AND target_path=? AND content_hash=?',(rid,target,hashed)).fetchone()
            delivery=old['delivery_id'] if old else str(uuid.uuid5(uuid.NAMESPACE_URL,str(p.store.db.resolve())+':'+target+':'+str(rid)+':'+hashed))
            payload=dict(payload,uuid=delivery)
            if old and old['payload_json']:payload=json.loads(old['payload_json'])
            c.execute('''INSERT INTO result_pushes(result_id,target_path,content_hash,delivery_id,title,article,category,updated_at,payload_json,phase,next_retry_at)
              VALUES(?,?,?,?,?,?,?,?,?,'queued',0) ON CONFLICT(result_id,target_path,content_hash) DO UPDATE SET
              payload_json=excluded.payload_json,state=CASE WHEN result_pushes.state='pushed' THEN 'pushed' ELSE 'pending' END,
              phase=CASE WHEN result_pushes.state='pushed' THEN 'verified' ELSE 'queued' END,error='',attempts=0,next_retry_at=0''',
              (rid,target,hashed,delivery,payload['title'],payload['body'],payload.get('source_category',payload['category']),stamp(),dump(payload)))
            c.execute('INSERT INTO push_batch_items VALUES(?,?,?,?,?,?)',(bid,i,rid,hashed,delivery,''))
        for i,item in enumerate(blocked,len(entries)):c.execute('INSERT INTO push_batch_items VALUES(?,?,?,?,?,?)',(bid,i,item['result_id'],'','',item['reason']))
        event(c,bid,'','queued',f'本地已保存{len(entries)}条待投递快照，{len(blocked)}条不符合推送规则；目标：{target}')
    return bid

def running_for(p,db):
    if p._running_override is not None:return p._running_override()
    from push_targets import running_factories
    found=running_factories(db.parent)
    matched=[r for r in found if Path(r['db']).resolve()==db.resolve()]
    if found and not matched:raise ValueError('目标库与当前运行的生图软件不一致；请绑定正确目标，或将此批补发到当前目标')
    if len(matched)>1:raise ValueError('同一标题库有多个生图窗口，暂缓投递以免缓存互相覆盖')
    return bool(matched)

def reconcile(p,check_all=False):
    with p.store.connect() as c:
        rows=[dict(r) for r in c.execute('SELECT * FROM result_pushes WHERE target_path=?'+('' if check_all else " AND state='pending'"),(str(p.db.resolve()),))]
    if not rows or not p.db.is_file():return
    target=None
    try:
        target=sqlite3.connect(p.db.resolve().as_uri()+'?mode=ro',uri=True,timeout=.3);target.row_factory=sqlite3.Row
        inbox=bool(target.execute("SELECT 1 FROM sqlite_master WHERE name='comic_article_inbox'").fetchone())
        for r in rows:
            ack=target.execute('SELECT state,target_key,error FROM comic_article_inbox WHERE delivery_id=?',(r['delivery_id'],)).fetchone() if inbox else None
            if not ack:continue
            if ack['state']=='failed':
                with p.store.connect() as c:c.execute("UPDATE result_pushes SET state='failed',phase='retry_wait',error=? WHERE delivery_id=?",(ack['error'] or '接收端报告失败',r['delivery_id']))
                continue
            if ack['state']!='pushed':continue
            saved=target.execute("SELECT payload FROM app_collections WHERE namespace='title_library' AND item_key=?",(ack['target_key'],)).fetchone()
            expected=json.loads(r['payload_json']) if r['payload_json'] else None
            if expected is None:
                original=target.execute('SELECT payload FROM comic_article_inbox WHERE delivery_id=?',(r['delivery_id'],)).fetchone();expected=json.loads(original[0]) if original else None
            value=json.loads(saved[0]) if saved else None
            good=bool(value and expected and all(str(value.get(k,'')).strip()==str(expected.get(k,'')).strip() for k in ('title','body','category')))
            if good and r['state']=='pushed' and r['phase']=='verified' and r['verified_at'] and r['payload_json'] and r['target_key']==ack['target_key']:continue
            with p.store.connect() as c:
                if good:
                    c.execute("UPDATE result_pushes SET state='pushed',phase='verified',target_key=?,error='',verified_at=?,payload_json=CASE WHEN payload_json='' THEN ? ELSE payload_json END WHERE delivery_id=?",(ack['target_key'],time.time(),dump(expected),r['delivery_id']))
                    if r['state']!='pushed' or not r['verified_at']:event(c,'',r['delivery_id'],'verified','接收回执及目标标题、正文、分类均已核对')
                else:
                    c.execute("UPDATE result_pushes SET state='failed',phase='missing',error=? WHERE delivery_id=?",('有接收回执，但目标标题已缺失或内容不一致；不会静默重新创建，请手动核对/重试',r['delivery_id']))
    except (sqlite3.Error,OSError,ValueError) as exc:
        p.last_error='回执核对暂缓：'+str(exc)
    finally:
        if target:target.close()

def dispatch(p,bid=None):
    with p.store.connect() as c:rows=receipt_rows(c,bid)
    due=[r for r in rows if r['state']!='pushed' and r['phase'] in ('queued','waiting','retry_wait') and r['next_retry_at']<=time.time()]
    groups={}
    for r in due:groups.setdefault(r['target_path'],[]).append(r)
    for path,items in groups.items():
        db=Path(path);target=None
        try:
            from push_targets import check_db
            check_db(db);is_running=running_for(p,db)
            target=sqlite3.connect(db,timeout=.5)
            from title_push import INBOX_SQL,resolve_record
            target.execute(INBOX_SQL);target.commit()
            for r in items[:500]:
                if r['attempts']>=3:
                    with p.store.connect() as c:c.execute("UPDATE result_pushes SET state='failed',phase='failed',error=CASE WHEN error='' THEN '三次投递后仍未收到有效入库回执，请检查接收端并手动重试' ELSE error END WHERE delivery_id=?",(r['delivery_id'],))
                    continue
                if not r['payload_json']:
                    with p.store.connect() as c:c.execute("UPDATE result_pushes SET state='failed',phase='failed',error='历史回执缺少投递快照，请从推送记录补发或重新选择文章' WHERE delivery_id=?",(r['delivery_id'],))
                    continue
                payload=json.loads(r['payload_json']);attempt=r['attempts']+1
                with p.store.connect() as c:
                    c.execute("UPDATE result_pushes SET attempts=?,state='pending',phase='waiting',next_retry_at=?,error='' WHERE delivery_id=?",(attempt,time.time()+[20,60,180][attempt-1],r['delivery_id']))
                    event(c,bid or '',r['delivery_id'],'dispatch',f'第{attempt}次投递；'+('等待在线软件合并内存并回执' if is_running else '目标未运行，事务入库后核对'))
                with target:
                    target.execute('INSERT OR IGNORE INTO comic_article_inbox(delivery_id,payload,created_at) VALUES(?,?,?)',(r['delivery_id'],dump(payload),time.time()))
                    ack=target.execute('SELECT state,target_key FROM comic_article_inbox WHERE delivery_id=?',(r['delivery_id'],)).fetchone()
                    if ack and ack[0]=='pushed':
                        saved=target.execute("SELECT payload FROM app_collections WHERE namespace='title_library' AND item_key=?",(ack[1],)).fetchone()
                        if not saved or not all(json.loads(saved[0]).get(k)==payload[k] for k in ('title','body','category')):target.execute("UPDATE comic_article_inbox SET state='pending',target_key='',error='' WHERE delivery_id=?",(r['delivery_id'],))
                    else:target.execute("UPDATE comic_article_inbox SET state='pending',error='' WHERE delivery_id=?",(r['delivery_id'],))
                    if not is_running:
                        key,_=resolve_record(target,payload)
                        target.execute("UPDATE comic_article_inbox SET state='pushed',target_key=?,error='',completed_at=? WHERE delivery_id=?",(key,time.time(),r['delivery_id']))
        except (sqlite3.Error,OSError,ValueError) as exc:
            p.last_error=str(exc)
            with p.store.connect() as c:
                for r in items:
                    attempts=r['attempts']+1
                    c.execute("UPDATE result_pushes SET state='failed',phase=?,attempts=?,next_retry_at=?,error=? WHERE delivery_id=?",('failed' if attempts>=3 else 'retry_wait',attempts,time.time()+[5,15,60][min(attempts-1,2)],str(exc),r['delivery_id']))
                event(c,bid or '','','error',str(exc))
        finally:
            if target:target.close()
    reconcile(p)

def detail(p,bid):
    with p.store.connect() as c:
        batch=c.execute('SELECT * FROM push_batches WHERE id=?',(bid,)).fetchone()
        if not batch:raise ValueError('推送批次不存在')
        rows=[dict(r) for r in c.execute("SELECT i.result_id,i.delivery_id,i.blocked_reason,p.title,p.state,p.phase,p.error,p.attempts,p.verified_at,p.target_key,p.payload_json FROM push_batch_items i LEFT JOIN result_pushes p ON p.delivery_id=i.delivery_id WHERE i.batch_id=? ORDER BY i.ordinal",(bid,))]
        for r in rows:
            payload=json.loads(r.pop('payload_json') or '{}');r['target_category']=payload.get('category','');r['state']='blocked' if r['blocked_reason'] else r['state'];r['error']=r['blocked_reason'] or r['error'] or ''
        counts=dict(Counter(r['state'] for r in rows))
        events=[dict(r) for r in c.execute('SELECT action,message,created_at FROM push_events WHERE batch_id=? OR delivery_id IN (SELECT delivery_id FROM push_batch_items WHERE batch_id=?) ORDER BY id DESC LIMIT 100',(bid,bid))]
        return {'batch':dict(batch),'rows':rows,'counts':counts,'events':events}

def response(p,bid):
    d=detail(p,bid);counts=d['counts']
    return {'ok':True,'batch_id':bid,'target':d['batch']['target_path'],'pushed':counts.get('pushed',0),'pending':counts.get('pending',0),'failed':counts.get('failed',0),'blocked':counts.get('blocked',0),'blocked_rows':[{'result_id':r['result_id'],'reason':r['error']} for r in d['rows'] if r['state']=='blocked'],'rows':d['rows']}

def history(p,q):
    page=max(1,int(q.get('page',1)));size=20
    with p.store.connect() as c:
        total=c.execute('SELECT count(*) FROM push_batches').fetchone()[0];bids=[r[0] for r in c.execute('SELECT id FROM push_batches ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',(size,(page-1)*size))]
    rows=[]
    for bid in bids:
        d=detail(p,bid);rows.append(dict(d['batch'],counts=d['counts']))
    return {'rows':rows,'total':total,'page':page,'size':size,'last_error':p.last_error}

def retry(p,bid=None):
    p.refresh_project()
    with p.store.connect() as c:
        rows=receipt_rows(c,bid) if bid else [dict(r) for r in c.execute("SELECT * FROM result_pushes WHERE target_path=? AND state IN ('pending','failed')",(str(p.db.resolve()),))]
        ids=[r['delivery_id'] for r in rows if r['state'] in ('pending','failed') and Path(r['target_path']).resolve()==p.db.resolve()]
        for delivery in ids:c.execute("UPDATE result_pushes SET state='pending',phase='queued',attempts=0,next_retry_at=0,error='' WHERE delivery_id=?",(delivery,))
        event(c,bid or '','','manual_retry',f'手动重试{len(ids)}条，保持原标题、正文、分类快照')
    dispatch(p,bid)
    return response(p,bid) if bid else {'ok':True,'retried':len(ids)}

def replay(p,bid):
    p.refresh_project();d=detail(p,bid);entries=[]
    with p.store.connect() as c:
        for item in d['rows']:
            if item['state']=='blocked':continue
            r=c.execute('SELECT * FROM result_pushes WHERE delivery_id=?',(item['delivery_id'],)).fetchone()
            if not r:raise ValueError('历史投递记录已缺失')
            payload=json.loads(r['payload_json']) if r['payload_json'] else None
            if not payload:
                db=Path(d['batch']['target_path'])
                with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=1)) as target:
                    old=target.execute('SELECT payload FROM comic_article_inbox WHERE delivery_id=?',(r['delivery_id'],)).fetchone();payload=json.loads(old[0]) if old else None
            if not payload:raise ValueError('历史快照缺失，未执行部分补发')
            entries.append((r['result_id'],r['content_hash'],payload))
    new=queue(p,entries,origin='补发历史批次 '+bid);dispatch(p,new)
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        reconcile(p);r=response(p,new)
        if not r['pending']:return r
        time.sleep(.15)
    return response(p,new)

def start(p):
    p.stop=threading.Event()
    def run():
        last_full=0
        while not p.stop.wait(3):
            try:
                with p.lock:
                    p.refresh_project();full=time.monotonic()-last_full>30;reconcile(p,full)
                    if full:last_full=time.monotonic()
                    dispatch(p)
            except Exception as exc:p.last_error=str(exc)
    p.thread=threading.Thread(target=run,daemon=True,name='push-outbox');p.thread.start()
