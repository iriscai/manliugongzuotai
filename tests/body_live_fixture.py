"""Run the exact user-provided executable on two local article fixtures."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import csv,json,threading,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store
from body_fetcher import BodyFetcher

TEXTS={
 '/one':'\n'.join(f'第{i}组：图书角把借还记录按日期保存，入口处有清楚说明，归还时核对对应书名，读者不需要猜测流程。' for i in range(1,35)),
 '/two':'\n'.join(f'第{i}段：社区花园更换了分区标牌，不同花盆各有编号，浇水记录保存在自己的区域，观察笔记与实际操作保持对应。' for i in range(1,15))
}
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        text=TEXTS.get(self.path)
        if text is None:self.send_response(404);self.end_headers();return
        raw=('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>集成测试文章</title><body><article><h1>集成测试文章</h1>'+''.join('<p>'+s+'</p>' for s in text.splitlines())+'</article></body></html>').encode('utf8')
        self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
folder=ROOT/'build/body-live-fixture';folder.mkdir(parents=True,exist_ok=True)
s=Store(folder/'data',ROOT/'resources')
s.save_settings({'body_max_chars':0,'body_workers':1,'body_wait':10,'body_delay':0,'body_rest_every':0,'body_rest_seconds':0,'body_timeout':240})
source=folder/'source.csv'
with source.open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['标题','链接','领域']);
    for suffix in ['/one','/two']:w.writerow(['相同标题不合并',f'http://127.0.0.1:{server.server_port}'+suffix,'生活'])
s.import_file({'path':str(source)})
fetch=BodyFetcher(s)
try:
    run=fetch.start({'limit':2});fetch.thread.join(260)
    if fetch.thread.is_alive():fetch.pause();raise AssertionError('live fixture timed out')
    detail=fetch.detail(run['job_id']);assert detail['job']['ok']==2,detail
    assert all(s.material(x['material_id'])['body'] for x in detail['items'])
    assert max(x['body_chars'] for x in detail['items'])>800
    report={'ok':True,'engine':fetch.engine_info()['path'],'job':run['job_id'],'success':2,'body_lengths':[x['body_chars'] for x in detail['items']],'checks':['真实指定EXE命令行调用','两个同标题不同链接均保留','超过800字未截断','逐行正文已写入独立SQLite'],'scope':'Two locally served synthetic article pages; no production material or model inference used.'}
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
finally:server.shutdown();server.server_close()
