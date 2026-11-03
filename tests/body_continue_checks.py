"""Resume queued/paused original scopes without browsers, network or model calls."""
import csv,json,sys,tempfile,sqlite3,threading
from pathlib import Path
from unittest.mock import patch
import openpyxl
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,dumps,now
from body_fetcher import BodyFetcher
calls=[]
class FakeProcess:
    def __init__(self,cmd,**kwargs):
        self.pid=999999;book=openpyxl.load_workbook(cmd[1]);ws=book.active;ids=[]
        for row in range(2,ws.max_row+1):
            mid=ws.cell(row,1).value;ids.append(mid);ws.cell(row,4,'本地续抓测试正文'+str(mid));ws.cell(row,5,'文章')
        calls.append(ids);book.save(cmd[cmd.index('-o')+1]);book.close()
    def poll(self):return 0
    def wait(self,timeout=None):return 0

with tempfile.TemporaryDirectory(prefix='body-continue-') as temp,patch('body_fetcher.subprocess.Popen',FakeProcess):
    root=Path(temp);s=Store(root/'data',ROOT/'resources');s.save_settings({'body_run_size':2,'body_queue_paused':True,'body_queue_pause_reason':'user','api_key_encrypted':'fixture-do-not-expose'})
    file=root/'source.csv'
    with file.open('w',encoding='utf8',newline='') as f:csv.writer(f).writerows([['标题','链接'],['续抓1','https://fixture.invalid/1'],['续抓2','https://fixture.invalid/2'],['续抓3','https://fixture.invalid/3']])
    s.import_file({'path':str(file)});fetch=BodyFetcher(s)
    q=fetch.enqueue_import([1,2]);stats=fetch.stats();assert stats['queue_paused'] and stats['resume_jobs'][0]['id']==q['job_id']
    assert stats['resume_jobs'][0]['remaining']==2 and stats['resume_jobs'][0]['eligible_remaining']==2
    assert 'fixture-do-not-expose' not in dumps(stats) and 'settings_json' not in dumps(stats)
    r=fetch.resume(q['job_id'],1);fetch.thread.join(5);assert not fetch.thread.is_alive() and calls==[[1]]
    assert fetch.detail(q['job_id'])['job']['state']=='paused' and s.material(1)['body'] and not s.material(2)['body']
    fetch.resume(q['job_id'],1);fetch.thread.join(5);assert calls==[[1],[2]] and fetch.detail(q['job_id'])['job']['state']=='completed'
    try:fetch.resume(q['job_id']);raise AssertionError('completed job resumed')
    except ValueError:pass
    old=fetch._new_job(fetch.select({'ids':[3],'limit':1}),s.settings(),state='queued')
    with s.connect() as c:
        c.execute("UPDATE body_jobs SET state='paused' WHERE id=?",(old,))
        for i in range(25):c.execute('INSERT INTO body_jobs(id,state,total,settings_json,created_at,updated_at) VALUES(?,?,?,?,?,?)',(f'new-completed-{i}','completed',0,dumps(s.settings()),now(),now()))
    stats=fetch.stats();assert old not in {j['id'] for j in stats['jobs']} and old in {j['id'] for j in stats['resume_jobs']}
    # Fixture contains a recent queued job and a paused job older than the 20-card window.
    with s.connect() as c:
        c.execute("UPDATE materials SET body='',body_status='missing',qualification='pending',state='needs_source' WHERE id=2")
    queued=fetch._new_job(fetch.select({'ids':[2],'limit':1,'include_held':True}),s.settings(),state='queued')
    fixture=ROOT/'build'/('body-continue-ui-'+__import__('uuid').uuid4().hex[:8]);fixture.mkdir()
    with s.connect() as c,sqlite3.connect(fixture/'workbench.sqlite3') as dest:c.backup(dest)
    (ROOT/'build/body-continue-ui-fixture.json').write_text(dumps({'data':str(fixture),'paused':old,'queued':queued}),encoding='utf8')
print(dumps({'ok':True,'queued_job_resumes':True,'single_run_limit':True,'completed_not_repeated':True,'paused_outside20_visible_to_resume':True,'snapshot_secrets_not_exposed':True,'browser_calls':0,'model_calls':0}))
