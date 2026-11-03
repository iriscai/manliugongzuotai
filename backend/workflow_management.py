"""Result versions, precise selection and recoverable editorial operations."""
import hashlib
import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from article_flow import normalize_article
from writing_prompts import POLICY_VERSION
from title_push import decorate,signature,PROJECT

def stamp():return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
def dump(value):return json.dumps(value,ensure_ascii=False)
def rule_hash(content,category,variant,requirements=''):
    from paragraph_policy import POLICY as FUNNY_POLICY
    policy=FUNNY_POLICY if category=='搞笑' else POLICY_VERSION
    return hashlib.sha256(dump([policy,content,category,variant,requirements]).encode('utf8')).hexdigest()

def install_schema(c):
    columns={r[1] for r in c.execute('PRAGMA table_info(results)')}
    for name,definition in [('rule_hash',"TEXT NOT NULL DEFAULT ''"),('rule_revision','INTEGER NOT NULL DEFAULT 0'),('write_variant',"TEXT NOT NULL DEFAULT ''"),('batch_id',"TEXT NOT NULL DEFAULT ''"),('writing_policy',"TEXT NOT NULL DEFAULT ''"),('edited_at',"TEXT NOT NULL DEFAULT ''")]:
        if name not in columns:c.execute('ALTER TABLE results ADD COLUMN '+name+' '+definition)
    c.executescript('''
      CREATE TABLE IF NOT EXISTS result_versions(id INTEGER PRIMARY KEY,batch_id TEXT NOT NULL,result_id INTEGER NOT NULL,extraction_id INTEGER NOT NULL,material_id INTEGER NOT NULL,category TEXT,title TEXT,article TEXT,payload_json TEXT NOT NULL,archived_at TEXT NOT NULL,UNIQUE(batch_id,result_id));
      CREATE INDEX IF NOT EXISTS idx_versions_result ON result_versions(result_id,id DESC);
      CREATE INDEX IF NOT EXISTS idx_results_batch ON results(batch_id,created_at);
      CREATE INDEX IF NOT EXISTS idx_results_rule ON results(rule_hash,current);
    ''')
    vcols={r[1] for r in c.execute('PRAGMA table_info(result_versions)')}
    if 'reason' not in vcols:c.execute("ALTER TABLE result_versions ADD COLUMN reason TEXT NOT NULL DEFAULT '历史留存'")
    # Only new columns are backfilled; existing articles, flags and push receipts stay intact.
    c.execute("""UPDATE results SET write_variant=coalesce(json_extract(data_json,'$.write_variant'),''),
      batch_id=coalesce(json_extract(data_json,'$.run_id'),json_extract(data_json,'$.regeneration_batch'),''),
      writing_policy=coalesce(json_extract(data_json,'$.writing_policy'),'') WHERE write_variant=''""")
    for row in c.execute("SELECT * FROM results WHERE rule_hash='' AND write_variant<>''").fetchall():
        evidence=c.execute("SELECT w.run_id,j.snapshot_json FROM run_writes w JOIN runs j ON j.id=w.run_id WHERE w.extraction_id=? AND w.state='completed' AND w.updated_at=?",(row['extraction_id'],row['created_at'])).fetchall()
        if len(evidence)!=1:continue
        snapshot=json.loads(evidence[0]['snapshot_json'])
        if snapshot.get('writing_policy')!=POLICY_VERSION:continue
        try:metadata=rule_metadata(snapshot,row['category'],row['write_variant'])
        except (KeyError,StopIteration):continue
        c.execute('UPDATE results SET rule_hash=?,rule_revision=?,writing_policy=? WHERE id=?',(metadata['rule_hash'],metadata['rule_revision'],metadata['writing_policy'],row['id']))

def archive(c,row,reason,batch=None):
    row=dict(row);batch=batch or ('version_'+uuid.uuid4().hex[:12])
    c.execute('INSERT INTO result_versions(batch_id,result_id,extraction_id,material_id,category,title,article,payload_json,archived_at,reason) VALUES(?,?,?,?,?,?,?,?,?,?)',
      (batch,row['id'],row['extraction_id'],row['material_id'],row['category'],row['title'],row.get('article') or row['short_text'],dump(row),stamp(),reason))

def rule_metadata(snapshot,category,variant):
    p=next(p for p in snapshot['prompts'] if p['category']==category and p['kind']=='write' and p['variant']==variant)
    from paragraph_policy import POLICY as FUNNY_POLICY
    return {'rule_hash':rule_hash(p['content'],category,variant,snapshot['settings'].get('requirements','')),'rule_revision':p['revision'],'write_variant':variant,'writing_policy':FUNNY_POLICY if category=='搞笑' else POLICY_VERSION}

def save_generated(c,result,eid,mid,rid,count,images,snapshot,variant):
    if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
    from data_integrity import validate_source,allocate
    validate_source(c,mid,result['source_hash'],eid)
    old=c.execute('SELECT * FROM results WHERE extraction_id=?',(eid,)).fetchone()
    if old and old['deleted_at']:raise ValueError('文章已删除，请先恢复文章再重新生成')
    metadata=rule_metadata(snapshot,result['category'],variant)
    result.update(metadata,run_id=rid)
    if old:
        if eid not in snapshot.get('regenerate_seed_ids',[]):return False
        attempt=c.execute('SELECT base_revision FROM run_writes WHERE run_id=? AND extraction_id=?',(rid,eid)).fetchone()
        if attempt and attempt['base_revision'] and attempt['base_revision']!=old['content_revision']:
            raise ValueError('文章已被其他任务或手动编辑更新，旧任务结果不会覆盖新版；请重新选择文章生成')
        archive(c,old,'按最新规则重新生成',rid)
        c.execute("""UPDATE results SET title=?,short_text=?,article=?,data_json=?,char_count=?,frame_count=?,current=1,state='成品',
          created_at=?,cleared_at='',rule_hash=?,rule_revision=?,write_variant=?,batch_id=?,writing_policy=?,edited_at='',content_revision=content_revision+1 WHERE id=?""",
          (result['title'],result['short_text'],result.get('article',result['short_text']),dump(result),count,images,stamp(),metadata['rule_hash'],metadata['rule_revision'],variant,rid,POLICY_VERSION,old['id']))
    else:
        c.execute('''INSERT INTO results(id,extraction_id,material_id,category,title,short_text,article,data_json,char_count,frame_count,state,created_at,rule_hash,rule_revision,write_variant,batch_id,writing_policy)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(allocate(c,'results'),eid,mid,result['category'],result['title'],result['short_text'],result.get('article',result['short_text']),dump(result),count,images,'成品',stamp(),metadata['rule_hash'],metadata['rule_revision'],variant,rid,POLICY_VERSION))
    from article_quality import after_generated
    after_generated(c,eid,result)
    return True

def _bounds(query,key,low,high,default):
    value=int(query.get(key,default))
    if not low<=value<=high:raise ValueError(key+'超出范围')
    return value

def query_parts(store,q):
    where=['r.current=1'];args=[]
    visibility=q.get('visibility','active')
    if visibility not in ('active','cleared','all','deleted'):raise ValueError('未知归档筛选')
    where.append("r.deleted_at"+("<>''" if visibility=='deleted' else "=''") )
    if visibility not in ('all','deleted'):where.append("r.cleared_at"+("<>''" if visibility=='cleared' else "=''") )
    if q.get('material_id'):
        from usability import integer
        where.append('r.material_id=?');args.append(integer(q['material_id'],1,10**12,'素材编号'))
    if q.get('category'):where.append('r.category=?');args.append(q['category'])
    if q.get('q'):
        where.append('(r.title LIKE ? OR r.article LIKE ? OR m.title LIKE ?)');args.extend(['%'+q['q']+'%']*3)
    if q.get('batch'):where.append('r.batch_id=?');args.append(q['batch'])
    for key,op in [('date_from','>='),('date_to','<=')]:
        if q.get(key):
            datetime.strptime(q[key],'%Y-%m-%d');where.append('substr(r.created_at,1,10)'+op+'?');args.append(q[key])
    rule=q.get('rule','');requirements=store.settings().get('requirements','')
    if rule=='unknown':where.append("r.rule_hash=''")
    elif rule in ('current','outdated'):
        where.append("r.rule_hash<>'' AND r.rule_hash "+('=' if rule=='current' else '<>')+" rule_fingerprint(p.content,r.category,r.write_variant,?)");args.append(requirements)
    elif rule:raise ValueError('未知规则版本筛选')
    push=q.get('push','')
    if push:
        if push not in ('not_pushed','pushed','pending','failed'):raise ValueError('未知推送状态')
        receipt="SELECT 1 FROM result_pushes ps WHERE ps.result_id=r.id AND ps.target_path=? AND ps.content_hash=result_delivery_signature(r.category,r.title,coalesce(nullif(r.article,''),r.short_text),r.score,r.score_status,r.score_content_hash)"
        if push=='not_pushed':where.append('NOT EXISTS('+receipt+')');args.append(str(__import__('push_targets').project_for(store)/'picfactory_matrix.db'))
        else:where.append('EXISTS('+receipt+' AND ps.state=?)');args.extend([str(__import__('push_targets').project_for(store)/'picfactory_matrix.db'),push])
    if q.get('score_band'):
        band=q['score_band']
        if band=='default':where.append("r.category<>'搞笑'")
        elif band=='pending':where.append("r.category='搞笑' AND (r.score_status<>'scored' OR r.score_content_hash<>result_signature(r.category,r.title,r.article))")
        elif band in ('excellent','good','low'):
            where.append("r.category='搞笑' AND r.score_status='scored' AND r.score_content_hash=result_signature(r.category,r.title,r.article)")
            where.append({'excellent':'r.score>=90','good':'r.score BETWEEN 80 AND 89','low':'r.score<80'}[band])
        else:raise ValueError('未知评分筛选')
    join=" FROM results r LEFT JOIN materials m ON m.id=r.material_id LEFT JOIN prompts p ON p.category=r.category AND p.kind='write' AND p.variant=r.write_variant WHERE "+' AND '.join(where)
    return join,args

def list_results(store,q):
    page=_bounds(q,'page',1,1000000,1);size=_bounds(q,'size',1,100,30)
    sort={'newest':'r.created_at DESC,r.id DESC','oldest':'r.created_at ASC,r.id ASC','id':'r.id DESC','title':'r.title,r.id DESC','score':'r.score DESC,r.id DESC'}.get(q.get('sort','newest'))
    if not sort:raise ValueError('未知排序字段')
    join,args=query_parts(store,q);requirements=store.settings().get('requirements','')
    category_join,category_args=query_parts(store,{k:v for k,v in q.items() if k!='category'})
    with store.connect() as c:
        categories=[dict(r) for r in c.execute('SELECT r.category,count(*) count'+category_join+' GROUP BY r.category ORDER BY count DESC,r.category',category_args)]
        total=c.execute('SELECT count(*)'+join,args).fetchone()[0]
        pages=max(1,(total+size-1)//size);page=min(page,pages)
        rows=[dict(r) for r in c.execute('SELECT r.*,m.title original_title,p.content active_rule,p.revision active_revision'+join+' ORDER BY '+sort+' LIMIT ? OFFSET ?',args+[size,(page-1)*size])]
        for r in rows:
            content=r.pop('active_rule');expected=rule_hash(content,r['category'],r['write_variant'],requirements) if content else ''
            r['rule_status']='unknown' if not r['rule_hash'] else 'current' if r['rule_hash']==expected else 'outdated'
            r['paragraph_count']=len([x for x in (r['article'] or r['short_text']).splitlines() if x.strip()]);r['title_chars']=len(r['title'])
        decorate(c,rows)
        from article_quality import decorate as quality_decorate
        routing=store.settings();quality_decorate(rows,routing.get('push_category_map',{}),routing.get('push_score_rules'))
        from result_cleanup import clearable_count
        return {'rows':rows,'total':total,'page':page,'size':size,'cleanup_supported':True,'clearable_count':clearable_count(c),'categories':categories}

def options(store):
    with store.connect() as c:
        return {'batches':[dict(r) for r in c.execute("SELECT batch_id,COUNT(*) count,MAX(created_at) created_at FROM results WHERE batch_id<>'' GROUP BY batch_id ORDER BY created_at DESC LIMIT 200")],
          'cleared':c.execute("SELECT count(*) FROM results WHERE current=1 AND deleted_at=\'\' AND cleared_at<>''").fetchone()[0]}

def selected_ids(store,payload):
    if payload.get('all_filtered'):
        join,args=query_parts(store,payload.get('filters',{}))
        with store.connect() as c:ids=[r[0] for r in c.execute('SELECT r.id'+join+' ORDER BY r.id LIMIT 501',args)]
    else:ids=payload.get('ids',[])
    if not isinstance(ids,list) or not ids or len(ids)>500 or any(type(x) is not int or x<1 for x in ids):raise ValueError('请选择1至500篇文章；筛选超过500篇时请缩小范围')
    return list(dict.fromkeys(ids))

def detail(store,rid):
    with store.connect() as c:
        row=c.execute('SELECT r.*,m.title original_title,m.body original_body FROM results r LEFT JOIN materials m ON m.id=r.material_id WHERE r.id=?',(int(rid),)).fetchone()
        if not row:raise ValueError('文章不存在')
        out=dict(row);decorate(c,[out])
        from article_quality import decorate as quality_decorate
        routing=store.settings();quality_decorate([out],routing.get('push_category_map',{}),routing.get('push_score_rules'))
        out['content_hash']=signature(out)
        out['history']=[dict(r) for r in c.execute('SELECT id,batch_id,title,article,archived_at,reason FROM result_versions WHERE result_id=? ORDER BY id DESC',(int(rid),))]
    return out

def assert_idle(c):
    if c.execute("SELECT 1 FROM runs WHERE state IN ('running','pausing') LIMIT 1").fetchone():raise ValueError('请先完成或暂停生文任务，再修改或恢复文章')

def edit(store,payload):
    rid=int(payload['id'])
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE');assert_idle(c)
        old=c.execute('SELECT * FROM results WHERE id=? AND current=1 AND deleted_at=\'\'',(rid,)).fetchone()
        if not old:raise ValueError('当前文章不存在')
        old=dict(old)
        if payload.get('content_hash')!=signature(old):raise ValueError('文章已发生变化，请重新打开后修改')
        value,count,images=normalize_article({'category':old['category'],'title':payload.get('title',''),'article':payload.get('article','')},old['category'])
        if value['title']==old['title'] and value['article']==old['article']:return {'ok':True,'changed':False}
        archive(c,old,'手动编辑前')
        data=json.loads(old['data_json']);data.update(value,edited_at=stamp())
        c.execute('UPDATE results SET title=?,article=?,short_text=?,data_json=?,char_count=?,frame_count=?,edited_at=?,content_revision=content_revision+1 WHERE id=?',(value['title'],value['article'],value['article'],dump(data),count,images,stamp(),rid))
        from article_quality import reset
        reset(c,rid)
    return {'ok':True,'changed':True}

def restore_version(store,payload):
    rid=int(payload['id']);vid=int(payload['version_id'])
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE');assert_idle(c)
        old=c.execute('SELECT * FROM results WHERE id=? AND current=1 AND deleted_at=\'\'',(rid,)).fetchone()
        version=c.execute('SELECT * FROM result_versions WHERE id=? AND result_id=?',(vid,rid)).fetchone()
        if not old or not version:raise ValueError('文章或历史版本不存在')
        old=dict(old)
        if payload.get('content_hash')!=signature(old):raise ValueError('当前文章已变化，请重新打开后恢复')
        saved=json.loads(version['payload_json'])
        # Historical formats can be restored exactly, even when today's output rules differ.
        archive(c,old,'恢复历史版本前')
        keys=['title','article','short_text','data_json','char_count','frame_count','state','rule_hash','rule_revision','write_variant','batch_id','writing_policy','created_at']
        defaults={'rule_revision':0,'frame_count':0,'char_count':0}
        values=[saved.get(k,defaults.get(k,'')) for k in keys]
        c.execute('UPDATE results SET '+','.join(k+'=?' for k in keys)+",edited_at=?,cleared_at='',content_revision=content_revision+1 WHERE id=?",values+[stamp(),rid])
        from article_quality import reset,apply
        reset(c,rid)
        if saved.get('score_status')=='scored' and saved.get('score_content_hash')==signature(saved):
            try:apply(c,dict(c.execute('SELECT * FROM results WHERE id=?',(rid,)).fetchone()),json.loads(saved.get('score_json','{}')),'恢复历史评分')
            except ValueError:pass
    return {'ok':True}

def restore_cleared(store,payload):
    ids=selected_ids(store,payload)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE');assert_idle(c)
        rows=c.execute('SELECT * FROM results WHERE current=1 AND cleared_at<>\'\' AND id IN ('+','.join('?' for _ in ids)+')',ids).fetchall()
        for row in rows:archive(c,row,'从已清除列表恢复')
        c.executemany("UPDATE results SET cleared_at='' WHERE id=?",[(r['id'],) for r in rows])
    return {'ok':True,'count':len(rows)}
