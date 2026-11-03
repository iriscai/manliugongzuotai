"""Explicit exclusions and execution of only the frozen, eligible subset."""
from workbench_fixtures import *
from model_queue import preview as queue_preview,ModelQueue
with tempfile.TemporaryDirectory() as tmp:
    s,w,fake=seed(Path(tmp)/'direct',30);s.save_settings({'run_size':20})
    ids=list(range(1,31));payload={'mode':'both','scope':'selected','ids':ids,'limit':30}
    assert len(w.start({**payload,'preview':True})['ids'])==30
    limited=w.start({**payload,'limit':20,'preview':True});assert len(limited['ids'])==20
    assert len(limited['excluded_rows'])==10 and all('本轮' in x['reason'] for x in limited['excluded_rows'])
    with s.connect() as c:
        c.execute("UPDATE materials SET state='written' WHERE id=1")
        c.execute("UPDATE materials SET state='needs_source',body='',body_status='missing',qualification='pending' WHERE id=2")
        c.execute("UPDATE materials SET state='skipped' WHERE id=3")
        c.execute("UPDATE materials SET deleted_at='2026-11-01T12:00:00' WHERE id=4")
    ready=w.start({**payload,'preview':True});assert len(ready['ids'])==26
    reasons={r['id']:r['reason'] for r in ready['excluded_rows']}
    assert '已生成' in reasons[1] and '正文' in reasons[2] and '适配' in reasons[3] and '删除' in reasons[4]
    assert len(fake.calls)==0,'Preview must never call a model'
    w.start({**payload,'ids':ready['ids'],'expected_hashes':ready['expected_hashes'],'config_hash':ready['config_hash']});wait(w)
    assert s.list_results({})['total']==52
    assert s.material(2)['state']=='needs_source' and s.material(3)['state']=='skipped'
    s,w,fake=seed(Path(tmp)/'queued',3)
    with s.connect() as c:
        c.execute("UPDATE materials SET state='written' WHERE id=1")
        c.execute("UPDATE materials SET state='needs_source',body='',body_status='missing',qualification='pending' WHERE id=2")
    payload={'mode':'both','scope':'selected','ids':[1,2,3],'limit':3};p=queue_preview(s,payload)
    assert p['ids']==[2,3] and p['excluded_rows'][0]['id']==1 and p['rows'][0]['waiting_body']
    queued=ModelQueue(s,w).enqueue({**payload,'ids':p['ids'],'expected_hashes':p['expected_hashes'],'expected_urls':p['expected_urls'],'config_hash':p['config_hash']})
    assert queued['total']==2 and len(fake.calls)==0
print(json.dumps({'ok':True,'selected30_accepted':True,'explicit_exclusions':True,'frozen_subset_executes':True,'queue_waits_for_missing_body':True,'preview_has_no_model_calls':True,'production_changes':0}))
