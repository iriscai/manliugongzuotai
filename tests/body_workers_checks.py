"""Check task snapshots and the external command without starting browsers."""
import csv,json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
import openpyxl
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store
from body_fetcher import BodyFetcher,browser_workers

calls=[]
class FakeProcess:
    def __init__(self,cmd,**kwargs):
        self.pid=999999;calls.append(cmd)
        wb=openpyxl.load_workbook(cmd[1]);ws=wb.active
        for row in range(2,ws.max_row+1):
            ws.cell(row,4,'隔离测试正文'+str(ws.cell(row,1).value));ws.cell(row,5,'文章')
        wb.save(cmd[cmd.index('-o')+1]);wb.close()
    def poll(self):return 0
    def wait(self,timeout=None):return 0

for invalid in [0,3,5,6,7,9,16,-1,True,False,None,1.5,2.0,'4.0','']:
    try:browser_workers(invalid);raise AssertionError(f'Accepted invalid value: {invalid!r}')
    except ValueError:pass
with tempfile.TemporaryDirectory(prefix='body-workers-') as tmp,patch('body_fetcher.subprocess.Popen',FakeProcess):
    folder=Path(tmp);store=Store(folder/'data',ROOT/'resources');fetch=BodyFetcher(store)
    assert store.settings()['body_workers']==2
    p=folder/'input.csv'
    with p.open('w',encoding='utf8',newline='') as f:
        w=csv.writer(f);w.writerow(['标题','链接']);w.writerows([[f'并发测试{i}',f'https://fixture.example.com/{i}'] for i in range(1,5)])
    ids=store.import_file({'path':str(p)})['intake_ids']
    for mid,workers in zip(ids,[1,2,4,8]):
        assert browser_workers(str(workers))==workers
        store.save_settings({'body_workers':workers})
        assert fetch.engine_info()['workers']==workers
        snapshot=store.settings();job=fetch._new_job(fetch.select({'ids':[mid],'limit':1}),snapshot)
        store.save_settings({'body_workers':2 if workers!=2 else 8})
        fetch._execute(job)
        assert calls[-1][calls[-1].index('--workers')+1]==str(workers)
        detail=fetch.detail(job)['job'];assert detail['state']=='completed' and detail['workers']==workers and detail['ok']==1,detail
        assert next(j for j in fetch.stats()['jobs'] if j['id']==job)['workers']==workers
    store.save_settings({'body_workers':8})
    assert Store(folder/'data',ROOT/'resources').settings()['body_workers']==8
report={'ok':True,'worker_options':[1,2,4,8],'default':2,'external_command_verified':True,'task_snapshots_preserved':True,'invalid_values_rejected':True,'real_browser_calls':0,'model_calls':0}
(ROOT/'build/body-workers-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
