"""Check configurable length through the frozen backend and designated EXE."""
import csv,json,os,subprocess,threading,time,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1];folder=ROOT/'build/body-length-live'/uuid.uuid4().hex[:10];folder.mkdir(parents=True)
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        raw=('<html><meta charset="utf-8"><body><article>'+''.join(f'<p>第{i}段记录阅读活动的时间和登记流程。书名、借阅日期与归还日期需要对应，归还图书后更新记录。此为隔离功能测试材料。</p>' for i in range(1,25))+'</article></body></html>').encode('utf8')
        try:self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass
web=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=web.serve_forever,daemon=True).start()
env=os.environ.copy();token=uuid.uuid4().hex;env['COMIC_WORKBENCH_TOKEN']=token
with (folder/'backend.log').open('wb') as log:
    process=subprocess.Popen([str(ROOT/'build/backend/comic-backend.exe'),'--data',str(folder/'data'),'--resources',str(ROOT/'resources')],env=env,stdout=subprocess.PIPE,stderr=log,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        port=json.loads(process.stdout.readline())['port']
        def api(route,body=None):
            req=Request(f'http://127.0.0.1:{port}'+route,data=None if body is None else json.dumps(body).encode('utf8'),headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
            with urlopen(req,timeout=30) as response:return json.loads(response.read())
        assert api('/health')['version']=='0.3.3'
        assert api('/settings')['body_max_chars']==800
        for bad in [-1,32767,True,1.5,'abc','']:
            try:api('/settings',{'body_max_chars':bad});raise AssertionError(f'invalid limit accepted: {bad!r}')
            except HTTPError as error:assert error.code==400
        api('/settings',{'body_workers':1,'body_wait':15,'body_delay':0,'body_rest_every':0,'body_rest_seconds':0,'body_timeout':180})
        jobs=[]
        for limit in [800,0]:
            api('/settings',{'body_max_chars':limit})
            assert api('/body/check',{})['max_chars']==limit
            p=folder/f'input-{limit}.csv'
            with p.open('w',encoding='utf8',newline='') as f:w=csv.writer(f);w.writerow(['标题','链接']);w.writerow([f'字数配置测试{limit}',f'http://127.0.0.1:{web.server_port}/article'])
            result=api('/import',{'path':str(p)});jobs.append((limit,result['auto_body']['job_id']))
        print(json.dumps({'phase':'real EXE length jobs queued','limits':[x[0] for x in jobs]}),flush=True)
        details=[]
        for index,(limit,jid) in enumerate(jobs):
            end=time.monotonic()+100
            while time.monotonic()<end:
                detail=api('/body/jobs/'+jid);active=api('/body/stats')['active_id']
                if index and detail['job']['state']=='queued' and active is None:
                    result=api('/body/start',{'limit':1,'ids':[index+1]});jid=result['job_id'];jobs[index]=(limit,jid)
                    continue
                if detail['job']['state'] not in ('queued','running','pausing') and active is None:break
                time.sleep(.7)
            details.append(detail)
        for (limit,jid),detail in zip(jobs,details):
            assert detail['job']['state']=='completed' and detail['job']['ok']==1,detail
            assert detail['job']['max_chars']==limit
            commands=list((folder/'data/body_fetch'/jid).glob('batch_*/command.json'));assert len(commands)==1
            command=json.loads(commands[0].read_text(encoding='utf8'));assert command[command.index('--max-chars')+1]==str(limit)
        first=api('/materials/1')['body'];second=api('/materials/2')['body']
        assert len(first)==800 and len(second)>800 and second.startswith(first),(len(first),len(second))
        assert api('/settings')['body_max_chars']==0
        report={'ok':True,'default':800,'actual_body_lengths':{'limit_800':len(first),'unlimited_0':len(second)},'invalid_values_rejected':True,'job_snapshots_preserved':True,'command_arguments_verified':True,'model_calls':0,'scope':'Frozen backend and designated EXE on isolated local articles; no production mutation.'}
        (ROOT/'build/body-length-live-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
    finally:
        if process.poll() is None:subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        process.wait(timeout=20);process.stdout.close();web.shutdown();web.server_close()
