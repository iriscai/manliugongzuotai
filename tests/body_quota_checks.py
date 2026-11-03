import csv,json,sys,tempfile,threading,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import openpyxl
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store
from body_fetcher import BodyFetcher,run_limit
calls=[];attempts={}
class FakeProcess:
    def __init__(self,cmd,**kwargs):
        self.pid=999999
        wb=openpyxl.load_workbook(cmd[1]);ws=wb.active;batch=[]
        for row in range(2,ws.max_row+1):
            mid=ws.cell(row,1).value;batch.append(mid);attempts[mid]=attempts.get(mid,0)+1
            if mid==1 and attempts[mid]==1:ws.cell(row,4,'[抓取失败] fixture');ws.cell(row,5,'')
            elif mid==2:ws.cell(row,4,'');ws.cell(row,5,'图')
            else:ws.cell(row,4,'有效正文'+str(mid));ws.cell(row,5,'文章')
        calls.append(batch);wb.save(cmd[cmd.index('-o')+1]);wb.close()
    def poll(self):return 0
    def wait(self,timeout=None):return 0
def seed(folder,count):
    s=Store(folder/'data',ROOT/'resources');p=folder/'input.csv'
    with p.open('w',encoding='utf8',newline='') as f:w=csv.writer(f);w.writerow(['标题','链接']);w.writerows([[f'素材{i}',f'https://fixture.example.com/{i}'] for i in range(1,count+1)])
    ids=s.import_file({'path':str(p)})['intake_ids'];return s,ids
def idle(fetch):
    end=time.monotonic()+6
    while time.monotonic()<end:
        if calls and fetch.active_id is None and fetch.store.settings().get('body_queue_paused'):return
        time.sleep(.03)
    raise AssertionError('single run did not stop')
def stop(fetch):
    fetch.shutdown_event.set()
    if fetch.dispatcher:fetch.dispatcher.join(3)
with tempfile.TemporaryDirectory(prefix='body-quota-') as tmp,patch('body_fetcher.subprocess.Popen',FakeProcess):
    folder=Path(tmp);s,ids=seed(folder,6);s.save_settings({'body_run_size':2});fetch=BodyFetcher(s)
    first=fetch.enqueue_import(ids);assert first['total']==2 and first['remaining']==4
    second=fetch.enqueue_import(ids);assert second['total']==2
    worker=SimpleNamespace(lock=threading.RLock(),thread=None);fetch.start_dispatcher(worker);idle(fetch);time.sleep(.8)
    assert calls==[[1,2]],calls
    detail=fetch.detail(first['job_id']);assert detail['job']['done']==2 and detail['job']['failed']==1 and detail['job']['image_deleted']==1
    assert fetch.detail(second['job_id'])['job']['state']=='queued'
    third=fetch.start({'limit':1});fetch.thread.join(6);assert calls==[[1,2],[3]],calls
    assert s.settings()['body_run_size']==1 and s.settings()['body_queue_paused'] is True
    assert fetch.detail(second['job_id'])['job']['state']=='paused'
    resumed=fetch.resume(second['job_id'],1);fetch.thread.join(6);assert resumed['total']==1 and calls[-1]==[4]
    assert fetch.detail(second['job_id'])['job']['state']=='completed'
    retried=fetch.start({'limit':1,'only_failed':True});fetch.thread.join(6);assert retried['total']==1 and calls[-1]==[1]
    assert s.material(5)['body']=='' and s.material(6)['body']==''
    for bad in [0,-1,True,1.5,10001,'']:
        try:run_limit(bad);raise AssertionError('invalid limit accepted')
        except ValueError:pass
    stop(fetch)
    # Simulate a large pre-upgrade queued job. Its next execution must be bounded too.
    legacy=folder/'legacy';legacy.mkdir();other,ids=seed(legacy,5);other.save_settings({'body_run_size':5});old=BodyFetcher(other)
    old_id=old._new_job(old.select({'limit':5}),other.settings(),state='queued');other.save_settings({'body_run_size':2});before=len(calls)
    old.start_dispatcher(worker);idle(old);time.sleep(.8)
    assert len(calls)==before+1 and len(calls[-1])==2,calls
    assert old.detail(old_id)['job']['state']=='paused'
    assert sum(x['status']=='pending' for x in old.detail(old_id)['items'])==3
    stop(old)
report={'ok':True,'checks':['导入单轮限额','达到上限后队列停止','失败与纯图删除计入条数且不补抓','下一批只领取本次数量','旧待办转移不重复抓取','续抓限额','失败重试限额','非法条数拒绝','升级前大任务也受单轮限额约束'],'browser_calls':0,'model_calls':0}
(ROOT/'build/body-quota-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
