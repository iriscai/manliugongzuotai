"""One source + selected rules -> one audited, reusable multi-category response."""
from collections import Counter
import json
import re

from schemas import MULTI_EXTRACT,MULTI_EXTRACT_LEGACY
from store import now,dumps,digest

SCHEME='three_topics_v1'
MULTI_SCHEMES=(SCHEME,'multi_category_v1')

def install_schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS extraction_batches(
        id INTEGER PRIMARY KEY,material_id INTEGER,source_hash TEXT,rule_key TEXT,run_id TEXT,
        rule_variant TEXT,prompt_text TEXT,data_json TEXT,category_count INTEGER,created_at TEXT,
        UNIQUE(material_id,source_hash,rule_key))''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_extraction_batch_run ON extraction_batches(run_id,id)')
    cols={r[1] for r in c.execute('PRAGMA table_info(extractions)')}
    if 'batch_id' not in cols:c.execute('ALTER TABLE extractions ADD COLUMN batch_id INTEGER')
    if 'extraction_mode' not in cols:c.execute("ALTER TABLE extractions ADD COLUMN extraction_mode TEXT NOT NULL DEFAULT 'multi'")
    c.execute('CREATE INDEX IF NOT EXISTS idx_extraction_mode ON extractions(material_id,source_hash,current,extraction_mode,category)')
    if 'topic' not in cols:c.execute("ALTER TABLE extractions ADD COLUMN topic TEXT DEFAULT ''")
    batch_cols={r[1] for r in c.execute('PRAGMA table_info(extraction_batches)')}
    if 'target_count' not in batch_cols:c.execute('ALTER TABLE extraction_batches ADD COLUMN target_count INTEGER DEFAULT 0')

def compile_rules(snapshot,variant,categories=None):
    from prompt_status import active_categories
    allowed,_=active_categories(snapshot['prompts'],snapshot['settings'],'extract')
    if categories is not None:allowed=[cat for cat in allowed if cat in categories]
    if not allowed:raise ValueError('没有启用提炼规则的赛道')
    catalog={x['name']:x for x in snapshot['categories']['categories']}
    rules=[]
    for cat in dict.fromkeys(allowed):
        if cat not in catalog:raise ValueError('允许分类不在当前分类库：'+str(cat))
        from funny_rules import selected_variant
        actual_variant=selected_variant(snapshot,cat,'extract',variant)
        rule=next((p for p in snapshot['prompts'] if p['category']==cat and p['kind']=='extract' and p['variant']==actual_variant),None)
        if not rule:raise ValueError(f'缺少{cat}的提炼规则{actual_variant}')
        # Keep every rule paragraph; only exact shared paragraphs are factored out.
        text=rule['content'].replace('{{source}}','[素材见统一输入]').replace('{{requirements}}','[要求见统一输入]')
        if cat=='军事':
            from military_ip_style import effective_extract,time_context
            text=effective_extract(text)+'\n'+time_context()
        paragraphs=[x.strip() for x in re.split(r'\n\s*\n',text) if x.strip()]
        focus=catalog[cat]['element_focus']
        if cat=='军事':
            from military_profile import PROFILES
            if actual_variant in PROFILES:focus=PROFILES[actual_variant]['focus']
        rules.append({'category':cat,'variant':actual_variant,'focus':focus,'paragraphs':paragraphs})
    frequencies=Counter(p for rule in rules for p in set(rule['paragraphs']))
    shared=list(dict.fromkeys(p for rule in rules for p in rule['paragraphs'] if frequencies[p]>1))
    specific=[{'category':r['category'],'variant':r['variant'],'element_focus':r['focus'],'rule':'\n\n'.join(p for p in r['paragraphs'] if p not in shared)} for r in rules]
    return allowed,{'shared_rules':shared,'category_rules':specific}

def make_prompt(source,rules,requirements,three_topics=True):
    shared='\n\n'.join(rules['shared_rules'])
    category_rules=[]
    for item in rules['category_rules']:
        focus=item['element_focus'];focus='、'.join(focus) if isinstance(focus,list) else str(focus)
        text=item['rule'].replace('当前分类：'+item['category']+'。','').strip()
        category_rules.append(f"【{item['category']} / {item['variant']}】元素重点：{focus}\n{text}")
    topic_contract='''本次目标是一次产出3组独立选题，每组对应一个不同的适配赛道，并有一个与另两组明显不同的主题topic。不是把同一重点换3个分类标签。topic写具体选题名称，angle写该主题要解释的中心问题，main_point写本主题有原文依据的重点；对应元素必须服务本主题。
先在本次响应内部比较3个主题是否信息重点不同，再返回3组方案，不额外请求评审。三个主题不得只是改人称、改职业、同义换词或同一观点加分类名前缀。写文将按这3个主题分别调用3次API，禁止把3主题合并成一篇。
素材只够支持少于3组时，仅返回实际有依据的方案，并在reason明确写出不足3组的原因；不编造事实凑3组。最多返回3组，不扩展成更多主题。
''' if three_topics else ''
    return topic_contract+'''在这一次请求中完成本条素材的分类适配和各分类元素提炼，不先返回候选分类再等待逐分类提炼。
完整阅读统一输入的一条素材；按照每个允许分类自己的规则判断适配。仅返回有原文依据且各有独立重点的分类；不凑类别数，不跨行取材，只有换标签且重点相同的分类合并，不逐类写不适配长报告。同一分类最多一个方案。没有适配分类时categories为空并简要说明原因。
每个适配分类返回目标分类、具体角度、核心重点及可直接供写文使用的元素。元素名应具体，例如行为主体、触发事件、关键条件、金额用途、动作过程、已知结果；元素内容必须符合该分类规则。正文是主要依据，原始标题只作来源字段，不将标题夸张断言当作已核实事实。
原句放在公共evidence池：id在本响应内唯一，field只能为title或body，quote必须逐字出自本行对应字段。多个分类使用同一原句时引用同一id，不重复抄写。每个元素都要列出真实支持该元素的evidence_ids，不允许空引用或引用其他素材。
逐分类记录缺失信息、可视化节点、待核实事项。needs_verification仅列本分类选题实际使用且必须核实的内容；无关背景不强加给所有分类。关键事实、数字、人物引语或因果无法确认时，仍须如实列待核实，不为了进入写文而清空。verified_additions只记录实际已核查且有可靠来源的网址，没有则为空。
本次只提炼，不生成文章、标题或分镜提示词。不同分类保留各自的元素、角度和事实边界。
提炼规则（共享规则适用于所有分类，各分类独有规则不得遗漏）：
'''+shared+'\n\n'+'\n\n'.join(category_rules)+'\n用户补充要求：'+str(requirements or '')+'\n统一输入素材：'+dumps(source)

def validate_batch(answer,source,allowed,three_topics=True):
    if not isinstance(answer,dict) or not isinstance(answer.get('categories'),list) or not isinstance(answer.get('evidence'),list):raise ValueError('多赛道提炼结构不完整')
    evidence={}
    for item in answer['evidence']:
        eid=str(item.get('id','')).strip();field=item.get('field');quote=item.get('quote')
        if not eid or eid in evidence:raise ValueError('公共证据编号为空或重复')
        if field not in ('title','body') or not isinstance(quote,str) or not quote.strip() or quote not in source[field]:raise ValueError('公共证据原句不在本行指定字段')
        evidence[eid]={'id':eid,'field':field,'quote':quote}
    if three_topics and len(answer['categories'])>3:raise ValueError('一次提炼最多返回3个不同赛道的独立主题')
    if three_topics and len(answer['categories'])<3 and not str(answer.get('reason','')).strip():raise ValueError('不足3个主题时必须说明原因')
    records=[];seen=set();topics=set();points=set()
    def topic_key_of(text):
        for category in allowed:text=text.replace(category,'')
        return re.sub(r'[^\w]+','',text).casefold()
    for item in answer['categories']:
        cat=item.get('category');angle=str(item.get('angle','')).strip();point=str(item.get('main_point','')).strip()
        if cat not in allowed or cat in seen or not angle or not point:raise ValueError('多赛道提炼包含未知/重复分类或缺少重点')
        topic=str(item.get('topic','')).strip() if three_topics else str(item.get('topic') or angle)
        if three_topics:
            topic_key=topic_key_of(topic);point_key=topic_key_of(point)
            if not topic_key or topic_key in topics or not point_key or point_key in points:raise ValueError('3个主题及核心重点必须不同，不能只换分类名')
            topics.add(topic_key);points.add(point_key)
        seen.add(cat);elements=item.get('elements');facts=[];used=[];normalized=[]
        if not isinstance(elements,list) or not elements:raise ValueError(f'{cat}缺少可用于写文的元素')
        for element in elements:
            name=str(element.get('name','')).strip();content=str(element.get('content','')).strip();ids=element.get('evidence_ids')
            if not name or not content or not isinstance(ids,list) or not ids or any(eid not in evidence for eid in ids):raise ValueError(f'{cat}元素内容或证据引用无效')
            ids=list(dict.fromkeys(ids));normalized.append({'name':name,'content':content,'evidence_ids':ids})
            for eid in ids:
                facts.append({'fact':content,'quote':evidence[eid]['quote'],'field':evidence[eid]['field']})
                if eid not in used:used.append(eid)
        for key in ['omissions','visual_nodes','needs_verification']:
            if not isinstance(item.get(key),list) or not all(isinstance(x,str) for x in item[key]):raise ValueError(f'{cat}的{key}格式不正确')
        data={'eligible':True,'topic':topic,'reason':str(item.get('reason','')),'main_point':point,'elements':normalized,'evidence':[evidence[eid] for eid in used],
              'facts':facts,'omissions':item['omissions'],'visual_nodes':item['visual_nodes'],'needs_verification':item['needs_verification'],
              'verified_additions':item.get('verified_additions',[]),'extraction_scheme':SCHEME if three_topics else 'multi_category_v1'}
        records.append((cat,angle,data))
    return records

def extract_once(worker,source,source_hash,rid,snapshot,variant):
    s=worker.store;mid=source['material_id'];allowed,rules=compile_rules(snapshot,variant)
    scheme=snapshot.get('extraction_scheme',SCHEME);three_topics=scheme==SCHEME
    prompt=make_prompt(source,rules,snapshot['settings'].get('requirements',''),three_topics);rule_key=digest(scheme+'\n'+dumps(rules)+'\n'+str(snapshot['settings'].get('requirements','')))
    with s.connect() as c:cached=c.execute('SELECT * FROM extraction_batches WHERE material_id=? AND source_hash=? AND rule_key=?',(mid,source_hash,rule_key)).fetchone()
    worker.update(rid,mid,'extracting')
    if cached:
        answer=json.loads(cached['data_json']);s.log(f'素材#{mid} 复用已保存的单次多赛道提炼，不调用模型。','extracting',rid,mid)
    else:
        s.log(f'素材#{mid} 单次提炼：一次返回多个适配赛道及对应元素（规则{variant}）。','extracting',rid,mid)
        answer=worker.call('multi-extract',prompt,MULTI_EXTRACT if three_topics else MULTI_EXTRACT_LEGACY,rid,mid,snapshot)
    # Audit the entire response before writing any category, avoiding partial batch commits.
    records=validate_batch(answer,source,allowed,three_topics)
    with s.connect() as c:
        from data_integrity import allocate,validate_source
        if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
        validate_source(c,mid,source_hash)
        c.execute('INSERT OR IGNORE INTO extraction_batches(material_id,source_hash,rule_key,run_id,rule_variant,prompt_text,data_json,category_count,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(mid,source_hash,rule_key,rid,variant,prompt,dumps(answer),len(records),now()))
        batch_id=c.execute('SELECT id FROM extraction_batches WHERE material_id=? AND source_hash=? AND rule_key=?',(mid,source_hash,rule_key)).fetchone()[0]
        c.execute('UPDATE extraction_batches SET target_count=? WHERE id=?',(3 if three_topics else 0,batch_id))
        for cat,angle,data in records:
            if c.execute('SELECT id FROM extractions WHERE material_id=? AND source_hash=? AND category=? AND angle=? AND current=1',(mid,source_hash,cat,angle)).fetchone():continue
            from funny_rules import selected_variant
            actual_variant=selected_variant(snapshot,cat,'extract',variant)
            c.execute('INSERT INTO extractions(id,material_id,category,topic,angle,source_hash,rule_variant,prompt_text,data_json,batch_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(allocate(c,'extractions'),mid,cat,data['topic'],angle,source_hash,actual_variant,prompt,dumps(data),batch_id,now()))
        existing=[dict(row) for row in c.execute('SELECT * FROM extractions WHERE material_id=? AND source_hash=? AND current=1 ORDER BY id',(mid,source_hash))]
    s.log(f'素材#{mid} 单次提炼已保存：{len(records)}个适配赛道，每个赛道的元素与原句依据分别入库。','extracting',rid,mid)
    if three_topics and len(records)<3:s.log(f'素材#{mid} 独立主题{len(records)}/3：'+str(answer.get('reason','')),'extracting',rid,mid,'warning')
    return existing

def writing_context(data,category,angle):
    if not data.get('elements'):return data
    return {key:value for key,value in {'category':category,'topic':data.get('topic',angle),'angle':angle,'main_point':data['main_point'],'elements':data['elements'],'evidence':data['evidence'],
        'omissions':data['omissions'],'visual_nodes':data['visual_nodes'],'needs_verification':data['needs_verification'],'verified_additions':data.get('verified_additions',[])}.items()}
