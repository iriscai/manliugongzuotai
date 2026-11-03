"""Reversible, independent material and article deletion with fixed previews."""
import uuid
from store import now,dumps,digest
def install_schema(c):
    for table in ['materials','results']:
        cols={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
        for name in ['deleted_at','deleted_batch']:
            if name not in cols:c.execute('ALTER TABLE '+table+' ADD COLUMN '+name+" TEXT NOT NULL DEFAULT ''")
        c.execute('CREATE INDEX IF NOT EXISTS idx_'+table+'_deleted ON '+table+'(deleted_at,id)')
    c.execute('CREATE TABLE IF NOT EXISTS library_deletions(id TEXT PRIMARY KEY,kind TEXT,action TEXT,created_at TEXT,ids_json TEXT,snapshot_json TEXT)')
def validated(payload):
    kind=payload.get('kind');action=payload.get('action','delete');ids=payload.get('ids')
    if kind not in ('materials','results') or action not in ('delete','restore'):raise ValueError('无效的删除范围或操作')
    if not isinstance(ids,list) or not ids or len(ids)>1000 or any(type(i) is not int or i<1 for i in ids):raise ValueError('请选择1至1000条记录')
    return kind,action,list(dict.fromkeys(ids))
def plan(store,payload,c=None):
    if c is None:
        with store.connect() as connection:return plan(store,payload,connection)
    kind,action,ids=validated(payload);marks=','.join('?' for _ in ids)
    rows=[dict(r) for r in c.execute('SELECT * FROM '+kind+' WHERE id IN ('+marks+')',ids)]
    if len(rows)!=len(ids) or any(bool(r['deleted_at'])!=(action=='restore') or kind=='results' and not r['current'] for r in rows):raise ValueError('部分记录已变化、已删除或不存在，请刷新后重新选择')
    rows.sort(key=lambda r:ids.index(r['id']));mids=ids if kind=='materials' else list({r['material_id'] for r in rows});params=','.join('?' for _ in mids)
    busy={r[0] for r in c.execute("SELECT DISTINCT i.material_id FROM run_items i JOIN runs j ON j.id=i.run_id WHERE j.state IN ('running','pausing') AND i.state IN ('queued','running') AND i.material_id IN ("+params+')',mids)}
    busy.update(r[0] for r in c.execute("SELECT DISTINCT i.material_id FROM body_items i JOIN body_jobs j ON j.id=i.job_id WHERE j.state IN ('running','pausing') AND i.status IN ('pending','running') AND i.material_id IN ("+params+')',mids))
    blocked=[{'id':r['id'],'reason':'对应素材正在处理，请暂停并等待当前步骤保存后再操作'} for r in rows if (r['id'] if kind=='materials' else r['material_id']) in busy]
    if kind=='materials' and action=='restore':
        keys=set()
        for row in rows:
            key=(row['title'].strip(),row['body'].strip())
            if not key[1]:continue
            duplicate=c.execute("SELECT id FROM materials WHERE deleted_at=\'\' AND qualification='qualified' AND content_key=? AND id<>?",(row['content_key'],row['id'])).fetchone()
            if duplicate or key in keys:blocked.append({'id':row['id'],'reason':'已有相同标题和正文的合格素材，不能直接恢复重复项'})
            keys.add(key)
    related=c.execute("SELECT count(*) FROM results WHERE material_id IN ("+params+") AND current=1 AND deleted_at=\'\'",mids).fetchone()[0] if kind=='materials' else 0
    return {'kind':kind,'action':action,'ids':ids,'count':len(rows),'rows':[{'id':r['id'],'title':r['title'],'category':r['category']} for r in rows],'blocked':blocked,'version':digest(dumps([kind,action,rows])),'preserved_articles':related}
def apply(store,payload):
    kind,action,ids=validated(payload)
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE');preview=plan(store,payload,c)
        if not payload.get('version') or payload['version']!=preview['version']:raise ValueError('记录或范围已变化，请重新预览后操作')
        if preview['blocked']:raise ValueError('部分记录正在处理或无法恢复，本次没有修改任何记录')
        batch='delete_'+uuid.uuid4().hex[:12];stamp=now();marks=','.join('?' for _ in ids)
        rows=[dict(r) for r in c.execute('SELECT * FROM '+kind+' WHERE id IN ('+marks+')',ids)]
        c.execute('INSERT INTO library_deletions VALUES(?,?,?,?,?,?)',(batch,kind,action,stamp,dumps(ids),dumps(rows)))
        c.execute('UPDATE '+kind+' SET deleted_at=?,deleted_batch=? WHERE id IN ('+marks+')',([stamp,batch] if action=='delete' else ['',''])+ids)
    return {'ok':True,'ids':ids,'count':len(ids),'batch':batch,'action':action,'kind':kind}
