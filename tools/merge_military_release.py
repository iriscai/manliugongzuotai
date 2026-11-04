"""Merge only new development records and their military-source state into a production copy."""
import argparse,json,sqlite3
from contextlib import closing
from pathlib import Path

def q(name):return '"'+name.replace('"','""')+'"'

def main():
    p=argparse.ArgumentParser()
    for k in ['production','development','baseline','output']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();assert not out.exists(),'合并输出已存在'
    out.parent.mkdir(parents=True,exist_ok=True)
    for path in [a.production,a.development]:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as c:
            assert all(c.execute("SELECT count(*) FROM "+t+" WHERE state IN ('running','pausing')").fetchone()[0]==0 for t in ['runs','body_jobs','score_jobs']),'仍有在途任务'
            assert c.execute("SELECT count(*) FROM model_queue WHERE state IN ('queued','waiting','running')").fetchone()[0]==0,'仍有排队任务'
    with closing(sqlite3.connect(a.production.resolve().as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(out.as_uri(),uri=True)) as c:
        src.backup(c);c.row_factory=sqlite3.Row
        c.execute('ATTACH DATABASE ? AS dev',(a.development.resolve().as_uri()+'?mode=ro',))
        c.execute('ATTACH DATABASE ? AS baseline',(a.baseline.resolve().as_uri()+'?mode=ro',))
        tables=[r[0] for r in c.execute("SELECT name FROM main.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        before={t:c.execute('SELECT count(*) FROM main.'+q(t)).fetchone()[0] for t in tables}
        # Both databases branched from this baseline. Stop on a production change rather than overwrite it.
        for t in tables:
            assert not c.execute('SELECT * FROM main.'+q(t)+' EXCEPT SELECT * FROM baseline.'+q(t)+' LIMIT 1').fetchone(),'正式库已改变：'+t
            assert not c.execute('SELECT * FROM baseline.'+q(t)+' EXCEPT SELECT * FROM main.'+q(t)+' LIMIT 1').fetchone(),'正式库已改变：'+t
        c.execute('BEGIN IMMEDIATE');added={}
        for t in tables:
            if t in ['settings','materials','id_counters']:continue
            cols=list(c.execute('PRAGMA main.table_info('+q(t)+')'));keys=[r['name'] for r in sorted(cols,key=lambda x:x['pk']) if r['pk']]
            assert keys,'无主键，不能无损合并：'+t
            join=' AND '.join('d.'+q(k)+'=b.'+q(k) for k in keys)
            rows=list(c.execute('SELECT d.* FROM dev.'+q(t)+' d LEFT JOIN baseline.'+q(t)+' b ON '+join+' WHERE b.'+q(keys[0])+' IS NULL'))
            for r in rows:c.execute('INSERT INTO main.'+q(t)+' VALUES('+','.join('?' for _ in r)+')',tuple(r))
            if rows:added[t]=len(rows)
        mids=[r[0] for r in c.execute('SELECT DISTINCT material_id FROM dev.extractions WHERE id>(SELECT coalesce(max(id),0) FROM baseline.extractions)')]
        assert len(mids)==20,'本次测试素材范围改变，需重新核对'
        for mid in mids:
            row=c.execute('SELECT * FROM dev.materials WHERE id=?',(mid,)).fetchone()
            original=c.execute('SELECT title,body,url FROM main.materials WHERE id=?',(mid,)).fetchone()
            assert tuple(original)==tuple(row[k] for k in ['title','body','url']),'素材原文改变'
            columns=[k for k in row.keys() if k!='id']
            c.execute('UPDATE main.materials SET '+','.join(q(k)+'=?' for k in columns)+' WHERE id=?',tuple(row[k] for k in columns)+(mid,))
        for row in c.execute("SELECT * FROM dev.prompts WHERE category='军事'").fetchall():
            original=c.execute('SELECT * FROM baseline.prompts WHERE id=?',(row['id'],)).fetchone()
            if original:
                assert row['content']==original['content'] and row['name']==original['name'],'旧军事规则内容被改动'
                c.execute('UPDATE main.prompts SET enabled=?,updated_at=? WHERE id=?',(row['enabled'],row['updated_at'],row['id']))
        for k in ['military_extract_variant','military_write_variant']:
            value=c.execute('SELECT value FROM dev.settings WHERE key=?',(k,)).fetchone()[0]
            c.execute('INSERT OR REPLACE INTO main.settings VALUES(?,?)',(k,value))
        for name,value in c.execute('SELECT name,value FROM dev.id_counters').fetchall():
            c.execute('INSERT INTO main.id_counters VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=max(value,excluded.value)',(name,value))
        c.commit()
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert c.execute('SELECT count(*) FROM main.results').fetchone()[0]==before['results']+19
        assert c.execute('SELECT count(*) FROM main.extractions').fetchone()[0]==before['extractions']+20
        assert c.execute("SELECT count(*) FROM main.result_pushes WHERE result_id>2212 AND state='pushed'").fetchone()[0]==19
        report={'output':str(out),'before':before,'added':added,'processed_materials':mids,'integrity_check':'ok','existing_result_rows_preserved':True,'production_settings_preserved':True}
        out.with_suffix('.merge.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'ok':True,'added':added,'materials':before['materials'],'results':before['results']+19,'integrity_check':'ok'},ensure_ascii=False))

if __name__=='__main__':main()
