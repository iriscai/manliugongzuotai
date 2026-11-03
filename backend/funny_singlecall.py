"""Funny I: one generation request with concrete draft/revision/title artifacts."""
import copy,json,hashlib
from schemas import ARTICLE,obj,arr,S,I

MODE='funny_singlecall_I_v1'
def adapt_prompt(prompt,category,rule):
    if category!='搞笑' or not any(m in rule for m in ('方案I：一次模型响应内的多阶段修订','方案J：单次响应·场景落地与口语收口')):return prompt
    return prompt.replace('一次返回category、title、article三个JSON字段','一次返回category、title、article、generation_audit四个JSON字段').replace('只返回JSON的三个字段category、title、article，分别是赛道、标题、文章。','只返回JSON的四个字段category、title、article、generation_audit，分别是赛道、标题、文章和单次响应内的实际创作记录。').replace('不新增模型评审或外部核实步骤','不新增外部模型评审或外部核实步骤')

AUDIT=obj({'draft':S,'r1_text':S,'r1_notes':arr(S),'r2_text':S,'r2_notes':arr(S),'t1_titles':arr(S),'t1_short_reasons':arr(S),'t1_choice':I,'t1_article':S,'t2_notes':arr(S)})
FUNNY_ARTICLE=copy.deepcopy(ARTICLE)
from paragraph_policy import ARTICLE_DESCRIPTION
FUNNY_ARTICLE['properties']['article']['description']=ARTICLE_DESCRIPTION
FUNNY_ARTICLE['properties']['generation_audit']=AUDIT
FUNNY_ARTICLE['required'].append('generation_audit')
from article_quality import GRADE_SCHEMA
FUNNY_ARTICLE['properties']['quality_score']=GRADE_SCHEMA
FUNNY_ARTICLE['required'].append('quality_score')
FUNNY_ARTICLE['properties']['title']['minLength']=60
FUNNY_ARTICLE['properties']['generation_audit']['properties']['t1_titles']['items']={'type':'string','minLength':60,'maxLength':64}

FUNNY_J_ARTICLE=copy.deepcopy(FUNNY_ARTICLE)
FUNNY_J_ARTICLE['properties']['title']['minLength']=48
FUNNY_J_ARTICLE['properties']['generation_audit']['properties']['t1_titles']['items']={'type':'string','minLength':48,'maxLength':64}
for key,schema in {'material_mode':S,'retained_core':S,'ending_link':obj({'setup':S,'trigger':S,'punchline':S})}.items():
    FUNNY_J_ARTICLE['properties']['generation_audit']['properties'][key]=schema
    FUNNY_J_ARTICLE['properties']['generation_audit']['required'].append(key)
for schema in (FUNNY_ARTICLE,FUNNY_J_ARTICLE):
    props=schema['properties']['generation_audit']['properties']
    props['t1_titles'].update(minItems=2,maxItems=2,uniqueItems=True,description='恰好两个不同的完整标题，优先60至64字符，不用省略号或空话凑长')
    props['t1_short_reasons'].update(minItems=2,maxItems=2,description='与两个候选一一对应；候选不足60字符时填写具体缺口，60至64字符时可留空字符串')
    props['t1_choice'].update(enum=[1,2])
MULTISTAGE_VARIANTS=('I','J')

def schema_for(variant):return FUNNY_J_ARTICLE if variant=='J' else FUNNY_ARTICLE
def is_singlecall_schema(schema):return schema is FUNNY_ARTICLE or schema is FUNNY_J_ARTICLE
def mode_for(variant):return 'funny_singlecall_J_v1' if variant=='J' else MODE

def content_hash(extract,write):return hashlib.sha256((extract+'\n'+write).encode('utf8')).hexdigest()

def audit_result(answer,variant='I',allow_missing_title_notes=False):
    audit=answer.get('generation_audit')
    if not isinstance(audit,dict):raise ValueError('方案I缺少一次响应内的创作记录')
    for key in ['draft','r1_text','r2_text','t1_article']:
        if not isinstance(audit.get(key),str) or not audit[key].strip():raise ValueError('方案I缺少实际稿件：'+key)
    for key in ['r1_notes','r2_notes','t2_notes']:
        notes=audit.get(key)
        if not isinstance(notes,list) or not 1<=len(notes)<=3 or any(not isinstance(x,str) or not x.strip() for x in notes):raise ValueError('方案I修订摘要无效：'+key)
    titles=audit.get('t1_titles');reasons=audit.get('t1_short_reasons')
    minimum=48 if variant=='J' else 60
    if not isinstance(titles,list) or len(titles)!=2 or any(not isinstance(t,str) or not minimum<=len(t)<=64 for t in titles) or len(set(titles))!=2:raise ValueError(f'方案{variant}的T1须有两个不同且{minimum}至64字符的完整标题候选')
    if not isinstance(reasons,list) or len(reasons)!=2 or any(not isinstance(x,str) for x in reasons):raise ValueError('T1标题短于60字符时须记录具体原因')
    for title,reason in zip(titles,reasons):
        if len(title)<60 and not reason.strip() and not allow_missing_title_notes:raise ValueError('T1短标题未说明具体原因')
    if type(audit.get('t1_choice')) is not int or audit['t1_choice'] not in (1,2):raise ValueError('T1未选定实际标题候选')
    if variant=='J':
        if audit.get('material_mode') not in ('keep_joke','daily_adaptation','fictional_transfer'):raise ValueError('方案J缺少取材模式')
        if not isinstance(audit.get('retained_core'),str) or not audit['retained_core'].strip():raise ValueError('方案J缺少实际保留与改编说明')
        link=audit.get('ending_link');article=answer.get('article','')
        if not isinstance(link,dict) or any(not isinstance(link.get(k),str) or not link[k].strip() or link[k] not in article for k in ('setup','trigger','punchline')):raise ValueError('方案J铺垫、触发和包袱证据必须逐字来自最终正文')
        if not article.rstrip().endswith(link['punchline']):raise ValueError('方案J包袱证据没有落在实际结尾')
        if len(answer.get('title',''))<60 and not reasons[audit['t1_choice']-1].strip() and not allow_missing_title_notes:raise ValueError('方案J最终短标题须有具体原因')
    final_title=answer.get('title')
    if not isinstance(final_title,str) or not minimum<=len(final_title.strip())<=64:raise ValueError(f'方案{variant}最终标题须为{minimum}至64字符，未截断或拼凑标题')
    return audit

def approved_release(resources):
    from pathlib import Path
    path=Path(resources)/'funny-singlecall-release.json'
    if not path.is_file():return {'status':'pending','mode':MODE}
    info=json.loads(path.read_text(encoding='utf8'))
    report=Path(resources)/'funny-singlecall-scores.json'
    if info.get('status')!='approved' or not report.is_file():return {'status':'pending','mode':MODE}
    raw=report.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=info.get('scores_sha256'):return {'status':'pending','mode':MODE}
    scores=json.loads(raw)
    if len(scores)<5 or any(s.get('final_total',0)<90 for s in scores):return {'status':'pending','mode':MODE}
    if len({s.get('text_sha256') for s in scores})!=len(scores):return {'status':'pending','mode':MODE}
    return info

def current_hash(c):
    rows={r['kind']:r['content'] for r in c.execute("SELECT kind,content FROM prompts WHERE category='搞笑' AND variant='I'")}
    return content_hash(rows.get('extract',''),rows.get('write',''))

def migrate(c,resources,stamp):
    from pathlib import Path
    from store import dumps
    path=Path(resources)/'funny-singlecall-I-write.txt'
    if not path.is_file():return
    extract=(Path(resources)/'funny-singlecall-I-extract.txt').read_text(encoding='utf8').strip();write=path.read_text(encoding='utf8').strip()
    fingerprint=content_hash(extract,write);key='singlecall_I_content_'+fingerprint
    if not c.execute('SELECT 1 FROM prompt_library_updates WHERE key=?',(key,)).fetchone():
        for kind,name,text in [('extract','单次多阶段·喜剧核与因果账本',extract),('write','单次多阶段·R1/R2与T1/T2',write)]:
            row=c.execute("SELECT * FROM prompts WHERE category='搞笑' AND kind=? AND variant='I'",(kind,)).fetchone()
            if row and row['content']!=text:
                c.execute('INSERT INTO prompt_history(prompt_id,content,revision,created_at) VALUES(?,?,?,?)',(row['id'],row['content'],row['revision'],stamp))
                c.execute('UPDATE prompts SET content=?,name=?,revision=revision+1,updated_at=?,enabled=0 WHERE id=?',(text,name,stamp,row['id']))
            elif not row:c.execute('INSERT INTO prompts(category,kind,variant,name,content,enabled,updated_at) VALUES(?,?,?,?,?,0,?)',('搞笑',kind,'I',name,text,stamp))
        c.execute('INSERT INTO prompt_library_updates VALUES(?,?)',(key,stamp))
    release=approved_release(resources);approval_key='singlecall_I_approved_'+fingerprint
    if release.get('status')=='approved' and release.get('content_sha256')==current_hash(c) and not c.execute('SELECT 1 FROM prompt_library_updates WHERE key=?',(approval_key,)).fetchone():
        for row in c.execute("SELECT id,variant,enabled FROM prompts WHERE category='搞笑'").fetchall():
            enabled=int(row['variant']=='I')
            if row['enabled']!=enabled:
                c.execute('INSERT INTO prompt_status_history(prompt_id,old_enabled,new_enabled,created_at) VALUES(?,?,?,?)',(row['id'],row['enabled'],enabled,stamp))
                c.execute('UPDATE prompts SET enabled=?,status_updated_at=? WHERE id=?',(enabled,stamp,row['id']))
        for kind in ['extract','write']:c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('funny_'+kind+'_variant',dumps('I')))
        c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('funny_singlecall_validation',dumps(release)))
        c.execute('INSERT INTO prompt_library_updates VALUES(?,?)',(approval_key,stamp))
    elif not c.execute("SELECT 1 FROM settings WHERE key='funny_singlecall_validation'").fetchone():
        c.execute('INSERT INTO settings VALUES(?,?)',('funny_singlecall_validation',dumps({'status':'pending','mode':MODE})))
