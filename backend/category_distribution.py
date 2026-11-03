"""Read-only, full-scope category totals for each workbench module."""
import json

def distribution(store,q):
    module=q.get('module','overview')
    if module not in ('overview','materials','bodies','queue','writing','results','rules','settings','history'):raise ValueError('未知统计模块')
    encoded=q.get('filters','{}')
    if len(encoded)>12000:raise ValueError('统计筛选条件过长')
    filters=json.loads(encoded)
    if not isinstance(filters,dict):raise ValueError('统计筛选必须为对象')
    args=[];extras='';unit='条'
    if module in ('overview','materials','bodies','settings'):
        from material_catalog import query_parts
        scope={'overview':'全部在库素材','materials':'当前筛选的全部素材','bodies':'正文抓取 · 全部在库素材','settings':'已验收的合格素材'}[module]
        selected=filters if module=='materials' else {'qualification':'qualified'} if module=='settings' else {}
        where,args,*_=query_parts(selected)
        source='SELECT m.category,m.qualification,m.body FROM materials m'+where
        extras=",sum(qualification='qualified') qualified,sum(body<>'') with_body"
    elif module=='results':
        from workflow_management import query_parts
        join,args=query_parts(store,filters);source='SELECT r.category'+join
        scope='当前筛选的全部文章成品';unit='篇'
    elif module=='writing':
        from pipeline_catalog import writing_scope
        join,args,effective=writing_scope(filters);source='SELECT e.category,('+effective+') write_state'+join
        extras=",sum(write_state='written') written,sum(write_state='ready') ready"
        scope='当前状态的全部写文种子';unit='份'
    elif module=='rules':
        source='SELECT category,enabled FROM prompts';scope='全部提炼规则与改写提示词';unit='份'
        extras=',sum(enabled=1) enabled,sum(enabled=0) disabled'
    elif module=='queue':
        source="SELECT m.category FROM materials m JOIN (SELECT material_id FROM run_items UNION SELECT material_id FROM model_queue_items) t ON t.material_id=m.id WHERE m.deleted_at=''"
        scope='处理记录中的在库素材 · 按素材去重'
    else:
        from operations import history_scope
        clause,args=history_scope(filters)
        source="SELECT coalesce(m.category,'已移除素材') category FROM run_items i JOIN (SELECT id FROM runs"+clause+") j ON j.id=i.run_id LEFT JOIN materials m ON m.id=i.material_id"
        scope='当前筛选的处理历史 · 每轮分别计数';unit='条次'
    category="coalesce(nullif(trim(category),''),'未分类')"
    with store.connect() as c:
        rows=[dict(r) for r in c.execute('SELECT '+category+' category,count(*) count'+extras+' FROM ('+source+') GROUP BY '+category+' ORDER BY count DESC,category',args)]
    total=sum(r['count'] for r in rows)
    for r in rows:r['percentage']=r['count']/total*100 if total else 0
    return {'module':module,'scope':scope,'unit':unit,'total':total,'category_count':len(rows),'rows':rows}
