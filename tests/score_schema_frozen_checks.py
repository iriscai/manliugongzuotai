"""A real frozen-backend generation against a localhost model fixture, never paid inference."""
import csv,json,os,subprocess,threading,time,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];folder=ROOT/'build'/('score-schema-frozen-'+uuid.uuid4().hex[:8]);folder.mkdir()
seen=[];article='朋友借我10元，说中午还。我等到下午，他递来一张午饭小票：“一起吃的，抵了。”';title='朋友借我十元'*10
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        schema=json.loads(payload['messages'][0]['content'].split('\n',1)[1]);seen.append(schema)
        if 'quality_score' in schema.get('properties',{}):
            for key in ('completeness','reversal','fun'):
                field=schema['properties']['quality_score']['properties'][key]
                assert field['minimum']==0 and field['maximum']==100 and 'enum' not in field
            assert schema['properties']['generation_audit']['properties']['t1_choice']['enum']==[1,2]
            answer={'category':'搞笑','title':title,'article':article,'generation_audit':{'draft':article,'r1_text':article,'r1_notes':['保留原稿的具体借款场景'],'r2_text':article,'r2_notes':['保留结尾实际还款动作'],'t1_titles':[title,'同事借我十元'*10],'t1_short_reasons':['',''],'t1_choice':1,'t1_article':article,'t2_notes':['标题长度及原稿字数核对']},'quality_score':{'completeness':94,'reversal':86,'fun':87,'reason':'仅用于百分制结构验证的本机模拟评分','evidence':['朋友借我10元'],'risks':[]}}
        else:answer={'categories':[],'reason':'本机测试，走原赛道保底'}
        raw=json.dumps({'choices':[{'message':{'content':json.dumps(answer,ensure_ascii=False)},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
web=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=web.serve_forever,daemon=True).start()
env=os.environ.copy();token=uuid.uuid4().hex;env['COMIC_WORKBENCH_TOKEN']=token
with (folder/'backend.log').open('wb') as log:
    p=subprocess.Popen([str(ROOT/'build/backend/comic-backend.exe'),'--data',str(folder/'data'),'--resources',str(ROOT/'resources')],env=env,stdout=subprocess.PIPE,stderr=log,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        port=json.loads(p.stdout.readline())['port']
        def api(route,body=None):
            request=Request(f'http://127.0.0.1:{port}'+route,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json','X-Workbench-Token':token})
            with urlopen(request,timeout=15) as response:return json.loads(response.read())
        assert api('/health')['version']=='0.23.2'
        api('/settings',{'provider':'api','api_base':f'http://127.0.0.1:{web.server_port}/v1','api_model':'fixture','api_key':'fixture-key','api_retry_count':0,'process_workers':1,'write_workers':1,'allowed_categories':['搞笑']})
        source=folder/'source.csv'
        with source.open('w',encoding='utf8',newline='') as f:csv.writer(f).writerows([['标题','正文','分类'],['借钱午饭',article,'搞笑']])
        api('/import',{'path':str(source)});run=api('/run/start',{'mode':'both','limit':1})
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            stats=api('/stats');row=next(r for r in stats['runs'] if r['id']==run['run_id'])
            if row['state'] not in ('running','pausing'):break
            time.sleep(.15)
        assert row['state']=='completed' and row['done']==1 and row['errors']==0,row
        results=api('/results')['rows'];assert len(results)==1 and results[0]['score']==94,results
        assert len(seen)==2 and sum('quality_score' in s.get('properties',{}) for s in seen)==1
        report={'ok':True,'frozen_backend_version':'0.23.2','actual_local_requests':2,'stored_score':94,'percentage_schema_in_actual_request':True,'title_choice_still_binary':True,'external_model_calls':0,'production_changes':0}
        (ROOT/'build/score-schema-frozen-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
    finally:
        if p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        p.wait(timeout=15);p.stdout.close();web.shutdown();web.server_close()
