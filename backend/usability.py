"""Scoped UI actions; delegate execution to the existing fetcher and pusher."""
import json,time,uuid
from collections import Counter
from pathlib import Path
from store import dumps,digest,now

MAX_PUSH=10000
BODY_KEYS=('body_tool_path','body_workers','body_max_chars','body_chunk_size','body_wait','body_delay','body_rest_every','body_rest_seconds','body_channel','body_headful','body_timeout')

def install_schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS ui_action_previews(id TEXT PRIMARY KEY,kind TEXT,payload TEXT,state TEXT,created_at REAL,result_json TEXT DEFAULT \'\')')
    c.execute('CREATE INDEX IF NOT EXISTS idx_occurrence_import_scope ON occurrences(import_id,material_id)')

def integer(value,low,high,label):
    if type(value) is bool or not str(value).isdigit() or not low<=int(value)<=high:raise ValueError(label+'超出允许范围')
    return int(value)

def scope(data):
    mode=data.get('scope','filtered')
    if mode not in ('filtered','selected','all'):raise ValueError('未知素材范围')
    filters=data.get('filters',{}) if mode=='filtered' else {}
    if not isinstance(filters,dict):raise ValueError('筛选条件格式无效')
    out={'scope_filters':filters}
    if mode=='selected':
        ids=data.get('ids')
        if not isinstance(ids,list) or not ids or len(ids)>10000 or any(type(i) is not int or i<1 for i in ids):raise ValueError('请勾选1至10000条素材')
        out['ids']=list(dict.fromkeys(ids))
    return out

def save_preview(store,kind,payload):
    pid='ui_'+uuid.uuid4().hex[:16]
    with store.connect() as c:c.execute('INSERT INTO ui_action_previews(id,kind,payload,state,created_at) VALUES(?,?,?,?,?)',(pid,kind,dumps(payload),'preview',time.time()))
    return pid

def load_preview(store,pid,kind):
    with store.connect() as c:row=c.execute('SELECT * FROM ui_action_previews WHERE id=? AND kind=?',(pid,kind)).fetchone()
    if not row:raise ValueError('操作预览不存在，请重新核对')
    if row['state']=='preview' and time.time()-row['created_at']>1800:raise ValueError('操作预览已过期，请重新核对')
    return dict(row),json.loads(row['payload'])

def workflow_summary(store,filters=None):
    from material_catalog import query_parts
    from material_workflow import GROUPS
    filters=dict(filters or {});filters.pop('workflow_node',None)
    where,args,*_=query_parts(filters)
    with store.connect() as c:
        counts={r['workflow_node']:r['n'] for r in c.execute('SELECT f.workflow_node,count(*) n FROM materials m JOIN material_workflow f ON f.material_id=m.id'+where+' GROUP BY f.workflow_node',args)}
    return {'total':sum(counts.values()),'counts':counts,'groups':[{**item,'count':sum(counts.get(n,0) for n in item['nodes'])} for item in GROUPS]}

def import_summary(store,iid):
    iid=integer(iid,1,10**12,'导入编号')
    with store.connect() as c:
        item=c.execute('SELECT * FROM imports WHERE id=?',(iid,)).fetchone()
        if not item:raise ValueError('导入批次不存在')
    summary=workflow_summary(store,{'import_id':iid})
    return {'id':iid,'file':Path(item['file']).name,'created_at':item['created_at'],'added':item['added'],'duplicates_at_import':item['duplicates'],**summary}

def body_preview(store,fetcher,data):
    s=store.settings();limit=integer(data.get('limit',s.get('body_run_size',100)),1,10000,'本次抓取条数')
    selection=scope(data);rows=fetcher.select({**selection,'limit':limit,'include_held':True})
    encoded={'ids':[r['id'] for r in rows],'hashes':{str(r['id']):digest(r['title']+'\n'+r['url']) for r in rows},
             'selection':selection,'limit':limit,'settings_hash':digest(dumps({k:s.get(k) for k in BODY_KEYS}))}
    pid=save_preview(store,'body',encoded)
    return {'id':pid,'rows':rows,'total':len(rows),'engine':fetcher.engine_info(s),'active':bool(fetcher.active_id),'limit':limit}

def body_start(store,fetcher,data):
    row,payload=load_preview(store,data.get('id'),'body')
    if row['state']=='submitted':return json.loads(row['result_json'])
    if not payload['ids']:raise ValueError('当前范围没有需要抓取的素材')
    settings=store.settings()
    if payload['settings_hash']!=digest(dumps({k:settings.get(k) for k in BODY_KEYS})):raise ValueError('抓取参数已变化，请重新核对')
    if not fetcher.engine_info(settings)['available']:raise ValueError(fetcher.engine_info(settings)['message'])
    candidates=fetcher.select({**payload['selection'],'ids':payload['ids'],'limit':payload['limit'],'include_held':True})
    if {r['id'] for r in candidates}!=set(payload['ids']) or any(digest(r['title']+'\n'+r['url'])!=payload['hashes'][str(r['id'])] for r in candidates):raise ValueError('预览中的素材或抓取状态已变化，请重新核对')
    result=fetcher.start({'ids':payload['ids'],'limit':payload['limit']})
    with store.connect() as c:c.execute("UPDATE ui_action_previews SET state='submitted',result_json=? WHERE id=?",(dumps(result),row['id']))
    return result

def pending_modes(store,mid):
    mid=integer(mid,1,10**12,'素材编号')
    with store.connect() as c:
        rows=c.execute("SELECT e.extraction_mode,count(*) n FROM extractions e WHERE e.material_id=? AND e.current=1 AND e.eligible=1 AND NOT EXISTS(SELECT 1 FROM results r WHERE r.extraction_id=e.id AND r.current=1) GROUP BY e.extraction_mode",(mid,)).fetchall()
    from pipeline_catalog import writing_scope
    join,args,_=writing_scope({'state':'failed'})
    with store.connect() as c:
        failed=[dict(r) for r in c.execute('SELECT e.id,e.category'+join+' AND e.material_id=? ORDER BY e.id',args+[mid])]
    return {'modes':{r['extraction_mode']:r['n'] for r in rows},'failed':failed}

def push_context(store):
    from push_targets import project_for
    from title_push import mapping_revision
    from article_quality import score_rules
    settings=store.settings()
    return str(project_for(store)/'picfactory_matrix.db'),mapping_revision(settings.get('push_category_map',{}),score_rules(settings.get('push_score_rules')))

def push_preview(store,data):
    from workflow_management import query_parts
    from title_push import decorate,delivery_signature
    from article_quality import route
    filters=dict(data.get('filters') or {})
    if filters.get('visibility','active')!='active':raise ValueError('请先切回结果库，再推送当前筛选文章')
    ids=data.get('ids')
    if ids is not None:
        if not isinstance(ids,list) or not ids or len(ids)>500 or any(type(i) is not int or i<1 for i in ids):raise ValueError('请选择1至500篇文章')
        filters={}
    join,args=query_parts(store,filters)
    if ids is not None:join+=' AND r.id IN (SELECT value FROM json_each(?))';args.append(dumps(ids))
    target,revision=push_context(store);settings=store.settings()
    with store.connect() as c:
        rows=[dict(r) for r in c.execute('SELECT r.*'+join+' ORDER BY r.id LIMIT ?',args+[MAX_PUSH+1])]
        if len(rows)>MAX_PUSH:raise ValueError('本次筛选超过10000篇，请缩小范围后推送')
        decorate(c,rows)
        scheduled={(r['result_id'],r['content_hash']) for r in c.execute("SELECT result_id,content_hash FROM result_pushes WHERE target_path=? AND phase IN ('queued','waiting','retry_wait') AND state<>'pushed'",(target,))}
        busy={r[0] for r in c.execute("SELECT DISTINCT i.material_id FROM run_items i JOIN runs j ON j.id=i.run_id WHERE i.state IN ('queued','running') AND j.state IN ('running','pausing')")}
    entries=[];skipped=[];categories=Counter()
    for row in rows:
        destination,reason=route(row,settings.get('push_category_map',{}),settings.get('push_score_rules'))
        if ids is None and row['push_state'] in ('pushed','pending'):reason='已送达或正在等待接收'
        if row['material_id'] in busy:reason='素材正在执行写文任务'
        if not row['title'].strip() or not (row.get('article') or row['short_text']).strip():reason='标题或正文为空'
        hashed=delivery_signature(row,settings.get('push_category_map',{}),settings.get('push_score_rules'))
        if ids is None and (row['id'],hashed) in scheduled:reason='已排队等待接收或自动重试'
        if reason:skipped.append({'id':row['id'],'reason':reason});continue
        hashed=delivery_signature(row,settings.get('push_category_map',{}),settings.get('push_score_rules'))
        entries.append({'id':row['id'],'hash':hashed,'revision':row['content_revision'],'title':row['title'],'category':destination});categories[destination]+=1
    payload={'entries':entries,'target':target,'routing_revision':revision,'cursor':0,'batches':[],'skipped_during_submit':[],'filters':filters}
    pid=save_preview(store,'push',payload)
    return {'id':pid,'total':len(entries),'matched':len(rows),'target':target,'categories':dict(categories),'skipped':skipped,
            'parts':(len(entries)+499)//500,'rows':entries[:20]}

def push_progress(store,pid):
    _,payload=load_preview(store,pid,'push');counts=Counter();entries=payload['entries'];submitted=entries[:payload['cursor']]
    with store.connect() as c:
        for entry in submitted:
            receipt=c.execute('SELECT state FROM result_pushes WHERE result_id=? AND target_path=? AND content_hash=?',(entry['id'],payload['target'],entry['hash'])).fetchone()
            if receipt:counts[receipt['state']]+=1
    return {'id':pid,'total':len(entries),'submitted':payload['cursor'],'remaining':len(entries)-payload['cursor'],
            'target':payload['target'],'batches':payload['batches'],'pushed':counts['pushed'],'pending':counts['pending'],'failed':counts['failed'],
            'skipped':payload['skipped_during_submit']}

def push_submit(store,pusher,data):
    from title_push import delivery_signature
    row,payload=load_preview(store,data.get('id'),'push')
    context=push_context(store)
    if context!=(payload['target'],payload['routing_revision']):raise ValueError('推送目标或分类分流已变化，请重新预览，已提交部分保留原回执')
    cursor=integer(data.get('cursor',0),0,MAX_PUSH,'推送位置')
    if cursor<payload['cursor']:return push_progress(store,row['id'])
    if cursor!=payload['cursor']:raise ValueError('提交进度已变化，请刷新推送进度')
    chunk=payload['entries'][cursor:cursor+500]
    if not chunk:return push_progress(store,row['id'])
    settings=store.settings();ids=[];skips=[]
    with store.connect() as c:
        for entry in chunk:
            current=c.execute("SELECT * FROM results WHERE id=? AND current=1 AND deleted_at='' AND cleared_at=''",(entry['id'],)).fetchone()
            if not current or current['content_revision']!=entry['revision'] or delivery_signature(dict(current),settings.get('push_category_map',{}),settings.get('push_score_rules'))!=entry['hash']:
                skips.append({'id':entry['id'],'reason':'文案或评分已变化／已归档，请重新筛选后推送'})
            else:ids.append(entry['id'])
    with store.connect() as c:c.execute("UPDATE ui_action_previews SET state='sending' WHERE id=?",(row['id'],))
    if ids:
        result=pusher.push(ids)
        if result.get('batch_id'):payload['batches'].append(result['batch_id'])
    payload['cursor']+=len(chunk);payload['skipped_during_submit'].extend(skips)
    with store.connect() as c:c.execute("UPDATE ui_action_previews SET state=?,payload=? WHERE id=?",('completed' if payload['cursor']==len(payload['entries']) else 'sending',dumps(payload),row['id']))
    return push_progress(store,row['id'])

def push_summary(store,pusher):
    from push_delivery import detail
    target,_=push_context(store)
    with store.connect() as c:
        bid=c.execute('SELECT id FROM push_batches WHERE target_path=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(target,)).fetchone()
        partial=c.execute("SELECT id FROM ui_action_previews WHERE kind='push' AND state='sending' ORDER BY created_at DESC LIMIT 1").fetchone()
    latest=detail(pusher,bid[0]) if bid else None
    return {'target':target,'latest':{'id':bid[0],'counts':latest['counts']} if latest else None,'unfinished':push_progress(store,partial[0]) if partial else None}
