import csv,json,sys,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from providers import Providers,ProviderLimit,protect
from store import Store
from worker import Worker
from schemas import obj,S
from relay_client import completion_url,models_url
from workbench_fixtures import TEXT
requests=[]
route={'routes':[{'category':'生活','angle':'开放与借还登记','reason':'生活服务说明','quote':'每天18时至20时开放'}],'reason':''}
extract={'eligible':True,'reason':'有明确原文','main_point':'借还登记','facts':[{'fact':'每天18时至20时开放','quote':'每天18时至20时开放'}],'omissions':[],'visual_nodes':['入口','借书','还书'],'needs_verification':[],'verified_additions':[]}
write={'title':'图书角借还提示','short_text':'图书角每天18时至20时开放。借书登记书名和日期，还书后划掉记录。','frames':[{'number':1,'purpose':'开放时间','scene':'入口','caption':'每天18时至20时开放。','dialogue':[],'visible_labels':[],'image_prompt':'图书角入口与开放时间'},{'number':2,'purpose':'借还登记','scene':'登记本','caption':'借书登记书名和日期，还书后划掉记录。','dialogue':[],'visible_labels':[],'image_prompt':'借还登记示意'}],'post_text':'','notice':'虚构功能测试','genre':'生活图解','adaptations':[]}
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send_json(self,code,data):
        raw=json.dumps(data,ensure_ascii=False).encode('utf8');self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        requests.append(('GET',self.path,self.headers.get('Authorization'),None))
        self.send_json(200,{'data':[{'id':'fixture-a'},{'id':'fixture-b'},{'id':'fixture-a'}]})
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(('POST',self.path,self.headers.get('Authorization'),data))
        assert self.headers.get('User-Agent')=='FunnyComicTitleGenerator/1.0'
        assert 'response_format' not in data
        if self.path.startswith('/rate'):
            self.send_json(429,{'error':self.headers.get('Authorization')});return
        if self.path.startswith('/auth'):
            self.send_json(401,{'error':self.headers.get('Authorization')});return
        if not data.get('stream'):
            self.send_json(200,{'choices':[{'message':{'content':'OK'},'finish_reason':'stop'}]});return
        system=data['messages'][0]['content'];assert '中文漫画标题主编' not in system
        source=json.loads(data['messages'][1]['content'].split('\n统一输入素材：',1)[1]) if '"categories"' in system else None
        evidence=source['body'][0] if source else None
        seed={'categories':[{'category':'生活','topic':'开放时间','angle':'开放时间','reason':'适配','main_point':'每天18时至20时开放','elements':[{'name':'时间','content':evidence['text'],'evidence_ids':[evidence['id']]}],'omissions':[],'visual_nodes':[]}],'reason':'适配'} if source else None
        value=seed if source else {'category':'生活','title':'图书角借还提示','article':TEXT} if '"article"' in system else route if '"routes"' in system else extract if '"eligible"' in system else write if '"frames"' in system else {'ok':'通过'}
        text=json.dumps(value,ensure_ascii=False)
        if self.path.startswith('/fallback'):
            self.send_json(200,{'choices':[{'message':{'content':text},'finish_reason':'stop'}]});return
        if self.path.startswith('/invalid'):text='非JSON返回'
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
        for start in range(0,len(text),31):
            piece=text[start:start+31];content=[{'type':'text','text':piece}] if self.path.startswith('/list') else piece
            self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':content}}]},ensure_ascii=False)+'\n\n').encode('utf8'))
        if not self.path.startswith('/incomplete'):
            reason='length' if self.path.startswith('/truncated') else 'stop'
            self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{},'finish_reason':reason}]})+'\n\ndata: [DONE]\n\n').encode('utf8'))
        self.wfile.flush()
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with tempfile.TemporaryDirectory(prefix='relay-checks-') as temp:
        root=Path(temp);s=Store(root/'data',ROOT/'resources');base=f'http://127.0.0.1:{server.server_port}'
        settings={**s.settings(),'provider':'api','api_base':base+'/v1','api_model':'fixture-a','api_key_encrypted':protect('fixture-key-a\nfixture-key-b\nfixture-key-a'),'api_temperature':.7,'api_retry_count':0,'api_timeout':30,'allowed_categories':['生活']}
        s.save_settings(settings);provider=Providers();schema=obj({'ok':S})
        for index in range(3):assert provider.call('只输出JSON',schema,settings,root/f'call-{index}')=={'ok':'通过'}
        assert [r[2] for r in requests[:3]]==['Bearer fixture-key-a','Bearer fixture-key-b','Bearer fixture-key-a']
        assert all(r[3]['temperature']==.7 and r[3]['stream'] is True for r in requests[:3])
        assert provider.api_test(settings)['ok'] is True
        assert provider.api_models(settings)['models']==['fixture-a','fixture-b']
        for path in ['/list/v1','/fallback/v1']:
            assert provider.call('JSON',schema,{**settings,'api_base':base+path},root/path.split('/')[1])=={'ok':'通过'}
        before=len(requests)
        try:provider.call('JSON',schema,{**settings,'api_base':base+'/rate/v1','api_retry_count':3},root/'rate');raise AssertionError('quota accepted')
        except ProviderLimit as error:assert 'fixture-key' not in str(error)
        assert len(requests)==before+1
        for path in ['/truncated/v1','/incomplete/v1','/auth/v1']:
            try:provider.call('JSON',schema,{**settings,'api_base':base+path},root/path.split('/')[1]);raise AssertionError('bad response accepted')
            except RuntimeError as error:assert 'fixture-key' not in str(error)
        before=len(requests)
        try:provider.call('JSON',schema,{**settings,'api_base':base+'/invalid/v1','api_retry_count':1},root/'retry');raise AssertionError('invalid JSON accepted')
        except RuntimeError:pass
        assert len(requests)==before+2
        assert provider.status(settings)['api_key_count']==2
        # Exercise the actual route -> extract -> write pipeline through streaming HTTP.
        p=root/'material.csv'
        with p.open('w',encoding='utf8',newline='') as f:w=csv.writer(f);w.writerow(['标题','正文','分类']);w.writerow(['图书角借还说明','图书角每天18时至20时开放。借书登记书名和日期，还书后划掉对应记录。本条为虚构功能测试素材。','生活'])
        mid=s.import_file({'path':str(p)})['intake_ids'][0];worker=Worker(s);worker.provider=Providers();job=worker.start({'ids':[mid],'mode':'both','limit':1});worker.thread.join(20);assert not worker.thread.is_alive()
        assert s.material(mid)['state']=='written' and s.material(mid)['extraction_count']==1
        assert s.stats()['counts']['result_count']==1
        for file in root.rglob('*'):
            if file.is_file() and file.suffix in ('.txt','.json','.jsonl'):
                content=file.read_text(encoding='utf8',errors='ignore');assert 'fixture-key-a' not in content and 'fixture-key-b' not in content,str(file)
        assert completion_url(base+'/v1/chat/completions')==base+'/v1/chat/completions'
        assert models_url(base+'/v1/chat/completions')==base+'/v1/models'
    report={'ok':True,'checks':['原项目Chat流式请求格式及Temperature','多Key跨请求轮询并去重','连接测试和模型列表读取','流式分片与列表内容解析','非流式JSON兼容','截断和中断拒绝入库','额度受限立即暂停','重试次数有上限','错误与落盘记录密钥隐藏','分类提炼生文全流程真实HTTP联通'],'external_model_calls':0,'production_changes':0}
    (ROOT/'build/relay-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
finally:server.shutdown();server.server_close()
