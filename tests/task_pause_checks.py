"""Safe pause and quota recovery with isolated data and localhost-only HTTP."""
from workbench_fixtures import *
from providers import Providers,ProviderLimit,protect
from model_queue import ModelQueue
from schemas import obj,S
from relay_client import RelayError,RelayLimit,RelayClient,RelayConfig
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

received=[];arrived=threading.Event();release=threading.Event()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']));received.append(self.path)
        if self.path.startswith('/retry'):
            arrived.set();assert release.wait(10)
            data={'choices':[{'message':{'content':'invalid JSON'},'finish_reason':'stop'}]};status=200
        else:
            data={'error':{'code':'insufficient_user_quota','message':'fixture-key-a 余额不足'}};status=403
            if self.path.startswith('/json'):status=200
            if self.path.startswith('/ordinary'):data={'error':'permission denied'}
        if self.path.startswith('/sse'):
            raw=('data: '+json.dumps(data)+'\n\n').encode();status=200;ctype='text/event-stream'
        else:raw=json.dumps(data).encode();ctype='application/json'
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

def runrow(s,rid):
    with s.connect() as c:return dict(c.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone())

class QuotaFake(Fake):
    def __init__(self):super().__init__();self.release=threading.Event();self.write_index=0
    def call(self,prompt,schema,settings,folder,on_event=None):
        if schema is ARTICLE:
            with self.lock:self.write_index+=1;index=self.write_index
            if index==2:
                assert self.started.wait(8)
                on_event({'event':'request_start'})
                with self.lock:self.calls.append(schema)
                on_event({'event':'request_finish','ok':False})
                raise ProviderLimit('模拟 HTTP403 insufficient_user_quota 余额不足')
        return super().call(prompt,schema,settings,folder,on_event)

server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with tempfile.TemporaryDirectory(prefix='task-pause-') as tmp:
        root=Path(tmp);s,w,p=seed(root/'manual')
        s.save_settings({'process_workers':1,'global_max_concurrency':1})
        p.release=threading.Event();r=w.start({'mode':'both','limit':1});rid=r['run_id'];assert p.started.wait(8)
        try:w.pause('wrong-run');raise AssertionError('wrong run paused')
        except ValueError:pass
        assert not w.pause_flag.is_set()
        w.pause(rid);assert runrow(s,rid)['state']=='pausing';p.release.set();wait(w)
        assert runrow(s,rid)['state']=='paused';assert s.list_results({})['total']==1
        assert p.calls.count(ARTICLE)==1 and p.calls.count(SEED_EXTRACT)==1
        w.resume(rid);wait(w);assert runrow(s,rid)['state']=='completed'
        assert s.list_results({})['total']==2 and p.calls.count(ARTICLE)==2 and p.calls.count(SEED_EXTRACT)==1
        assert '没有运行' in w.pause()['message']

        s,w,_=seed(root/'quota',2);s.save_settings({'process_workers':1,'global_max_concurrency':2});p=QuotaFake();w.provider=p
        rid=w.start({'mode':'both','limit':2})['run_id']
        assert w.pause_flag.wait(10)
        deadline=time.monotonic()+2
        while runrow(s,rid)['state']=='running' and time.monotonic()<deadline:time.sleep(.01)
        assert runrow(s,rid)['state']=='pausing'
        p.release.set();wait(w)
        assert runrow(s,rid)['state']=='blocked';assert s.list_results({})['total']==1
        assert p.calls.count(SEED_EXTRACT)==1 and p.calls.count(ARTICLE)==2
        with s.connect() as c:
            assert c.execute("SELECT count(*) FROM run_items WHERE run_id=? AND state='queued'",(rid,)).fetchone()[0]==2
            assert c.execute("SELECT count(*) FROM run_writes WHERE run_id=? AND state='queued'",(rid,)).fetchone()[0]==1
        w.resume(rid);wait(w);assert runrow(s,rid)['state']=='completed'
        assert s.list_results({})['total']==4 and p.calls.count(SEED_EXTRACT)==2 and p.calls.count(ARTICLE)==5

        s,w,p=seed(root/'queue',2);s.save_settings({'process_workers':1,'global_max_concurrency':1})
        p.release=threading.Event();q=ModelQueue(s,w);jid=q.enqueue({'mode':'both','limit':2})['job_id'];q.tick();assert p.started.wait(8)
        q.pause(jid);p.release.set();wait(w)
        for _ in range(3):q.tick()
        with s.connect() as c:
            job=dict(c.execute('SELECT * FROM model_queue WHERE id=?',(jid,)).fetchone());assert job['state']=='paused' and job['user_paused']==1
        before=len(p.calls);q.tick();assert len(p.calls)==before
        q.resume(jid);wait(w);q.tick();assert q.stats()['rows'][0]['state']=='completed'

        settings={'provider':'api','api_base':f'http://127.0.0.1:{server.server_port}/quota','api_model':'fixture','api_key_encrypted':protect('fixture-key-a\nfixture-key-b'),'api_retry_count':3,'api_timeout':10}
        for path in ['quota','json','sse']:
            provider=Providers();before=len(received)
            try:provider.call('JSON',obj({'ok':S}),{**settings,'api_base':settings['api_base'].replace('/quota','/'+path)},root/path);raise AssertionError('quota accepted')
            except ProviderLimit as exc:assert 'fixture-key' not in str(exc)
            assert len(received)==before+1,'quota retried or rotated keys'
        provider=Providers()
        try:provider.client({**settings,'api_base':settings['api_base'].replace('/quota','/ordinary')}).complete('test',threading.Event(),lambda _:None,'test');raise AssertionError('403 accepted')
        except RelayLimit:raise AssertionError('ordinary 403 mistaken for quota')
        except RelayError:pass
        # A real Providers retry reaches Worker.request_start after a safe pause.
        s,w,_=seed(root/'retry');s.save_settings({**settings,'api_base':settings['api_base'].replace('/quota','/retry'),'api_retry_count':3,'process_workers':1});w.provider=Providers()
        before=len(received);rid=w.start({'mode':'extract','limit':1})['run_id'];assert arrived.wait(8);w.pause(rid);release.set();wait(w)
        assert runrow(s,rid)['state']=='paused' and len(received)==before+1
        with s.connect() as c:assert c.execute('SELECT count(*) FROM model_requests WHERE run_id=?',(rid,)).fetchone()[0]==1
    print(dumps({'ok':True,'manual_safe_pause':True,'quota_preserves_inflight_and_seeds':True,'resume_skips_saved_work':True,'quota403_json_sse_no_retries':True,'ordinary403_unchanged':True,'manual_pause_stops_retry':True,'queue_stays_paused':True,'external_calls':0,'production_changes':0}))
finally:release.set();server.shutdown();server.server_close()
