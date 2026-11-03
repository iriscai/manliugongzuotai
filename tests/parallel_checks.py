"""Isolated scheduling, independent pools, pause/resume, and verification gates."""
import collections,csv,json,sys,tempfile,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store
from worker import Worker
from schemas import ROUTE,EXTRACT,WRITE
from providers import ProviderLimit
from pipeline_catalog import concurrency,run_detail,writing_detail

class Provider:
    def __init__(self,blocked=False,pause=None,limit=False,fail_write=False):
        self.lock=threading.Lock();self.active=collections.Counter();self.peak=collections.Counter();self.calls=[];self.worker=None;self.blocked=blocked;self.pause_at=pause;self.limit=limit;self.fail_write=fail_write
    def auth_status(self,_):return {'ok':True}
    def call(self,prompt,schema,settings,folder,on_event=None):
        mid=int(Path(folder).name.split('-')[0]);kind='write' if schema is WRITE else 'process'
        with self.lock:
            self.calls.append((mid,'route' if schema is ROUTE else 'extract' if schema is EXTRACT else 'write'))
            self.active[kind]+=1;self.peak[kind]=max(self.peak[kind],self.active[kind])
        try:
            time.sleep(.08 if kind=='process' else .15)
            if self.limit and mid==1:raise ProviderLimit('fixture quota')
            if self.fail_write and schema is WRITE:
                with self.lock:fail=self.fail_write;self.fail_write=False
                if fail:raise RuntimeError('fixture write failure')
            if schema is ROUTE:data={'routes':[{'category':cat,'angle':cat+'借还过程','reason':'适配','quote':'每天18时至20时开放'} for cat in ['生活','教育']],'reason':''}
            elif schema is EXTRACT:data={'eligible':True,'reason':'原文支持','main_point':'图书角登记','facts':[{'fact':'开放时间','quote':'每天18时至20时开放'}],'omissions':[],'visual_nodes':['图书角'],'needs_verification':['核实具体时间和实际安排'] if self.blocked else [],'verified_additions':[]}
            else:data={'title':f'借还提示{mid}','short_text':f'素材{mid}：图书角每天18时至20时开放，借还时登记。','frames':[{'number':1,'purpose':'开放时间','scene':'图书角','caption':'每天18时至20时开放','dialogue':[],'visible_labels':[],'image_prompt':'借书登记示意'}],'post_text':'','notice':'虚构功能测试','genre':'图解','adaptations':[]}
            folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);(folder/'answer.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
            if self.pause_at is schema:
                with self.lock:pause=self.pause_at;self.pause_at=None
                if pause:self.worker.pause()
            return data
        finally:
            with self.lock:self.active[kind]-=1
    def terminate(self):pass

def seed(path,n,processing=4,writing=8):
    s=Store(path/'data',ROOT/'resources');s.save_settings({'process_workers':processing,'write_workers':writing,'allowed_categories':['生活','教育']})
    p=path/'input.csv'
    with p.open('w',encoding='utf8',newline='') as f:
        w=csv.writer(f);w.writerow(['标题','正文','分类']);w.writerows([[f'隔离素材{i}',f'图书角每天18时至20时开放。借书登记书名和日期。隔离编号{i}。','生活'] for i in range(1,n+1)])
    s.import_file({'path':str(p)});return s
def wait(w):w.thread.join(30);assert not w.thread.is_alive(),'Worker stuck'
def attach(s,p):w=Worker(s);w.provider=p;p.worker=w;return w

for bad in [0,3,12,33,True,1.5,'4.0']:
    try:concurrency(bad);raise AssertionError('Bad concurrency accepted')
    except ValueError:pass
with tempfile.TemporaryDirectory(prefix='parallel-workbench-') as tmp:
    root=Path(tmp);s=seed(root/'parallel',12);p=Provider();w=attach(s,p);r=w.start({'mode':'both','limit':12});wait(w)
    assert 2<=p.peak['process']<=4 and 2<=p.peak['write']<=8,p.peak
    assert s.stats()['counts']['result_count']==24,s.stats()
    assert all(x['state']=='written' for x in s.list_materials({'size':50})['rows'])
    assert s.stats()['runs'][0]['progress']['write_completed']==24
    peaks=dict(p.peak)
    s=seed(root/'32',32,32,32);p=Provider();w=attach(s,p);w.start({'mode':'both','limit':32});wait(w)
    assert p.peak['process']>=8 and p.peak['process']<=32 and p.peak['write']>=8 and p.peak['write']<=32,p.peak
    assert s.stats()['counts']['result_count']==64
    high_peaks=dict(p.peak)
    s=seed(root/'blocked',2);p=Provider(blocked=True);w=attach(s,p);r=w.start({'mode':'both','limit':2});wait(w)
    assert not any(stage=='write' for _,stage in p.calls)
    stats=s.stats();assert stats['writing']['needs_review']==4 and stats['writing']['ready']==0 and stats['counts']['result_count']==0
    assert '已有文案0份' in stats['runs'][0]['current_phase']
    detail=run_detail(s,{'id':r['run_id']});assert detail['verification_total']==4 and detail['verification'][0]['needs_verification']
    assert writing_detail(s,{'state':'needs_review'})['total']==4
    try:w.start({'mode':'write'});raise AssertionError('Blocked facts scheduled for writing')
    except ValueError as e:assert '待核实' in str(e)
    s=seed(root/'resume',4);p=Provider(pause=EXTRACT);w=attach(s,p);r=w.start({'mode':'both','limit':4});wait(w)
    assert s.stats()['runs'][0]['state']=='paused'
    w.resume(r['run_id']);wait(w);assert s.stats()['counts']['result_count']==8
    assert len([x for x in p.calls if x[1]=='route'])==4,'Routes repeated after resume'
    assert len([x for x in p.calls if x[1]=='extract'])==8,'Missing or repeated partial-route extraction'
    s=seed(root/'limit',12);p=Provider(limit=True);w=attach(s,p);r=w.start({'mode':'both','limit':12});wait(w)
    assert s.stats()['runs'][0]['state']=='blocked' and len(set(mid for mid,_ in p.calls))<=4
    p.limit=False;w.resume(r['run_id']);wait(w);assert s.stats()['counts']['result_count']==24
    s=seed(root/'failure',2);p=Provider(fail_write=True);w=attach(s,p);r=w.start({'mode':'both','limit':2});wait(w)
    assert s.stats()['counts']['result_count']==3 and s.stats()['runs'][0]['errors']==1
    w.retry(r['run_id']);wait(w);assert s.stats()['counts']['result_count']==4
    assert len([x for x in p.calls if x[1]=='extract'])==4,'Retry regenerated successful extraction'
report={'ok':True,'configured_4_8_observed_peaks':peaks,'configured_32_32_observed_peaks':high_peaks,'verification_blocks_writing':True,'pause_resume_and_partial_routes':True,'quota_drains_inflight_then_blocks':True,'partial_write_failure_retry_no_duplicates':True,'external_model_calls':0,'production_changes':0}
(ROOT/'build/parallel-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
