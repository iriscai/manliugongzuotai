"""Only funny relaxes paragraph count, prompts, storage and editing; no API."""
from workbench_fixtures import *
from article_flow import normalize_article,article_prompt
from paragraph_policy import POLICY
from schemas import ARTICLE
from funny_singlecall import FUNNY_ARTICLE,FUNNY_J_ARTICLE
from article_quality import scored_schema
import re,copy,hashlib
import workflow_management
from writing_prompts import POLICY_VERSION

for n in [1,2,7,8,15,16,25]:
    text='\n\n\n'.join(f'第{i}句。' for i in range(n))
    result,_,_=normalize_article({'category':'搞笑','title':'自然分段','article':text},'搞笑')
    assert result['paragraph_count']==n and result['planned_image_count']==0 and result['paragraph_policy']==POLICY
    assert '\n\n' not in result['article']
    if n in (8,15):
        other,_,_=normalize_article({'category':'生活','title':'原有规格','article':text},'生活');assert other['planned_image_count']==n and '\n\n' in other['article']
    else:
        try:normalize_article({'category':'生活','title':'原有规格','article':text},'生活');raise AssertionError('other lane relaxed')
        except ValueError:pass
for category in ['搞笑','生活']:
    for title,article in [('题',' \n\n '),('题'*65,TEXT),('题','文'*301)]:
        try:normalize_article({'category':category,'title':title,'article':article},category);raise AssertionError('other validation removed')
        except ValueError:pass
assert '8至15' in dumps(ARTICLE)
for schema in [FUNNY_ARTICLE,FUNNY_J_ARTICLE,scored_schema(ARTICLE,'搞笑')]:assert '8至15' not in dumps(schema)
with tempfile.TemporaryDirectory(prefix='funny-paragraph-') as temp:
    root=Path(temp);s=Store(root/'data',ROOT/'resources');before=s.prompts()
    source={'title':'普通标题','body':'原标题提到8至15个自然段，这句话是素材，不应替换。','material_id':1,'source_category':'生活'}
    data={'topic':'本组主题','main_point':'正文重点','elements':[]};checked=0;unchanged=0
    for rule in s.prompts():
        if rule['kind']!='write':continue
        prompt=article_prompt(rule['content'],source,data,rule['category'],'本组主题','');pre_source=prompt.split('\n本条原始素材：')[0]
        if rule['category']=='搞笑':
            assert not re.search(r'8[至—–-]15.{0,6}(?:段|张)',pre_source),rule['variant']
            assert '不设段数上下限' in prompt;checked+=1
        else:
            assert 'article必须为8至15个自然段' in pre_source
            expected=hashlib.sha256(workflow_management.dump([POLICY_VERSION,rule['content'],rule['category'],rule['variant'],'']).encode()).hexdigest()
            assert workflow_management.rule_hash(rule['content'],rule['category'],rule['variant'])==expected;unchanged+=1
        assert source['body'] in prompt
    assert s.prompts()==before
    trial=ROOT/'outputs/funny-singlecall-20261031/v4/bonus';original=json.loads((trial/'result.json').read_text(encoding='utf8'))['source']
    answer=json.loads((trial/'write/answer.json').read_text(encoding='utf8'));answer['article']=''.join(line.strip() for line in answer['article'].splitlines())
    answer['quality_score']={'completeness':94,'reversal':85,'fun':85,'reason':'本地单段通路测试','evidence':[answer['article']],'risks':[]}
    class OneParagraph:
        def auth_status(self,_):return {'ok':True}
        def reset(self):pass
        def call(self,prompt,schema,settings,folder,on_event=None):
            on_event({'event':'request_start'})
            value={'categories':[],'reason':'保底测试'} if schema is SEED_EXTRACT else copy.deepcopy(answer)
            if schema is not SEED_EXTRACT:assert schema is FUNNY_ARTICLE and '8至15' not in prompt.split('\n本条原始素材：')[0]
            on_event({'event':'request_finish','ok':True,'usage':{}});return value
    s.save_settings({'allowed_categories':['搞笑'],'funny_extract_variant':'I','funny_write_variant':'I'})
    f=root/'funny.csv'
    with f.open('w',encoding='utf8',newline='') as handle:csv.writer(handle).writerows([['标题','正文','分类'],[original['title'],original['body'],'搞笑']])
    s.import_file({'path':str(f)});w=Worker(s);w.provider=OneParagraph();w.start({'mode':'both','limit':1});wait(w)
    row=s.list_results({})['rows'][0];result=json.loads(row['data_json']);rid=row['id']
    assert result['paragraph_count']==1 and result['planned_image_count']==0 and row['score']==93
    edit(s,{'id':rid,'content_hash':detail(s,rid)['content_hash'],'title':row['title'],'article':'这是完整的一段搞笑正文，按意思表达即可。'})
    f=root/'other.csv'
    with f.open('w',encoding='utf8',newline='') as handle:csv.writer(handle).writerows([['标题','正文','分类'],['图书角','图书角每天18时至20时开放。老师让孩子轮流讲故事。','生活']])
    s.import_file({'path':str(f)});s.save_settings({'allowed_categories':['生活','教育']});w.provider=Fake();w.start({'mode':'both','limit':1});wait(w)
    other=next(r for r in s.list_results({})['rows'] if r['category']=='生活')
    try:edit(s,{'id':other['id'],'content_hash':detail(s,other['id'])['content_hash'],'title':other['title'],'article':'其他赛道的一段正文仍应拒绝。'});raise AssertionError('other editor relaxed')
    except ValueError:pass
    assert s.prompts()==before
    import sqlite3,uuid
    fixture=ROOT/'build'/('natural-paragraph-ui-'+uuid.uuid4().hex[:8]);fixture.mkdir()
    with s.connect() as c,sqlite3.connect(fixture/'workbench.sqlite3') as dest:c.backup(dest)
    (ROOT/'build/natural-paragraph-ui-fixture.json').write_text(dumps({'data':str(fixture),'funny_id':rid,'other_id':other['id']}),encoding='utf8')
print(dumps({'ok':True,'funny_versions_checked':checked,'other_versions_preserved':unchanged,'funny_one_paragraph_generation_and_edit':True,'funny_above15_allowed':True,'other_count_limits_and_rule_hash_preserved':True,'source_and_stored_prompts_unchanged':True,'funny_score_stages_preserved':True,'external_calls':0}))
