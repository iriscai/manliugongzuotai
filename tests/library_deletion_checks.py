"""Isolated deletion, restore, execution guards and retained associations."""
from workbench_fixtures import *
import sqlite3
from library_deletion import plan,apply
from body_fetcher import BodyFetcher
from model_queue import ModelQueue
from title_push import TitlePusher
def mutate(s,kind,ids,action='delete'):
    p={'kind':kind,'ids':ids,'action':action};v=plan(s,p);return apply(s,{**p,'version':v['version']})
with tempfile.TemporaryDirectory(prefix='library-delete-') as tmp:
    root=Path(tmp);s,w,p=seed(root,5);run=w.start({'mode':'both','ids':[1],'limit':1});wait(w)
    result=s.list_results({})['rows'][0];rid=result['id'];eid=result['extraction_id']
    with s.connect() as c:history=[tuple(r) for r in c.execute('SELECT * FROM result_versions')]
    mutate(s,'results',[rid]);assert s.list_results({})['total']==1 and s.list_results({'visibility':'deleted'})['total']==1
    assert s.list_materials({})['total']==5 and len(s.material(1)['extractions'])==2
    out=root/'export.json';assert s.export(out)['count']==1
    calls=len(p.calls);w.retry_seeds([eid]);wait(w);assert len(p.calls)==calls,'deleted article regenerated'
    try:w.regenerate({'ids':[rid]});raise AssertionError('deleted article accepted')
    except ValueError:pass
    push=TitlePusher(s);push.sync=lambda *args,**kwargs:None;push.target=lambda:(_ for _ in ()).throw(AssertionError('external target accessed'))
    try:push.push([rid]);raise AssertionError('deleted article pushed')
    except ValueError:pass
    mutate(s,'materials',[1]);assert s.list_materials({})['total']==4 and s.list_results({})['total']==1
    assert s.list_results({})['rows'][0]['original_title']=='图书角0'
    assert w.start({'mode':'both','ids':[1],'preview':True})['ids']==[]
    mutate(s,'results',[rid],'restore');assert s.list_results({})['total']==2
    mutate(s,'materials',[1],'restore');assert s.list_materials({})['total']==5
    with s.connect() as c:assert [tuple(r) for r in c.execute('SELECT * FROM result_versions')]==history
    # Entire mixed batch is refused while any selected item is running.
    with s.connect() as c:
        c.execute("INSERT INTO runs(id,mode,state,total,snapshot_json,created_at,updated_at) VALUES('busy','both','running',1,'{}','x','x')")
        c.execute("INSERT INTO run_items(run_id,material_id,state) VALUES('busy',2,'queued')")
    v=plan(s,{'kind':'materials','ids':[2,3]});assert [r['id'] for r in v['blocked']]==[2]
    try:apply(s,{'kind':'materials','ids':[2,3],'version':v['version']});raise AssertionError('busy batch partially deleted')
    except ValueError:pass
    assert s.list_materials({})['total']==5
    with s.connect() as c:c.execute("UPDATE runs SET state='completed' WHERE id='busy'")
    v=plan(s,{'kind':'materials','ids':[3]});s.save_body(3,s.material(3)['body']+'补充一条真实动作。')
    try:apply(s,{'kind':'materials','ids':[3],'version':v['version']});raise AssertionError('stale preview accepted')
    except ValueError:pass
    # Deleted records do not enter fetch selection or a waiting model queue.
    file=root/'missing.csv';file.write_text('标题,链接\n待抓取但要删除,https://fixture.invalid/deleted\n',encoding='utf8');s.import_file({'path':str(file)})
    q=ModelQueue(s,w);job=q.enqueue({'mode':'both','scope':'selected','ids':[6],'limit':1});mutate(s,'materials',[6]);q.tick()
    assert not BodyFetcher(s).select({'ids':[6],'limit':1})
    assert q.detail(job['job_id'])['items'][0]['state']=='skipped'
    assert len(p.calls)==calls
    before=s.material(4);mutate(s,'materials',[4]);s=Store(s.root,ROOT/'resources');assert s.material(4)['deleted_at']
    mutate(s,'materials',[4],'restore');after=s.material(4)
    for key in ('title','body','qualification','state','updated_at'):assert after[key]==before[key]
    # Prepare a separate fixture, never the installed data directory.
    ui=root/'ui';ui.mkdir();us,uw,_=seed(ui,3);uw.start({'mode':'both','ids':[1],'limit':1});wait(uw)
    fixture=ROOT/'build/deletion-ui-data';fixture.mkdir(exist_ok=True)
    with us.connect() as c,sqlite3.connect(fixture/'workbench.sqlite3') as dest:c.backup(dest)
report={'ok':True,'independent_deletion_preserves_associations':True,'delete_restore_roundtrip':True,'busy_batch_atomic_refusal':True,'stale_preview_refusal':True,'deleted_material_skips_fetch_and_model_queue':True,'deleted_article_not_regenerated_or_pushed':True,'history_and_content_unchanged':True,'external_model_calls':0,'production_changes':0}
(ROOT/'build/library-deletion-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
