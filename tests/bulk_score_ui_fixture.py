"""Isolated database and localhost-only scoring API for UI checks."""
from workbench_fixtures import *
from providers import protect
from contextlib import closing
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import sqlite3,uuid
root=ROOT/'build'/('bulk-score-ui-'+uuid.uuid4().hex[:8]);s,w,p=seed(root,18)
w.start({'mode':'both','limit':18});wait(w)
with s.connect() as c:
    ids=[r[0] for r in c.execute('SELECT id FROM results ORDER BY id')]
    for i,rid in enumerate(ids[:-1]):c.execute('UPDATE results SET category=?,score=NULL,score_status=?,score_json=? WHERE id=?',('搞笑','invalid_contract' if i<31 else 'score_failed' if i<33 else 'pending',dumps({'error':'本机界面测试待重评'}),rid))
    original=[list(r) for r in c.execute('SELECT id,title,article,data_json,content_revision FROM results ORDER BY id')]
target=root/'target';target.mkdir()
with closing(sqlite3.connect(target/'picfactory_matrix.db')) as c:c.execute('CREATE TABLE app_collections(namespace TEXT,item_key TEXT,payload TEXT,sort_order INTEGER,PRIMARY KEY(namespace,item_key))');c.commit()
calls=[];lock=threading.Lock();fail_once={ids[31]};stop=threading.Event()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def do_GET(self):
        raw=dumps({'calls':calls}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        if self.path=='/stop':self.send_response(200);self.end_headers();stop.set();return
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        schema=json.loads(request['messages'][0]['content'].split('\n',1)[1]);assert set(schema['properties'])=={'quality_score'}
        for key in ('completeness','reversal','fun'):
            field=schema['properties']['quality_score']['properties'][key];assert field['minimum']==0 and field['maximum']==100 and 'enum' not in field
        row=json.loads(request['messages'][1]['content'].split('待评分作品：',1)[1]);rid=row['result_id']
        with lock:
            calls.append(rid);bad=rid in fail_once;fail_once.discard(rid)
        time.sleep(.12)
        answer={'quality_score':{'completeness':90,'reversal':90,'fun':90,'reason':'仅用于独立评分界面测试','evidence':['错误证据'] if bad else [row['title']],'risks':[]}}
        raw=dumps({'choices':[{'message':{'content':dumps(answer)},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
web=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=web.serve_forever,daemon=True).start()
s.save_settings({'provider':'api','api_base':f'http://127.0.0.1:{web.server_port}/v1','api_model':'fixture-score-only','api_key_encrypted':protect('fixture-key'),'api_retry_count':0,'write_workers':2,'global_max_concurrency':2,'push_target_project':str(target)})
fixture={'data':str(s.root),'target':str(target),'ids':ids,'original':original,'api':f'http://127.0.0.1:{web.server_port}'}
(root/'fixture.json').write_text(dumps(fixture),encoding='utf8');print(dumps({'fixture':str(root/'fixture.json')}),flush=True)
try:stop.wait(180)
finally:web.shutdown();web.server_close()
