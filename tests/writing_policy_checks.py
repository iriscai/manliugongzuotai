"""No paid inference: check prompt migration, old snapshots and writing routing."""
import copy,json,sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,dumps
from article_flow import article_prompt
from writing_prompts import COMMON_RULE,PARAGRAPH_RULE_V3,COMIC_RULE_V2,DIRECT_RULE_V1,LEGACY_RULE,LEGACY_OPENING,POLICY_OPENING,source_policy,migrate_stock_rules,upgrade_stock_rule

new=json.loads((ROOT/'resources/prompt-library.json').read_text(encoding='utf8'))
old=copy.deepcopy(new)
for category in old['categories']:
    for prompt in category['rewrite_prompts']:
        prompt['text']=LEGACY_RULE+'\n\n当前分类：'+prompt['text'].split('\n\n当前分类：',1)[1]
assert len(old['categories'])==len(new['categories'])==37
checked=0
for before,after in zip(old['categories'],new['categories']):
    assert before['category']==after['category'] and before['extraction_rules']==after['extraction_rules']
    for a,b in zip(before['rewrite_prompts'],after['rewrite_prompts']):
        assert a['id']==b['id'] and a['name']==b['name']
        assert upgrade_stock_rule(a['text'],after['category'])==b['text']
        assert a['text'].split('本版改写方向：',1)[1]==b['text'].split('本版改写方向：',1)[1]
        checked+=1
with tempfile.TemporaryDirectory(prefix='writing-policy-') as tmp:
    s=Store(Path(tmp),ROOT/'resources')
    # Seed legacy prompts and one custom prompt, then verify history + idempotence.
    with s.connect() as c:
        for cat in old['categories']:
            for p in cat['rewrite_prompts']:
                c.execute("UPDATE prompts SET content=?,revision=1 WHERE category=? AND kind='write' AND variant=?",(p['text'],cat['category'],p['id']))
        c.execute("INSERT INTO prompts(category,kind,variant,name,content,revision,updated_at) VALUES('自定义','write','A','自定义','请以轻松的口吻解释。',3,'原时间')")
        extracts=[tuple(r) for r in c.execute("SELECT * FROM prompts WHERE kind='extract' ORDER BY id")]
        assert migrate_stock_rules(c,'本次升级')==74
        assert migrate_stock_rules(c,'重复启动')==0
        assert c.execute('SELECT count(*) FROM prompt_history').fetchone()[0]==74
        assert c.execute("SELECT count(*) FROM prompts WHERE kind='write' AND revision=2").fetchone()[0]==74
        assert tuple(c.execute("SELECT content,revision,updated_at FROM prompts WHERE category='自定义'").fetchone())==('请以轻松的口吻解释。',3,'原时间')
        assert extracts==[tuple(r) for r in c.execute("SELECT * FROM prompts WHERE kind='extract' ORDER BY id")]
        for p in new['categories'][0]['rewrite_prompts']:
            v1=DIRECT_RULE_V1+'\n\n'+source_policy(new['categories'][0]['category'])+'\n\n当前分类：'+p['text'].split('\n\n当前分类：',1)[1]
            c.execute("UPDATE prompts SET content=? WHERE category=? AND kind='write' AND variant=?",(v1,new['categories'][0]['category'],p['id']))
        assert migrate_stock_rules(c,'升级亲近漫画版')==2 and migrate_stock_rules(c,'再次启动')==0
        assert c.execute('SELECT count(*) FROM prompt_history').fetchone()[0]==76
        for p in new['categories'][0]['rewrite_prompts']:
            v2=COMIC_RULE_V2+'\n\n'+source_policy(new['categories'][0]['category'])+'\n\n当前分类：'+p['text'].split('\n\n当前分类：',1)[1]
            c.execute("UPDATE prompts SET content=? WHERE category=? AND kind='write' AND variant=?",(v2,new['categories'][0]['category'],p['id']))
        assert migrate_stock_rules(c,'升级自然段版')==2 and migrate_stock_rules(c,'再次启动')==0
        for p in new['categories'][0]['rewrite_prompts']:
            v3=PARAGRAPH_RULE_V3+'\n\n'+source_policy(new['categories'][0]['category'])+'\n\n当前分类：'+p['text'].split('\n\n当前分类：',1)[1]
            c.execute("UPDATE prompts SET content=? WHERE category=? AND kind='write' AND variant=?",(v3,new['categories'][0]['category'],p['id']))
        assert migrate_stock_rules(c,'强化原题与64字符上限')==2 and migrate_stock_rules(c,'再次启动')==0

    for category,expected in [('情感','普通内容直接成文'),('国际','新闻和公共事件'),('健康','专业结论时')]:
        rule=next(c for c in old['categories'] if c['category']==category)['rewrite_prompts'][0]['text']
        source={'material_id':1,'title':'标题','body':'本行正文内容。','url':'https://example.invalid/article','source_category':category}
        seed={'topic':'本篇主题','main_point':'本篇重点','elements':[{'name':'元素','content':'本行正文内容。'}]}
        old_prompt=article_prompt(rule,source,seed,category,'本篇角度','保留自定义要求')
        new_prompt=article_prompt(upgrade_stock_rule(rule,category),source,seed,category,'本篇角度','保留自定义要求')
        assert old_prompt==new_prompt # Paused old snapshots receive the current policy too.
        assert expected in new_prompt and new_prompt.count(COMMON_RULE)==1 and new_prompt.count(POLICY_OPENING)==1
        assert LEGACY_OPENING not in new_prompt and '清楚归因、必要限定' not in new_prompt
        assert new_prompt.count(dumps(source))==1 and '保留自定义要求' in new_prompt
        prompt_seed=json.loads(new_prompt.split('本组种子：',1)[1].split('\n本条原始素材：',1)[0])
        assert prompt_seed['original_title']==source['title']
        custom=article_prompt(rule+'\n\n本篇额外规则：用动作收尾。',source,seed,category,'角度','')
        assert '本篇额外规则：用动作收尾。' in custom
report={'ok':True,'writing_prompts':checked,'extraction_prompts_unchanged':74,'migration_history_saved':True,'migration_idempotent':True,'custom_prompts_preserved':True,'legacy_snapshot_policy_updated':True,'news_and_professional_attribution_retained':True,'external_model_calls':0}
(ROOT/'build/writing-policy-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(dumps(report))
