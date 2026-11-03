"""No network: gate enforcement, one-call artifacts and unchanged other lanes."""
from workbench_fixtures import *
import shutil
from funny_singlecall import FUNNY_ARTICLE,approved_release,content_hash
from prompt_status import set_enabled
trial=ROOT/'outputs/funny-singlecall-20261031';source=json.loads((trial/'v4/bonus/result.json').read_text(encoding='utf8'))['source']
extract=json.loads((trial/'v4/bonus/extract/answer.json').read_text(encoding='utf8'));answer=json.loads((trial/'v4/bonus/write/answer.json').read_text(encoding='utf8'))
baseline=json.loads((trial/'before-library.json').read_text(encoding='utf8'));library=json.loads((ROOT/'resources/prompt-library.json').read_text(encoding='utf8'))
answer['quality_score']={'completeness':94,'reversal':85,'fun':85,'reason':'奖金与自付庆功宴账本对应，结尾有金额反差。','evidence':[answer['article'].splitlines()[-1]],'risks':[]}
assert [x for x in baseline['categories'] if x['category']!='搞笑']==[x for x in library['categories'] if x['category']!='搞笑']
class OneCall:
    def __init__(self):self.calls=[]
    def auth_status(self,_):return {'ok':True}
    def call(self,prompt,schema,settings,folder,on_event=None):
        self.calls.append(schema)
        if on_event:on_event({'event':'request_start'})
        if schema is SEED_EXTRACT:result=extract
        else:
            assert schema is FUNNY_ARTICLE and settings['api_retry_count']==1 and settings['api_retry_transient_only'] is True
            assert '五个JSON字段' in prompt and '标题泄底专查' in prompt and 'completeness故事完整性' in prompt
            result=answer
        if on_event:on_event({'event':'request_finish','ok':True,'usage':{'input_tokens':100,'output_tokens':100,'total_tokens':200}})
        return result
    def reset(self):pass
with tempfile.TemporaryDirectory(prefix='singlecall-check-') as tmp:
    root=Path(tmp);s=Store(root/'data',ROOT/'resources');s.save_settings({'allowed_categories':['搞笑']})
    p=s.prompts('搞笑');assert len([x for x in p if x['variant']!='J'])==18 and {x['variant'] for x in p if x['enabled'] and x['variant']!='J'}=={'I'}
    assert s.settings()['funny_write_variant']=='I'
    file=root/'source.csv'
    with file.open('w',encoding='utf-8-sig',newline='') as f:csv.writer(f).writerows([['标题','正文','分类'],[source['title'],source['body'],'搞笑']])
    s.import_file({'path':str(file)});w=Worker(s);fake=OneCall();w.provider=fake;w.start({'mode':'both','limit':1});wait(w)
    assert fake.calls==[SEED_EXTRACT,FUNNY_ARTICLE]
    r=s.list_results({})['rows'][0];data=json.loads(r['data_json']);assert data['generation_audit']['t1_titles']==answer['generation_audit']['t1_titles']
    assert data['generation_mode']=='funny_singlecall_I_v1' and r['write_variant']=='I'
    assert r['score_status']=='scored' and r['score']==93 and r['push_category']=='搞笑漫画-优秀'
    ui=ROOT/'build/singlecall-ui-data';ui.mkdir(exist_ok=True)
    import sqlite3
    with s.connect() as c,sqlite3.connect(ui/'workbench.sqlite3') as dest:c.backup(dest)
    other=[x for x in s.prompts() if x['category']!='搞笑'];rule=next(p for p in s.prompts('搞笑') if p['kind']=='write' and p['variant']=='I')
    s.save_prompt({'id':rule['id'],'content':rule['content']+'\n本地试改'})
    assert next(p for p in s.prompts('搞笑') if p['id']==rule['id'])['enabled']==0
    try:set_enabled(s,{'id':rule['id'],'enabled':True});raise AssertionError('unscored edit enabled')
    except ValueError:pass
    s=Store(s.root,ROOT/'resources');assert next(p for p in s.prompts('搞笑') if p['id']==rule['id'])['content'].endswith('本地试改')
    assert [p for p in s.prompts() if p['category']!='搞笑']==other
    # A missing/corrupted score bundle never enables the candidate.
    pending=root/'pending';shutil.copytree(ROOT/'resources',pending);(pending/'funny-singlecall-scores.json').write_text('[]',encoding='utf8')
    assert approved_release(pending)['status']=='pending'
    ps=Store(root/'pending-data',pending);pr=next(p for p in ps.prompts('搞笑') if p['variant']=='I' and p['kind']=='write');assert not pr['enabled']
    try:set_enabled(ps,{'id':pr['id'],'enabled':True});raise AssertionError('unapproved candidate enabled')
    except ValueError:pass
report={'ok':True,'only_funny_I_enabled_after_score_gate':True,'one_extraction_plus_one_generation_request':True,'actual_artifacts_saved':True,'unscored_edit_cannot_enable':True,'invalid_score_bundle_stays_disabled':True,'other_36_lanes_unchanged':True,'external_model_calls':0,'production_changes':0}
(ROOT/'build/singlecall-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
