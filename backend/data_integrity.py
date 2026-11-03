"""Stable identities and input/output revisions across pause, edit and retry."""
import hashlib

def source_hash(title,body):return hashlib.sha256((title+'\n'+body).encode('utf8')).hexdigest()

def install_schema(c):
    c.execute('CREATE TABLE IF NOT EXISTS id_counters(name TEXT PRIMARY KEY,value INTEGER NOT NULL)')
    for table,refs in {'extractions':[('run_writes','extraction_id'),('results','extraction_id'),('result_versions','extraction_id')],
                       'results':[('result_versions','result_id'),('result_pushes','result_id')]}.items():
        peak=c.execute('SELECT coalesce(max(id),0) FROM '+table).fetchone()[0]
        for ref,col in refs:peak=max(peak,c.execute('SELECT coalesce(max('+col+'),0) FROM '+ref).fetchone()[0])
        c.execute('INSERT INTO id_counters(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=max(value,excluded.value)',(table,peak))
    for table,name,definition in [('run_items','source_hash',"TEXT NOT NULL DEFAULT ''"),('run_writes','base_revision','INTEGER NOT NULL DEFAULT 0'),('results','content_revision','INTEGER NOT NULL DEFAULT 1')]:
        columns={r[1] for r in c.execute('PRAGMA table_info('+table+')')}
        if name not in columns:c.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+definition)
    # Migrate only unambiguous historical input evidence; never guess the old source.
    for row in c.execute("SELECT run_id,material_id FROM run_items WHERE source_hash='' AND state IN ('queued','running','failed')").fetchall():
        hashes={r[0] for r in c.execute('SELECT DISTINCT e.source_hash FROM run_writes w JOIN extractions e ON e.id=w.extraction_id WHERE w.run_id=? AND w.material_id=?',(row['run_id'],row['material_id']))}
        hashes.update(r[0] for r in c.execute('SELECT DISTINCT source_hash FROM extraction_batches WHERE run_id=? AND material_id=?',(row['run_id'],row['material_id'])))
        if len(hashes)==1:c.execute('UPDATE run_items SET source_hash=? WHERE run_id=? AND material_id=?',(hashes.pop(),row['run_id'],row['material_id']))

def allocate(c,table):
    if table not in ('extractions','results'):raise ValueError('不支持的编号类型')
    if not c.in_transaction:c.execute('BEGIN IMMEDIATE')
    prior=c.execute('SELECT value FROM id_counters WHERE name=?',(table,)).fetchone()
    peak=c.execute('SELECT coalesce(max(id),0) FROM '+table).fetchone()[0]
    value=max(prior[0] if prior else 0,peak)+1
    c.execute('INSERT OR REPLACE INTO id_counters(name,value) VALUES(?,?)',(table,value))
    return value

def validate_source(c,mid,expected,eid=None):
    row=c.execute('SELECT title,body,qualification,deleted_at FROM materials WHERE id=?',(mid,)).fetchone()
    if not row or row['deleted_at'] or row['qualification']!='qualified' or source_hash(row['title'],row['body'])!=expected:
        raise ValueError('素材正文或验收状态已变化，旧任务不能继续使用原种子；请按新正文创建任务')
    if eid is not None:
        deleted=c.execute("SELECT 1 FROM results WHERE extraction_id=? AND deleted_at<>\'\'",(eid,)).fetchone()
        if deleted:raise ValueError('文章已删除，请先恢复后再生成')
        extraction=c.execute('SELECT source_hash,current,material_id FROM extractions WHERE id=?',(eid,)).fetchone()
        if not extraction or not extraction['current'] or extraction['material_id']!=mid or extraction['source_hash']!=expected:
            raise ValueError('提炼种子已失效或不属于当前正文，请重新提炼后生文')
