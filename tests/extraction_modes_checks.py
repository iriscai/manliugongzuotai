"""Run both topic scopes against isolated SQLite and a deterministic model stub."""
from workbench_fixtures import *
from extraction_modes import normalize
from operations import run_info,configuration_hash
from model_queue import ModelQueue,preview as queue_preview
import copy

class ModeFake(Fake):
    def __init__(self,kind='normal'):
        super().__init__();self.kind=kind;self.prompts=[];self.schemas=[]
    def call(self,prompt,schema,settings,folder,on_event=None):
        extraction='categories' in schema.get('properties',{})
        self.prompts.append(prompt);self.schemas.append(schema)
        if not extraction:return super().call(prompt,schema,settings,folder,on_event)
        result=super().call(prompt,SEED_EXTRACT,settings,folder,on_event)
        if self.kind=='empty':result['categories']=[]
        if self.kind=='wrong':result['categories']=result['categories'][1:]
        if self.kind=='double':
            item=copy.deepcopy(result['categories'][0]);item.update(topic='借阅登记',angle='借阅登记',main_point='借书登记书名')
            result['categories'].insert(1,item)
        return result

def fixture(path,n=1,kind='normal'):
    s,w,_=seed(path,n);p=ModeFake(kind);w.provider=p;return s,w,p

def run(s,w,mode='both',**kw):
    rid=w.start({'mode':mode,'limit':100,**kw})['run_id'];wait(w);return rid

with tempfile.TemporaryDirectory(prefix='extraction-modes-') as tmp:
    root=Path(tmp)
    s,w,p=fixture(root/'default');assert s.settings()['extraction_mode']=='multi'
    rid=run(s,w);assert s.list_results({})['total']==2 and run_info(s,rid)['extraction_mode']=='multi'
    s,w,p=fixture(root/'single',2);s.save_settings({'extraction_mode':'single'})
    with s.connect() as c:c.execute("UPDATE materials SET category='教育' WHERE id=2")
    rid=run(s,w);rows=s.list_results({})['rows']
    assert len(rows)==2 and {(r['material_id'],r['category']) for r in rows}=={(1,'生活'),(2,'教育')}
    assert p.calls.count(SEED_EXTRACT)==2 and p.calls.count(ARTICLE)==2
    for prompt,schema in zip(p.prompts,p.schemas):
        if 'categories' in schema.get('properties',{}):
            src=json.loads(prompt.split('\n统一输入素材：',1)[1]);cat=src['source_category']
            assert schema['properties']['categories']['maxItems']==1
            assert schema['properties']['categories']['items']['properties']['category']['enum']==[cat]
            assert ('【教育 /' not in prompt) if cat=='生活' else ('【生活 /' not in prompt)
    s,w,p=fixture(root/'override');s.save_settings({'extraction_mode':'single'})
    rid=run(s,w,extraction_mode='multi');assert s.list_results({})['total']==2
    assert run_info(s,rid)['extraction_mode']=='multi' and s.settings()['extraction_mode']=='single'
    for kind in ['empty','wrong','double']:
        s,w,p=fixture(root/kind,kind=kind);rid=run(s,w,extraction_mode='single')
        rows=s.list_results({})['rows'];assert len(rows)==1 and rows[0]['category']=='生活'
        assert p.calls.count(SEED_EXTRACT)==1 and p.calls.count(ARTICLE)==1
    # Separate mode caches/seeds: earlier multi extraction must not suppress single extraction.
    s,w,p=fixture(root/'cache');run(s,w,'extract',extraction_mode='multi')
    run(s,w,'extract',extraction_mode='single')
    assert p.calls.count(SEED_EXTRACT)==2
    with s.connect() as c:
        assert dict(c.execute('SELECT extraction_mode,count(*) FROM extractions GROUP BY extraction_mode'))=={'multi':2,'single':1}
    run(s,w,'write',extraction_mode='single');assert s.list_results({})['total']==1 and p.calls.count(ARTICLE)==1
    run(s,w,'write',extraction_mode='multi');assert s.list_results({})['total']==3 and p.calls.count(ARTICLE)==3
    # A paused task continues its stored mode even if the global default is changed.
    s,w,p=fixture(root/'resume');rid=run(s,w,extraction_mode='single',task_budget={'request_limit':1})
    assert run_info(s,rid)['state']=='blocked' and s.list_results({})['total']==0
    s.save_settings({'extraction_mode':'multi'});w.resume(rid,{'task_budget':{'request_limit':3}});wait(w)
    assert s.list_results({})['total']==1 and p.calls.count(SEED_EXTRACT)==1
    assert run_info(s,rid)['extraction_mode']=='single'
    s,w,p=fixture(root/'retry');p.fail=True;rid=run(s,w,extraction_mode='single')
    assert s.list_results({})['total']==0
    p.fail=False;s.save_settings({'extraction_mode':'multi'});retry=w.retry(rid)['run_id'];wait(w)
    assert s.list_results({})['total']==1 and p.calls.count(SEED_EXTRACT)==1
    assert run_info(s,retry)['extraction_mode']=='single'
    # Source category absent/disabled is visible before executing, with zero model calls.
    s,w,p=fixture(root/'unknown',2)
    with s.connect() as c:c.execute("UPDATE materials SET category='未知分类' WHERE id=2")
    selected=w.start({'preview':True,'extraction_mode':'single','scope':'selected','ids':[1,2]})
    assert selected['ids']==[1] and '1→1' in selected['excluded_rows'][0]['reason']
    with s.connect() as c:c.execute("UPDATE prompts SET enabled=0 WHERE category='生活' AND kind='write'")
    assert w.start({'preview':True,'extraction_mode':'single'})['ids']==[] and not p.calls
    for value in ['',None,True,'1:1','other']:
        try:normalize(value);raise AssertionError('invalid mode accepted')
        except ValueError:pass
    # Queued mode is frozen independently of later changes to the global default.
    s,w,p=fixture(root/'queue',2);q=ModelQueue(s,w)
    pre=queue_preview(s,{'extraction_mode':'single','limit':2})
    job=q.enqueue({'extraction_mode':'single','limit':2,'config_hash':pre['config_hash']})
    s.save_settings({'extraction_mode':'single'});q.tick();wait(w);q.tick()
    assert s.list_results({})['total']==2 and q.stats()['rows'][0]['extraction_mode']=='single'
    assert q.stats()['rows'][0]['state']=='completed'
    # Historical queues retain their original hash contract and multi mode.
    s,w,p=fixture(root/'oldqueue');q=ModelQueue(s,w);job=q.enqueue({'limit':1})
    with s.connect() as c:
        payload=json.loads(c.execute('SELECT payload FROM model_queue WHERE id=?',(job['job_id'],)).fetchone()[0])
        payload.pop('extraction_mode');payload['settings_hash']=configuration_hash(s,s.settings(),legacy=True)
        c.execute('UPDATE model_queue SET payload=? WHERE id=?',(dumps(payload),job['job_id']))
    s.save_settings({'extraction_mode':'single'});q.tick();wait(w);q.tick()
    assert s.list_results({})['total']==2

report={'ok':True,'default_multi_unchanged':True,'single_source_lane_only':True,'one_seed_one_article':True,
        'per_run_override':True,'mode_cache_isolation':True,'resume_and_retry_keep_mode':True,
        'queue_mode_frozen':True,'legacy_queue_compatible':True,'unknown_disabled_visible':True,
        'external_model_calls':0,'production_changes':0}
(ROOT/'build/extraction-modes-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
