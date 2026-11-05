"""Persisted phase progress and evidence-based writing eligibility."""
import json
from collections import Counter

WORKER_OPTIONS=(1,2,4,8,16,32)

def concurrency(value):
    if isinstance(value,bool) or not str(value).strip().isdigit() or int(value) not in WORKER_OPTIONS:
        raise ValueError('模型并发数仅支持1、2、4、8、16、32')
    return int(value)

def install_schema(c):
    run_cols={r[1] for r in c.execute('PRAGMA table_info(runs)')}
    if 'summary_json' not in run_cols:c.execute("ALTER TABLE runs ADD COLUMN summary_json TEXT NOT NULL DEFAULT ''")
    cols={r[1] for r in c.execute('PRAGMA table_info(run_items)')}
    if 'phase' not in cols:c.execute("ALTER TABLE run_items ADD COLUMN phase TEXT DEFAULT ''")
    extraction_cols={r[1] for r in c.execute('PRAGMA table_info(extractions)')}
    if 'eligible' not in extraction_cols:
        c.execute('ALTER TABLE extractions ADD COLUMN eligible INTEGER DEFAULT 0')
        c.execute('ALTER TABLE extractions ADD COLUMN verification_count INTEGER DEFAULT 0')
        c.execute("UPDATE extractions SET eligible=coalesce(json_extract(data_json,'$.eligible'),0),verification_count=coalesce(json_array_length(json_extract(data_json,'$.needs_verification')),0)")
    c.executescript('''
        CREATE TABLE IF NOT EXISTS run_writes(run_id TEXT,extraction_id INTEGER,material_id INTEGER,category TEXT,state TEXT,error TEXT DEFAULT '',updated_at TEXT,PRIMARY KEY(run_id,extraction_id));
        CREATE INDEX IF NOT EXISTS idx_run_writes_state ON run_writes(run_id,state);
        CREATE INDEX IF NOT EXISTS idx_run_writes_extraction ON run_writes(extraction_id,updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_run_items_phase ON run_items(run_id,phase);
        CREATE INDEX IF NOT EXISTS idx_extraction_writing_ready ON extractions(current,eligible,verification_count,material_id);
        CREATE TRIGGER IF NOT EXISTS extraction_write_flags_insert AFTER INSERT ON extractions BEGIN
          UPDATE extractions SET eligible=coalesce(json_extract(NEW.data_json,'$.eligible'),0),verification_count=coalesce(json_array_length(json_extract(NEW.data_json,'$.needs_verification')),0) WHERE id=NEW.id; END;
        CREATE TRIGGER IF NOT EXISTS extraction_write_flags_update AFTER UPDATE OF data_json ON extractions BEGIN
          UPDATE extractions SET eligible=coalesce(json_extract(NEW.data_json,'$.eligible'),0),verification_count=coalesce(json_array_length(json_extract(NEW.data_json,'$.needs_verification')),0) WHERE id=NEW.id; END;
    ''')
    c.execute("UPDATE run_writes SET state='queued' WHERE state='writing'")
    c.execute("UPDATE run_items SET phase='' WHERE state<>'running'")

def pending_extractions(c,rid=None,limit=50,offset=0,only_blocked=False):
    where="e.current=1 AND m.deleted_at=\'\' AND coalesce(r.deleted_at,'')='' AND m.qualification='qualified' AND m.title<>'' AND m.body<>''"
    args=[]
    if rid:where+=' AND e.material_id IN (SELECT material_id FROM run_items WHERE run_id=?)';args.append(rid)
    if only_blocked:where+=' AND 0'
    rows=c.execute('SELECT e.id,e.material_id,e.category,e.angle,e.data_json,m.title,r.id result_id FROM extractions e JOIN materials m ON m.id=e.material_id LEFT JOIN results r ON r.extraction_id=e.id AND r.current=1 WHERE '+where+' ORDER BY e.id DESC LIMIT ? OFFSET ?',args+[limit,offset])
    counts=Counter();details=[]
    for row in rows:
        item=dict(row);data=json.loads(item.pop('data_json'));counts['extracted']+=1
        if not data.get('eligible'):state='ineligible'
        elif item['result_id']:state='written'
        else:state='ready'
        counts[state]+=1;item.update(state=state,main_point=data.get('main_point',''),needs_verification=data.get('needs_verification',[]));details.append(item)
    return extraction_counts(c,rid),details

def extraction_counts(c,rid=None):
    where="e.current=1 AND m.deleted_at=\'\' AND coalesce(r.deleted_at,'')='' AND m.qualification='qualified' AND m.title<>'' AND m.body<>''";args=[]
    if rid:where+=' AND e.material_id IN (SELECT material_id FROM run_items WHERE run_id=?)';args.append(rid)
    row=c.execute('''SELECT count(*) extracted,coalesce(sum(e.eligible=0),0) ineligible,
        coalesce(sum(e.eligible=1 AND r.id IS NOT NULL),0) written,
        0 needs_review,
        coalesce(sum(e.eligible=1 AND r.id IS NULL),0) ready
        FROM extractions e JOIN materials m ON m.id=e.material_id LEFT JOIN results r ON r.extraction_id=e.id AND r.current=1 WHERE '''+where,args).fetchone()
    return dict(row)

def run_summary(c,rid):
    run=c.execute('SELECT state,summary_json FROM runs WHERE id=?',(rid,)).fetchone()
    if run and run['summary_json'] and run['state'] not in ('running','pausing'):return json.loads(run['summary_json'])
    writes=Counter({r['state']:r['n'] for r in c.execute('SELECT state,count(*) n FROM run_writes WHERE run_id=? GROUP BY state',(rid,))})
    counts={'extracted':sum(writes.values()),'ineligible':0,'needs_review':0,'written':writes['completed']+writes['reused'],'ready':writes['queued']+writes['extracted'],
      'reused':writes['reused'],'remaining':writes['queued']+writes['extracted'],'writing':writes['writing'],'write_failed':writes['failed'],'write_completed':writes['completed']}
    states=Counter();phases=Counter()
    for row in c.execute('SELECT state,phase FROM run_items WHERE run_id=?',(rid,)):
        states[row['state']]+=1
        if row['state']=='running':phases[row['phase'] or 'preparing']+=1
    counts.update(material_states=dict(states),active_phases=dict(phases))
    counts['writing']=c.execute("SELECT count(*) FROM run_writes WHERE run_id=? AND state='writing'",(rid,)).fetchone()[0]
    counts['write_failed']=c.execute("SELECT count(*) FROM run_writes WHERE run_id=? AND state='failed'",(rid,)).fetchone()[0]
    counts['write_completed']=c.execute("SELECT count(*) FROM run_writes WHERE run_id=? AND state='completed'",(rid,)).fetchone()[0]
    counts['multi_batches']=c.execute('SELECT count(*) FROM extraction_batches WHERE run_id=?',(rid,)).fetchone()[0]
    return counts

def freeze_summary(c,rid):
    c.execute("UPDATE runs SET summary_json='' WHERE id=?",(rid,))
    value=run_summary(c,rid)
    c.execute('UPDATE runs SET summary_json=? WHERE id=?',(json.dumps(value,ensure_ascii=False),rid))

def overview(c):
    counts=extraction_counts(c)
    counts['ready']=c.execute("""SELECT count(*) FROM materials m WHERE m.qualification='qualified' AND m.deleted_at=''
        AND NOT EXISTS(SELECT 1 FROM results r WHERE r.material_id=m.id AND r.category=m.category AND r.current=1)""").fetchone()[0]
    counts['writing']=c.execute("SELECT count(*) FROM run_writes w JOIN runs r ON r.id=w.run_id WHERE w.state='writing' AND r.state IN ('running','pausing')").fetchone()[0]
    return counts

def run_detail(store,query):
    rid=str(query.get('id',''));page=max(1,int(query.get('page',1)));offset=(page-1)*50
    with store.connect() as c:
        row=c.execute('SELECT id,mode,state,total,done,errors,current_phase,created_at,updated_at FROM runs WHERE id=?',(rid,)).fetchone()
        if not row:raise ValueError('处理任务不存在')
        counts,blocked=pending_extractions(c,rid,offset=offset,only_blocked=True)
        items=[dict(x) for x in c.execute('SELECT i.*,m.title,m.state material_state FROM run_items i LEFT JOIN materials m ON m.id=i.material_id WHERE i.run_id=? ORDER BY i.material_id LIMIT 50 OFFSET ?',(rid,offset))]
        return {'run':dict(row),'summary':run_summary(c,rid),'items':items,'verification':blocked,'verification_total':counts['needs_review'],'page':page,'size':50}

def writing_scope(query):
    state=query.get('state','')
    where="e.current=1 AND m.deleted_at=\'\' AND coalesce(r.deleted_at,'')='' AND m.qualification='qualified' AND e.eligible=1 AND e.category=m.category AND (e.extraction_mode='direct' OR r.id IS NOT NULL OR w.state='failed')";args=[]
    effective="CASE WHEN w.state IN ('queued','writing') AND j.state IN ('running','pausing') THEN w.state WHEN w.state='failed' AND (r.id IS NULL OR r.content_revision<=max(1,w.base_revision)) THEN 'failed' WHEN w.state='queued' AND j.state IN ('paused','blocked','interrupted') AND (r.id IS NULL OR r.content_revision<=max(1,w.base_revision)) THEN 'paused' WHEN r.id IS NOT NULL THEN 'written' ELSE 'ready' END"
    if state=='needs_review':where+=' AND 0'
    elif state in ('ready','queued','writing','failed','written','paused'):where+=' AND ('+effective+')=?';args.append(state)
    elif state:raise ValueError('未知写文筛选')
    query_sql=""" FROM extractions e JOIN materials m ON m.id=e.material_id
          LEFT JOIN results r ON r.extraction_id=e.id AND r.current=1
          LEFT JOIN run_writes w ON w.rowid=(SELECT z.rowid FROM run_writes z JOIN runs zr ON zr.id=z.run_id WHERE z.extraction_id=e.id ORDER BY (zr.state IN ('running','pausing')) DESC,z.updated_at DESC,z.rowid DESC LIMIT 1)
          LEFT JOIN runs j ON j.id=w.run_id WHERE """+where
    return query_sql,args,effective

def writing_detail(store,query):
    page=max(1,int(query.get('page',1)));offset=(page-1)*50
    query_sql,args,effective=writing_scope(query)
    with store.connect() as c:
        total=c.execute('SELECT count(*)'+query_sql,args).fetchone()[0]
        rows=[]
        for row in c.execute('SELECT e.id,e.material_id,e.category,e.angle,e.data_json,m.title,r.id result_id,r.cleared_at,w.error,w.run_id,('+effective+') write_state'+query_sql+' ORDER BY e.id DESC LIMIT 50 OFFSET ?',args+[offset]):
            item=dict(row);data=json.loads(item.pop('data_json'));verification=data.get('needs_verification',[])
            item.update(needs_verification=verification,state=item.pop('write_state'));rows.append(item)
            if item['state']=='written':item['error']=''
            item['elements']=data.get('elements',[])
            item['topic']=data.get('topic') or item['angle']
    return {'rows':rows,'total':total,'page':page,'size':50}
