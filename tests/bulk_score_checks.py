"""Score-only batches, persistence, budgets, manual edits and retries; fake inference only."""
from workbench_fixtures import *
from score_jobs import ScoreJobs,SCHEMA,select_pending
from providers import ProviderLimit
from article_quality import apply as apply_grade
from title_push import signature

class ScoreFake:
    def __init__(self):self.calls=[];self.started=threading.Event();self.release=None;self.fail=set();self.quota=False;self.lock=threading.Lock();self.active=0;self.peak=0
    def auth_status(self,_):return {'ok':True}
    def reset(self):pass
    def call(self,prompt,schema,settings,folder,on_event=None):
        assert schema is SCHEMA and '禁止改写' in prompt and '待评分作品：' in prompt
        r=json.loads(prompt.split('待评分作品：',1)[1]);rid=int(Path(folder).name)
        on_event({'event':'request_start'})
        with self.lock:self.calls.append(rid);self.active+=1;self.peak=max(self.peak,self.active)
        self.started.set();ok=False
        try:
            if self.release:assert self.release.wait(8)
            if self.quota:raise ProviderLimit('本机模拟余额不足')
            time.sleep(.03);ok=True
            return {'quality_score':{'completeness':90,'reversal':90,'fun':90,'reason':'本机模拟按现有标题正文评分','evidence':['不存在的证据'] if rid in self.fail else [r['title']],'risks':[]}}
        finally:
            with self.lock:self.active-=1
            on_event({'event':'request_finish','ok':ok,'usage':{'input_tokens':100,'output_tokens':10,'total_tokens':110}})

def setup(path,count=3):
    s,w,_=seed(path,count);w.start({'mode':'both','limit':count});wait(w)
    with s.connect() as c:
        ids=[r[0] for r in c.execute('SELECT id FROM results ORDER BY id')]
        c.execute("UPDATE results SET category='搞笑',score=NULL,score_status='invalid_contract',score_json='{}',score_content_hash='' ")
    s.save_settings({'write_workers':2,'global_max_concurrency':2})
    fake=ScoreFake();w.provider=fake;sc=ScoreJobs(s,w)
    return s,w,fake,sc,ids

def protect(s):
    with s.connect() as c:
        return {t:c.execute('SELECT '+('id,title,article,data_json,content_revision,batch_id,created_at,write_variant' if t=='results' else '*')+' FROM '+t+' ORDER BY rowid').fetchall() for t in ['materials','extractions','results','result_versions','prompts']}

with tempfile.TemporaryDirectory(prefix='bulk-score-') as tmp:
    root=Path(tmp);s,w,f,sc,ids=setup(root/'batch')
    with s.connect() as c:
        c.execute("UPDATE results SET category='生活',score=60,score_status='default' WHERE id=?",(ids[-1],))
        c.execute("UPDATE results SET score_status='score_failed' WHERE id=?",(ids[1],))
        row=dict(c.execute('SELECT * FROM results WHERE id=?',(ids[-2],)).fetchone());apply_grade(c,row,{'completeness':80,'reversal':80,'fun':80,'reason':'原人工复核','evidence':[row['title']],'risks':[]},'人工复核')
    baseline=protect(s);p=sc.preview({'ids':ids});assert p['total']==4 and len(p['skipped'])==2 and not f.calls
    assert set(select_pending(s,{})['ids'])==set(ids[:4])
    assert set(select_pending(s,{'score_band':'rescore'})['ids'])==set(ids[:4])-{ids[1]}
    assert select_pending(s,{'score_band':'score_failed'})['ids']==[ids[1]]
    job=sc.start(p['id']);assert sc.start(p['id'])['id']==job['id'];wait(w)
    assert sorted(f.calls)==ids[:4] and f.peak==2 and protect(s)==baseline
    with s.connect() as c:
        assert {r[0] for r in c.execute("SELECT score FROM results WHERE id IN (SELECT result_id FROM score_items WHERE job_id=?)",(job['id'],))}=={95}
        assert c.execute("SELECT count(*) FROM model_requests WHERE run_id=? AND stage='score'",(job['id'],)).fetchone()[0]==4
    summary=sc.list()['rows'][0];assert summary['counts']['completed']==4 and summary['usage']['total_tokens']==440 and 'snapshot_json' not in summary

    # Preview/config changes cannot silently turn into paid requests.
    s,w,f,sc,ids=setup(root/'preview',1);p=sc.preview({'ids':ids})
    s.save_settings({'write_workers':1})
    try:sc.start(p['id']);raise AssertionError('changed settings accepted')
    except ValueError:pass
    assert not f.calls
    p=sc.preview({'ids':ids})
    with s.connect() as c:c.execute("UPDATE results SET title='修改后的标题',content_revision=content_revision+1 WHERE id=?",(ids[0],))
    try:sc.start(p['id']);raise AssertionError('changed article accepted')
    except ValueError:pass
    assert not f.calls

    # Safe pause persists completed scores; restart/resume never repeats them.
    s,w,f,sc,ids=setup(root/'pause');s.save_settings({'write_workers':1});f.release=threading.Event()
    jid=sc.start(sc.preview({'ids':ids})['id'])['id'];assert f.started.wait(5)
    w.pause(jid);f.release.set();wait(w)
    first=sc.list()['rows'][0];assert first['state']=='paused' and first['counts']['completed']==1 and first['counts']['queued']==5
    assert len(f.calls)==1
    s=Store(s.root,ROOT/'resources');w=Worker(s);f2=ScoreFake();w.provider=f2;sc=ScoreJobs(s,w);sc.resume(jid);wait(w)
    assert len(f2.calls)==5 and sc.list()['rows'][0]['counts']['completed']==6

    # A late response cannot overwrite a user edit or a new manual grade.
    s,w,f,sc,ids=setup(root/'changed',1);f.release=threading.Event();s.save_settings({'write_workers':1})
    jid=sc.start(sc.preview({'ids':[ids[0]]})['id'])['id'];assert f.started.wait(5)
    with s.connect() as c:c.execute("UPDATE results SET title='评分期间的新版',content_revision=content_revision+1 WHERE id=?",(ids[0],))
    f.release.set();wait(w);assert sc.list()['rows'][0]['counts']['skipped']==1
    with s.connect() as c:assert c.execute('SELECT title,score FROM results WHERE id=?',(ids[0],)).fetchone()[:]==('评分期间的新版',None)

    s,w,f,sc,ids=setup(root/'manual',1);f.release=threading.Event();s.save_settings({'write_workers':1})
    jid=sc.start(sc.preview({'ids':[ids[0]]})['id'])['id'];assert f.started.wait(5)
    with s.connect() as c:
        row=dict(c.execute('SELECT * FROM results WHERE id=?',(ids[0],)).fetchone())
        apply_grade(c,row,{'completeness':80,'reversal':80,'fun':80,'reason':'在途期间人工复核','evidence':[row['title']],'risks':[]},'人工复核')
    f.release.set();wait(w);assert sc.list()['rows'][0]['counts']['skipped']==1
    with s.connect() as c:assert c.execute('SELECT score FROM results WHERE id=?',(ids[0],)).fetchone()[0]==85

    # Failed grade validation can be retried without repeating successful siblings.
    s,w,f,sc,ids=setup(root/'failure',2);f.fail={ids[1]};jid=sc.start(sc.preview({'ids':ids})['id'])['id'];wait(w)
    status=sc.list()['rows'][0];assert status['counts']['completed']==3 and status['counts']['failed']==1
    assert s.list_results({'score_band':'score_failed'})['total']==1
    f.fail.clear();sc.resume(jid,True);wait(w)
    assert len(f.calls)==5 and f.calls.count(ids[1])==2 and sc.list()['rows'][0]['counts']['completed']==4

    # Quota and task budgets pause rather than consuming the rest of the batch.
    s,w,f,sc,ids=setup(root/'quota',1);s.save_settings({'write_workers':1});f.quota=True
    jid=sc.start(sc.preview({'ids':ids})['id'])['id'];wait(w)
    assert len(f.calls)==1 and sc.list()['rows'][0]['state']=='blocked' and sc.limit_blocked
    f.quota=False;sc.resume(jid);wait(w);assert len(f.calls)==3 and not sc.limit_blocked
    s,w,f,sc,ids=setup(root/'budget',1);s.save_settings({'write_workers':1,'task_request_limit':1})
    jid=sc.start(sc.preview({'ids':ids})['id'])['id'];wait(w)
    assert len(f.calls)==1 and sc.list()['rows'][0]['state']=='blocked' and sc.list()['rows'][0]['counts']['completed']==1
    s.save_settings({'task_request_limit':3});sc.resume(jid);wait(w)
    assert len(f.calls)==2 and sc.list()['rows'][0]['counts']['completed']==2

    # Existing history cleanup removes completed old scoring batches, retaining unfinished cost records.
    import history_cleanup
    paused='score_ffffffffffff'
    with s.connect() as c:
        c.execute("UPDATE score_jobs SET created_at='2025-01-01T00:00:00',updated_at='2025-01-01T00:00:00' WHERE id=?",(jid,))
        snapshot=c.execute('SELECT snapshot_json FROM score_jobs WHERE id=?',(jid,)).fetchone()[0]
        c.execute("INSERT INTO score_jobs(id,state,total,snapshot_json,created_at,updated_at) VALUES(?,'paused',1,?,'2025-01-01T00:00:00','2025-01-01T00:00:00')",(paused,snapshot))
        c.execute("UPDATE model_requests SET created_at='2025-01-01T00:00:00',completed_at='2025-01-01T00:00:00',day='2025-01-01' WHERE run_id=?",(jid,))
        c.execute("INSERT INTO model_requests(run_id,state,day,created_at,completed_at) VALUES(?,'completed','2025-01-01','2025-01-01T00:00:00','2025-01-01T00:00:00')",(paused,))
    before=protect(s);p=history_cleanup.preview(s,{'period':'7d','files':False})
    assert p['counts']['score_jobs']==1 and p['counts']['score_items']==2 and p['protected_tasks']>=1
    history_cleanup.apply(s,{'preview_id':p['preview_id'],'digest':p['digest']})
    assert protect(s)==before
    with s.connect() as c:
        assert c.execute('SELECT count(*) FROM score_jobs WHERE id=?',(jid,)).fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM model_requests WHERE run_id=?',(paused,)).fetchone()[0]==1

report={'ok':True,'only_selected_pending_funny_articles':True,'other_lanes_and_valid_scores_skipped':True,'duplicate_start_idempotent':True,'parallel_score_only_calls':True,'original_articles_seeds_and_versions_unchanged':True,'changed_preview_refused':True,'late_response_does_not_overwrite':True,'pause_restart_resume_skips_completed':True,'failed_only_retry':True,'quota_and_budget_pause':True,'usage_recorded_per_request':True,'external_model_calls':0,'production_changes':0}
(ROOT/'build/bulk-score-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
