"""Execution scopes, public task records and per-run limits."""
import json,time
from providers import ProviderLimit

def configuration_hash(store,settings,legacy=False):
    from store import digest
    keys=['provider','codex_path','api_base','api_protocol','api_model','model','reasoning','allowed_categories','extract_variant','write_variant','extraction_mode','requirements','api_temperature','api_timeout','api_retry_count','api_skip_tls_verify','timeout','process_workers','write_workers','global_max_concurrency','batch_size','funny_extract_variant','funny_write_variant']
    values={k:settings.get(k) for k in keys}
    if legacy:values.pop('extraction_mode',None)
    if values['provider']=='codex':
        from providers import local_config
        local=local_config();values['model']=values['model'] or local.get('model','');values['reasoning']=values['reasoning'] or local.get('reasoning','')
    prompts=store.prompts()
    if values.get('extraction_mode')=='direct':
        for key in ('extract_variant','process_workers','funny_extract_variant'):values.pop(key,None)
        values['military_write_variant']=settings.get('military_write_variant')
        prompts=[p for p in prompts if p['kind']=='write']
    return digest(json.dumps({'settings':values,'prompts':prompts},ensure_ascii=False,sort_keys=True))

def install_schema(c):
    cols={r[1] for r in c.execute('PRAGMA table_info(run_items)')}
    if 'ordinal' not in cols:c.execute('ALTER TABLE run_items ADD COLUMN ordinal INTEGER NOT NULL DEFAULT 0')
    c.executescript('''CREATE TABLE IF NOT EXISTS run_article_slots(run_id TEXT,extraction_id INTEGER,state TEXT NOT NULL,PRIMARY KEY(run_id,extraction_id));
      CREATE INDEX IF NOT EXISTS idx_requests_material_stage ON model_requests(material_id,stage);
      CREATE INDEX IF NOT EXISTS idx_runs_history ON runs(created_at DESC,id);''')
    c.execute("DELETE FROM run_article_slots WHERE state='reserved'")

def budget(values,settings=None):
    settings=settings or {};out={}
    for key,high in [('request_limit',1000000),('article_limit',1000000),('token_limit',1000000000)]:
        value=values.get(key,settings.get('task_'+key,0))
        if isinstance(value,bool) or not str(value).isdigit() or not 0<=int(value)<=high:raise ValueError('本轮额度需填写有效非负整数，0表示不限')
        out[key]=int(value)
    return out

def acquire_article(worker,rid,eid,snapshot):
    limit=snapshot.get('task_budget',{}).get('article_limit',0)
    while True:
        if worker.pause_flag.is_set():
            from parallel_worker import StepPaused
            raise StepPaused()
        with worker.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM run_article_slots WHERE run_id=? AND extraction_id=?',(rid,eid)).fetchone():return
            counts={r['state']:r['n'] for r in c.execute('SELECT state,count(*) n FROM run_article_slots WHERE run_id=? GROUP BY state',(rid,))}
            completed=counts.get('completed',0);reserved=counts.get('reserved',0)
            if limit and completed>=limit:raise ProviderLimit('已达到本轮生成篇数上限；种子已保留，可提高本轮上限续跑或另开一轮')
            if not limit or completed+reserved<limit:
                c.execute("INSERT INTO run_article_slots VALUES(?,?,'reserved')",(rid,eid));return
        worker.pause_flag.wait(.08)

def public_run(c,row):
    from pipeline_catalog import run_summary
    from usage_budget import summary
    out=dict(row);snapshot=json.loads(out.pop('snapshot_json'));settings=snapshot['settings']
    out.update(provider=settings.get('provider'),model=settings.get('api_model') if settings.get('provider')=='api' else settings.get('model') or '历史未记录，跟随本机',
      api_base=settings.get('api_base') if settings.get('provider')=='api' else '',temperature=settings.get('api_temperature'),
      writing_policy=snapshot.get('writing_policy','历史未标注'),process_workers=settings.get('process_workers',1),write_workers=settings.get('write_workers',1),
      global_max_concurrency=settings.get('global_max_concurrency',16),task_budget=snapshot.get('task_budget',budget({})),
      credential_refreshed_at=snapshot.get('credential_refreshed_at',''),progress=run_summary(c,row['id']),usage=summary(c,row['id']))
    out['rule_versions']=[{'category':p['category'],'kind':p['kind'],'variant':p['variant'],'revision':p['revision']} for p in snapshot.get('prompts',[])]
    out['usage_available']=bool(snapshot.get('usage_tracking') or out['usage']['requests'] or not out['total'])
    from extraction_modes import for_snapshot,LABELS
    out['extraction_mode']=for_snapshot(snapshot)
    out['extraction_mode_label']=LABELS[out['extraction_mode']]
    out['targeted_seeds']=bool(snapshot.get('target_seed_ids'))
    out['extraction_policy']=snapshot.get('extraction_policy','')
    out['funny_paragraph_policy']=snapshot.get('funny_paragraph_policy','')
    out.pop('summary_json',None)
    return out

def history_scope(q):
    where=[];args=[]
    for key in ['state','mode']:
        if q.get(key):where.append(key+'=?');args.append(q[key])
    if q.get('q'):where.append('(id LIKE ? OR snapshot_json LIKE ?)');args.extend(['%'+q['q']+'%']*2)
    # Search only public model/identity metadata, never credentials or private prompt content.
    if q.get('q'):
        where[-1]="(id LIKE ? OR coalesce(nullif(json_extract(snapshot_json,'$.settings.api_model'),''),json_extract(snapshot_json,'$.settings.model'),'') LIKE ?)"
    from datetime import date
    for key,op in [('from','>='),('to','<=')]:
        if q.get(key):date.fromisoformat(q[key]);where.append('substr(created_at,1,10)'+op+'?');args.append(q[key])
    clause=' WHERE '+' AND '.join(where) if where else ''
    return clause,args

def history(store,q):
    page=max(1,int(q.get('page',1)));size=min(100,max(1,int(q.get('size',20))));clause,args=history_scope(q)
    with store.connect() as c:
        total=c.execute('SELECT count(*) FROM runs'+clause,args).fetchone()[0];page=min(page,max(1,(total+size-1)//size))
        rows=[public_run(c,r) for r in c.execute('SELECT * FROM runs'+clause+' ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',args+[size,(page-1)*size])]
    return {'rows':rows,'total':total,'page':page,'size':size}

def run_info(store,rid):
    with store.connect() as c:
        row=c.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
        if not row:raise ValueError('任务不存在')
        return public_run(c,row)

def selection(store,payload):
    from workflow_management import selected_ids,query_parts
    from title_push import decorate
    ids=selected_ids(store,payload);join,args=query_parts(store,payload.get('filters',{}))
    with store.connect() as c:
        inside={r[0] for r in c.execute('SELECT r.id'+join+' AND r.id IN ('+','.join('?' for _ in ids)+')',args+ids)}
        rows=[dict(r) for r in c.execute('SELECT id,category,title,article,short_text,current,cleared_at FROM results WHERE id IN ('+','.join('?' for _ in ids)+') ORDER BY id',ids)]
        decorate(c,rows)
        for r in rows:r['in_filter']=r['id'] in inside;r.pop('article');r.pop('short_text')
    return {'rows':rows,'inside':sorted(inside),'outside':[i for i in ids if i not in inside],'missing':[i for i in ids if i not in {r['id'] for r in rows}]}
