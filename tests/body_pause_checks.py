import csv,json,sys,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store
from body_fetcher import BodyFetcher
hits={'/one':0,'/two':0}
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  if self.path not in hits:self.send_response(404);self.end_headers();return
  hits[self.path]+=1
  if self.path=='/two':time.sleep(5)
  raw=('<html><meta charset="utf-8"><body><article>'+''.join(f'<p>第{i}段记录说明借阅步骤，书名和日期需要对应，归还之后更新登记，虚构集成测试并不代表真实通知。</p>' for i in range(1,12))+'</article></body></html>').encode('utf8')
  try:self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(raw)
  except (BrokenPipeError,ConnectionResetError):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
folder=ROOT/'build/body-pause-fixture';folder.mkdir(parents=True,exist_ok=True);s=Store(folder/'data',ROOT/'resources')
s.save_settings({'body_workers':1,'body_wait':15,'body_delay':0,'body_rest_every':0,'body_rest_seconds':0,'body_timeout':240})
p=folder/'input.csv'
with p.open('w',encoding='utf8',newline='') as f:
 w=csv.writer(f);w.writerow(['标题','链接','领域'])
 for suffix in ['/one','/two']:w.writerow(['暂停续抓测试'+suffix,f'http://127.0.0.1:{server.server_port}'+suffix,'生活'])
s.import_file({'path':str(p)});fetch=BodyFetcher(s)
try:
 job=fetch.start({'limit':2});end=time.monotonic()+120
 while time.monotonic()<end:
  d=fetch.detail(job['job_id'])
  if d['job']['ok']>=1:break
  time.sleep(.3)
 assert d['job']['ok']>=1,d
 fetch.pause();fetch.thread.join(25);assert not fetch.thread.is_alive()
 paused=fetch.detail(job['job_id']);assert paused['job']['state']=='paused',paused
 assert paused['job']['ok']==1,paused
 first_hits=hits['/one'];resumed=fetch.resume(job['job_id']);fetch.thread.join(180)
 assert not fetch.thread.is_alive()
 done=fetch.detail(resumed['job_id']);assert done['job']['ok']==1 and paused['job']['ok']+done['job']['ok']==2,done
 assert hits['/one']==first_hits,(hits,first_hits)
 report={'ok':True,'paused_after_success':1,'success_after_resume':2,'completed_article_repeated':False,'scope':'Real designated EXE on isolated local fixture pages; no production/model work.'}
 (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
finally:fetch.pause();server.shutdown();server.server_close()
