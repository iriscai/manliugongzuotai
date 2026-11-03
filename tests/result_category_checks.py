"""Article categories must come from generated results, including historical lanes."""
from workbench_fixtures import *
import sqlite3
with tempfile.TemporaryDirectory(prefix='result-categories-') as tmp:
    root=Path(tmp);s,w,p=seed(root,2);w.start({'mode':'both','limit':2});wait(w)
    def counts(q=None):return {r['category']:r['count'] for r in s.list_results(q or {})['categories']}
    assert counts()=={'生活':2,'教育':2}
    with s.connect() as c:
        c.execute("UPDATE materials SET category='国际'")
        legacy=c.execute("SELECT id FROM results WHERE category='教育' LIMIT 1").fetchone()[0]
        c.execute("UPDATE results SET category='历史赛道',title='历史作品' WHERE id=?",(legacy,))
    assert counts()=={'生活':2,'教育':1,'历史赛道':1} and '国际' not in counts()
    r=s.list_results({'category':'教育','size':1,'page':5});assert r['total']==1 and r['page']==1 and all(x['category']=='教育' for x in r['rows'])
    assert counts({'category':'教育'})==counts()
    assert counts({'q':'历史作品'})=={'历史赛道':1}
    ids=selected_ids(s,{'all_filtered':True,'filters':{'category':'教育'}});assert ids==[r['rows'][0]['id']]
    output=root/'export.json';assert s.export(output,filters={'category':'教育'})['count']==1
    assert {x['赛道'] for x in json.loads(output.read_text(encoding='utf8'))}=={'教育'}
    with s.connect() as c:c.execute("UPDATE results SET cleared_at='2026-10-31' WHERE id=?",(legacy,))
    assert '历史赛道' not in counts() and counts({'visibility':'cleared'})=={'历史赛道':1}
    assert counts({'visibility':'all'})=={'生活':2,'教育':1,'历史赛道':1}
    with s.connect() as c:c.execute("UPDATE results SET cleared_at='' WHERE id=?",(legacy,))
    fixture=ROOT/'build/result-category-ui-data';fixture.mkdir(exist_ok=True)
    with s.connect() as c,sqlite3.connect(fixture/'workbench.sqlite3') as dest:c.backup(dest)
report={'ok':True,'uses_generated_categories_not_source_or_rules':True,'historical_lanes_included':True,'counts_follow_search_and_visibility':True,'category_scope_matches_selection_and_export':True,'external_model_calls':0,'production_changes':0}
(ROOT/'build/result-category-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
