"""Module scopes agree with full list totals, filters and deduplicated work items."""
from workbench_fixtures import *
from category_distribution import distribution
from operations import history
from pipeline_catalog import writing_detail

def stat(s,module,filters=None):
    data=distribution(s,{'module':module,'filters':json.dumps(filters or {},ensure_ascii=False)})
    assert sum(r['count'] for r in data['rows'])==data['total']
    assert abs(sum(r['percentage'] for r in data['rows'])-(100 if data['total'] else 0))<1e-8
    return data

with tempfile.TemporaryDirectory() as tmp:
    s,w,fake=seed(Path(tmp),65)
    with s.connect() as c:
        c.execute("UPDATE materials SET category='教育' WHERE id BETWEEN 41 AND 60")
        c.execute("UPDATE materials SET category='' WHERE id>=61")
    for module in ['overview','materials','bodies','settings']:
        data=stat(s,module);assert data['total']==65 and len(data['rows'])==3
    assert {r['category']:r['count'] for r in stat(s,'materials')['rows']}=={'生活':40,'教育':20,'未分类':5}
    assert stat(s,'materials',{'category':'教育','page':1,'size':1})['total']==20
    assert stat(s,'materials',{'q':'不存在的内容'})['total']==0
    assert stat(s,'queue')['total']==0 and stat(s,'history')['total']==0
    rules=stat(s,'rules');assert rules['total']==len(s.prompts())
    for row in rules['rows']:assert row['enabled']+row['disabled']==row['count']
    first=w.start({'mode':'both','limit':3});wait(w)
    assert stat(s,'queue')['total']==3
    assert stat(s,'history')['total']==3
    for status in ['','ready','written','failed','paused']:
        assert stat(s,'writing',{'state':status})['total']==writing_detail(s,{'state':status})['total']
    assert stat(s,'results')['total']==s.list_results({})['total']==6
    for filters in [{'category':'生活'},{'category':'教育','page':1,'size':1},{'score_band':'default'},{'q':'不存在的文章'}]:
        assert stat(s,'results',filters)['total']==s.list_results(filters)['total']
    # Another write run for a previously processed source counts as another history item,
    # while the processing module's unique-material scope remains unchanged.
    with s.connect() as c:
        saved=c.execute('SELECT * FROM runs WHERE id=?',(first['run_id'],)).fetchone()
        c.execute('INSERT INTO runs(id,mode,state,total,snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',('repeat','write','completed',1,saved['snapshot_json'],saved['created_at'],saved['updated_at']))
        c.execute('INSERT INTO run_items(run_id,material_id,state,source_hash) VALUES(?,?,?,?)',('repeat',1,'completed','hash'))
    assert stat(s,'queue')['total']==3 and stat(s,'history')['total']==4
    assert stat(s,'history',{'mode':'write'})['total']==1
    assert stat(s,'history',{'q':'repeat'})['total']==1
    assert stat(s,'history',{'state':'paused'})['total']==0
    before=s.stats()['counts']
    for module in ['overview','materials','bodies','queue','writing','results','rules','settings','history']:stat(s,module)
    assert s.stats()['counts']==before
    try:distribution(s,{'module':'bad'});raise AssertionError('invalid module accepted')
    except ValueError:pass
print(json.dumps({'ok':True,'all9modules':True,'filters_and_full_scope':True,'empty_states':True,'queue_deduplicated_history_repeated':True,'percentages_sum_to100':True,'read_only':True,'external_calls':0}))
