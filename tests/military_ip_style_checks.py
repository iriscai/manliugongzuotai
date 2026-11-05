"""Military-only migration, direct-reporting gate, time context and private provenance."""
import sys,json,sqlite3,tempfile,re,hashlib
from pathlib import Path
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store
from military_ip_style import install,WRITE_MARKER,EXTRACT_MARKER,validate_article,time_context,RULE
from military_profile import PROFILES,prepare_answer,safe_html,visible,prompt,normalize,policy_for,row_profile

for text in ['素材转述，美军部署部队。','原文称，辽宁舰开始航行。','素材作者预测可能发生冲突。','材料转述海警局通报称开展巡查。']:
    try:validate_article('报道',text);raise AssertionError('Meta narration accepted: '+text)
    except ValueError:pass
validate_article('军工材料的供应问题','10月14日，编队开始航行。国防部通报了演训安排。在我看来，保障节奏更值得看。复合材料提高了强度。')
assert re.search(r'\d{4}-\d{2}-\d{2}',time_context())
from military_ip_style import STANCE_MARKER,STANCE_EXTRACT_MARKER,ORAL_MARKER,ORAL_EXTRACT_MARKER,effective_write,effective_extract
old_write='用户自定义内容'+WRITE_MARKER+'旧直接成文规则'+ORAL_MARKER+'旧口述规则'
new_write=effective_write(old_write)
assert new_write.startswith(old_write) and new_write.count(STANCE_MARKER)==1 and effective_write(new_write)==new_write
old_extract='用户自定义内容'+EXTRACT_MARKER+'旧事件规则'+ORAL_EXTRACT_MARKER+'旧口述元素'
new_extract=effective_extract(old_extract)
assert new_extract.startswith(old_extract) and new_extract.count(STANCE_EXTRACT_MARKER)==1 and effective_extract(new_extract)==new_extract

assert not PROFILES['C']['question'] and not PROFILES['D']['question']
assert all(PROFILES[v]['min']==400 and PROFILES[v]['max']==600 and PROFILES[v]['scope']=='body' for v in 'CDE')
legacy={'category':'军事','title':'历史稿','article':'甲'*245+'？'}
assert normalize(legacy,'military_ip_C_v1')[0]['writing_profile']=='military_ip_C_v1'
assert policy_for('military_ip_C_v1')['max']==300 and policy_for('military_ip_C_v2')['max']==600
assert row_profile({'write_variant':'C','data_json':json.dumps({'writing_profile':'military_ip_C_v1'})})=='military_ip_C_v1'
answer={'content_status':'ready','title':'报道','article':safe_html('正文。\n\n资料来源\n\n输入素材：旧输入')}
clean=prepare_answer(answer,'G',{'title':'输入标题','url':'https://example.invalid'},{});assert visible(clean['article'])=='正文。'
assert '资料来源' in visible(answer['article']) # Do not mutate prior responses in place.
source={'title':'题','body':'10月14日开展行动。','published_at':'2026-11-03','url':'https://example.invalid'}
text=prompt('规则',source,{'topic':'审查素材能证明什么'},'角度','','C');assert WRITE_MARKER in text and '2026-11-03' in text and time_context() in text

with tempfile.TemporaryDirectory(prefix='military-ip-migration-') as temp:
    root=Path(temp);before=ROOT/'build/military-ip-report-20261104/before.sqlite3'
    with closing(sqlite3.connect(before.as_uri()+'?mode=ro',uri=True)) as c,closing(sqlite3.connect(root/'workbench.sqlite3')) as dst:
        c.row_factory=sqlite3.Row;rows=[dict(r) for r in c.execute('SELECT * FROM prompts')];results=[tuple(r) for r in c.execute('SELECT * FROM results')];history=c.execute('SELECT count(*) FROM prompt_history').fetchone()[0];c.backup(dst)
    store=Store(root,ROOT/'resources');after={r['id']:r for r in store.prompts()}
    with store.connect() as c:
        assert all(after[r['id']]==r for r in rows if r['category']!='军事')
        for r in rows:
            if r['category']!='军事':continue
            now=after[r['id']];marker=WRITE_MARKER if r['kind']=='write' else EXTRACT_MARKER
            assert now['content'].startswith(r['content']) and marker in now['content']
            assert now['revision']==r['revision']+1 and now['enabled']==r['enabled']
            saved=c.execute('SELECT content,revision FROM prompt_history WHERE prompt_id=? ORDER BY id DESC LIMIT 1',(r['id'],)).fetchone();assert tuple(saved)==(r['content'],r['revision'])
        assert c.execute('SELECT count(*) FROM prompt_history').fetchone()[0]==history+14
        assert install(c,'second start')==0
        assert [tuple(r) for r in c.execute('SELECT * FROM results')]==results
    assert store.settings()['military_write_variant']=='C'
report={'ok':True,'military_prompts_upgraded':14,'original_content_in_history':True,'idempotent':True,'other_lanes_unchanged':True,'results_preserved':True,'meta_narration_gate':True,'event_time_context':True,'G_no_public_input_footer':True,'C_D_optional_ending':True,'external_calls':0}
(ROOT/'build/military-ip-style-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
