"""Topic-level recovery and original-lane writing without external model calls."""
from workbench_fixtures import *
from providers import ProviderLimit,Providers,protect
from extraction_recovery import POLICY
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import copy

class RecoveryFake(Fake):
    def __init__(self,kind):super().__init__();self.kind=kind;self.worker=None;self.last=None
    def call(self,prompt,schema,settings,folder,on_event=None):
        if schema is SEED_EXTRACT and self.kind in ('error','quota'):
            on_event({'event':'request_start'});self.calls.append(schema);on_event({'event':'request_finish','ok':False})
            raise (ProviderLimit('模拟余额不足') if self.kind=='quota' else RuntimeError('模拟模型输出不是JSON'))
        result=super().call(prompt,schema,settings,folder,on_event)
        if schema is ARTICLE:
            self.last=prompt;return result
        if self.kind=='empty':result['categories']=[]
        elif self.kind=='partial':
            result['categories'][0].pop('main_point');result['categories']+=[None,{'category':'未知赛道'}]
        elif self.kind=='duplicate':result['categories'].append(copy.deepcopy(result['categories'][0]))
        elif self.kind=='anchors':
            for item in result['categories']:item['elements'][0]['evidence_ids']=['OTHER_ROW']
        elif self.kind=='other':result['categories']=result['categories'][1:]
        elif self.kind=='pause':self.worker.pause()
        elif self.kind=='changed':
            with self.worker.store.connect() as c:c.execute("UPDATE materials SET body='正文在请求期间已被更改，不能用旧输出写文。' WHERE id=1")
        self.extracted=result;return result

def execute(root,kind,mode='both'):
    s,w,_=seed(root);s.save_settings({'process_workers':1});p=RecoveryFake(kind);w.provider=p;p.worker=w
    rid=w.start({'mode':mode,'limit':1})['run_id'];wait(w)
    return s,w,p,rid

def state(s,rid):
    with s.connect() as c:return c.execute('SELECT state FROM runs WHERE id=?',(rid,)).fetchone()[0]

with tempfile.TemporaryDirectory(prefix='extraction-recovery-') as temp:
    root=Path(temp)
    for kind,expected in [('empty',1),('error',1),('anchors',1),('partial',2),('duplicate',2),('other',2)]:
        s,w,p,rid=execute(root/kind,kind);rows=s.list_results({})['rows']
        assert state(s,rid)=='completed' and len(rows)==expected,(kind,state(s,rid),len(rows))
        assert p.calls.count(SEED_EXTRACT)==1 and p.calls.count(ARTICLE)==expected
        assert any(r['category']=='生活' for r in rows)
        with s.connect() as c:
            seeds=[dict(x) for x in c.execute('SELECT * FROM extractions')];fallback=[json.loads(x['data_json']) for x in seeds if json.loads(x['data_json']).get('seed_origin')]
            if kind!='duplicate':
                assert len(fallback)==1 and fallback[0]['fallback_policy']==POLICY
                assert all(e['quote'] in s.material(1)['body'] for e in fallback[0]['evidence'])
                assert c.execute("SELECT count(*) FROM results WHERE json_extract(data_json,'$.seed_origin')='source_category_fallback'").fetchone()[0]==1
            else:assert not fallback
        if kind in ('empty','error','anchors'):assert '原赛道直接生文保底种子' in p.last
    # Saved fallback seeds survive write failures and are reused by retry.
    s,w,_=seed(root/'retry');p=RecoveryFake('empty');p.fail=True;w.provider=p;p.worker=w
    rid=w.start({'mode':'both','limit':1})['run_id'];wait(w);assert s.list_results({})['total']==0
    p.fail=False;w.retry(rid);wait(w);assert s.list_results({})['total']==1 and p.calls.count(SEED_EXTRACT)==1
    s,w,p,rid=execute(root/'extract-only','empty','extract');assert p.calls.count(ARTICLE)==0 and s.material(1)['extraction_count']==1
    w.start({'mode':'write','limit':1});wait(w);assert s.list_results({})['total']==1 and p.calls.count(SEED_EXTRACT)==1
    s,w,p,rid=execute(root/'quota','quota');assert state(s,rid)=='blocked' and p.calls.count(ARTICLE)==0 and not s.material(1)['extractions']
    s,w,_=seed(root/'budget');p=RecoveryFake('empty');w.provider=p;p.worker=w
    rid=w.start({'mode':'both','limit':1,'task_budget':{'request_limit':1}})['run_id'];wait(w)
    assert state(s,rid)=='blocked' and p.calls.count(ARTICLE)==0 and s.material(1)['extraction_count']==1
    w.resume(rid,{'task_budget':{'request_limit':2}});wait(w);assert s.list_results({})['total']==1 and p.calls.count(SEED_EXTRACT)==1
    s,w,p,rid=execute(root/'pause','pause');assert state(s,rid)=='paused' and p.calls.count(ARTICLE)==0
    w.resume(rid);wait(w);assert s.list_results({})['total']==2 and p.calls.count(SEED_EXTRACT)==1
    s,w,p,rid=execute(root/'changed','changed');assert state(s,rid)=='completed' and s.stats()['runs'][0]['errors']==1 and p.calls.count(ARTICLE)==0
    s,w,_=seed(root/'unknown');p=RecoveryFake('empty');w.provider=p;p.worker=w
    with s.connect() as c:c.execute("UPDATE materials SET category='未知赛道' WHERE id=1")
    rid=w.start({'mode':'both','limit':1})['run_id'];wait(w)
    with s.connect() as c:assert '无法确定保底生文赛道' in c.execute('SELECT error FROM run_items WHERE run_id=?',(rid,)).fetchone()[0]
    assert p.calls.count(ARTICLE)==0
    s,w,_=seed(root/'disabled');p=RecoveryFake('empty');w.provider=p;p.worker=w
    with s.connect() as c:c.execute("UPDATE prompts SET enabled=0 WHERE category='生活' AND kind='write'")
    rid=w.start({'mode':'both','limit':1})['run_id'];wait(w);assert p.calls.count(ARTICLE)==0
    # Funny fallback must retain its existing I stages, scoring and normal validation.
    from funny_singlecall import FUNNY_ARTICLE
    trial=ROOT/'outputs/funny-singlecall-20261031/v4/bonus'
    funny_source=json.loads((trial/'result.json').read_text(encoding='utf8'))['source']
    funny_answer=json.loads((trial/'write/answer.json').read_text(encoding='utf8'))
    funny_answer['quality_score']={'completeness':94,'reversal':85,'fun':85,'reason':'原文账本闭环。','evidence':[funny_answer['article'].splitlines()[-1]],'risks':[]}
    class Funny:
        def __init__(self):self.calls=[]
        def auth_status(self,_):return {'ok':True}
        def call(self,prompt,schema,settings,folder,on_event=None):
            self.calls.append(schema);on_event({'event':'request_start'})
            if schema is SEED_EXTRACT:answer={'categories':[],'reason':'没有跨赛道主题'}
            else:
                assert schema is FUNNY_ARTICLE and settings['api_retry_count']==0
                assert '原赛道直接生文保底种子' in prompt and '标题泄底专查' in prompt and 'completeness故事完整性' in prompt
                answer=funny_answer
            on_event({'event':'request_finish','ok':True,'usage':{'input_tokens':10,'output_tokens':10,'total_tokens':20}})
            return answer
    s=Store(root/'funny/data',ROOT/'resources');s.save_settings({'allowed_categories':['搞笑']});f=root/'funny/input.csv'
    with f.open('w',encoding='utf8',newline='') as out:csv.writer(out).writerows([['标题','正文','分类'],[funny_source['title'],funny_source['body'],'搞笑']])
    s.import_file({'path':str(f)});w=Worker(s);w.provider=Funny();w.start({'mode':'both','limit':1});wait(w)
    assert w.provider.calls==[SEED_EXTRACT,FUNNY_ARTICLE]
    r=s.list_results({})['rows'][0];assert r['score']==93 and r['score_status']=='scored' and r['write_variant']=='I'
    # HTTP transport must deliver partial seed arrays without retrying the entire response.
    delivered=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));delivered.append(data)
            if '"categories"' in data['messages'][0]['content']:
                src=json.loads(data['messages'][1]['content'].split('\n统一输入素材：')[1]);e=src['body'][0]
                good={'category':'教育','topic':'轮流讲故事','angle':'轮流讲故事','reason':'有依据','main_point':'老师让孩子轮流讲故事',
                      'elements':[{'name':'故事','content':e['text'],'evidence_ids':[e['id']]}],'omissions':[],'visual_nodes':[]}
                answer={'categories':[{'category':'生活'},good],'reason':''}
            else:
                src=json.loads(data['messages'][1]['content'].split('本组种子：')[1].split('\n本条原始素材：')[0]);answer={'category':src['category'],'title':src['category']+'图书角','article':TEXT}
            raw=json.dumps({'choices':[{'message':{'content':dumps(answer)},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}},ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        s,w,_=seed(root/'http');s.save_settings({'provider':'api','api_base':f'http://127.0.0.1:{server.server_port}/v1','api_key_encrypted':protect('fixture-only'),'api_model':'fixture','api_retry_count':3})
        w.provider=Providers();rid=w.start({'mode':'both','limit':1})['run_id'];wait(w)
        assert len(delivered)==3 and s.list_results({})['total']==2
        with s.connect() as c:assert c.execute('SELECT count(*) FROM model_requests WHERE run_id=?',(rid,)).fetchone()[0]==3
        import os,subprocess,urllib.request
        if os.environ.get('COMIC_TEST_FROZEN'):
            # A separate frozen process exercises the deployed import graph and HTTP API.
            s,w,_=seed(root/'frozen');s.save_settings({'provider':'api','api_base':f'http://127.0.0.1:{server.server_port}/v1','api_key_encrypted':protect('fixture-only'),'api_model':'fixture','api_retry_count':3,'body_queue_paused':True})
            env={**os.environ,'COMIC_WORKBENCH_TOKEN':'fixture-token'}
            process=subprocess.Popen([os.environ['COMIC_TEST_FROZEN'],'--data',str(s.root),'--resources',str(ROOT/'resources'),'--port','0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8',env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                line=process.stdout.readline();info=json.loads(line);port=info['port']
                def call(route,data=None):
                    req=urllib.request.Request(f'http://127.0.0.1:{port}'+route,data=dumps(data).encode() if data is not None else None,headers={'X-Workbench-Token':'fixture-token','Content-Type':'application/json'})
                    with urllib.request.urlopen(req,timeout=10) as response:return json.loads(response.read())
                before=len(delivered);job=call('/run/start',{'mode':'both','limit':1})
                for _ in range(100):
                    stats=call('/stats')
                    if stats['runs'] and stats['runs'][0]['state'] not in ('running','pausing'):break
                    time.sleep(.1)
                assert stats['runs'][0]['done']==1 and stats['runs'][0]['errors']==0,stats['runs'][0]
                assert stats['counts']['result_count']==2 and len(delivered)==before+3
            finally:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                else:process.terminate()
                process.communicate(timeout=15)
    finally:server.shutdown();server.server_close()
print(dumps({'ok':True,'partial_topics_preserved':True,'empty_and_failed_extraction_source_fallback':True,'original_lane_prompt_used':True,'source_anchors_preserved':True,'no_extra_extraction_calls':True,'retry_and_resume_reuse_saved_seeds':True,'pause_quota_budget_not_bypassed':True,'unknown_and_disabled_not_forced':True,'http_partial_response_not_retried':True,'external_model_calls':0,'production_changes':0}))
