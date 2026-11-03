"""Local protocol fixture, no external model/API calls."""
import json
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler,HTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from providers import Providers,protect

seen=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append((self.path,data,self.headers.get('Authorization')))
        text=json.dumps({'answer':'协议测试通过'},ensure_ascii=False)
        if self.path.endswith('/responses'):obj={'status':'completed','output':[{'content':[{'type':'output_text','text':text}]}]}
        else:obj={'choices':[{'finish_reason':'stop','message':{'content':text}}]}
        raw=json.dumps(obj,ensure_ascii=False).encode('utf8');self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
    settings={'api_base':f'http://127.0.0.1:{server.server_port}/v1','api_model':'fixture-model','api_key_encrypted':protect('fixture-only-key'),'timeout':60}
    provider=Providers();schema={'type':'object','properties':{'answer':{'type':'string'}},'required':['answer'],'additionalProperties':False}
    for protocol in ['chat','responses']:
        settings['api_protocol']=protocol
        assert provider.api('只返回JSON',schema,settings)=={'answer':'协议测试通过'}
    assert seen[0][0]=='/v1/chat/completions' and seen[1][0]=='/v1/responses'
    assert all(x[2]=='Bearer fixture-only-key' for x in seen)
    assert seen[1][1]['text']['format']['schema']==schema
    print(json.dumps({'ok':True,'protocols':['chat','responses'],'scope':'Local fixture only; no user API credential or external inference used.'},ensure_ascii=False))
finally:server.shutdown();server.server_close()
