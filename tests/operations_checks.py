"""Scope, credentials, budgets, counts, history, selection and parallel queues."""
from workbench_fixtures import *
from operations import history,selection
from model_queue import ModelQueue
from types import SimpleNamespace
with tempfile.TemporaryDirectory(prefix='operations-check-') as tmp:
    root=Path(tmp)
    s,w,p=seed(root/'scope',3)
    with s.connect() as c:c.executemany('UPDATE materials SET read_count=? WHERE id=?',[(50,1),(100,2),(200,3)])
    payload={'mode':'extract','scope':'filtered','filters':{'read_min':'100','sort_by':'read_count','sort_dir':'desc'},'limit':2}
    preview=w.start({**payload,'preview':True});assert preview['ids']==[3,2]
    r=w.start({**payload,'ids':preview['ids'],'expected_hashes':preview['expected_hashes'],'config_hash':preview['config_hash']});wait(w)
    with s.connect() as c:assert [x[0] for x in c.execute('SELECT material_id FROM run_items WHERE run_id=? ORDER BY ordinal',(r['run_id'],))]==[3,2]
    before=len(p.calls);assert s.material(1)['current_extraction_count']==0
    preview=w.start({'mode':'both','scope':'selected','ids':[1],'preview':True});s.save_body(1,s.material(1)['body']+'增加正文。')
    try:w.start({'mode':'both','scope':'selected','ids':[1],'expected_hashes':preview['expected_hashes']});raise AssertionError('changed preview accepted')
    except ValueError:pass
    assert len(p.calls)==before
    s,w,p=seed(root/'articles');r=w.start({'mode':'both','limit':1,'task_budget':{'article_limit':1}});wait(w)
    assert len(s.list_results({})['rows'])==1 and s.stats()['runs'][0]['state']=='blocked'
    w.resume(r['run_id'],{'task_budget':{'article_limit':2}});wait(w)
    assert s.list_results({})['total']==2 and p.calls.count(SEED_EXTRACT)==1 and p.calls.count(ARTICLE)==2
    metrics=s.list_materials({})['rows'][0];assert metrics['extraction_calls']==1 and metrics['extraction_count']==2 and metrics['article_count']==2,metrics
    chosen=[x['id'] for x in s.list_results({})['rows']];selected=selection(s,{'ids':chosen,'filters':{'category':'生活'}});assert len(selected['inside'])==1 and len(selected['outside'])==1
    s,w,p=seed(root/'credentials');s.save_settings({'provider':'api','api_base':'https://fixture.invalid/v1','api_model':'original-model','api_key_encrypted':'fake-old'})
    r=w.start({'mode':'both','limit':1,'task_budget':{'request_limit':1}});wait(w)
    with s.connect() as c:assert summary(c,r['run_id'])['requests']==1
    s.save_settings({'api_key_encrypted':'fake-new','api_model':'new-model','api_base':'https://other.invalid/v1'})
    try:w.resume(r['run_id'],{'refresh_credentials':True});raise AssertionError('key sent to old host')
    except ValueError:pass
    s.save_settings({'api_base':'https://fixture.invalid/v1'})
    w.resume(r['run_id'],{'refresh_credentials':True,'task_budget':{'request_limit':8}});wait(w)
    with s.connect() as c:
        saved=json.loads(c.execute('SELECT snapshot_json FROM runs WHERE id=?',(r['run_id'],)).fetchone()[0])
        assert saved['settings']['api_key_encrypted']=='fake-new' and saved['settings']['api_model']=='original-model'
        template=dict(c.execute('SELECT * FROM runs WHERE id=?',(r['run_id'],)).fetchone())
        for i in range(17):c.execute('INSERT INTO runs(id,mode,state,total,snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(f'history-{i:02}','write','completed',0,template['snapshot_json'],f'2026-10-{i+1:02}T01:00:00',f'2026-10-{i+1:02}T01:00:00'))
    h=history(s,{'size':5});assert h['total']==18 and len(h['rows'])==5
    assert 'api_key_encrypted' not in dumps(h) and 'fake-new' not in dumps(h)
    assert history(s,{'q':'original-model'})['total']==18
    # Body-fetch state can coexist with a model run on separate qualified materials.
    s,w,p=seed(root/'parallel');w.body_fetcher=SimpleNamespace(active_id='fixture-body',pause=lambda **kw:None)
    w.start({'mode':'both','limit':1});wait(w);assert s.list_results({})['total']==2
    # A fixed queue first writes qualified material, then waits for body arrival.
    s,w,p=seed(root/'queue');file=root/'missing.csv';file.write_text('标题,链接\n等待正文的素材,https://fixture.invalid/material\n',encoding='utf8');s.import_file({'path':str(file)})
    q=ModelQueue(s,w);job=q.enqueue({'mode':'both','scope':'all','limit':2,'task_budget':{'article_limit':3}})
    q.tick();wait(w);q.tick();assert q.stats()['rows'][0]['state']=='waiting'
    s.save_body(2,'图书角每天18时至20时开放。老师让孩子轮流讲故事。')
    q.tick();wait(w);q.tick();assert s.list_results({})['total']==3
    assert q.stats()['rows'][0]['state']=='paused','queue reset the article budget across child runs'
    assert p.calls.count(SEED_EXTRACT)==2
    # GUI fixture with unprocessed material and multiple history pages.
    s,w,p=seed(root/'ui',6)
    with s.connect() as c:c.executemany('UPDATE materials SET read_count=? WHERE id=?',[(i*100,i) for i in range(1,7)])
    run=w.start({'mode':'both','ids':[1,2],'limit':2});wait(w)
    with s.connect() as c:
        snapshot=c.execute('SELECT snapshot_json FROM runs WHERE id=?',(run['run_id'],)).fetchone()[0]
        for i in range(25):c.execute('INSERT INTO runs(id,mode,state,total,snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(f'ui-history-{i:02}','write','completed',0,snapshot,'2026-10-31T08:00:00','2026-10-31T08:00:00'))
    import sqlite3
    fixture=ROOT/'build/operations-ui-fixture';fixture.mkdir(exist_ok=True)
    with s.connect() as c,sqlite3.connect(fixture/'workbench.sqlite3') as dest:c.backup(dest)
    (ROOT/'build/operations-ui-fixture.json').write_text(dumps({'data':str(fixture)}),encoding='utf8')
report={'ok':True,'preview_matches_exact_scope_and_order':True,'changed_preview_refused':True,'per_run_request_and_article_caps':True,'resume_refreshes_only_same_host_key':True,'original_model_and_rules_preserved':True,'counts_distinguish_calls_topics_articles':True,'selected_inside_outside_visible':True,'full_history_without_secrets':True,'fetch_and_models_coexist':True,'queue_waits_for_body_and_keeps_total_budget':True,'external_model_calls':0,'production_changes':0}
(ROOT/'build/operations-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
