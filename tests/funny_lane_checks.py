"""No paid calls: funny-only migration, profile routing and normal-lane preservation."""
from workbench_fixtures import *
from multi_extraction import compile_rules
from article_flow import article_prompt
from funny_rules import selected_variant
baseline=json.loads((ROOT/'build/funny-1005/before-prompt-library.json').read_text(encoding='utf8'))
library=json.loads((ROOT/'resources/prompt-library.json').read_text(encoding='utf8'))
assert [p for p in library['categories'] if p['category']!='搞笑']==[p for p in baseline['categories'] if p['category']!='搞笑']
funny=next(p for p in library['categories'] if p['category']=='搞笑')
assert all({p['id'] for p in funny[k]}==set('ABCDEFGH') for k in ['extraction_rules','rewrite_prompts'])
class Profiles(Fake):
    def call(self,prompt,schema,settings,folder,on_event=None):
        self.calls.append((schema,prompt));
        if on_event:on_event({'event':'request_start'})
        if schema is SEED_EXTRACT:
            assert '【搞笑 / D】' in prompt and '【生活 / B】' in prompt
            source=json.loads(prompt.split('\n统一输入素材：',1)[1]);ref=source['body'][0]
            answer={'categories':[{'category':c,'topic':t,'angle':t,'reason':'原文明确','main_point':point,'elements':[{'name':'人物动作','content':ref['text'],'evidence_ids':[ref['id']]}],'omissions':[],'visual_nodes':[]} for c,t,point in [('搞笑','帮忙与加油的误会','同事答应帮忙却只在旁边加油'),('生活','搬家现场分工','搬家前需说清实际要完成的动作')]],'reason':'适配两类'}
        else:
            assert schema is ARTICLE
            seed_data=json.loads(prompt.split('本组种子：',1)[1].split('\n本条原始素材：',1)[0])
            if seed_data['category']=='搞笑':assert '本版创作路线：让关键物件自然在前面出现' in prompt
            else:assert '本版创作路线：让关键物件自然在前面出现' not in prompt
            answer={'category':seed_data['category'],'title':seed_data['category']+'搬家现场','article':TEXT}
        if on_event:on_event({'event':'request_finish','ok':True,'usage':{'input_tokens':100,'output_tokens':50,'total_tokens':150}})
        return answer
with tempfile.TemporaryDirectory(prefix='funny-lane-') as tmp:
    root=Path(tmp);s,w,_=seed(root)
    with s.connect() as c:c.execute("UPDATE materials SET category='生活'")
    s.save_body(1,'同事答应帮我搬办公室，到了现场却把椅子挪到门边坐下。我问他怎么还不帮忙，他说坐着喊加油比较省力。')
    s.save_settings({'allowed_categories':['搞笑','生活'],'extract_variant':'B','write_variant':'B','funny_extract_variant':'D','funny_write_variant':'C'})
    w.provider=Profiles();run=w.start({'mode':'both','limit':1});wait(w)
    with s.connect() as c:
        assert {r['category']:r['rule_variant'] for r in c.execute('SELECT category,rule_variant FROM extractions')}=={'搞笑':'D','生活':'B'}
        assert {r['category']:r['write_variant'] for r in c.execute('SELECT category,write_variant FROM results')}=={'搞笑':'C','生活':'B'}
        snapshot=json.loads(c.execute('SELECT snapshot_json FROM runs WHERE id=?',(run['run_id'],)).fetchone()[0])
    assert len(w.provider.calls)==3,'profile selection added model calls'
    # Other lane uses byte-for-byte identical prompt content and generation wrapper.
    normal=next(x for x in baseline['categories'] if x['category']=='生活')['rewrite_prompts'][1]['text']
    assert normal==next(p['content'] for p in s.prompts() if p['category']=='生活' and p['kind']=='write' and p['variant']=='B')
    assert selected_variant({'settings':{}},'搞笑','write','B')=='B','old snapshots changed'
    with s.connect() as c:
        before=[tuple(r) for r in c.execute("SELECT * FROM prompts WHERE category<>'搞笑' ORDER BY id")]
        target=c.execute("SELECT id FROM prompts WHERE category='搞笑' AND kind='write' AND variant='C'").fetchone()[0]
        c.execute("UPDATE prompts SET content=content||'\n用户的自定义修订' WHERE id=?",(target,))
    s=Store(s.root,ROOT/'resources')
    with s.connect() as c:
        assert c.execute('SELECT content FROM prompts WHERE id=?',(target,)).fetchone()[0].endswith('用户的自定义修订')
        assert [tuple(r) for r in c.execute("SELECT * FROM prompts WHERE category<>'搞笑' ORDER BY id")]==before
    # Independent fresh fixture for UI profile selection, with no model execution.
    ui=ROOT/'build/funny-ui-data';ui.mkdir(exist_ok=True);Store(ui,ROOT/'resources')
report={'ok':True,'other_36_categories_byte_identical':True,'funny_has_8_extraction_and_8_writing_rules':True,'actual_variants_used_and_recorded':True,'old_snapshots_follow_original_variants':True,'custom_edits_survive_reopen':True,'one_extraction_plus_one_call_per_seed':True,'external_model_calls':0,'production_changes':0}
(ROOT/'build/funny-lane-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
