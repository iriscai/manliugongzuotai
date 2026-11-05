"""Local-only C-G boundaries, routing, provenance, drafts and existing-rule preservation."""
from workbench_fixtures import *
import copy,hashlib,sqlite3
from contextlib import closing
from military_profile import PROFILES,SCHEMAS,SCHEMA,CONTRACT,contract_for,profile_for,normalize,prepare_answer,safe_html,visible
from article_flow import normalize_article
from workflow_management import edit

def sample(variant):
    title='测试素材的保障条件要分开看'
    length={'C':480,'D':500,'E':520,'F':1300,'G':730}[variant]
    # Synthetic filler exercises storage and counting only; it is not a military-quality sample.
    text=('这是虚构程序测试材料，仅验证字符和段落计数，不作为真实军事事实。'*60)[:length]
    text=text[:-1]+('？' if PROFILES[variant]['question'] else '。')
    body='\n\n'.join([text[:100],text[100:200],text[200:]])
    raw=safe_html(body)
    if variant=='F':raw=raw.replace('<p style="font-size:12px;font-weight:bold;margin:0 0 12px">','<h3>测试章节</h3><p style="font-size:12px;font-weight:bold;margin:0 0 12px">',1)
    return {'category':'军事','content_status':'ready','title':title,'article':raw,'draft_title':title,'draft_article':raw,'edit_notes':['测试替换一个口语转接，不添事实'],'material_notes':[]}

class VersionFake(Fake):
    def __init__(self,variant):super().__init__();self.variant=variant
    def call(self,prompt,schema,settings,folder,on_event=None):
        self.calls.append(schema)
        if on_event:on_event({'event':'request_start'})
        if 'categories' in schema['properties']:
            src=json.loads(prompt.split('\n统一输入素材：',1)[1]);eid=src['body'][0]['id']
            assert '军事'+self.variant+'｜' in prompt
            result={'categories':[{'category':'军事','topic':'虚构测试的保障条件','angle':'区分测试中的不同条件','reason':'仅程序测试','main_point':'以输入为依据','elements':[{'name':'事实','content':'本条是虚构测试输入','evidence_ids':[eid]}],'omissions':[],'visual_nodes':[]}],'reason':'一个测试主题'}
        else:
            assert schema is SCHEMAS[self.variant] and '只执行本条军事'+self.variant+'写作' in prompt
            assert 'article必须为8至15个自然段' not in prompt
            result=sample(self.variant)
        if on_event:on_event({'event':'request_finish','ok':True,'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}})
        return result

assert SCHEMAS['C'] is SCHEMA and contract_for(SCHEMA)==CONTRACT
original=copy.deepcopy(SCHEMAS['D']);SCHEMAS['E']['properties']['title']['temporary_test']=True
assert SCHEMAS['D']==original and 'temporary_test' not in SCHEMA['properties']['title']
del SCHEMAS['E']['properties']['title']['temporary_test']
for variant in 'CDEFG':
    value,count,_=normalize(sample(variant),profile_for(variant));assert value['writing_profile']==profile_for(variant)
    bad=sample(variant);bad['article']=safe_html('字'*50+'？')
    try:normalize(bad,profile_for(variant));raise AssertionError('short text accepted')
    except ValueError:pass
assert normalize(sample('E'),profile_for('E'))[0]['article'].endswith('。')
assert normalize(sample('G'),profile_for('G'))[0]['article'].endswith('。')
bad=sample('F');bad['title']='长'*31
try:normalize(bad,profile_for('F'));raise AssertionError('F title limit ignored')
except ValueError:pass
try:normalize_article(sample('G'),'生活',profile_for('G'));raise AssertionError('relaxed another lane')
except ValueError:pass

with tempfile.TemporaryDirectory(prefix='military-versions-') as temp:
    root=Path(temp);s=Store(root/'data',ROOT/'resources');assert len(s.prompts('军事'))==14
    assert s.settings()['military_write_variant']=='C'
    original_other=[p for p in s.prompts() if p['category']!='军事']
    for variant in 'DEFG':
        s.save_settings({'allowed_categories':['军事'],'extraction_mode':'single','military_extract_variant':variant,'military_write_variant':variant})
        path=root/(variant+'.csv')
        with path.open('w',encoding='utf8',newline='') as f:csv.writer(f).writerows([['标题','正文','分类','链接'],[variant+'版虚构程序测试','测试五条动作、时间、数字、口径和结果，仅作程序验证。'+variant,'军事','https://example.invalid/'+variant+'x'*250]])
        s.import_file({'path':str(path)});mid=max(r['id'] for r in s.list_materials({})['rows'])
        w=Worker(s);w.provider=VersionFake(variant);w.start({'mode':'both','limit':1,'ids':[mid]});wait(w)
        assert len(w.provider.calls)==2,(variant,len(w.provider.calls))
        row=next(r for r in s.list_results({})['rows'] if r['write_variant']==variant);data=json.loads(row['data_json'])
        assert row['score']==60 and row['writing_policy']==profile_for(variant)
        folder=s.root/data['military_artifact_folder'];assert json.loads((folder/'版本.json').read_text(encoding='utf8'))['profile']==profile_for(variant)
        before=(folder/'0-AI初稿.md').read_bytes()
        if variant=='G':
            assert '资料来源' not in row['article'] and '输入素材' not in row['article'] and data['body_char_count']==730
            assert 'https://example.invalid/G' in (folder/'素材与事实.md').read_text(encoding='utf8') # Provenance stays internal.
            edit(s,{'id':row['id'],'content_hash':signature(row),'title':'修改后的测试标题','article':row['article']})
            assert (folder/'0-AI初稿.md').read_bytes()==before
        if variant=='F':assert '<h3 ' in data['article_html'] and data['military_headings']==['测试章节']
        destination=root/(variant+'.html');s.export(destination,'military_html',[row['id']]);assert 'font-size:12px' in destination.read_text(encoding='utf8')
    assert [p for p in s.prompts() if p['category']!='军事']==original_other
    fixture=ROOT/'build/military-versions-ui-data';fixture.mkdir(exist_ok=True)
    with s.connect() as c,closing(sqlite3.connect(fixture/'workbench.sqlite3')) as dst:c.backup(dst)

baseline=ROOT/'build/military-versions-20261104/before'
for name in ['military-C-extract.txt','military-C-write.txt']:assert (ROOT/'resources'/name).read_text(encoding='utf8').startswith((baseline/'resources'/name).read_text(encoding='utf8').rstrip())
with tempfile.TemporaryDirectory(prefix='military-existing-') as temp:
    path=Path(temp)
    with closing(sqlite3.connect((baseline/'workbench.sqlite3').as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(path/'workbench.sqlite3')) as dst:
        src.row_factory=sqlite3.Row;before=[dict(r) for r in src.execute('SELECT * FROM prompts ORDER BY id')];src.backup(dst)
    store=Store(path,ROOT/'resources')
    after={r['id']:r for r in store.prompts()};assert all(after[r['id']]==r for r in before if r['category']!='军事')
    from military_ip_style import WRITE_MARKER,EXTRACT_MARKER
    assert all((WRITE_MARKER if r['kind']=='write' else EXTRACT_MARKER) in after[r['id']]['content'] for r in before if r['category']=='军事')
    assert len(after)==len(before)+8 and store.settings()['military_write_variant']=='C'
report={'ok':True,'new_versions':list('DEFG'),'two_fake_calls_each':True,'independent_length_and_ending_policies':True,'F_headings_and_title_limit':True,'G_private_provenance_and_body_count':True,'drafts_and_edit_preservation':True,'existing_nonmilitary_prompts_unchanged':sum(r['category']!='军事' for r in before),'C_resource_base_preserved_IP_overlay_added':True,'default_C_unchanged':True,'external_model_calls':0,'production_changes':0}
(ROOT/'build/military-versions-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
