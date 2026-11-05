"""Local JSON model endpoint and disposable database for prompt-lab UI verification."""
from pathlib import Path
import json,sys,threading,time,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,dumps
from providers import protect
from prompt_lab import DIMENSIONS

folder=ROOT/'build'/('prompt-lab-ui-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
store=Store(folder/'data',ROOT/'resources')
for cat in ['生活','军事']:
    source=folder/(cat+'.csv');source.write_text('标题,正文,分类\n'+cat+'图书角开放安排,图书角每天18时至20时开放。借书还书都登记。老师让孩子轮流讲故事。,'+cat+'\n',encoding='utf8');store.import_file({'path':str(source)})
original={}
with store.connect() as c:
    for table in ('prompts','materials','results','extractions','runs','settings'):
        original[table]=[list(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY 1')]
stop=threading.Event();calls=[]
article='\n\n'.join(['孩子走进图书角。','先看看开放时间。','每天18时至20时开放。','借书时登记书名。','还书时也要登记。','老师让孩子轮流讲故事。','家长记下孩子的问题。','走道留出通行空间。'])
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        raw=dumps({'calls':calls}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        if self.path=='/stop':self.send_response(200);self.end_headers();stop.set();return
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        schema=json.loads(payload['messages'][0]['content'].split('\n',1)[1]);prompt=payload['messages'][1]['content'];props=schema['properties']
        assert 'categories' not in props and '本组种子：' not in prompt
        result={'category':'生活','title':'图书角开放时间，借书还书要登记','article':article};stage='write'
        if 'assessment' in props:
            result['assessment']={**{k:90 for k in DIMENSIONS},'reason':'本机测试夹具评分','evidence':[result['title']],'risks':[]}
        calls.append({'stage':stage,'prompt':prompt});time.sleep(.2)
        raw=dumps({'choices':[{'message':{'content':dumps(result)},'finish_reason':'stop'}],'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
store.save_settings({'provider':'api','api_base':f'http://127.0.0.1:{server.server_port}/v1','api_model':'fixture-prompt-test','api_key_encrypted':protect('fixture-local-key'),'api_retry_count':0,'body_queue_paused':True,'push_target_project':str(folder/'receiver')})
(folder/'before.json').write_text(dumps({k:v for k,v in original.items() if k!='settings'}),encoding='utf8')
print(dumps({'data':str(store.root),'folder':str(folder),'api':f'http://127.0.0.1:{server.server_port}'}),flush=True)
try:stop.wait(240)
finally:server.shutdown();server.server_close()
