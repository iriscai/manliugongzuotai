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
        elif not queue and (m['qualification']!='qualified' or not m['title'] or not m['body']):reason='尚未取得有效正文并通过验收；可选择加入队列等待正文'
        elif allowed and m['category'] not in allowed:reason='素材原赛道为空、未知或未启用写文提示词'
        elif c.execute('SELECT 1 FROM results WHERE material_id=? AND category=? AND current=1',(mid,m['category'])).fetchone():reason='原赛道已有文章；重写请到结果库操作'
        else:reason='超出本轮最多领取条数，留待下一轮'
        result.append({'id':mid,'title':m['title'] if m else '素材已不存在','category':m['category'] if m else '', 'reason':reason})
    return result
