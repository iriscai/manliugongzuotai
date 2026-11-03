"""Normalize auxiliary fields without inventing creative steps or rewriting publication text."""
import copy

POLICY='funny_metadata_normalization_v1'

def normalize(answer):
    out=copy.deepcopy(answer);existing=out.get('_metadata_normalization',[]);changes=list(existing) if isinstance(existing,list) else []
    audit=out.get('generation_audit')
    if not isinstance(audit,dict):return out,changes
    titles=audit.get('t1_titles')
    if isinstance(titles,list) and all(isinstance(t,str) for t in titles):
        trimmed=[t.strip() for t in titles]
        if trimmed!=titles:
            audit['t1_titles']=trimmed;changes.append({'field':'t1_titles','action':'仅去除候选标题首尾空白，未改写内容'})
        titles=trimmed
    reasons=audit.get('t1_short_reasons')
    if not isinstance(reasons,list) or len(reasons)!=2 or any(not isinstance(r,str) for r in reasons):
        audit['t1_short_reasons']=[reasons[i] if isinstance(reasons,list) and i<len(reasons) and isinstance(reasons[i],str) else '' for i in range(2)]
        changes.append({'field':'t1_short_reasons','action':'辅助数组归一为两个字符串；缺失说明保留为空，未编造原因'})
    choice=audit.get('t1_choice')
    if isinstance(choice,str) and choice.strip() in ('1','2'):
        audit['t1_choice']=int(choice.strip());changes.append({'field':'t1_choice','action':'明确的数字字符串转为整数'})
    elif choice not in (1,2) and isinstance(titles,list) and len(titles)==2 and titles.count(out.get('title'))==1:
        audit['t1_choice']=titles.index(out['title'])+1
        changes.append({'field':'t1_choice','action':'根据最终标题与已有候选的唯一逐字匹配回填编号'})
    return out,changes

def validation_record(answer,changes):
    audit=answer['generation_audit'];warnings=[]
    for i,(title,reason) in enumerate(zip(audit['t1_titles'],audit['t1_short_reasons']),1):
        if len(title)<60 and not reason.strip():warnings.append({'code':'short_title_explanation_missing','candidate':i,'length':len(title),'message':'模型未提供短标题说明；程序未判断素材不足，也未改写标题或正文'})
    if len(answer.get('title','').strip())<60 and not audit['t1_short_reasons'][audit['t1_choice']-1].strip():
        warnings.append({'code':'final_short_title_explanation_missing','message':'最终短标题说明缺失，仅记录过程警告，不伪造素材缺口或提高评分'})
    return {'policy':POLICY,'origin':'program_format_audit','changes':changes,'warnings':warnings,'publication_text_changed':False}

def output_contract(variant):
    minimum=48 if variant=='J' else 60
    return f'''输出结构核对：t1_titles必须恰好两个不同的完整标题，每个{minimum}至64个字符，含标点与空格；优先60至64字符。最终title也须{minimum}至64字符。t1_short_reasons必须恰好两个字符串，与候选顺序对应；候选不足60字符时写本故事的具体缺口，禁止漏填、用空数组代替或笼统宣称素材不足。t1_choice只用整数1或2。ending_link逐字复制最终article，punchline必须是实际最后一句或末段。只核对输出格式，不新增模型请求，不重写已合格的故事凑字段。\n'''
