"""Local-only: explicit manual trial does not forge a J quality approval."""
from workbench_fixtures import *
from prompt_status import set_enabled
from funny_rules import selected_variant
import uuid
with tempfile.TemporaryDirectory(prefix='J-manual-trial-') as temp:
    s=Store(Path(temp)/'data',ROOT/'resources');s.save_settings({'body_queue_paused':True,'body_queue_pause_reason':'user'})
    old=[p for p in s.prompts() if p['variant']!='J'];validation=s.settings()['funny_J_validation']
    p=next(p for p in s.prompts('搞笑') if p['variant']=='J' and p['kind']=='write')
    for payload in [{'id':p['id'],'enabled':True},{'id':p['id'],'enabled':True,'trial_enable':True},{'id':p['id'],'enabled':True,'trial_enable':True,'expected_revision':p['revision']+1}]:
        try:set_enabled(s,payload);raise AssertionError('implicit/stale trial allowed')
        except ValueError:pass
    result=set_enabled(s,{'id':p['id'],'enabled':True,'trial_enable':True,'expected_revision':p['revision'],'expected_enabled':False})
    assert result['trial'] and result['enabled']
    assert s.settings()['funny_J_validation']==validation and validation['status']=='pending'
    trial=s.settings()['funny_J_trial']['write'];assert trial['revision']==p['revision'] and trial['source']=='manual_trial'
    s.save_settings({'funny_write_variant':'J'})
    assert selected_variant({'settings':s.settings(),'prompts':s.prompts()},'搞笑','write','A')=='J'
    s=Store(s.root,ROOT/'resources');assert next(x for x in s.prompts() if x['id']==p['id'])['enabled']==1
    assert s.settings()['funny_J_validation']==validation and [x for x in s.prompts() if x['variant']!='J']==old
    set_enabled(s,{'id':p['id'],'enabled':False,'expected_enabled':True})
    assert not next(x for x in s.prompts() if x['id']==p['id'])['enabled']
    set_enabled(s,{'id':p['id'],'enabled':True,'trial_enable':True,'expected_revision':p['revision']})
    s.save_prompt({'id':p['id'],'content':p['content']+'\n仅本地测试修改'})
    assert not next(x for x in s.prompts() if x['id']==p['id'])['enabled']
    assert s.settings()['funny_J_validation']['status']=='needs_trial'
    assert [x for x in s.prompts() if x['variant']!='J']==old
    # A fresh UI fixture always starts with J disabled and the real pending score.
    fixture=ROOT/'build'/('J-manual-ui-'+uuid.uuid4().hex[:8]);store=Store(fixture,ROOT/'resources');store.save_settings({'body_queue_paused':True,'body_queue_pause_reason':'user'})
    (ROOT/'build/J-manual-ui-fixture.json').write_text(dumps({'data':str(fixture)}),encoding='utf8')
print(dumps({'ok':True,'explicit_J_trial_enable':True,'pending_score_record_preserved':True,'revision_guard':True,'restart_preserves_trial':True,'disable_and_edit_invalidation':True,'old_prompts_unchanged':True,'external_calls':0}))
