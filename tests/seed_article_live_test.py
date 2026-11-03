"""Reuse the prior real extraction; pay only for its direct article generation."""
import hashlib,json,os,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,dumps
INSTALLED=Path('C:/Users/74319/Desktop/漫画文章工作台_V0.3.0')
previous=json.loads((ROOT/'build/adaptive-live-report.json').read_text(encoding='utf8'))
source=Path(previous['output_folder'])/'隔离数据/workbench.sqlite3'
folder=Path('C:/Users/74319/Desktop')/('种子生文成品测试_素材189_'+uuid.uuid4().hex[:6]);folder.mkdir();data=folder/'隔离数据';data.mkdir()
with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(data/'workbench.sqlite3') as dst:src.backup(dst)
s=Store(data,INSTALLED/'resources/app/resources');s.save_settings({'api_retry_count':0})
with s.connect() as c:
    seed_count=c.execute('SELECT count(*) FROM extractions WHERE current=1 AND eligible=1').fetchone()[0]
    assert seed_count>0 and c.execute('SELECT count(*) FROM results').fetchone()[0]==0
    mid=c.execute('SELECT id FROM materials LIMIT 1').fetchone()[0]
with sqlite3.connect((INSTALLED/'data/workbench.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
    c.row_factory=sqlite3.Row;original=dict(c.execute('SELECT * FROM materials WHERE id=189').fetchone())
fingerprint=hashlib.sha256(dumps(original).encode()).hexdigest();token=uuid.uuid4().hex;env=os.environ.copy();env['COMIC_WORKBENCH_TOKEN']=token
settings=s.settings();run=None;error='';rows=[]
with (folder/'后端日志.txt').open('wb') as log:
    p=subprocess.Popen([str(INSTALLED/'resources/app/backend/comic-backend.exe'),'--data',str(data),'--resources',str(INSTALLED/'resources/app/resources')],env=env,stdout=subprocess.PIPE,stderr=log,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        port=json.loads(p.stdout.readline())['port']
        def api(route,body=None):
            req=Request(f'http://127.0.0.1:{port}'+route,data=None if body is None else dumps(body).encode('utf8'),headers={'Content-Type':'application/json','X-Workbench-Token':token})
            with urlopen(req,timeout=30) as response:return json.loads(response.read())
        assert api('/health')['output_mode']=='article'
        job=api('/run/start',{'mode':'write','limit':1,'ids':[mid]})
        print(dumps({'phase':'real_article_generation_started','model':settings['api_model'],'reused_extraction_groups':seed_count,'maximum_new_requests':seed_count,'output_folder':str(folder)}),flush=True)
        start=time.monotonic();notice=-20
        while time.monotonic()-start<360:
            stats=api('/stats');run=next(r for r in stats['runs'] if r['id']==job['run_id'])
            if run['state'] not in ('running','pausing'):break
            elapsed=int(time.monotonic()-start)
            if elapsed-notice>=20:print(dumps({'phase':'writing','elapsed_seconds':elapsed,'written':run['progress']['written']}),flush=True);notice=elapsed
            time.sleep(1)
        else:raise TimeoutError('Article live test timeout')
        rows=api('/results')['rows'];api('/export',{'path':str(folder/'文章成品.json'),'kind':'results'});api('/export',{'path':str(folder/'文章成品.csv'),'kind':'results'})
        material=api('/materials/'+str(mid));error=material.get('error','')
    except Exception as exc:error=str(exc)
    finally:
        if p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        p.wait(timeout=25);p.stdout.close()
attempts=list((data/'runs'/job['run_id']).rglob('api-request-*.json')) if run else []
with sqlite3.connect((INSTALLED/'data/workbench.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
    c.row_factory=sqlite3.Row;after=dict(c.execute('SELECT * FROM materials WHERE id=189').fetchone())
unchanged=hashlib.sha256(dumps(after).encode()).hexdigest()==fingerprint
assert unchanged
report={'ok':bool(run and run['state']=='completed' and run['errors']==0 and len(rows)==seed_count),'model':settings['api_model'],'source_material_id':189,'reused_extraction_groups':seed_count,'new_extraction_requests':0,'new_article_requests':len(attempts),'articles':len(rows),'fields':['赛道','标题','文章'],'output_folder':str(folder),'error':error,'production_material_unchanged':unchanged}
for i,row in enumerate(rows,1):
    text='赛道：'+row['category']+'\n标题：'+row['title']+'\n\n'+(row['article'] or row['short_text'])+'\n'
    (folder/('文章.txt' if len(rows)==1 else f'文章{i}.txt')).write_text(text,encoding='utf8')
(folder/'测试报告.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
(folder/'测试报告.md').write_text('# 正文＋元素＋分类直接生文实测\n\n'+f'模型：{settings["api_model"]}\n\n复用已有提炼{seed_count}组。本次新增提炼请求0次，新增生文请求{len(attempts)}次，得到{len(rows)}篇文章成品。\n\n成品字段：赛道、标题、文章。无需待核实队列、审核稿或分镜。\n\n正式素材保持原样：'+('是' if unchanged else '否')+'。\n\n'+('执行错误：'+error if error else '测试通过。'),encoding='utf8')
(ROOT/'build/seed-article-live-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(dumps({'phase':'article_live_test_complete',**report}),flush=True)
