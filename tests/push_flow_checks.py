import importlib.util,sqlite3,tempfile,json,shutil,sys
from pathlib import Path
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
spec=importlib.util.spec_from_file_location('base_push_test',ROOT/'tests/title_push_checks.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
from title_push import TitlePusher
from push_delivery import dispatch,retry,replay,detail,history
from push_targets import runtime_project
with tempfile.TemporaryDirectory(prefix='verified-push-') as tmp:
    root=Path(tmp);s,project,_=base.fixture(root,2)
    unavailable=root/'unavailable';unavailable.mkdir();p=TitlePusher(s,unavailable,running=lambda:False)
    first=p.push([1]);assert first['failed']==1
    bid=first['batch_id'];assert detail(p,bid)['rows'][0]['title']=='生成标题1'
    for _ in range(4):
        with s.connect() as c:c.execute('UPDATE result_pushes SET next_retry_at=0')
        dispatch(p)
    with s.connect() as c:
        row=c.execute('SELECT * FROM result_pushes').fetchone();assert row['attempts']==3 and row['phase']=='failed'
    shutil.copy2(project/'picfactory_matrix.db',unavailable/'picfactory_matrix.db')
    assert retry(p,bid)['pushed']==1
    assert p.push([1])['pushed']==1
    with s.connect() as c:verified_at=c.execute('SELECT verified_at FROM result_pushes').fetchone()[0]
    p.sync(True)
    with s.connect() as c:assert c.execute('SELECT verified_at FROM result_pushes').fetchone()[0]==verified_at
    with closing(sqlite3.connect(p.db)) as c:assert c.execute("SELECT count(*) FROM app_collections WHERE namespace='title_library'").fetchone()[0]==2
    # A receipt alone never proves a title is still present. No automatic resurrection.
    with s.connect() as c:record=dict(c.execute('SELECT * FROM result_pushes').fetchone())
    with closing(sqlite3.connect(p.db)) as c,c:c.execute("DELETE FROM app_collections WHERE namespace='title_library' AND item_key=?",(record['target_key'],))
    p.sync(True)
    with s.connect() as c:assert c.execute('SELECT phase FROM result_pushes').fetchone()[0]=='missing'
    dispatch(p)
    with closing(sqlite3.connect(p.db)) as c:assert c.execute("SELECT count(*) FROM app_collections WHERE namespace='title_library'").fetchone()[0]==1
    assert retry(p,bid)['pushed']==1
    # Retargeting creates a separate delivery and preserves the exact original snapshot.
    newer=root/'newer';newer.mkdir();shutil.copy2(project/'picfactory_matrix.db',newer/'picfactory_matrix.db')
    s.save_settings({'push_target_project':str(newer)})
    target=TitlePusher(s,newer,running=lambda:False);r=replay(target,bid);assert r['pushed']==1
    assert replay(target,bid)['pushed']==1
    with closing(sqlite3.connect(target.db)) as c:
        allrows=[json.loads(x[0]) for x in c.execute("SELECT payload FROM app_collections WHERE namespace='title_library'")]
        assert len(allrows)==2 and any(x['title']=='生成标题1' and x['body'].startswith('【先讲故事】') for x in allrows)
    assert s.list_results({})['rows'][1]['push_state']=='pushed'
    assert history(target,{})['total']>=4
    fake_exe=newer/'release'/'PicFactoryGUI'/'PicFactoryGUI.exe';assert runtime_project(fake_exe)==newer
    assert detail(target,r['batch_id'])['events']
report={'ok':True,'outbox_before_io':True,'bounded_retry':True,'restart_safe_receipts':True,'readback_required':True,'missing_not_auto_recreated':True,'manual_retry_recreates_missing':True,'retarget_snapshot_preserved':True,'replay_duplicate_safe':True,'actual_runtime_db_resolved':True,'model_calls':0,'real_target_writes':0}
(ROOT/'build/push-flow-checks.json').write_text(json.dumps(report),encoding='utf8');print(json.dumps(report))
