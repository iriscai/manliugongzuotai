"""Frozen backend executes the full parallel pipeline against a local fixture API."""
import csv,json,os,re,subprocess,sys,threading,time,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from providers import protect
folder=ROOT/'build'/('parallel-frozen-'+uuid.uuid4().hex[:8]);folder.mkdir()
lock=threading.Lock();active={'process':0,'write':0};peak={'process':0,'write':0}
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));system=request['messages'][0]['content'];prompt=request['messages'][1]['content'];mid=int(re.search(r'"material_id"\s*:\s*(\d+)',prompt).group(1))
        kind='write' if '"frames"' in system else 'process'
        with lock:active[kind]+=1;peak[kind]=max(peak[kind],active[kind])
        try:
            time.sleep(.15)
            if '"routes"' in system:data={'routes':[{'category':'生活','angle':'借还流程','reason':'生活信息','quote':'每天18时至20时开放'}],'reason':''}
            elif '"eligible"' in system:data={'eligible':True,'reason':'有效','main_point':'借书登记','facts':[{'fact':'开放时间','quote':'每天18时至20时开放'}],'omissions':[],'visual_nodes':['借书角'],'needs_verification':['隔离测试：核实开放时间'] if mid==8 else [],'verified_additions':[]}
            else:data={'title':f'借书提示{mid}','short_text':'图书角每天18时至20时开放。借还书时登记。','frames':[{'number':1,'purpose':'开放时间','scene':'图书角','caption':'每天18时至20时开放','dialogue':[],'visible_labels':[],'image_prompt':'图书角示意图'}],'post_text':'','notice':'虚构功能测试','genre':'生活图解','adaptations':[]}
            raw=json.dumps({'choices':[{'message':{'content':json.dumps(data,ensure_ascii=False)},'finish_reason':'stop'}]},ensure_ascii=False).encode('utf8')
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        finally:
            with lock:active[kind]-=1
web=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=web.serve_forever,daemon=True).start()
env=os.environ.copy();token=uuid.uuid4().hex;env['COMIC_WORKBENCH_TOKEN']=token
with (folder/'backend.log').open('wb') as log:
    p=subprocess.Popen([str(ROOT/'build/backend/comic-backend.exe'),'--data',str(folder/'data'),'--resources',str(ROOT/'resources')],env=env,stdout=subprocess.PIPE,stderr=log,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        port=json.loads(p.stdout.readline())['port']
        def api(route,body=None):
            req=Request(f'http://127.0.0.1:{port}'+route,data=None if body is None else json.dumps(body).encode('utf8'),headers={'Content-Type':'application/json','X-Workbench-Token':token})
            with urlopen(req,timeout=30) as r:return json.loads(r.read())
        assert api('/health')['version']=='0.6.0'
        api('/settings',{'provider':'api','api_base':f'http://127.0.0.1:{web.server_port}/v1','api_model':'fixture','api_key':'fixture-key-a\nfixture-key-b','api_retry_count':0,'process_workers':4,'write_workers':4,'allowed_categories':['生活']})
        path=folder/'input.csv'
        with path.open('w',encoding='utf8',newline='') as f:
            w=csv.writer(f);w.writerow(['标题','正文','分类']);w.writerows([[f'隔离素材{i}',f'图书角每天18时至20时开放。借书登记书名和日期。隔离编号{i}。','生活'] for i in range(1,9)])
        api('/import',{'path':str(path)});run=api('/run/start',{'mode':'both','limit':8})
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            stats=api('/stats');r=next(x for x in stats['runs'] if x['id']==run['run_id'])
            if r['state'] not in ('running','pausing'):break
            time.sleep(.2)
        assert r['state']=='completed' and r['errors']==0,r
        assert stats['counts']['result_count']==7 and stats['writing']['needs_review']==1,stats
        assert peak['process']>1 and peak['write']>1,peak
        assert api('/run/writing?state=needs_review')['total']==1
        assert api('/run/detail?id='+run['run_id'])['verification_total']==1
        report={'ok':True,'frozen_backend':True,'materials':8,'extractions':8,'written':7,'verification_blocked':1,'observed_peaks':peak,'external_model_calls':0,'production_changes':0}
        (ROOT/'build/parallel-frozen-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
    finally:
        if p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        p.wait(timeout=20);p.stdout.close();web.shutdown();web.server_close()
