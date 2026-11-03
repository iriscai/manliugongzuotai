"""Model-selected N topic/category pairs with server-owned source evidence IDs."""
import json
import re

from store import now,dumps,digest
from schemas import ADAPTIVE_EXTRACT,SEED_EXTRACT
from multi_extraction import compile_rules,make_prompt,validate_batch

SCHEME='adaptive_topics_v1'

def source_segments(source):
    encoded={k:v for k,v in source.items() if k not in ('title','body')};pool={}
    for field,prefix in [('title','T'),('body','B')]:
        segments=[];index=0
        for match in re.finditer(r'[^\r\n]+',source[field]):
            line=match.group(0)
            if not line.strip():continue
            for offset in range(0,len(line),240):
                text=line[offset:offset+240];index+=1;eid=f'{prefix}{index:04d}'
                pool[eid]={'id':eid,'field':field,'quote':text}
                segments.append({'id':eid,'text':text})
        encoded[field]=segments
    return encoded,pool

def adaptive_prompt(source,rules,requirements,seed_mode=False,extraction_mode="multi"):
    encoded,pool=source_segments(source)
    prompt=make_prompt(encoded,rules,requirements,three_topics=False)
    old='原句放在公共evidence池：id在本响应内唯一，field只能为title或body，quote必须逐字出自本行对应字段。多个分类使用同一原句时引用同一id，不重复抄写。每个元素都要列出真实支持该元素的evidence_ids，不允许空引用或引用其他素材。'
    new='统一输入中的title和body已按原文顺序编号，T开头来自原始标题，B开头来自正文。连续片段共同组成完整原文，不是摘要。每个元素的evidence_ids只选择输入中真实存在、且能支持本元素的片段编号；同一编号可被不同主题共用。不要重新抄写、改写原句，不生成新的证据编号，也不要返回公共evidence池；程序将按编号原样回填对应原句。'
    assert old in prompt
    prompt=prompt.replace(old,new)
    if seed_mode:
        start=prompt.index('逐分类记录缺失信息、可视化节点、待核实事项。')
        end=prompt.index('\n本次只提炼',start)
        prompt=prompt[:start]+'本步骤只提炼创作种子及来源元素，不执行外部核实，不生成待核实列表，不设置生文前的核实门槛。保留本组主题实际需要的原文条件和信息边界；来源未明确的内容不自行编造成已经确认的事实。'+prompt[end:]
    contract='''本次选题数量N完全由你根据本条素材及允许分类的提示词规则判断。选题数量没有预设目标，不设人为的最少组数。仅输出有本行依据的适配方案，没有适配方案就返回空数组并说明原因。
一次返回N条选题记录，每条记录绑定一个具体主题topic、该主题所属的适配赛道category、独立角度angle、核心重点main_point及对应元素elements。上述字段组内绑定，不拆成主题清单和赛道清单再交叉组合。同一赛道最多一个方案。
每个主题都要有独立信息重点，不能仅换分类名、角色名或同义改写同一个主题。元素必须服务本主题。写文阶段会以原始正文、本组主题、所属赛道和对应元素逐组调用生文API，符合写文条件的组各生成一篇文章。
'''
    if extraction_mode=='single':
        contract='本次执行1→1同赛道模式。只提炼素材source_category对应赛道的一个具体主题；categories最多一项，category必须等于'+str(source['source_category'])+'。不得改投其他赛道，不返回多个主题。结合本赛道规则提炼重点及元素，随后只生成本赛道的一篇文章。无法提炼时返回空数组并说明原因，由程序按原赛道保底处理。\n'
    return contract+prompt,pool

def resolve_and_validate(answer,source,allowed,pool,seed_mode=False):
    if not isinstance(answer,dict) or not isinstance(answer.get('categories'),list):raise ValueError('自适应提炼结果缺少选题记录数组')
    topics=set();points=set();used=[]
    def key(text):
        for category in allowed:text=text.replace(category,'')
        return re.sub(r'[^\w]+','',text).casefold()
    for item in answer['categories']:
        topic=str(item.get('topic','')).strip();point=str(item.get('main_point','')).strip()
        tkey=key(topic);pkey=key(point)
        if not tkey or tkey in topics or not pkey or pkey in points:raise ValueError('主题或核心重点为空、重复，不能只换分类名')
        topics.add(tkey);points.add(pkey)
        for element in item.get('elements',[]):
            ids=element.get('evidence_ids')
            if not isinstance(ids,list) or not ids or any(not isinstance(eid,str) or eid not in pool for eid in ids):raise ValueError('元素引用了不存在的本行原文片段编号')
            for eid in ids:
                if eid not in used:used.append(eid)
    categories=json.loads(dumps(answer['categories']))
    if seed_mode:
        for item in categories:item.setdefault('needs_verification',[]);item.setdefault('verified_additions',[])
    normalized={'categories':categories,'reason':str(answer.get('reason','')),'evidence':[pool[eid] for eid in used]}
    # Reuse the same strict, per-field source check, without a fixed output count.
    records=validate_batch(normalized,source,allowed,three_topics=False)
    for _,_,data in records:
        data['extraction_scheme']=SCHEME
        if seed_mode:data['output_mode']='article';data['verification_performed']=False
    return normalized,records

def extract_once(worker,source,source_hash,rid,snapshot,variant):
    from extraction_modes import for_snapshot
    extraction_mode=for_snapshot(snapshot)
    single=extraction_mode=='single'
    s=worker.store;mid=source['material_id']
    allowed,rules=compile_rules(snapshot,variant,[source['source_category']] if single else None)
    seed_mode=snapshot.get('output_mode')=='article'
    prompt,pool=adaptive_prompt(source,rules,snapshot['settings'].get('requirements',''),seed_mode,extraction_mode)
    rule_key=digest(SCHEME+'\n'+dumps(rules)+'\n'+str(snapshot['settings'].get('requirements',''))+('\nseed_article_v1' if seed_mode else ''))
    if single:rule_key=digest(rule_key+'\nsingle_v1\n'+source['source_category'])
    worker.update(rid,mid,'extracting')
    with s.connect() as c:cached=c.execute('SELECT * FROM extraction_batches WHERE material_id=? AND source_hash=? AND rule_key=?',(mid,source_hash,rule_key)).fetchone()
    if cached:
        answer=json.loads(cached['data_json']);answer.pop('evidence',None)
        s.log(f'素材#{mid} 复用已保存的{"1→1同赛道" if single else "1→N多赛道"}选题，不调用模型。','extracting',rid,mid)
    else:
        s.log(f'素材#{mid} 开始一次提炼：{"仅原赛道的一个主题" if single else "模型根据素材与赛道规则自行确定N组主题"}。','extracting',rid,mid)
        schema=SEED_EXTRACT if seed_mode else ADAPTIVE_EXTRACT
        if single:
            schema=json.loads(dumps(schema))
            schema['properties']['categories']['maxItems']=1
            schema['properties']['categories']['items']['properties']['category']['enum']=[source['source_category']]
        try:answer=worker.call('adaptive-extract',prompt,schema,rid,mid,snapshot)
        except (ValueError,RuntimeError) as exc:
            if not seed_mode:raise
            # Quota/budget limits and safe pauses are different exception types and propagate.
            answer={'categories':[],'reason':'提炼调用未取得有效结构','model_error':str(exc)[:1200]}
            s.log(f'素材#{mid} 提炼调用失败，转入原赛道保底；错误：'+str(exc)[:1200],'fallback',rid,mid,'warning')
    if seed_mode:
        from extraction_recovery import resolve_topics
        normalized,records=resolve_topics(answer,source,allowed,pool)
        if normalized['validation_issues']:
            s.log(f'素材#{mid} 提炼逐项校验：保留{len(records)}个有效主题；'+ '；'.join(f"第{(x['index']+1) if x['index'] is not None else '?'}项 {x['category']}：{x['reason']}" for x in normalized['validation_issues'][:8]),'extracting',rid,mid,'warning')
    else:normalized,records=resolve_and_validate(answer,source,allowed,pool,seed_mode)
    normalized['extraction_mode']=extraction_mode
    for _,_,data in records:data['extraction_mode']=extraction_mode
    with s.connect() as c:
        from data_integrity import allocate,validate_source
        if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
        validate_source(c,mid,source_hash)
        c.execute('INSERT OR IGNORE INTO extraction_batches(material_id,source_hash,rule_key,run_id,rule_variant,prompt_text,data_json,category_count,target_count,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(mid,source_hash,rule_key,rid,variant,prompt,dumps(normalized),len(records),0,now()))
        bid=c.execute('SELECT id FROM extraction_batches WHERE material_id=? AND source_hash=? AND rule_key=?',(mid,source_hash,rule_key)).fetchone()[0]
        for cat,angle,data in records:
            if c.execute('SELECT id FROM extractions WHERE material_id=? AND source_hash=? AND category=? AND angle=? AND current=1 AND extraction_mode=?',(mid,source_hash,cat,angle,extraction_mode)).fetchone():continue
            from funny_rules import selected_variant
            actual_variant=selected_variant(snapshot,cat,'extract',variant)
            c.execute('INSERT INTO extractions(id,material_id,category,topic,angle,source_hash,rule_variant,prompt_text,data_json,batch_id,created_at,extraction_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(allocate(c,'extractions'),mid,cat,data['topic'],angle,source_hash,actual_variant,prompt,dumps(data),bid,now(),extraction_mode))
        existing=[dict(row) for row in c.execute('SELECT * FROM extractions WHERE material_id=? AND source_hash=? AND current=1 AND extraction_mode=? ORDER BY id',(mid,source_hash,extraction_mode))]
    if single:existing=[x for x in existing if x['category']==source['source_category']][:1]
    s.log(f'素材#{mid} 一次提炼已保存：{len(records)}个有效模型主题，原分类缺失时将补建保底种子。','extracting',rid,mid)
    return existing
