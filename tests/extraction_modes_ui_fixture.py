from workbench_fixtures import *
root=ROOT/'build'/('extraction-modes-ui-'+str(time.time_ns()))
s,w,p=seed(root,3)
with s.connect() as c:
    c.execute("UPDATE materials SET category='教育' WHERE id=2")
    c.execute("UPDATE materials SET category='未知分类' WHERE id=3")
(ROOT/'build/extraction-modes-ui-fixture.json').write_text(dumps({'data':str(s.root)}),encoding='utf8')
print('Isolated extraction-modes UI fixture ready')
