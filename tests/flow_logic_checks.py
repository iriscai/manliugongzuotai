"""User-visible lifecycle regressions with fake model execution only."""
from workbench_fixtures import *
cases=[]
def case(name,fn):
    try:fn();cases.append({'case':name,'ok':True})
    except Exception as e:cases.append({'case':name,'ok':False,'error':str(e)})
with tempfile.TemporaryDirectory(prefix='flow-logic-') as tmp:
    base=Path(tmp)
    def cached_categories():
        s,w,p=seed(base/'categories');w.start({'mode':'extract','limit':1});wait(w)
        s.save_settings({'allowed_categories':['生活']});w.start({'mode':'write','limit':1});wait(w)
        cats=[r['category'] for r in s.list_results({})['rows']]
        assert cats==['生活'],f'configured only 生活, generated {cats}'
    case('cached_seeds_respect_allowed_categories',cached_categories)
    def edited_after_failure():
        s,w,p=seed(base/'manual');w.start({'mode':'both','limit':1});wait(w);a=s.list_results({})['rows'][0]
        p.fail=True;w.regenerate({'ids':[a['id']]});wait(w)
        d=detail(s,a['id']);edit(s,{'id':a['id'],'content_hash':d['content_hash'],'title':'人工修好标题','article':TEXT})
        rows=writing_detail(s,{'state':'failed'})['rows']
        assert not rows,'old failed attempt still marks the manually repaired article failed'
    case('manual_fix_supersedes_old_failure_without_rewriting_history',edited_after_failure)
    def changed_source_resume():
        s,w,p=seed(base/'source');w.start({'mode':'both','limit':1});wait(w)
        s.save_settings({'global_max_concurrency':1});p.release=threading.Event();p.started.clear()
        r=w.regenerate({'ids':[a['id'] for a in s.list_results({})['rows']]});assert p.started.wait(5)
        w.pause();p.release.set();wait(w);s.save_body(1,s.material(1)['body']+'新补充的正文。')
        calls=len(p.calls);w.resume(r['run_id']);wait(w)
        with s.connect() as c:run=dict(c.execute('SELECT * FROM runs WHERE id=?',(r['run_id'],)).fetchone())
        assert len(p.calls)==calls and run['errors']==1,'changed input was silently skipped or reprocessed by the old task'
    case('changed_source_rejected_on_old_task_resume',changed_source_resume)
    def exact_selection():
        s,w,p=seed(base/'scope',2);w.start({'mode':'extract','limit':2});wait(w)
        with s.connect() as c:
            ids=[r[0] for r in c.execute("SELECT id FROM extractions WHERE category='生活' ORDER BY material_id")]
            c.execute("UPDATE materials SET qualification='pending' WHERE id=2")
        rejected=False
        try:w.start({'mode':'write','seed_ids':ids})
        except ValueError:rejected=True
        if w.thread and w.thread.is_alive():wait(w)
        assert rejected,'part of the explicitly selected scope was silently omitted'
    case('explicit_seed_selection_is_all_or_rejected',exact_selection)
    def stable_ids():
        s,w,p=seed(base/'ids');w.start({'mode':'both','limit':1});wait(w)
        old=s.list_results({})['rows'];old_e=max(r['extraction_id'] for r in old);old_r=max(r['id'] for r in old)
        with s.connect() as c:s.remove_material_in(c,1,'duplicate')
        file=base/'replacement.csv';file.write_text('标题,正文,分类\n另一素材,图书角每天18时至20时开放。老师让孩子轮流讲故事。新素材,生活\n',encoding='utf8')
        s.import_file({'path':str(file)});w.start({'mode':'both','limit':1});wait(w)
        new=s.list_results({})['rows']
        assert min(r['id'] for r in new)>old_r and min(r['extraction_id'] for r in new)>old_e,'deleted IDs were reused and can attach old history to new articles'
    case('deleted_seed_and_article_ids_never_reused',stable_ids)
    def next_extraction_batch():
        s,w,p=seed(base/'nextbatch',2);w.start({'mode':'extract','limit':1});wait(w);w.start({'mode':'extract','limit':1});wait(w)
        with s.connect() as c:mids=[r[0] for r in c.execute('SELECT DISTINCT material_id FROM extractions ORDER BY material_id')]
        assert mids==[1,2] and p.calls.count(SEED_EXTRACT)==2,'next batch repeatedly picked already extracted materials'
    case('next_extract_batch_advances_to_unprocessed_materials',next_extraction_batch)
    def edited_while_paused():
        s,w,p=seed(base/'paused-edit');w.start({'mode':'both','limit':1});wait(w)
        s.save_settings({'global_max_concurrency':1});p.release=threading.Event();p.started.clear()
        run=w.regenerate({'ids':[r['id'] for r in s.list_results({})['rows']]});assert p.started.wait(5)
        w.pause();p.release.set();wait(w)
        paused=writing_detail(s,{'state':'paused'})['rows'];assert len(paused)==1,'paused regeneration with an old result was mislabeled completed'
        d=detail(s,paused[0]['result_id']);edit(s,{'id':d['id'],'content_hash':d['content_hash'],'title':'暂停后人工确认的新稿','article':TEXT})
        calls=len(p.calls);w.resume(run['run_id']);wait(w)
        assert len(p.calls)==calls and detail(s,d['id'])['title']=='暂停后人工确认的新稿','old paused task overwrote the edited version'
        with s.connect() as c:assert c.execute('SELECT errors FROM runs WHERE id=?',(run['run_id'],)).fetchone()[0]==1
    case('paused_regeneration_never_overwrites_later_manual_edit',edited_while_paused)
    def refuse_push_during_regeneration():
        from title_push import TitlePusher
        s,w,p=seed(base/'push');w.start({'mode':'both','limit':1});wait(w);a=s.list_results({})['rows'][0]
        p.release=threading.Event();p.started.clear();w.regenerate({'ids':[a['id']]});assert p.started.wait(5)
        target_calls=[]
        t=TitlePusher(s,project=base/'fake-target',running=lambda:target_calls.append(1))
        rejected=False
        try:t.push([a['id']])
        except ValueError as e:rejected='正在排队或生文' in str(e)
        finally:p.release.set();wait(w)
        assert rejected and not target_calls,'push was not refused before contacting the target'
    case('push_of_inflight_revision_rejected_before_target_access',refuse_push_during_regeneration)
report={'ok':all(x['ok'] for x in cases),'cases':cases,'external_model_calls':0,'production_changes':0}
(ROOT/'build/flow-logic-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
if not report['ok']:raise SystemExit(1)
