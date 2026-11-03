"""Content-bound funny scores and explicit publishing-category routing."""
import copy,json,re
from datetime import datetime
from zoneinfo import ZoneInfo
from schemas import obj,arr,S,I

VERSION='funny_three_dimensions_v1'
GRADE_SCHEMA=obj({'completeness':I,'reversal':I,'fun':I,'reason':S,'evidence':arr(S),'risks':arr(S)})
GRADE_INSTRUCTION='''
最终title和article定稿后，仅对这份最终标题与正文评分一次，返回quality_score对象。
completeness故事完整性、reversal反转程度、fun趣味性分别给0—100整数。完整性看人物、因果、结果闭环；反转看结尾是否有场景依据且出人意料；趣味性看实际笑点、口语自然度、生硬和解释感。90+要有明确笑点且自然，80—89完整但较常见或偏平，60—79笑点有限，60以下缺包袱或依赖补设定。不得预设优秀比例或为通过推送门槛倒填分数。
reason写本篇具体优点与扣分点；evidence列1—3段逐字来自最终title或article的短句；risks列具体问题，没有则空数组。不能用初稿或审计说明补齐终稿。仅返回维度分，程序等权四舍五入、按最终发布文案中的数字字符加5并封顶100。这是模型评分，不冒充用户或读者评分。不重新创作、不另发模型请求。
'''

def stamp():return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')

def install_schema(c):
    cols={r[1] for r in c.execute('PRAGMA table_info(results)')}
    for name,definition in [('score','INTEGER DEFAULT 60'),('score_status',"TEXT NOT NULL DEFAULT 'default'"),('score_content_hash',"TEXT NOT NULL DEFAULT ''"),('score_json',"TEXT NOT NULL DEFAULT '{}' ")]:
        if name not in cols:c.execute('ALTER TABLE results ADD COLUMN '+name+' '+definition)
    if 'score' not in cols:c.execute("UPDATE results SET score=NULL,score_status='pending' WHERE category='搞笑'")
    c.execute('CREATE INDEX IF NOT EXISTS idx_results_score ON results(category,score_status,score)')
    c.execute('''CREATE TABLE IF NOT EXISTS article_score_history(id INTEGER PRIMARY KEY,result_id INTEGER,content_hash TEXT,score INTEGER,review_json TEXT,evaluator TEXT,created_at TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS article_quality_migrations(id TEXT PRIMARY KEY,created_at TEXT)')

def backfill(c,resources):
    from pathlib import Path
    from title_push import signature
    path=Path(resources)/'quality-backfill-20261101.json'
    key='review_existing_funny_20261101'
    if not path.is_file() or c.execute('SELECT 1 FROM article_quality_migrations WHERE id=?',(key,)).fetchone():return
    for item in json.loads(path.read_text(encoding='utf8')):
        row=c.execute("SELECT * FROM results WHERE id=? AND category='搞笑' AND score_status='pending'",(item['id'],)).fetchone()
        if row and signature(dict(row))==item['content_hash']:apply(c,row,item['review'],'当前任务窗口模型语义评分')
    c.execute('INSERT INTO article_quality_migrations VALUES(?,?)',(key,stamp()))

def grade(text,review):
    if not isinstance(review,dict):raise ValueError('缺少搞笑评分')
    dims=[review.get(k) for k in ['completeness','reversal','fun']]
    if any(type(n) is not int or not 0<=n<=100 for n in dims):raise ValueError('三项分数必须为0至100整数')
    evidence=review.get('evidence');reason=review.get('reason')
    if not isinstance(reason,str) or not reason.strip():raise ValueError('请填写本篇评分理由')
    if not isinstance(evidence,list) or not 1<=len(evidence)<=3 or any(not isinstance(q,str) or not q.strip() or q not in text for q in evidence):raise ValueError('评分证据必须为最终标题或正文中的1至3段原句')
    risks=review.get('risks',[])
    if not isinstance(risks,list) or any(not isinstance(x,str) for x in risks):raise ValueError('评分风险格式错误')
    base=(sum(dims)+1)//3
    hit=re.search(r'[0-9零一二三四五六七八九十百千万亿两]',text)
    bonus=5 if hit else 0
    score=min(100,base+bonus)
    return {**review,'base_total':base,'number_bonus':bonus,'bonus_evidence':text[max(0,hit.start()-3):hit.end()+5] if hit else '',
            'final_total':score,'final_tier':'精品' if score>=96 else '优秀' if score>=90 else '良好' if score>=80 else '合格' if score>=60 else '备选','version':VERSION,'scope':'最终标题与正文'}

def apply(c,row,review,evaluator='生成模型同次响应'):
    from title_push import signature
    row=dict(row)
    if row['category']!='搞笑':raise ValueError('其他赛道不评分，默认60分')
    data=grade(row['title']+'\n'+(row.get('article') or row['short_text']),review)
    hashed=signature(row);data.update(content_hash=hashed,evaluator=evaluator,scored_at=stamp())
    encoded=json.dumps(data,ensure_ascii=False)
    c.execute("UPDATE results SET score=?,score_status='scored',score_content_hash=?,score_json=? WHERE id=?",(data['final_total'],hashed,encoded,row['id']))
    c.execute('INSERT INTO article_score_history(result_id,content_hash,score,review_json,evaluator,created_at) VALUES(?,?,?,?,?,?)',(row['id'],hashed,data['final_total'],encoded,evaluator,stamp()))
    return data

def reset(c,rid):
    c.execute("UPDATE results SET score=CASE WHEN category='搞笑' THEN NULL ELSE 60 END,score_status=CASE WHEN category='搞笑' THEN 'pending' ELSE 'default' END,score_content_hash='',score_json='{}' WHERE id=?",(rid,))

def after_generated(c,eid,answer):
    row=c.execute('SELECT * FROM results WHERE extraction_id=?',(eid,)).fetchone();reset(c,row['id'])
    if row['category']=='搞笑' and answer.get('quality_score'):
        try:apply(c,row,answer['quality_score'])
        except ValueError as exc:c.execute('UPDATE results SET score_json=? WHERE id=?',(json.dumps({'error':str(exc)},ensure_ascii=False),row['id']))

def valid_score(row):
    from title_push import signature
    if row['category']!='搞笑':return 60
    return row.get('score') if row.get('score_status')=='scored' and row.get('score_content_hash')==signature(row) else None

DEFAULT_SCORE_RULES=[{'min_score':90,'max_score':100,'target':'搞笑漫画-优秀','enabled':True},{'min_score':80,'max_score':89,'target':'搞笑漫画-良好','enabled':True}]

def validate_score_rules(value):
    if not isinstance(value,list) or len(value)>100:raise ValueError('评分分流规则需为列表，最多100个区间')
    rules=[]
    for item in value:
        if not isinstance(item,dict):raise ValueError('评分区间格式无效')
        low,high,target,enabled=item.get('min_score'),item.get('max_score'),item.get('target'),item.get('enabled',True)
        if type(low) is not int or type(high) is not int or not 0<=low<=high<=100:raise ValueError('评分上下限需为0至100整数，最低分不能大于最高分')
        if type(enabled) is not bool:raise ValueError('评分区间的启用状态无效')
        if not isinstance(target,str) or len(target.strip())>80 or enabled and not target.strip():raise ValueError('启用的评分区间需填写目标分类，最多80字符')
        rules.append({'min_score':low,'max_score':high,'target':target.strip(),'enabled':enabled})
    active=sorted([r for r in rules if r['enabled']],key=lambda r:r['min_score'])
    for first,second in zip(active,active[1:]):
        if second['min_score']<=first['max_score']:raise ValueError(f'启用的评分区间 {first["min_score"]}—{first["max_score"]} 与 {second["min_score"]}—{second["max_score"]} 重叠，请调整')
    return rules

def score_rules(value=None):return copy.deepcopy(DEFAULT_SCORE_RULES) if value is None else validate_score_rules(value)

def route(row,mapping=None,rules=None):
    score=valid_score(row)
    if row['category']=='搞笑':
        if score is None:return '','搞笑作品未评分或评分已失效'
        for rule in score_rules(rules):
            if rule['enabled'] and rule['min_score']<=score<=rule['max_score']:return rule['target'],''
        return '',f'搞笑作品{score}分未匹配启用的评分区间，暂不推送'
    return ((mapping or {}).get(row['category']) or row['category'],'')

def decorate(rows,mapping=None,rules=None):
    for r in rows:
        r['score']=valid_score(r);r['score_display_status']='default' if r['category']!='搞笑' else 'scored' if r['score'] is not None else 'pending'
        r['push_category'],r['push_block_reason']=route(r,mapping,rules)

def set_score(store,payload):
    from title_push import signature
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT * FROM results WHERE id=? AND current=1 AND deleted_at=''",(int(payload['id']),)).fetchone()
        if not row:raise ValueError('文章不存在')
        row=dict(row)
        if payload.get('content_hash')!=signature(row):raise ValueError('文案已变化，请重新打开后评分')
        if c.execute("SELECT 1 FROM runs WHERE state IN ('running','pausing')").fetchone():raise ValueError('请等待当前任务保存后再调整评分')
        return {'ok':True,'review':apply(c,row,payload['review'],'人工复核')}

def scored_schema(schema,category):
    if category!='搞笑':return schema
    value=copy.deepcopy(schema);value['properties']['quality_score']=GRADE_SCHEMA;value['required'].append('quality_score')
    from paragraph_policy import ARTICLE_DESCRIPTION
    value['properties']['article']['description']=ARTICLE_DESCRIPTION
    return value
