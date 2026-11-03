"""Human-readable exclusions for a selected, bounded execution preview."""
def excluded_rows(c,payload,included,mode,allowed=None,queue=False):
    selected=payload.get('ids',[]) if payload.get('scope')=='selected' else []
    included=set(included);missing=[i for i in selected if i not in included]
    if not missing:return []
    rows={r['id']:dict(r) for r in c.execute('SELECT id,title,category,state,qualification,body,deleted_at FROM materials WHERE id IN ('+','.join('?' for _ in missing)+')',missing)}
    result=[]
    for mid in missing:
        m=rows.get(mid)
        if not m or m['deleted_at']:reason='素材不存在或已删除'
        elif m['state'] in ('routing','extracting','writing','fetching'):reason='素材正在处理，请等待当前步骤完成'
        elif m['state']=='written':reason='已生成文章；重生成请到结果库操作'
        elif m['state']=='skipped':reason='已提炼但没有适配主题，当前不重复执行'
        elif not queue and (m['qualification']!='qualified' or not m['title'] or not m['body']):reason='尚未取得有效正文并通过验收；可选择加入队列等待正文'
        elif payload.get('extraction_mode', 'multi')=='single' and allowed and m['category'] not in allowed:reason='原分类为空、未知或未启用所需规则，1→1不会改投其他赛道'
        else:
            from extraction_modes import resolve,seed_scope
            mode_scope=resolve(payload,{})
            seeds=list(c.execute('SELECT e.id,e.category,e.eligible FROM extractions e JOIN materials m ON m.id=e.material_id WHERE e.material_id=? AND e.current=1 AND '+seed_scope(mode_scope,'e','m'),(mid,)))
            if mode=='extract' and seeds:reason='已有提炼结果，不重复提炼'
            elif mode in ('both','write') and seeds:
                pending=[x for x in seeds if x['eligible'] and (not allowed or x['category'] in allowed) and not c.execute('SELECT 1 FROM results WHERE extraction_id=? AND current=1',(x['id'],)).fetchone()]
                reason='超出本轮最多领取条数，留待下一轮' if pending else '已有提炼结果，但没有当前允许赛道的待生文主题'
            elif mode=='write':reason='没有可直接生文的适配提炼种子'
            else:reason='超出本轮最多领取条数，留待下一轮'
        result.append({'id':mid,'title':m['title'] if m else '素材已不存在','category':m['category'] if m else '', 'reason':reason})
    return result
