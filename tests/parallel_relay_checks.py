"""Interleaved HTTP streams through the shared multi-key production client."""
import collections,json,sys,tempfile,threading,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from providers import Providers,protect
from schemas import obj,S
lock=threading.Lock();keys=[];active=0;peak=0
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        global active,peak
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));value=data['messages'][-1]['content']
        with lock:keys.append(self.headers['Authorization']);active+=1;peak=max(peak,active)
        try:
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
            text=json.dumps({'value':value},ensure_ascii=False)
            for start in range(0,len(text),4):
                self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':text[start:start+4]}}]})+'\n\n').encode());self.wfile.flush();time.sleep(.006)
            self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n');self.wfile.flush()
        finally:
            with lock:active-=1
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.request_queue_size=64
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with tempfile.TemporaryDirectory(prefix='parallel-relay-') as tmp:
        p=Providers();settings={'provider':'api','api_base':f'http://127.0.0.1:{server.server_port}/v1','api_model':'fixture','api_key_encrypted':protect('\n'.join(f'fixture-key-{i}' for i in range(4))),'api_retry_count':0}
        def call(i):return p.call('request-'+str(i),obj({'value':S}),settings,Path(tmp)/str(i))['value']
        with ThreadPoolExecutor(max_workers=16) as pool:answers=list(pool.map(call,range(32)))
        assert answers==['request-'+str(i) for i in range(32)],answers
        counts=collections.Counter(keys);assert sorted(counts.values())==[8,8,8,8],counts
        assert peak>=4 and peak<=16,peak
        assert not p.client(settings)._active
        for file in Path(tmp).rglob('*.txt'):assert 'fixture-key-' not in file.read_text(encoding='utf8')
    report={'ok':True,'requests':32,'observed_http_peak':peak,'unique_key_count':4,'each_key_requests':8,'interleaved_responses_isolated':True,'external_model_calls':0}
    (ROOT/'build/parallel-relay-checks.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report))
finally:server.shutdown();server.server_close()
