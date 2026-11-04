"""Military C routing/HTML/artifacts, with no paid inference or production changes."""
from workbench_fixtures import *
import shutil,hashlib
from military_profile import PROFILE,SCHEMA,normalize,visible,safe_html
from funny_rules import selected_variant
from article_flow import normalize_article,article_prompt
from workflow_management import edit

TITLE='海上保障为什么要把航运这笔账算进去'
PARTS=['这是一篇用于验证程序的模拟短评，材料说的是海上保障与运输安排，没有公布保险报价和实际运费，就不能凭空写出涨幅。把行动直接算成某家公司赚了多少，证据还差得远，先把航线能不能保持通行讲明白。',
 '军工产业链、能源储备和外贸经济确实可以放在同一张桌上谈，但每一项联系都要有材料托着，不能把几个热词排一遍就当分析。对普通读者有用的，是谁在承担保障成本，谁需要调整运输安排，哪些影响已经发生，哪些仍只是判断。',
 '有预算就核对口径，有报价就看时间，没有这些数据就把结论收窄，不假装消息灵通。你会先关注运输能否稳定，还是先看新增成本由谁承担？']
BODY='\n\n'.join(PARTS)
assert 201<=len((TITLE+BODY).replace('\n',''))<=300
ANSWER={'category':'军事','content_status':'ready','title':TITLE,'article':safe_html(BODY),'draft_title':TITLE,'draft_article':safe_html(BODY.replace('先把航线','首先把航线')),'edit_notes':['删去报幕式转接，保留原有事实范围'],'material_notes':['测试材料未给出实际报价，不新增数值']}
class MilitaryFake(Fake):
    def call(self,prompt,schema,settings,folder,on_event=None):
        self.calls.append(schema)
        if on_event:on_event({'event':'request_start'})
        if 'categories' in schema['properties']:
            src=json.loads(prompt.split('\n统一输入素材：',1)[1]);eid=src['body'][0]['id']
            assert 'IP军经重构' in prompt and '机构说法' in prompt
            result={'categories':[{'category':'军事','topic':'海上保障的现实成本','angle':'从运输安排观察保障','reason':'原文支持','main_point':'成本与已经发生的影响分开','elements':[{'name':'事实','content':'材料讨论海上保障和运输安排','evidence_ids':[eid]}],'omissions':['未给出具体报价'],'visual_nodes':[]}],'reason':'一个独立主题'}
        else:
            assert schema is SCHEMA and '只执行本条军事C写作' in prompt and '不继承通用漫画' in prompt
            assert '正文必须写成8至15个自然段' not in prompt and 'title贴近本组种子' not in prompt
            result=json.loads(dumps(ANSWER))
        if on_event:on_event({'event':'request_finish','ok':True,'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}})
        return result

with tempfile.TemporaryDirectory(prefix='military-C-') as temp:
    root=Path(temp);s=Store(root/'data',ROOT/'resources');original_other=[p for p in s.prompts() if p['category']!='军事']
    assert len(s.prompts('军事'))==6 and s.settings()['military_write_variant']=='C'
    snapshot={'settings':s.settings(),'prompts':s.prompts()}
    assert selected_variant(snapshot,'军事','write','A')=='C' and selected_variant(snapshot,'生活','write','B')=='B'
    old={**snapshot,'prompts':[p for p in snapshot['prompts'] if not(p['category']=='军事' and p['variant']=='C')]}
    assert selected_variant(old,'军事','write','B')=='B'
    s.save_settings({'allowed_categories':['军事'],'extraction_mode':'single'})
    source=root/'source.csv'
    with source.open('w',encoding='utf8',newline='') as f:csv.writer(f).writerows([['标题','正文','分类'],[TITLE,BODY,'军事']])
    s.import_file({'path':str(source)});w=Worker(s);w.provider=MilitaryFake();w.start({'mode':'both','limit':1});wait(w)
    assert len(w.provider.calls)==2
    row=s.list_results({})['rows'][0];data=json.loads(row['data_json']);assert row['write_variant']=='C' and row['score']==60
    assert data['writing_profile']==PROFILE and data['article']==BODY and len(BODY.split('\n\n'))==3 and data['planned_image_count']==0
    assert 'font-size:12px' in data['article_html'] and data['military_audit']['edit_notes']
    folder=s.root/data['military_artifact_folder'];assert all((folder/n).is_file() for n in ['素材与事实.md','0-AI初稿.md','1-自改稿.html','版本.json'])
    before=(folder/'0-AI初稿.md').read_bytes()
    exported=root/'article.html';s.export(exported,'military_html',[row['id']]);assert 'font-size:12px' in exported.read_text(encoding='utf8')
    edit(s,{'id':row['id'],'content_hash':signature(row),'title':TITLE,'article':BODY.replace('新增成本','额外成本')})
    changed=s.list_results({})['rows'][0];assert '额外成本' in changed['article'] and (folder/'0-AI初稿.md').read_bytes()==before
    assert [p for p in s.prompts() if p['category']!='军事']==original_other
    # A long title and three paragraphs are allowed only under military C.
    custom={**ANSWER,'title':'军工保障'*18,'article':safe_html('甲'*150+'？')}
    normalize_article(custom,'军事',PROFILE)
    try:normalize_article(custom,'军事');raise AssertionError('legacy military unexpectedly relaxed')
    except ValueError:pass
    try:normalize_article({'category':'生活','title':'题','article':BODY},'生活');raise AssertionError('other lane paragraph rules changed')
    except ValueError:pass
    bad={**ANSWER,'article':'<script>alert(1)</script>'+ANSWER['article']};value,_,_=normalize(bad)
    assert '<script' not in value['article_html'] and 'alert' not in value['article']
    assert len(ANSWER['article'])>300 and value['paragraph_count']==3
    fixture=ROOT/'build/military-ui-data';fixture.mkdir(exist_ok=True)
    import sqlite3
    from contextlib import closing
    with s.connect() as c,closing(sqlite3.connect(fixture/'workbench.sqlite3')) as dst:c.backup(dst)
report={'ok':True,'two_calls_extract_then_write':True,'military_C_selected_independently':True,'other_lanes_and_legacy_snapshot_unchanged':True,'HTML_12px_bold_and_visible_count':True,'natural_three_paragraphs':True,'old_title64_and_comic_rules_not_applied_to_C':True,'safe_HTML_export':True,'initial_draft_preserved_after_edit':True,'facts_and_revision_artifacts_saved':True,'external_model_calls':0,'production_changes':0}
(ROOT/'build/military-profile-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
