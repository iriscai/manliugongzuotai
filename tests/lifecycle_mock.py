"""Loopback-only held response for the desktop's graceful-exit test."""
import json,sqlite3,sys,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
source=Path(sys.argv[1]);dest=Path(sys.argv[2]);dest.mkdir(parents=True,exist_ok=True)
with sqlite3.connect(source/'workbench.sqlite3') as a,sqlite3.connect(dest/'workbench.sqlite3') as b:a.backup(b)
started=threading.Event();release=threading.Event()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send_json(self,data):
        raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if self.path=='/release':release.set()
        self.send_json({'started':started.is_set()})
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']));started.set()
        if not release.wait(20):self.send_error(504);return
        article='\n\n'.join(['孩子走进图书角。','先看看开放时间。','每天18时至20时开放。','借书时登记书名。','还书时也要登记。','老师让孩子轮流讲故事。','家长记下孩子的问题。','走道留出通行空间。'])
        text=json.dumps({'category':'生活','title':'安全退出验证稿','article':article},ensure_ascii=False)
        self.send_json({'choices':[{'message':{'content':text},'finish_reason':'stop'}],'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}})
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
print(json.dumps({'port':server.server_port}),flush=True);server.serve_forever()
