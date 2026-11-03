"""Frozen backend -> automatic queue -> designated EXE -> qualifying SQLite.
Uses isolated local fixture articles, never production material or LLM calls.
"""
import csv,json,os,subprocess,sys,threading,time,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'build/auto-intake-live'/uuid.uuid4().hex[:10];folder.mkdir(parents=True)
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        kind='甲' if self.path in ('/same1','/same2') else '乙' if self.path=='/different' else '丙'
        text=''.join(f'<p>{kind}类测试第{i}段记录图书角借阅流程，登记书名与日期，归还后及时更新登记。这是隔离测试文章，不代表真实通知。</p>' for i in range(1,22))
        raw=('<html><meta charset="utf-8"><body><article>'+text+'</article></body></html>').encode('utf8')
        try:self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass
web=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=web.serve_forever,daemon=True).start()
token=uuid.uuid4().hex;env=os.environ.copy();env['COMIC_WORKBENCH_TOKEN']=token
exe=ROOT/'build/backend/comic-backend.exe'
process=subprocess.Popen([str(exe),'--data',str(folder/'data'),'--resources',str(ROOT/'resources')],env=env,stdout=subprocess.PIPE,stderr=(folder/'backend.log').open('wb'),text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
def write(name,rows):
    p=folder/name
    with p.open('w',encoding='utf8',newline='') as f:w=csv.writer(f);w.writerow(['标题','链接','领域']);w.writerows(rows)
    return str(p)
try:
    ready=json.loads(process.stdout.readline());port=ready['port']
    def api(path,body=None):
        raw=None if body is None else json.dumps(body).encode('utf8')
        req=Request(f'http://127.0.0.1:{port}'+path,data=raw,headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
        with urlopen(req,timeout=30) as response:return json.loads(response.read())
    assert api('/health')['version']=='0.3.3'
    api('/settings',{'body_run_size':2,'body_max_chars':0,'body_workers':1,'body_wait':15,'body_delay':1,'body_rest_every':0,'body_rest_seconds':0,'body_timeout':180})
    prefix=f'http://127.0.0.1:{web.server_port}'
    first=api('/import',{'path':write('first.csv',[['相同标题',prefix+'/same1','生活'],['相同标题',prefix+'/same2','财经'],['相同标题',prefix+'/different','生活'],['没有链接的待验收素材','','生活']])})
    second=api('/import',{'path':write('second.csv',[['第二批标题',prefix+'/other','生活']])})
    assert first['added']==4 and first['duplicates']==0 and first['auto_body']['total']==2 and first['auto_body']['remaining']==1,first
    assert second['auto_body']['total']==1,second
    print(json.dumps({'phase':'automatic jobs queued','job_ids':[first['auto_body']['job_id'],second['auto_body']['job_id']]}),flush=True)
    try:api('/run/start',{'mode':'both','ids':[4],'limit':1});raise AssertionError('unqualified model run accepted')
    except HTTPError as error:assert error.code==400
    def wait_job(jid):
        end=time.monotonic()+120
        while time.monotonic()<end:
            detail=api('/body/jobs/'+jid)
            if detail['job']['state'] not in ('queued','running','pausing') and api('/body/stats')['active_id'] is None:
                assert detail['job']['state']=='completed',detail
                return detail
            time.sleep(.6)
        raise AssertionError('body job did not stop')
    finished=wait_job(first['auto_body']['job_id']);assert finished['job']['done']==2
    time.sleep(1.2)
    assert api('/body/jobs/'+second['auto_body']['job_id'])['job']['state']=='queued'
    assert api('/materials/3')['body']=='' and api('/materials/5')['body']==''
    assert api('/body/stats')['queue_paused'] is True
    third=api('/body/start',{'limit':1});assert third['total']==1;wait_job(third['job_id'])
    time.sleep(1.2);assert api('/materials/5')['body']==''
    fourth=api('/body/start',{'limit':1});assert fourth['total']==1;wait_job(fourth['job_id'])
    assert api('/settings')['body_run_size']==1
    counts=api('/stats')['counts'];assert counts['qualified']==3 and counts['deduplicated']==1 and counts['total']==4,counts
    material=api('/materials/1');assert len(material['origins'])==2 and len(material['body'])>800
    assert api('/materials/3')['qualification']=='qualified'
    assert api('/materials/4')['qualification']=='pending'
    assert api('/stats')['runs']==[]
    api('/body/pause',{});assert api('/body/stats')['queue_paused'] is True
    report={'ok':True,'frozen_backend':True,'designated_exe':True,'qualified':counts['qualified'],'duplicates_merged':counts['deduplicated'],'pending_no_url':counts['unqualified'],'retained_body_length':len(material['body']),'single_run_sizes':[2,1,1],'stopped_between_runs':True,'saved_next_default':1,'model_calls':0,'scope':'Isolated local HTTP fixture articles; production database unchanged.'}
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    (ROOT/'build/auto-intake-live-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
finally:
    if process.poll() is None:subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    process.wait(timeout=20);process.stdout.close();web.shutdown();web.server_close()
