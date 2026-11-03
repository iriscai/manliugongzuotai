"""Independent, bounded model jobs waiting for their own materials to qualify."""
import json,threading,uuid
from store import now,dumps,digest

def install_schema(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS model_queue(id TEXT PRIMARY KEY,state TEXT,payload TEXT,run_id TEXT DEFAULT '',error TEXT DEFAULT '',created_at TEXT,updated_at TEXT);
      CREATE TABLE IF NOT EXISTS model_queue_items(job_id TEXT,material_id INTEGER,state TEXT DEFAULT 'pending',source_hash TEXT,has_body INTEGER,title_url_hash TEXT,error TEXT DEFAULT '',PRIMARY KEY(job_id,material_id));''')
    c.execute('CREATE TABLE IF NOT EXISTS model_queue_runs(job_id TEXT,run_id TEXT PRIMARY KEY)')
    if 'user_paused' not in {r[1] for r in c.execute('PRAGMA table_info(model_queue)')}:c.execute('ALTER TABLE model_queue ADD COLUMN user_paused INTEGER NOT NULL DEFAULT 0')
    if 'title' not in {r[1] for r in c.execute('PRAGMA table_info(model_queue_items)')}:c.execute("ALTER TABLE model_queue_items ADD COLUMN title TEXT NOT NULL DEFAULT ''")
    c.execute("UPDATE model_queue SET state='paused',error='上次任务已中断，可从任务历史续跑或继续队列' WHERE state='running'")

def preview(store,payload):
    from material_catalog import query_parts
    from prompt_status import active_categories
    mode=payload.get('mode','both')
    if mode not in ('both','extract'):raise ValueError('等待正文队列仅支持完整流程或仅提炼')
    from extraction_modes import resolve
    settings=store.settings();extraction_mode=resolve(payload,settings)
    settings={**settings,'extraction_mode':extraction_mode}
    active,disabled_categories=active_categories(store.prompts(),settings,mode)
    if not active:raise ValueError('当前范围没有启用完整规则的赛道，请先启用所需规则')
    limit=int(payload.get('limit',store.settings()['run_size']))
    if not 1<=limit<=1000:raise ValueError('每轮素材数量需为1至1000')
    scope=payload.get('scope','all');where,args,order,_,_=query_parts(payload.get('filters',{}) if scope=='filtered' else {})
    clauses=[where.removeprefix(' WHERE ')] if where else []
    clauses.append("m.deleted_at=\'\' AND m.state NOT IN ('written','skipped','routing','extracting','writing')")
    if extraction_mode=='single':
        clauses.append('m.category IN ('+','.join('?' for _ in active)+')');args.extend(active)
    if scope=='selected':
        ids=payload.get('ids')
        if not isinstance(ids,list) or not ids or len(ids)>1000 or any(type(i) is not int or i<1 for i in ids):raise ValueError('请勾选1至1000条素材')
        clauses.append('m.id IN ('+','.join('?' for _ in ids)+')');args.extend(ids)
    with store.connect() as c:
        rows=[dict(r) for r in c.execute('SELECT m.id,m.title,m.body,m.url,m.category,m.qualification FROM materials m WHERE '+' AND '.join(clauses)+' ORDER BY '+order+' LIMIT ?',args+[limit])]
    if scope=='selected':rows.sort(key=lambda r:ids.index(r['id']))
    from operations import configuration_hash
    from execution_preview import excluded_rows
    with store.connect() as c:excluded=excluded_rows(c,{**payload,'extraction_mode':extraction_mode},[r['id'] for r in rows],mode,active,queue=True)
    return {'ids':[r['id'] for r in rows],'rows':[{'id':r['id'],'title':r['title'],'category':r['category'],'waiting_body':r['qualification']!='qualified'} for r in rows],
      'expected_hashes':{str(r['id']):digest(r['title']+'\n'+r['body']) for r in rows},'expected_urls':{str(r['id']):digest(r['title']+'\n'+r['url']) for r in rows},
      'config_hash':configuration_hash(store,settings),'extraction_mode':extraction_mode,'disabled_categories':disabled_categories,'excluded_ids':[i for i in payload.get('ids',[]) if i not in {r['id'] for r in rows}] if scope=='selected' else [],'excluded_rows':excluded}

class ModelQueue:
    def __init__(self,store,worker):self.store=store;self.worker=worker;self.stop=threading.Event();self.lock=threading.RLock();self.draining=False
    def enqueue(self,payload):
        from operations import budget
        with self.worker.lock,self.lock:
            selected=preview(self.store,payload)
            if not selected['ids']:raise ValueError('当前范围没有可排队素材')
            if selected['excluded_ids']:raise ValueError('所选素材包含不可排队或超出本轮条数的记录，请调整选择后重试')
            if payload.get('config_hash') and payload['config_hash']!=selected['config_hash']:raise ValueError('执行设置或规则已变化，请重新预览')
            if payload.get('expected_hashes') is not None and set(map(str,selected['ids']))!=set(payload['expected_hashes']):raise ValueError('预览范围已变化，请重新预览')
            if payload.get('expected_hashes') is not None and any(payload['expected_hashes'].get(str(i))!=selected['expected_hashes'][str(i)] for i in selected['ids']):raise ValueError('预览中的素材已变化，请重新预览')
            if payload.get('expected_urls') is not None and payload['expected_urls']!=selected['expected_urls']:raise ValueError('预览中的来源链接已变化，请重新预览')
            jid='model_'+uuid.uuid4().hex[:12];s=self.store.settings();payload={k:v for k,v in payload.items() if k in ('mode','task_budget')};payload['task_budget']=budget(payload.get('task_budget',{}),s)
            payload['extraction_mode']=selected['extraction_mode']
            payload['settings_hash']=self.settings_hash(s,payload['extraction_mode'])
            with self.store.connect() as c:
                c.execute('INSERT INTO model_queue(id,state,payload,created_at,updated_at) VALUES(?,?,?,?,?)',(jid,'queued',dumps(payload),now(),now()))
                for i in selected['ids']:
                    m=c.execute('SELECT body,title FROM materials WHERE id=?',(i,)).fetchone()
                    c.execute('INSERT INTO model_queue_items(job_id,material_id,source_hash,has_body,title_url_hash,title) VALUES(?,?,?,?,?,?)',(jid,i,selected['expected_hashes'][str(i)],bool(m['body']),selected['expected_urls'][str(i)],m['title']))
            self.draining=False;return {'job_id':jid,'total':len(selected['ids'])}
    def settings_hash(self,s,extraction_mode=None,legacy=False):
        from operations import configuration_hash
        if extraction_mode is not None:s={**s,'extraction_mode':extraction_mode}
        return configuration_hash(self.store,s,legacy=legacy)
    def stats(self):
        with self.store.connect() as c:
            rows=[dict(r) for r in c.execute('SELECT id,state,run_id,error,created_at FROM model_queue ORDER BY created_at DESC LIMIT 30')]
            for r in rows:
                payload=json.loads(c.execute('SELECT payload FROM model_queue WHERE id=?',(r['id'],)).fetchone()[0])
                r['extraction_mode']=payload.get('extraction_mode','multi')
                r['counts']={z['state']:z['n'] for z in c.execute('SELECT state,count(*) n FROM model_queue_items WHERE job_id=? GROUP BY state',(r['id'],))}
        return {'rows':rows,'draining':self.draining}
    def detail(self,jid):
        with self.store.connect() as c:
            job=c.execute('SELECT id,state,error,run_id FROM model_queue WHERE id=?',(jid,)).fetchone()
            if not job:raise ValueError('队列任务不存在')
            rows=[dict(r) for r in c.execute('SELECT i.material_id,coalesce(m.title,i.title) title,i.state,i.error,m.qualification FROM model_queue_items i LEFT JOIN materials m ON m.id=i.material_id WHERE job_id=? ORDER BY i.rowid',(jid,))]
        return {'job':dict(job),'items':rows}
    def pause(self,jid):
        with self.worker.lock,self.lock:
            with self.store.connect() as c:
                row=c.execute('SELECT * FROM model_queue WHERE id=?',(jid,)).fetchone()
                if not row:raise ValueError('排队任务不存在')
                c.execute("UPDATE model_queue SET state='paused',user_paused=1,updated_at=? WHERE id=?",(now(),jid))
            if self.worker.current_run==row['run_id']:self.worker.pause()
        return {'ok':True}
    def resume(self,jid,options=None):
        with self.worker.lock,self.lock:
            with self.store.connect() as c:
                row=c.execute('SELECT * FROM model_queue WHERE id=?',(jid,)).fetchone()
                if not row or row['state']!='paused':raise ValueError('此队列任务不可继续')
                if row['run_id']:
                    state=c.execute('SELECT state FROM runs WHERE id=?',(row['run_id'],)).fetchone()
                    if state and state['state'] in ('paused','blocked','interrupted'):self.worker.resume(row['run_id'],options)
                    if state and state['state']=='completed':
                        c.execute("UPDATE model_queue SET run_id='' WHERE id=?",(jid,));row=dict(row);row['run_id']=''
                c.execute("UPDATE model_queue SET state=?,user_paused=0,updated_at=? WHERE id=?",('running' if row['run_id'] else 'queued',now(),jid))
            self.draining=False
        return {'ok':True}
    def drain(self):
        with self.worker.lock,self.lock:
            self.draining=True
            with self.store.connect() as c:c.execute("UPDATE model_queue SET state='paused',user_paused=1,error='已请求保存当前步骤后停止',updated_at=? WHERE state IN ('queued','waiting','running')",(now(),))
    def tick(self):
        with self.worker.lock,self.lock:
            with self.store.connect() as c:
                for job in c.execute("SELECT * FROM model_queue WHERE run_id<>'' AND state IN ('running','paused')").fetchall():
                    run=c.execute('SELECT state FROM runs WHERE id=?',(job['run_id'],)).fetchone()
                    if not run or run['state'] in ('running','pausing'):continue
                    for item in c.execute('SELECT material_id,state,error FROM run_items WHERE run_id=?',(job['run_id'],)):
                        if item['state'] in ('completed','skipped'):c.execute("UPDATE model_queue_items SET state='done',error=? WHERE job_id=? AND material_id=?",(item['error'],job['id'],item['material_id']))
                    if run['state']!='completed':c.execute("UPDATE model_queue SET state='paused',error='执行已暂停或额度受限，可从任务历史续跑',updated_at=? WHERE id=?",(now(),job['id']));continue
                    failed=c.execute("SELECT 1 FROM run_items WHERE run_id=? AND state='failed'",(job['run_id'],)).fetchone()
                    c.execute('UPDATE model_queue SET state=?,run_id=?,error=?,updated_at=? WHERE id=?',('paused' if failed or job['user_paused'] else 'queued',job['run_id'] if failed else '', '部分素材失败，请从任务历史重试' if failed else '',now(),job['id']))
            if self.draining or self.worker.thread and self.worker.thread.is_alive():return
            with self.store.connect() as c:job=c.execute("SELECT * FROM model_queue WHERE state IN ('queued','waiting') ORDER BY created_at,id LIMIT 1").fetchone()
            if not job:return
            payload=json.loads(job['payload']);settings=self.store.settings()
            if payload['settings_hash']!=self.settings_hash(settings,payload.get('extraction_mode','multi'),legacy='extraction_mode' not in payload):
                with self.store.connect() as c:c.execute("UPDATE model_queue SET state='paused',error='执行设置已变化，请恢复原设置或重新建立队列',updated_at=? WHERE id=?",(now(),job['id']))
                return
            ready=[]
            with self.store.connect() as c:
                for item in c.execute("SELECT * FROM model_queue_items WHERE job_id=? AND state='pending' ORDER BY rowid",(job['id'],)).fetchall():
                    m=c.execute('SELECT * FROM materials WHERE id=?',(item['material_id'],)).fetchone();reason=''
                    if not m or m['deleted_at']:reason='素材已被去重合并或删除'
                    elif digest(m['title']+'\n'+m['url'])!=item['title_url_hash'] or item['has_body'] and digest(m['title']+'\n'+m['body'])!=item['source_hash']:reason='素材来源已变化，请重新建立任务'
                    if reason:c.execute("UPDATE model_queue_items SET state='skipped',error=? WHERE job_id=? AND material_id=?",(reason,job['id'],item['material_id']));continue
                    if m['qualification']=='qualified':ready.append(m['id'])
                pending=c.execute("SELECT count(*) FROM model_queue_items WHERE job_id=? AND state='pending'",(job['id'],)).fetchone()[0]
                if not pending:c.execute("UPDATE model_queue SET state='completed',error='',updated_at=? WHERE id=?",(now(),job['id']));return
                if not ready:c.execute("UPDATE model_queue SET state='waiting',error='等待本范围素材取得有效正文并通过去重验收',updated_at=? WHERE id=?",(now(),job['id']));return
            try:
                limits=dict(payload['task_budget'])
                with self.store.connect() as c:
                    used=c.execute('SELECT count(*) n,coalesce(sum(total_tokens),0) tokens FROM model_requests WHERE run_id IN (SELECT run_id FROM model_queue_runs WHERE job_id=?)',(job['id'],)).fetchone()
                    articles=c.execute("SELECT count(*) FROM run_article_slots WHERE state='completed' AND run_id IN (SELECT run_id FROM model_queue_runs WHERE job_id=?)",(job['id'],)).fetchone()[0]
                for key,value in [('request_limit',used['n']),('token_limit',used['tokens']),('article_limit',articles)]:
                    if limits.get(key):
                        if value>=limits[key]:raise ValueError('此队列已达到本轮预算；剩余种子保留，可调整后重建队列')
                        limits[key]-=value
                chosen=self.worker.start({'preview':True,'extraction_mode':payload.get('extraction_mode','multi'),'mode':payload.get('mode','both'),'scope':'selected','ids':ready,'limit':len(ready)})
                if not chosen['ids']:
                    with self.store.connect() as c:c.executemany("UPDATE model_queue_items SET state='done',error='当前允许赛道已完成或不适配' WHERE job_id=? AND material_id=?",[(job['id'],i) for i in ready])
                    return
                run=self.worker.start({'extraction_mode':payload.get('extraction_mode','multi'),'mode':payload.get('mode','both'),'scope':'selected','ids':chosen['ids'],'limit':len(chosen['ids']),'expected_hashes':chosen['expected_hashes'],'task_budget':limits})
                with self.store.connect() as c:
                    c.execute('INSERT INTO model_queue_runs VALUES(?,?)',(job['id'],run['run_id']))
                    c.execute("UPDATE model_queue SET state='running',run_id=?,error='',updated_at=? WHERE id=?",(run['run_id'],now(),job['id']))
            except ValueError as e:
                with self.store.connect() as c:c.execute("UPDATE model_queue SET state='paused',error=?,updated_at=? WHERE id=?",(str(e),now(),job['id']))
    def start(self):
        def dispatch():
            while not self.stop.wait(.5):
                try:self.tick()
                except Exception as e:self.store.log('模型队列暂缓：'+str(e),'queue',level='error')
        self.thread=threading.Thread(target=dispatch,daemon=True);self.thread.start()
