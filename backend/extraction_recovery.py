"""Salvage independent topics, with one source-category article seed as a floor."""
import json
import re
from store import now,dumps

POLICY='source_category_floor_v1'

def resolve_topics(answer,source,allowed,pool):
    from adaptive_extraction import resolve_and_validate
    accepted=[];records=[];issues=[];categories=set();topics=set();points=set()
    def key(text):
        for cat in allowed:text=text.replace(cat,'')
        return re.sub(r'[^\w]+','',text).casefold()
    raw=answer.get('categories') if isinstance(answer,dict) else None
    if not isinstance(raw,list):
        issues.append({'index':None,'category':'','reason':'提炼结果缺少选题数组'})
        raw=[]
    for index,item in enumerate(raw):
        cat=item.get('category','') if isinstance(item,dict) else ''
        try:
            if not isinstance(item,dict):raise ValueError('选题记录不是对象')
            candidate=json.loads(dumps(item))
            for field in ['category','topic','angle','main_point']:
                value=candidate.get(field,'')
                candidate[field]=value.strip() if isinstance(value,str) else ''
            cat=candidate['category']
            if not candidate['topic']:candidate['topic']=candidate['angle']
            if cat not in allowed:raise ValueError('分类不在本轮启用范围')
            if cat in categories:raise ValueError('与已保留选题的分类重复')
            if not candidate['angle'] or not candidate['main_point']:raise ValueError('缺少具体角度或核心重点')
            elements=candidate.get('elements')
            if not isinstance(elements,list):raise ValueError('缺少有效元素数组')
            valid=[]
            for element in elements:
                ids=element.get('evidence_ids') if isinstance(element,dict) else None
                if (isinstance(element,dict) and isinstance(element.get('name'),str) and element['name'].strip()
                    and isinstance(element.get('content'),str) and element['content'].strip()
                    and isinstance(ids,list) and ids and all(isinstance(eid,str) and eid in pool for eid in ids)):
                    valid.append(element)
                else:issues.append({'index':index,'category':cat,'reason':'移除内容或本行证据编号无效的元素'})
            candidate['elements']=valid
            for field in ['omissions','visual_nodes','needs_verification','verified_additions']:candidate.setdefault(field,[])
            _,part=resolve_and_validate({'categories':[candidate],'reason':''},source,allowed,pool,True)
            topic_key=key(candidate['topic']);point_key=key(candidate['main_point'])
            if topic_key in topics or point_key in points:raise ValueError('主题或重点与已保留选题重复')
            categories.add(cat);topics.add(topic_key);points.add(point_key)
            accepted.append(candidate);records.extend(part)
        except (ValueError,TypeError,AttributeError) as exc:
            issues.append({'index':index,'category':str(cat)[:60],'reason':str(exc)[:300]})
    evidence={e['id']:e for _,_,data in records for e in data['evidence']}
    normalized={'categories':accepted,'reason':str(answer.get('reason','')) if isinstance(answer,dict) else '',
                'evidence':list(evidence.values()),'resolution_policy':POLICY,'validation_issues':issues,
                'model_topic_count':len(raw),'accepted_topic_count':len(records)}
    if isinstance(answer,dict) and answer.get('model_error'):normalized['model_error']=answer['model_error']
    return normalized,records

def ensure_source_seed(worker,source,source_hash,rid,snapshot,variant,existing,mode):
    """Persist source text verbatim; never pretend this was a model extraction."""
    from prompt_status import enabled_rules
    from funny_rules import selected_variant
    from adaptive_extraction import source_segments,SCHEME
    from data_integrity import allocate,validate_source
    from extraction_modes import for_snapshot
    extraction_mode=for_snapshot(snapshot)
    s=worker.store;mid=source['material_id'];cat=source.get('source_category','').strip()
    eligible=[x for x in existing if json.loads(x['data_json']).get('eligible')]
    if any(x['category']==cat for x in eligible):return existing
    known={x['name'] for x in snapshot['categories']['categories']}
    allowed=snapshot['settings'].get('allowed_categories') or list(known)
    kinds=['extract','write'] if mode=='both' else ['extract']
    reason=''
    if not cat or cat not in known:reason='素材原分类为空或不在分类库，无法确定保底生文赛道'
    elif cat not in allowed:reason=f'素材原分类“{cat}”不在本轮允许赛道中，无法保底生文'
    elif any(not enabled_rules(snapshot,cat,kind) for kind in kinds):reason=f'素材原分类“{cat}”缺少启用规则，无法保底生文'
    if reason:
        if not eligible:raise ValueError(reason+'；请配置对应赛道后重试')
        s.log(f'素材#{mid}：{reason}，已保留其他有效赛道主题。','extracting',rid,mid,'warning')
        return existing
    _,pool=source_segments(source);body=[e for e in pool.values() if e['field']=='body']
    if not body:raise ValueError('素材正文为空，不能创建原赛道保底种子')
    evidence=[body[0]]+([body[-1]] if len(body)>1 else [])
    angle='原赛道保底：'+cat
    with s.connect() as c:
        if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
        validate_source(c,mid,source_hash)
        prior=c.execute('SELECT * FROM extractions WHERE material_id=? AND source_hash=? AND category=? AND angle=? AND current=1 AND extraction_mode=?',(mid,source_hash,cat,angle,extraction_mode)).fetchone()
        if prior:return existing+[dict(prior)] if all(x['id']!=prior['id'] for x in existing) else existing
        batch=c.execute("SELECT id,data_json FROM extraction_batches WHERE material_id=? AND source_hash=? AND coalesce(json_extract(data_json,'$.extraction_mode'),'multi')=? ORDER BY id DESC LIMIT 1",(mid,source_hash,extraction_mode)).fetchone()
        resolution=json.loads(batch['data_json']) if batch else {}
        why=resolution.get('model_error') or ('多赛道提炼没有有效主题' if not eligible else '多赛道选题未包含素材原分类')
        issues=resolution.get('validation_issues',[])
        if not eligible and issues:why+='：'+issues[0]['reason']
        data={'eligible':True,'topic':source['title'],'main_point':body[0]['quote'],'reason':why,
              'elements':[{'name':'原文定位片段','content':e['quote'],'evidence_ids':[e['id']]} for e in evidence],
              'evidence':evidence,'facts':[{'fact':e['quote'],'quote':e['quote'],'field':'body'} for e in evidence],
              'omissions':[],'visual_nodes':[],'needs_verification':[],'verified_additions':[],
              'extraction_scheme':SCHEME,'extraction_mode':extraction_mode,'output_mode':'article','verification_performed':False,
              'seed_origin':'source_category_fallback','fallback_policy':POLICY,'fallback_reason':why}
        eid=allocate(c,'extractions');actual_variant=selected_variant(snapshot,cat,'extract',variant)
        c.execute('INSERT INTO extractions(id,material_id,category,topic,angle,source_hash,rule_variant,prompt_text,data_json,batch_id,created_at,extraction_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                  (eid,mid,cat,data['topic'],angle,source_hash,actual_variant,'程序保底种子；未额外调用提炼模型，生文阶段执行对应赛道提示词。',dumps(data),batch['id'] if batch else None,now(),extraction_mode))
        result=dict(c.execute('SELECT * FROM extractions WHERE id=?',(eid,)).fetchone())
    s.log(f'素材#{mid} · {cat} 已建立原赛道保底种子，接下来按对应赛道提示词'+('生文。' if mode=='both' else '等待写文。')+'原因：'+why,'fallback',rid,mid,'warning')
    return existing+[result]
