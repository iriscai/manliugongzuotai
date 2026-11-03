"""No network: regeneration safety, truthful progress, history, filters and budgets."""
import csv,json,sys,tempfile,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,dumps
from worker import Worker
from schemas import SEED_EXTRACT,ARTICLE
from pipeline_catalog import writing_detail,run_summary
from workflow_management import detail,edit,restore_version,restore_cleared,selected_ids
from usage_budget import summary
from title_push import signature,PROJECT,decorate
from result_cleanup import clear_pushed
TEXT='\n\n'.join(['孩子走进图书角。','先看看开放时间。','每天18时至20时开放。','借书时登记书名。','还书时也要登记。','老师让孩子轮流讲故事。','家长记下孩子的问题。','走道留出通行空间。'])
class Fake:
    def __init__(self):self.calls=[];self.fail=False;self.edition=1;self.lock=threading.Lock();self.active=0;self.peak=0;self.started=threading.Event();self.release=None
    def auth_status(self,_):return {'ok':True}
    def call(self,prompt,schema,settings,folder,on_event=None):
        if on_event:on_event({'event':'request_start'})
        with self.lock:self.active+=1;self.peak=max(self.peak,self.active);self.calls.append(schema)
        ok=False
        try:
            if schema is SEED_EXTRACT:
                src=json.loads(prompt.split('\n统一输入素材：',1)[1]);e=src['body'][0]
                out={'categories':[{'category':cat,'topic':('开放时间' if cat=='生活' else '轮流讲故事'),'angle':('开放时间' if cat=='生活' else '轮流讲故事'),'reason':'适配','main_point':('每天18时至20时开放' if cat=='生活' else '老师让孩子轮流讲故事'),'elements':[{'name':'登记','content':e['text'],'evidence_ids':[e['id']]}],'omissions':[],'visual_nodes':[]} for cat in ['生活','教育']],'reason':'适配两类'}
            else:
                assert schema is ARTICLE;self.started.set()
                if self.release:self.release.wait(8)
                if self.fail:raise RuntimeError('模拟本篇生成失败')
                seed=json.loads(prompt.split('本组种子：',1)[1].split('\n本条原始素材：',1)[0]);out={'category':seed['category'],'title':seed['category']+'图书角第'+str(self.edition)+'版','article':TEXT}
            time.sleep(.035);ok=True;return out
        finally:
            with self.lock:self.active-=1
            if on_event:on_event({'event':'request_finish','ok':ok,'usage':{'input_tokens':100,'output_tokens':50,'total_tokens':150}})
    def reset(self):pass
def wait(w):w.thread.join(20);assert not w.thread.is_alive()
def seed(path,n=1):
    s=Store(path/'data',ROOT/'resources');s.save_settings({'allowed_categories':['生活','教育'],'process_workers':4,'write_workers':8,'global_max_concurrency':2})
    file=path/'input.csv'
    with file.open('w',encoding='utf8',newline='') as f:
        writer=csv.writer(f);writer.writerow(['标题','正文','分类']);writer.writerows([[f'图书角{i}','图书角每天18时至20时开放。老师让孩子轮流讲故事。编号'+str(i),'生活'] for i in range(n)])
    s.import_file({'path':str(file)});w=Worker(s);p=Fake();w.provider=p;return s,w,p
with tempfile.TemporaryDirectory(prefix='workbench-management-') as tmp:
    s,w,p=seed(Path(tmp)/'editor');initial=w.start({'mode':'both','limit':1});wait(w)
    rows=s.list_results({})['rows'];assert len(rows)==2 and all(x['rule_status']=='current' for x in rows)
    a,b=rows;old=detail(s,a['id']);extractions_before=s.material(a['material_id'])['extractions']
    prompt=next(x for x in s.prompts() if x['category']==a['category'] and x['kind']=='write' and x['variant']==a['write_variant'])
    s.save_prompt({'id':prompt['id'],'content':prompt['content']+'\n测试规则微调。'})
    assert s.list_results({'rule':'outdated'})['total']==1
    p.fail=True;r=w.regenerate({'ids':[a['id']]});wait(w)
    assert detail(s,a['id'])['title']==old['title'] and not detail(s,a['id'])['history']
    failed=writing_detail(s,{'state':'failed'});assert failed['total']==1 and failed['rows'][0]['result_id']==a['id'] and '模拟' in failed['rows'][0]['error']
    p.fail=False;p.edition=2;retry=w.retry(r['run_id']);wait(w)
    new=detail(s,a['id']);assert new['title']!=old['title'] and len(new['history'])==1
    assert detail(s,b['id'])['title']==b['title']
    assert s.material(a['material_id'])['extractions']==extractions_before
    assert p.calls.count(SEED_EXTRACT)==1
    with s.connect() as c:
        assert run_summary(c,r['run_id'])['write_failed']==1
        assert run_summary(c,retry['run_id'])['write_completed']==1 and run_summary(c,retry['run_id'])['reused']==0
        assert run_summary(c,initial['run_id'])['write_completed']==2
    edit(s,{'id':a['id'],'content_hash':new['content_hash'],'title':'手动修改标题','article':TEXT})
    edited=detail(s,a['id']);assert len(edited['history'])==2
    try:edit(s,{'id':a['id'],'content_hash':new['content_hash'],'title':'覆盖旧稿','article':TEXT});raise AssertionError('stale edit accepted')
    except ValueError:pass
    restore_version(s,{'id':a['id'],'version_id':edited['history'][0]['id'],'content_hash':edited['content_hash']})
    restored=detail(s,a['id']);assert restored['title']==new['title'] and len(restored['history'])==3
    with s.connect() as c:
        c.execute('INSERT INTO result_pushes(result_id,target_path,content_hash,delivery_id,title,article,category,state,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
          (a['id'],str(PROJECT/'picfactory_matrix.db'),signature(restored),'fixture',restored['title'],restored['article'],restored['category'],'pushed','2026-10-31'))
    assert s.list_results({'push':'pushed'})['total']==1 and s.list_results({'push':'not_pushed'})['total']==1
    clear=clear_pushed(s);assert clear['count']==1 and s.list_results({})['total']==1 and s.list_results({'visibility':'cleared'})['total']==1
    assert restore_cleared(s,{'ids':[a['id']]})['count']==1 and detail(s,a['id'])['push_state']=='pushed'
    assert s.list_results({'batch':retry['run_id']})['total']==1
    assert len(selected_ids(s,{'all_filtered':True,'filters':{'category':a['category']}}))==1
    p.release=threading.Event();p.started.clear();w.regenerate({'ids':[b['id']]});assert p.started.wait(5)
    assert writing_detail(s,{'state':'writing'})['total']==1
    p.release.set();wait(w)
    # Pausing a partial regeneration must not rewrite completed outputs on resume.
    s.save_settings({'global_max_concurrency':1});p.release=threading.Event();p.started.clear()
    calls_before=p.calls.count(ARTICLE);paused=w.regenerate({'ids':[a['id'],b['id']]});assert p.started.wait(5)
    w.pause();p.release.set();wait(w)
    with s.connect() as c:assert c.execute('SELECT state FROM runs WHERE id=?',(paused['run_id'],)).fetchone()[0]=='paused'
    w.resume(paused['run_id']);wait(w)
    assert p.calls.count(ARTICLE)-calls_before==2,'Resume rewrote an already completed article'
    with s.connect() as c:assert run_summary(c,paused['run_id'])['write_completed']==2
    s,w,p=seed(Path(tmp)/'budget',5);s.save_settings({'daily_request_limit':2});r=w.start({'mode':'both','limit':5});wait(w)
    with s.connect() as c:
        u=summary(c);assert u['requests']==2 and u['total_tokens']==300 and u['unknown_usage']==0,u
        assert c.execute('SELECT state FROM runs WHERE id=?',(r['run_id'],)).fetchone()[0]=='blocked'
    assert p.peak<=2,p.peak
    s.save_settings({'daily_request_limit':100});w.resume(r['run_id']);wait(w)
    assert s.list_results({})['total']==10
    assert p.peak<=2
    with s.connect() as c:assert summary(c)['active']==0
    # Fixture for Electron, isolated from user data and reference factory.
    fixture=ROOT/'build/management-ui-fixture';fixture.mkdir(exist_ok=True)
    import shutil
    (fixture/'data').mkdir(exist_ok=True)
    import sqlite3
    with s.connect() as c,sqlite3.connect(fixture/'data/workbench.sqlite3') as dest:c.backup(dest)
    (ROOT/'build/management-ui-fixture.json').write_text(dumps({'data':str(fixture/'data')}),encoding='utf8')
report={'ok':True,'regeneration_preserves_old_on_failure':True,'targeted_retry_only':True,'no_reextraction':True,'rule_version_filters':True,'history_edit_restore':True,'clear_restore_preserves_push_state':True,'truthful_writing_states':True,'immutable_run_counts':True,'daily_budget_atomic':True,'global_concurrency_limit':2,'external_model_calls':0,'production_changes':0}
(ROOT/'build/management-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
