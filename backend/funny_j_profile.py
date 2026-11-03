"""Additive J release: retain every existing prompt row and its enabled state."""
import hashlib,json
from pathlib import Path
from store import dumps
from funny_singlecall import content_hash

def current_hash(c):
    rows={r['kind']:r['content'] for r in c.execute("SELECT kind,content FROM prompts WHERE category='搞笑' AND variant='J'")}
    return content_hash(rows.get('extract',''),rows.get('write',''))

def release_info(resources):
    resources=Path(resources);file=resources/'funny-J-release.json'
    if not file.is_file():return {'status':'pending','variant':'J'}
    info=json.loads(file.read_text(encoding='utf8'))
    if info.get('status')!='approved':return info
    scores=resources/'funny-J-scores.json'
    if not scores.is_file() or hashlib.sha256(scores.read_bytes()).hexdigest()!=info.get('scores_sha256'):return {'status':'pending','variant':'J','note':'试跑评分记录缺失或校验失败'}
    rows=json.loads(scores.read_text(encoding='utf8'))
    if len(rows)<6 or len({r.get('source_result_id') for r in rows})!=len(rows) or any(r.get('final_total',0)<90 or r.get('model_score',0)<90 for r in rows):return {'status':'pending','variant':'J','note':'试跑尚未达到启用标准'}
    return info

def migrate(c,resources,stamp):
    resources=Path(resources)
    if not all((resources/f'funny-J-{k}.txt').is_file() for k in ['extract','write']):return
    for kind,name in [('extract','喜剧核与改编空间提炼'),('write','场景落地·口语收口·R1/R2/T1/T2')]:
        content=(resources/f'funny-J-{kind}.txt').read_text(encoding='utf8').strip()
        c.execute('INSERT OR IGNORE INTO prompts(category,kind,variant,name,content,enabled,updated_at) VALUES(?,?,?,?,?,0,?)',('搞笑',kind,'J',name,content,stamp))
    info=release_info(resources);fingerprint=current_hash(c)
    approval='funny_J_approved_'+fingerprint
    if info.get('status')=='approved' and info.get('content_sha256')==fingerprint and not c.execute('SELECT 1 FROM prompt_library_updates WHERE key=?',(approval,)).fetchone():
        for row in c.execute("SELECT id,enabled FROM prompts WHERE category='搞笑' AND variant='J'").fetchall():
            if not row['enabled']:
                c.execute('INSERT INTO prompt_status_history(prompt_id,old_enabled,new_enabled,created_at) VALUES(?,?,1,?)',(row['id'],0,stamp))
                c.execute('UPDATE prompts SET enabled=1,status_updated_at=? WHERE id=?',(stamp,row['id']))
        for kind in ['extract','write']:c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('funny_'+kind+'_variant',dumps('J')))
        c.execute('INSERT INTO prompt_library_updates VALUES(?,?)',(approval,stamp))
    existing=c.execute("SELECT value FROM settings WHERE key='funny_J_validation'").fetchone()
    if not existing:c.execute('INSERT INTO settings VALUES(?,?)',('funny_J_validation',dumps(info)))
    elif info.get('status')=='approved' and info.get('content_sha256')==fingerprint:
        old=json.loads(existing[0])
        if old.get('status')!='needs_trial':c.execute('UPDATE settings SET value=? WHERE key=?',(dumps(info),'funny_J_validation'))
