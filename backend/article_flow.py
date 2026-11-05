"""Direct seed-to-article production, without a verification workflow gate."""
import json
import re
from store import chars,dumps
from writing_prompts import COMMON_RULE,source_policy,writing_directions
from paragraph_policy import effective_rule,INSTRUCTION,POLICY

def install_schema(c):
    cols={r[1] for r in c.execute('PRAGMA table_info(results)')}
    c.execute('CREATE INDEX IF NOT EXISTS idx_extraction_direct_write ON extractions(current,eligible,material_id)')
    if 'article' not in cols:
        c.execute("ALTER TABLE results ADD COLUMN article TEXT DEFAULT ''")
        c.execute("UPDATE results SET article=coalesce(short_text,'')")

def article_prompt(rule,source,data,category,angle,requirements,variant=None):
    if category=='军事':
        from military_profile import VARIANTS,prompt
        inferred=variant if variant in VARIANTS else next((v for v in VARIANTS if rule.startswith('军事'+v+'｜')),None)
        if inferred:return prompt(rule,source,data,angle,requirements,inferred)
    funny=category=='搞笑'
    if funny:rule=effective_rule(rule)
    elements=data.get('elements') or [{'name':'来源元素','content':f.get('fact',''),'evidence':f.get('quote','')} for f in data.get('facts',[])]
    seed={'original_title':source.get('title',''),'category':category,'topic':data.get('topic') or angle,'main_point':data.get('main_point',''),'elements':elements,'evidence':data.get('evidence',[])}
    if category=='搞笑' and '方案J：单次响应·场景落地与口语收口' in rule:
        seed.update(seed_origin=data.get('seed_origin','model_extraction'),fallback_reason=data.get('fallback_reason',''))
        return INSTRUCTION+'\n'+rule+'\n本组种子：'+dumps(seed)+'\n本条原始素材：'+dumps(source)+'\n用户补充要求：'+str(requirements or '')
    if data.get('seed_origin')=='source_category_fallback':
        seed.update(seed_origin=data['seed_origin'],fallback_reason=data.get('fallback_reason',''))
        rule+='\n本组为原赛道直接生文保底种子。定位片段不代表全文重点，必须完整阅读本条原始正文，在本次生文响应内选出适合目标赛道的重点，再严格执行本赛道写文方向，直接生成一篇完整文章。不输出提炼过程，不强凑跨赛道主题，不凭原标题添加没有依据的事实。'
    specification='只返回JSON的三个字段category、title、article，分别是赛道、标题、文章。category必须原样等于目标赛道。title贴近本组种子original_title中的相关爆点；article必须为8至15个自然段，用空行分隔，不加每段主题或小标题。标题不计入正文段数。历史规则里的3至5节、分段小标题或最多10张图要求不再执行。不能用提纲、待核实提示或占位文字代替正文。'
    if funny:specification='只返回JSON的三个字段category、title、article，分别是赛道、标题、文章。category必须原样等于目标赛道。title贴近本组种子original_title中的相关爆点。'+INSTRUCTION+'不加每段主题或小标题，不能用提纲、待核实提示或占位文字代替正文。'
    prompt=(effective_rule(COMMON_RULE) if funny else COMMON_RULE)+'\n\n'+source_policy(category)+'''
每次只写本组选题，不混入其他组或其他素材。本步骤是直接创作，参考规则中的旧版核实、审核副本或分镜格式要求本次不执行，历史核实备注也不阻止生文。
'''+specification+'''
本赛道写文方向：
'''+writing_directions(rule)+'\n本组种子：'+dumps(seed)+'\n本条原始素材：'+dumps(source)+'\n用户补充要求：'+str(requirements or '')

    from funny_singlecall import adapt_prompt
    if category=='军事':
        from military_ip_style import effective_write,time_context
        return effective_write(prompt)+'\n'+time_context()
    return adapt_prompt(prompt,category,rule)

def normalize_article(answer,category,profile=None):
    if not isinstance(answer,dict) or answer.get('category')!=category:raise ValueError('文章成品缺少正确的所属赛道')
    if category=='军事':
        from military_profile import variant_for,normalize
        if variant_for(profile):return normalize(answer,profile)
    title=str(answer.get('title','')).strip();article=str(answer.get('article','')).strip()
    if not title or not article:raise ValueError('文章成品缺少标题或正文')
    if len(title)>64:raise ValueError(f'作品标题共{len(title)}个字符，超过64字符上限（含标点和空格）')
    length=chars(title+article)
    if length>300:raise ValueError(f'标题和文章合计{length}字符，超过300上限')
    paragraphs=[line.strip() for line in article.splitlines() if line.strip()]
    if category!='搞笑' and not 8<=len(paragraphs)<=15:raise ValueError(f'正文共{len(paragraphs)}段，需要8至15个自然段')
    if any(re.match(r'^(?:【[^】\n]{1,24}】|#{1,6}\s|第[一二三四五六七八九十\d]+段[：:、])',p) for p in paragraphs):raise ValueError('正文不能带每段主题、小标题或段落编号，请直接输出自然段')
    article=('\n' if category=='搞笑' else '\n\n').join(paragraphs)
    result={'category':category,'title':title,'article':article,'short_text':article,'frames':[],'output_kind':'article','stage':'文章成品','actual_images':0,'paragraph_count':len(paragraphs),'planned_image_count':0 if category=='搞笑' else len(paragraphs)}
    if category=='搞笑':result['paragraph_policy']=POLICY
    return result,length,0
