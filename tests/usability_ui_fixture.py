from workbench_fixtures import *
import sqlite3
from contextlib import closing
root=ROOT/'build'/('usability-ui-'+str(time.time_ns()));s,w,p=seed(root,12)
w.start({'mode':'both','scope':'selected','ids':[1,2],'limit':2});wait(w)
w.start({'mode':'extract','scope':'selected','ids':[3],'limit':1});wait(w)
p.fail=True;w.start({'mode':'both','scope':'selected','ids':[7],'limit':1});wait(w);p.fail=False
engine=root/'engine';(engine/'_internal').mkdir(parents=True);(engine/'fixture.exe').write_text('non-executable UI fixture',encoding='utf8')
target=root/'target';target.mkdir()
with closing(sqlite3.connect(target/'picfactory_matrix.db')) as c:
    c.execute('CREATE TABLE app_collections(namespace TEXT,item_key TEXT,payload TEXT,sort_order INTEGER,PRIMARY KEY(namespace,item_key))');c.commit()
s.save_settings({'body_tool_path':str(engine/'fixture.exe'),'body_queue_paused':True,'body_queue_pause_reason':'user','push_target_project':str(target)})
with s.connect() as c:
    c.execute("UPDATE materials SET body='',url='https://fixture.invalid/'||id,qualification='pending',body_status='missing',state='needs_source' WHERE id IN (4,5,6)")
    c.execute("UPDATE materials SET category='教育' WHERE id=5")
    results=[dict(r) for r in c.execute('SELECT id,material_id,category FROM results ORDER BY id')]
file=root/'new-import.csv';file.write_text('标题,正文,分类\n本批导入测试,用于测试批次面板的完整正文。,生活\n',encoding='utf8')
(ROOT/'build/usability-ui-fixture.json').write_text(dumps({'data':str(s.root),'target':str(target),'import_file':str(file),'results':results}),encoding='utf8')
print(dumps({'fixture':str(root),'external_model_calls':0}))
