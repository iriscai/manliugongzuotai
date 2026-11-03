"""Availability persists independently and disabled templates never enter new calls."""
from workbench_fixtures import *
import copy
from prompt_status import set_enabled,active_categories
from funny_rules import selected_variant
class RespectAllowed(Fake):
    def call(self,prompt,schema,settings,folder,on_event=None):
        answer=super().call(prompt,schema,settings,folder,on_event)
        if schema is SEED_EXTRACT:answer['categories']=[c for c in answer['categories'] if c['category'] in settings['allowed_categories']]
        return answer
with tempfile.TemporaryDirectory(prefix='prompt-status-') as tmp:
    root=Path(tmp);s,w,_=seed(root,3);w.provider=RespectAllowed();s.save_settings({'extract_variant':'A','write_variant':'B'})
    old_prompts=copy.deepcopy(s.prompts());old_snapshot={'settings':s.settings(),'prompts':old_prompts}
    def rule(category,kind,variant):return next(p for p in s.prompts() if (p['category'],p['kind'],p['variant'])==(category,kind,variant))
    def toggle(category,kind,variant,value):
        p=rule(category,kind,variant);return set_enabled(s,{'id':p['id'],'enabled':value,'expected_enabled':bool(p['enabled'])})
    first=rule('生活','extract','A');toggle('生活','extract','A',False)
    assert rule('生活','write','A')['enabled']==1
    before_rev=first['revision'];assert rule('生活','extract','A')['revision']==before_rev
    assert not set_enabled(s,{'id':first['id'],'enabled':False})['changed']
    try:set_enabled(s,{'id':first['id'],'enabled':True,'expected_enabled':True});raise AssertionError('stale toggle accepted')
    except ValueError:pass
    toggle('生活','write','B',False)
    run=w.start({'mode':'both','ids':[1],'limit':1});wait(w)
    with s.connect() as c:
        assert {r['category']:r['rule_variant'] for r in c.execute('SELECT category,rule_variant FROM extractions WHERE material_id=1')}=={'生活':'B','教育':'A'}
        assert {r['category']:r['write_variant'] for r in c.execute('SELECT category,write_variant FROM results WHERE material_id=1')}=={'生活':'A','教育':'B'}
    assert selected_variant(old_snapshot,'生活','extract','A')=='A','status update rewrote old snapshots'
    toggle('生活','extract','B',False)
    preview=w.start({'mode':'both','ids':[2],'limit':1,'preview':True});assert preview['disabled_categories']==['生活']
    w.start({'mode':'both','ids':[2],'limit':1});wait(w)
    with s.connect() as c:assert {r[0] for r in c.execute('SELECT category FROM results WHERE material_id=2')}=={'教育'}
    s.save_settings({'allowed_categories':['生活']});calls=len(w.provider.calls)
    try:w.start({'mode':'both','ids':[3],'limit':1});raise AssertionError('all disabled still ran')
    except ValueError:pass
    assert len(w.provider.calls)==calls
    # Writing does not require an enabled extraction template for saved seeds.
    active,_=active_categories(s.prompts(),s.settings(),'write');assert active==['生活']
    # Content, revision and original timestamps remain intact for every template.
    current={p['id']:p for p in s.prompts()}
    for old in old_prompts:
        for key in ('content','revision','name','updated_at'):assert current[old['id']][key]==old[key]
    s=Store(s.root,ROOT/'resources');assert rule('生活','extract','A')['enabled']==0
    output=root/'rules.json';s.export(output,'prompts');export=json.loads(output.read_text(encoding='utf8'));assert any(p['enabled']==0 for p in export)
    ui=ROOT/'build/prompt-status-ui-data';ui.mkdir(exist_ok=True);Store(ui,ROOT/'resources')
report={'ok':True,'independent_extraction_and_write_status':True,'disabled_versions_replaced_before_calls':True,'all_off_lane_excluded':True,'all_off_task_stops_before_calls':True,'old_snapshot_preserved':True,'content_and_revision_unchanged':True,'status_persists_and_exports':True,'external_model_calls':0,'production_changes':0}
(ROOT/'build/prompt-status-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
