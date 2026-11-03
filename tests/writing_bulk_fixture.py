from workbench_fixtures import *
root=ROOT/'build'/('writing-bulk-fixture-'+str(time.time_ns()))
s,w,p=seed(root,66);p.fail=True
run=w.start({'mode':'both','ids':list(range(1,66)),'limit':65});wait(w)
p.fail=False
with s.connect() as c:ids=[r[0] for r in c.execute('SELECT id FROM extractions ORDER BY id LIMIT 2')]
w.retry_seeds(ids);wait(w)
w.start({'mode':'extract','ids':[66],'limit':1});wait(w)
failed=writing_detail(s,{'state':'failed'})
assert failed['total']==128
(ROOT/'build/writing-bulk-fixture.json').write_text(dumps({'data':str(s.root),'failed':failed['total']}),encoding='utf8')
print(dumps({'fixture':str(s.root),'failed':128,'external_model_calls':0}))
