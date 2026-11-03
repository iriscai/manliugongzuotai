"""Exercise delivery against isolated SQLite libraries, never the real title bank."""
import csv,importlib.util,json,sqlite3,sys,tempfile,threading,time,uuid
from pathlib import Path
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,dumps,digest,now
from title_push import TitlePusher
spec=importlib.util.spec_from_file_location('factory_receiver','D:/BIGDATA/CODES/PyCharmFiles/Factorys/ReferenceImageBatchFactory/title_library_bridge.py');receiver=importlib.util.module_from_spec(spec);spec.loader.exec_module(receiver)
def fixture(root,count):
    s=Store(root/'data',ROOT/'resources');p=root/'input.csv'
    with p.open('w',encoding='utf8',newline='') as f:
        w=csv.writer(f);w.writerow(['标题','正文','分类']);w.writerows((f'原始标题{i}','图书角开放时孩子轮流讲故事，家长把孩子的问题记下来，阅读区留出通行空间。','生活') for i in range(1,count+1))
    s.import_file({'path':str(p)})
    with s.connect() as c:
        for mid in range(1,count+1):
            eid=c.execute('INSERT INTO extractions(material_id,category,angle,source_hash,rule_variant,prompt_text,data_json,created_at) VALUES(?,?,?,?,?,?,?,?)',(mid,'生活','阅读安排','hash','A','fixture',dumps({'eligible':True}),now())).lastrowid
            article='【先讲故事】\n孩子轮流讲故事。\n\n【再记问题】\n家长把问题记下来。'
            c.execute('INSERT INTO results(extraction_id,material_id,category,title,short_text,article,data_json,char_count,frame_count,state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(eid,mid,'生活',f'生成标题{mid}',article,article,'{}',len(article),0,'成品',now()))
    project=root/'factory';project.mkdir();db=project/'picfactory_matrix.db'
    with closing(sqlite3.connect(db)) as c,c:
        c.execute('CREATE TABLE app_collections(namespace TEXT,item_key TEXT,payload TEXT,sort_order INTEGER DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(namespace,item_key))')
        existing={'uuid':'existing','title':'原库文章','body':'保留原库正文','category':'旧分类','status':'停用','used':True,'used_at':'原使用时间'}
        c.execute("INSERT INTO app_collections(namespace,item_key,payload) VALUES('title_library','existing',?)",(dumps(existing),))
    return s,project,existing

with tempfile.TemporaryDirectory(prefix='title-push-') as tmp:
    s,project,existing=fixture(Path(tmp),3);p=TitlePusher(s,project,running=lambda:False)
    report=p.push([1,3]);assert report['pushed']==2
    assert p.push([1,3])['pushed']==2
    with closing(sqlite3.connect(project/'picfactory_matrix.db')) as c,c:
        rows=[json.loads(r[0]) for r in c.execute("SELECT payload FROM app_collections WHERE namespace='title_library'")]
        assert len(rows)==3 and existing in rows
        new=[x for x in rows if x.get('source_app')];assert {x['source_result_id'] for x in new}=={1,3}
        assert all('\n\n' in x['body'] and x['category']=='生活' and x['status']=='启用' and not x['used'] for x in new)
    # Open receiver: enqueue, merge into its cached list, then acknowledge.
    memory={'title_library':rows.copy()};open_p=TitlePusher(s,project,running=lambda:True)
    def consume():
        for _ in range(30):
            if receiver.receive_pending(memory,project/'picfactory_matrix.db'):return
            time.sleep(.05)
    t=threading.Thread(target=consume);t.start();assert open_p.push([2])['pushed']==1;t.join(3)
    assert len(memory['title_library'])==4
    # A subsequent full-list save from the target preserves the delivered record.
    with closing(sqlite3.connect(project/'picfactory_matrix.db')) as c,c:
        c.execute("DELETE FROM app_collections WHERE namespace='title_library'")
        c.executemany("INSERT INTO app_collections(namespace,item_key,payload) VALUES('title_library',?,?)",[(x['uuid'],dumps(x)) for x in memory['title_library']])
        assert c.execute("SELECT count(*) FROM app_collections WHERE namespace='title_library'").fetchone()[0]==4
    # Changing the generated content creates a new delivery version, retaining the old one.
    with s.connect() as c:c.execute("UPDATE results SET title='生成标题1的新版本' WHERE id=1")
    assert p.push([1])['pushed']==1
    with closing(sqlite3.connect(project/'picfactory_matrix.db')) as c:assert c.execute("SELECT count(*) FROM app_collections WHERE namespace='title_library'").fetchone()[0]==5
    for invalid in [[],[True],[999],[1,'2']]:
        try:p.push(invalid);raise AssertionError('Invalid selection was accepted')
        except ValueError:pass

# Persistent fixture for the native Electron UI test, containing no API credentials.
ui=ROOT/'build'/('push-ui-fixture-'+uuid.uuid4().hex[:6]);ui.mkdir()
if (ui/'data/workbench.sqlite3').exists():raise RuntimeError('Use a fresh UI fixture directory')
s,project,_=fixture(ui,31)
info={'data':str(s.root),'target_project':str(project),'target_db':str(project/'picfactory_matrix.db')}
(ROOT/'build/push-ui-fixture.json').write_text(dumps(info),encoding='utf8')
print(dumps({'ok':True,'selected_only':True,'duplicate_safe':True,'receiver_cache_updated':True,'paragraphs_preserved':True,'consumed_state_preserved':True,'content_versions_independent':True,'model_calls':0,'real_target_writes':0}))
