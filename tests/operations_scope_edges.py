from workbench_fixtures import *
from model_queue import ModelQueue,preview
with tempfile.TemporaryDirectory(prefix='scope-edges-') as tmp:
    s,w,p=seed(Path(tmp),3);q=ModelQueue(s,w)
    def refused(fn):
        try:fn()
        except ValueError:return
        raise AssertionError('stale or partial selection accepted')
    refused(lambda:q.enqueue({'scope':'selected','ids':[1,2,3],'limit':2,'mode':'both'}))
    v=preview(s,{'scope':'selected','ids':[3,1],'limit':2});assert v['ids']==[3,1]
    s.save_settings({'api_temperature':.2})
    refused(lambda:q.enqueue({'scope':'selected','ids':v['ids'],'mode':'both',**{k:v[k] for k in ['expected_hashes','expected_urls','config_hash']}}))
    v=preview(s,{'scope':'selected','ids':[1],'limit':1})
    with s.connect() as c:c.execute("UPDATE materials SET url='https://fixture.invalid/changed' WHERE id=1")
    refused(lambda:q.enqueue({'scope':'selected','ids':v['ids'],'mode':'both',**{k:v[k] for k in ['expected_hashes','expected_urls','config_hash']}}))
    assert len(p.calls)==0
print('{"ok":true,"selected_queue_never_truncates_silently":true,"preview_rejects_changed_config_or_link":true,"external_model_calls":0}')
