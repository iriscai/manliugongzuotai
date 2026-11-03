"""No API: additive prompt preservation, J routing, audits and release gate."""
from workbench_fixtures import *
from funny_singlecall import FUNNY_ARTICLE,FUNNY_J_ARTICLE,audit_result
from funny_j_profile import current_hash,release_info
from prompt_status import set_enabled
import copy

trial=ROOT/'outputs/funny-J-20261101';answer=json.loads((trial/'v2/110/answer.json').read_text(encoding='utf8'))
source=next(r for r in json.loads((trial/'today-results-snapshot.json').read_text(encoding='utf8')) if r['id']==110)
assert FUNNY_ARTICLE['properties']['title']['minLength']==60
assert 'ending_link' not in FUNNY_ARTICLE['properties']['generation_audit']['properties']
assert FUNNY_J_ARTICLE['properties']['title']['minLength']==48
class FakeJ:
    def __init__(self):self.calls=[]
    def auth_status(self,_):return {'ok':True}
    def reset(self):pass
    def call(self,prompt,schema,settings,folder,on_event=None):
        self.calls.append(schema);on_event({'event':'request_start'})
        if schema is SEED_EXTRACT:result={'categories':[],'reason':'测试原分类保底'}
        else:
            assert schema is FUNNY_J_ARTICLE and settings['api_retry_count']==1 and settings['api_retry_transient_only'] is True
            assert '方案J：单次响应' in prompt and 'material_mode' in prompt and '原本素材不足' not in prompt
            assert '你正在以素材正文' not in prompt
            result=copy.deepcopy(answer)
            if getattr(self,'missing_title_notes',False):
                result['generation_audit']['t1_short_reasons']=[]
                result['generation_audit']['t1_titles']=[t[:55+i] for i,t in enumerate(result['generation_audit']['t1_titles'])]
        on_event({'event':'request_finish','ok':True,'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}});return result

with tempfile.TemporaryDirectory(prefix='funny-J-check-') as temp:
    s=Store(Path(temp)/'data',ROOT/'resources');old=[dict(p) for p in s.prompts() if p['variant']!='J']
    j=s.prompts('搞笑');j=[p for p in j if p['variant']=='J'];assert len(j)==2 and all(not p['enabled'] for p in j)
    assert s.settings()['funny_write_variant']=='I'
    try:set_enabled(s,{'id':j[0]['id'],'enabled':True});raise AssertionError('pending J enabled')
    except ValueError:pass
    s=Store(s.root,ROOT/'resources');assert [dict(p) for p in s.prompts() if p['variant']!='J']==old
    # Explicitly bypass the gate only inside this local fixture to test the execution path.
    with s.connect() as c:c.execute("UPDATE prompts SET enabled=1 WHERE category='搞笑' AND variant='J'")
    s.save_settings({'allowed_categories':['搞笑'],'funny_extract_variant':'J','funny_write_variant':'J'})
    file=Path(temp)/'source.csv'
    with file.open('w',encoding='utf8',newline='') as f:csv.writer(f).writerows([['标题','正文','分类'],[source['source_title'],source['source_body'],'搞笑']])
    s.import_file({'path':str(file)});w=Worker(s);w.provider=FakeJ();w.start({'mode':'both','limit':1});wait(w)
    assert w.provider.calls==[SEED_EXTRACT,FUNNY_J_ARTICLE]
    r=s.list_results({})['rows'][0];data=json.loads(r['data_json'])
    assert r['write_variant']=='J' and r['score']==92 and data['generation_mode']=='funny_singlecall_J_v1'
    assert data['generation_audit']['ending_link']['punchline'] in r['article']
    # Metadata compatibility saves warning evidence and keeps publication text and score.
    w.provider.missing_title_notes=True;before=len(w.provider.calls)
    w.regenerate({'ids':[r['id']]});wait(w)
    fresh=s.list_results({})['rows'][0];meta=json.loads(fresh['data_json'])
    assert len(w.provider.calls)==before+1 and fresh['article']==r['article'] and fresh['title']==r['title'] and fresh['score']==r['score']
    assert meta['validation_audit']['warnings'] and meta['validation_audit']['changes'] and not meta['validation_audit']['publication_text_changed']
    broken=copy.deepcopy(answer);broken['generation_audit']['ending_link']['trigger']='不存在的假证据'
    try:audit_result(broken,'J');raise AssertionError('invented audit passed')
    except ValueError:pass
    p=j[0];s.save_prompt({'id':p['id'],'content':p['content']+'\n仅本地测试修改'})
    assert not next(p for p in s.prompts() if p['id']==j[0]['id'])['enabled']
    try:set_enabled(s,{'id':p['id'],'enabled':True});raise AssertionError('edited J enabled')
    except ValueError:pass
    assert [dict(p) for p in s.prompts() if p['variant']!='J']==old
print(dumps({'ok':True,'old_prompts_unchanged':True,'J_pending_and_gated':True,'J_single_call_stages_and_score':True,'fallback_uses_J':True,'I_schema_preserved':True,'exact_ending_evidence':True,'external_calls':0}))
