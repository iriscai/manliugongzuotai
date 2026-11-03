"""Hide confirmed delivered results while preserving their completion receipts."""
import json,uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from title_push import PROJECT,delivery_signature

def install_schema(c):
    columns={r[1] for r in c.execute('PRAGMA table_info(results)')}
    if 'cleared_at' not in columns:c.execute("ALTER TABLE results ADD COLUMN cleared_at TEXT NOT NULL DEFAULT ''")
    c.execute('CREATE INDEX IF NOT EXISTS idx_result_visible ON results(cleared_at,current,id)')
    c.execute('''CREATE TABLE IF NOT EXISTS result_cleanup_batches(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,count INTEGER NOT NULL,backup_path TEXT NOT NULL,result_ids TEXT NOT NULL)''')

def delivered_where(alias='r'):
    return f'''{alias}.current=1 AND {alias}.deleted_at=\'\' AND {alias}.cleared_at='' AND EXISTS(SELECT 1 FROM result_pushes p WHERE p.result_id={alias}.id AND p.target_path=? AND p.state='pushed' AND p.content_hash=result_delivery_signature({alias}.category,{alias}.title,coalesce(nullif({alias}.article,''),{alias}.short_text),{alias}.score,{alias}.score_status,{alias}.score_content_hash))'''

def clearable_count(c):
    return c.execute('SELECT count(*) FROM results r WHERE '+delivered_where(),(str(__import__('push_targets').project_in(c)/'picfactory_matrix.db'),)).fetchone()[0]

def clear_pushed(store):
    """Back up and clear every delivered current content version, across all pages."""
    target=str(__import__('push_targets').project_for(store)/'picfactory_matrix.db')
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        candidates=[dict(r) for r in c.execute('SELECT r.* FROM results r WHERE '+delivered_where(),(target,))]
        rows=[];receipts=[]
        for row in candidates:
            routing=store.settings()
            receipt=c.execute("SELECT * FROM result_pushes WHERE result_id=? AND target_path=? AND content_hash=? AND state='pushed'",(row['id'],target,delivery_signature(row,routing.get('push_category_map',{}),routing.get('push_score_rules')))).fetchone()
            if receipt:rows.append(row);receipts.append(dict(receipt))
        if not rows:return {'ok':True,'count':0,'ids':[],'backup_path':''}
        timestamp=datetime.now(ZoneInfo('Asia/Shanghai'));batch=uuid.uuid4().hex[:12]
        folder=store.root/'result_cleanup_backups';folder.mkdir(parents=True,exist_ok=True)
        path=folder/('已推送文章_'+timestamp.strftime('%Y%m%d-%H%M%S')+'_'+batch+'.json')
        payload={'kind':'cleared_pushed_results','batch_id':batch,'created_at':timestamp.isoformat(timespec='seconds'),'count':len(rows),'results':rows,'push_receipts':receipts}
        # A failed backup aborts the transaction before any visible article is removed.
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)
        ids=[row['id'] for row in rows];stamp=timestamp.isoformat(timespec='seconds')
        c.executemany('UPDATE results SET cleared_at=? WHERE id=?',[(stamp,rid) for rid in ids])
        c.execute('INSERT INTO result_cleanup_batches VALUES(?,?,?,?,?)',(batch,stamp,len(ids),str(path),json.dumps(ids)))
        c.execute('INSERT INTO events(run_id,material_id,phase,level,message,created_at) VALUES(?,?,?,?,?,?)',('',None,'cleanup','info',f'已清除{len(ids)}篇已推送成品，素材、种子和完成状态保留；备份：{path}',stamp))
    return {'ok':True,'count':len(ids),'ids':ids,'backup_path':str(path)}
