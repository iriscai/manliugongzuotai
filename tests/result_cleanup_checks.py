"""Clear only confirmed current versions; preserve completion and both libraries."""
import json,runpy,sqlite3,tempfile,sys
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
fixture=runpy.run_path(str(ROOT/'tests/title_push_checks.py'))['fixture']
import result_cleanup,title_push
from title_push import TitlePusher,signature
from worker import Worker
with tempfile.TemporaryDirectory(prefix='result-cleanup-') as tmp:
    store,project,_=fixture(Path(tmp),6);result_cleanup.PROJECT=title_push.PROJECT=project
    p=TitlePusher(store,project,running=lambda:False);assert p.push([1,2,5,6])['pushed']==4
    with store.connect() as c:
        c.execute("UPDATE results SET title='新版本尚未推送' WHERE id=2")
        for rid,state in [(3,'pending'),(4,'failed')]:
            row=dict(c.execute('SELECT * FROM results WHERE id=?',(rid,)).fetchone())
            c.execute('INSERT INTO result_pushes(result_id,target_path,content_hash,delivery_id,title,article,category,state,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(rid,str(project/'picfactory_matrix.db'),signature(row),'fixture-'+str(rid),row['title'],row['article'],row['category'],state,'测试时间'))
        materials=[tuple(r) for r in c.execute('SELECT * FROM materials ORDER BY id')]
        seeds=[tuple(r) for r in c.execute('SELECT * FROM extractions ORDER BY id')]
        pushes=[tuple(r) for r in c.execute('SELECT * FROM result_pushes ORDER BY result_id')]
    with closing(sqlite3.connect(project/'picfactory_matrix.db')) as c:target=c.execute('SELECT * FROM app_collections ORDER BY item_key').fetchall()
    assert store.list_results({})['clearable_count']==3
    with patch('pathlib.Path.write_text',side_effect=OSError('模拟磁盘写入失败')):
        try:result_cleanup.clear_pushed(store);raise AssertionError('Cleanup ignored failed backup')
        except OSError:pass
    assert store.list_results({})['total']==6
    report=result_cleanup.clear_pushed(store);assert report['count']==3 and report['ids']==[1,5,6]
    backup=json.loads(Path(report['backup_path']).read_text(encoding='utf8'));assert backup['count']==3 and len(backup['push_receipts'])==3
    assert {r['id'] for r in store.list_results({})['rows']}=={2,3,4}
    assert store.list_results({})['clearable_count']==0 and store.stats()['writing']['ready']==0
    assert result_cleanup.clear_pushed(store)['count']==0
    assert store.material(1)['results']==[] and store.material(1)['extractions']
    exported=Path(tmp)/'results.json';store.export(exported);assert len(json.loads(exported.read_text(encoding='utf8')))==3
    with store.connect() as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM materials ORDER BY id')]==materials
        assert [tuple(r) for r in c.execute('SELECT * FROM extractions ORDER BY id')]==seeds
        assert [tuple(r) for r in c.execute('SELECT * FROM result_pushes ORDER BY result_id')]==pushes
        assert c.execute('SELECT count(*) FROM results WHERE current=1').fetchone()[0]==6
        assert c.execute('SELECT count(*) FROM result_cleanup_batches').fetchone()[0]==1
    with closing(sqlite3.connect(project/'picfactory_matrix.db')) as c:assert c.execute('SELECT * FROM app_collections ORDER BY item_key').fetchall()==target
    try:Worker(store).start({'mode':'write','limit':6});raise AssertionError('Cleared seeds became writable')
    except ValueError as exc:assert '没有尚未生成文章' in str(exc)
    try:p.push([1]);raise AssertionError('Hidden article was submitted')
    except ValueError:pass
print(json.dumps({'ok':True,'only_confirmed_current_versions_cleared':True,'pending_failed_and_new_versions_retained':True,'backup_before_clear':True,'backup_failure_aborts_clear':True,'sources_seeds_and_target_unchanged':True,'no_unintended_regeneration':True,'repeat_clear_safe':True,'model_calls':0,'real_articles_cleared':0},ensure_ascii=False))
