def obj(properties): return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def arr(item): return {'type':'array','items':item}
S={'type':'string'}
B={'type':'boolean'}
I={'type':'integer'}
ROUTE=obj({'routes':arr(obj({'category':S,'angle':S,'reason':S,'quote':S})),'reason':S})
EXTRACT=obj({'eligible':B,'reason':S,'main_point':S,'facts':arr(obj({'fact':S,'quote':S})),'omissions':arr(S),'visual_nodes':arr(S),'needs_verification':arr(S),'verified_additions':arr(obj({'claim':S,'url':S}))})
MULTI_EXTRACT_LEGACY=obj({'evidence':arr(obj({'id':S,'field':S,'quote':S})),
    'categories':arr(obj({'category':S,'angle':S,'reason':S,'main_point':S,
        'elements':arr(obj({'name':S,'content':S,'evidence_ids':arr(S)})),
        'omissions':arr(S),'visual_nodes':arr(S),'needs_verification':arr(S),
        'verified_additions':arr(obj({'claim':S,'url':S}))})),
    'reason':S})
import copy
MULTI_EXTRACT=copy.deepcopy(MULTI_EXTRACT_LEGACY)
MULTI_EXTRACT['properties']['categories']['items']['properties']['topic']=S
MULTI_EXTRACT['properties']['categories']['items']['required'].append('topic')
ADAPTIVE_EXTRACT=copy.deepcopy(MULTI_EXTRACT)
ADAPTIVE_EXTRACT['properties'].pop('evidence')
ADAPTIVE_EXTRACT['required'].remove('evidence')
SEED_EXTRACT=copy.deepcopy(ADAPTIVE_EXTRACT)
for key in ['needs_verification','verified_additions']:
    SEED_EXTRACT['properties']['categories']['items']['properties'].pop(key)
    SEED_EXTRACT['properties']['categories']['items']['required'].remove(key)
ARTICLE=obj({'category':S,'title':{'type':'string','maxLength':64,'description':'尽量参考本条原文标题，保留其核心词与爆点，仅做必要微调或压缩；最多64个Unicode字符，标点和空格也计入'},'article':{'type':'string','description':'8至15个自然段的完整短文，段间空行，不写每段主题、小标题、标签或编号；一段承接一张图文案。标题不计入正文段数，标题和正文合计不超过300非空白字符'}})
WRITE=obj({'title':S,'short_text':S,'frames':arr(obj({'number':I,'purpose':S,'scene':S,'caption':S,'dialogue':arr(obj({'speaker':S,'text':S})),'visible_labels':arr(S),'image_prompt':S})),'post_text':S,'notice':S,'genre':S,'adaptations':arr(S)})
