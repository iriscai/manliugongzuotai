"""Calendar retention, fixed previews, backup-first and protected workflow state."""
from workbench_fixtures import *
import os,zipfile
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
import history_cleanup as hc
CURRENT=datetime(2026,11,1,12,0,tzinfo=ZoneInfo('Asia/Shanghai'))
assert hc.cutoff_for('month',datetime(2027,3,31,tzinfo=hc.TZ)).isoformat().startswith('2027-02-28')
assert hc.cutoff_for('month',datetime(2028,3,31,tzinfo=hc.TZ)).isoformat().startswith('2028-02-29')

def protected(s):
    names=['materials','results','extractions','extraction_batches','result_versions','result_pushes','article_score_history','prompts']
    with s.connect() as c:return {name:[tuple(r) for r in c.execute('SELECT * FROM '+name+' ORDER BY rowid')] for name in names}

with tempfile.TemporaryDirectory() as tmp,patch.object(hc,'clock',lambda:CURRENT):
    s,w,fake=seed(Path(tmp),3);task=w.start({'mode':'both','limit':3});wait(w);rid=task['run_id']
    with s.connect() as c:
        c.execute("UPDATE runs SET created_at='2026-09-29T10:00:00',updated_at='2026-09-30T10:00:00' WHERE id=?",(rid,))
        snapshot=c.execute('SELECT snapshot_json FROM runs WHERE id=?',(rid,)).fetchone()[0]
        for name,state,errors in [('paused_old','paused',0),('failed_old','completed',1),('budget_old','completed',0)]:
            c.execute('INSERT INTO runs(id,mode,state,total,errors,snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(name,'both',state,1,errors,snapshot,'2026-09-20T10:00:00','2026-09-21T10:00:00'))
            c.execute('INSERT INTO run_items(run_id,material_id,state) VALUES(?,?,?)',(name,1,'queued' if state=='paused' else 'failed' if errors else 'completed'))
        c.execute("INSERT INTO model_queue(id,state,payload,created_at,updated_at) VALUES('queue_old','paused','{}','2026-09-20T10:00:00','2026-09-20T10:00:00')")
        c.execute("INSERT INTO model_queue_runs VALUES('queue_old','budget_old')")
        c.execute("INSERT INTO model_requests(run_id,stage,day,state,total_tokens,created_at,completed_at) VALUES('budget_old','write','2026-09-20','completed',123,'2026-09-20T10:00:00+08:00','2026-09-20T10:01:00+08:00')")
        for jid,state in [('body_old','completed'),('body_paused','paused')]:
            c.execute('INSERT INTO body_jobs(id,state,total,settings_json,created_at,updated_at) VALUES(?,?,1,?,?,?)',(jid,state,'{}','2026-09-20T10:00:00','2026-09-20T10:00:00'))
            c.execute('INSERT INTO body_items(job_id,material_id,status) VALUES(?,1,?)',(jid,'scraped' if state=='completed' else 'pending'))
        for message,ts,run in [('month_old','2026-09-20T10:00:00',''),('week_old','2026-10-24T10:00:00',''),('naive_before','2026-10-25T11:59:59',''),('utc_before','2026-10-25T03:59:59Z',''),('boundary','2026-10-25T04:00:00Z',''),('recent','2026-10-31T12:00:00',''),('keep_paused','2026-09-20T12:00:00','paused_old')]:
            c.execute('INSERT INTO events(run_id,phase,level,message,created_at) VALUES(?,?,?,?,?)',(run,'fixture','info',message,ts))
    epoch=datetime(2026,9,20,12,tzinfo=hc.TZ).timestamp()
    for rel in ['runs/'+rid+'/answer.json','body_fetch/body_old/result.txt','body_fetch/body_paused/protected.txt','runs/manual_backup/keep.txt','backend.log']:
        path=s.root/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('历史缓存',encoding='utf8');os.utime(path,(epoch,epoch))
    outside=Path(tmp)/'outside.txt';outside.write_text('keep',encoding='utf8');assert hc.safe_file(s.root,outside) is None
    before=protected(s);month=hc.preview(s,{'period':'month'});week=hc.preview(s,{'period':'7d'})
    assert month['counts']['runs']==1 and month['counts']['body_jobs']==1 and month['protected_tasks']>=4
    assert week['counts']['events']>month['counts']['events'] and month['files']==3
    # Any concurrent change in the selected scope invalidates the concrete preview.
    with s.connect() as c:c.execute("INSERT INTO events(phase,message,created_at) VALUES('fixture','changed','2026-09-01T12:00:00')")
    try:hc.apply(s,month);raise AssertionError('stale preview accepted')
    except ValueError:pass
    assert protected(s)==before
    fresh=hc.preview(s,{'period':'month'})
    with patch.object(zipfile.ZipFile,'writestr',side_effect=OSError('disk unavailable')):
        try:hc.apply(s,fresh);raise AssertionError('backup failure ignored')
        except OSError:pass
    with s.connect() as c:assert c.execute('SELECT 1 FROM runs WHERE id=?',(rid,)).fetchone()
    assert protected(s)==before
    done=hc.apply(s,hc.preview(s,{'period':'month'}));assert done['files_removed']==3 and not done['warnings']
    assert protected(s)==before and outside.read_text(encoding='utf8')=='keep'
    assert (s.root/'body_fetch/body_paused/protected.txt').exists() and (s.root/'runs/manual_backup/keep.txt').exists()
    with zipfile.ZipFile(done['backup_path']) as z:
        assert z.read('files/runs/'+rid+'/answer.json').decode('utf8')=='历史缓存'
        assert 'records/runs.jsonl' in z.namelist()
    with s.connect() as c:
        assert c.execute('SELECT count(*) FROM runs WHERE id=?',(rid,)).fetchone()[0]==0
        assert c.execute("SELECT count(*) FROM runs WHERE id IN ('paused_old','failed_old','budget_old')").fetchone()[0]==3
        assert c.execute("SELECT total_tokens FROM model_requests WHERE run_id='budget_old'").fetchone()[0]==123
        assert c.execute('SELECT count(*) FROM model_requests WHERE run_id=?',(rid,)).fetchone()[0]>0,'Recent usage must not be reset'
        assert c.execute("SELECT count(*) FROM events WHERE message='keep_paused'").fetchone()[0]==1
    # Cleaning old history cannot make completed material eligible for regeneration.
    try:w.start({'mode':'both','limit':3});raise AssertionError('old material got regenerated')
    except ValueError:pass
    logs=hc.preview(s,{'period':'7d','records':False,'logs':True,'files':False});hc.apply(s,logs)
    with s.connect() as c:
        assert not c.execute("SELECT 1 FROM events WHERE message IN ('week_old','naive_before','utc_before')").fetchone()
        assert c.execute("SELECT count(*) FROM events WHERE message IN ('boundary','recent','keep_paused')").fetchone()[0]==3
        c.execute("UPDATE runs SET state='running' WHERE id='paused_old'")
    blocked=hc.preview(s,{'period':'month'});assert blocked['busy']
    try:hc.apply(s,blocked);raise AssertionError('active task cleanup allowed')
    except ValueError:pass
print(json.dumps({'ok':True,'calendar_month_and7days':True,'beijing_boundary_correct':True,'backup_failure_aborts':True,'stale_preview_refused':True,'unfinished_and_budget_tasks_preserved':True,'libraries_scores_receipts_unchanged':True,'only_safe_cache_paths':True,'no_regeneration':True,'external_calls':0}))
