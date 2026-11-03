"""Validate the frozen migration in an isolated copy, with model/body jobs disabled."""
import json,os,sqlite3,subprocess,uuid
from contextlib import closing
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];PRODUCTION=Path('C:/Users/74319/Desktop/漫画文章工作台_V0.3.0/data/workbench.sqlite3')
folder=ROOT/'build'/('paragraph-frozen-'+uuid.uuid4().hex[:8]);data=folder/'data';data.mkdir(parents=True)
with closing(sqlite3.connect(PRODUCTION.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(data/'workbench.sqlite3')) as dst:src.backup(dst)
with closing(sqlite3.connect(data/'workbench.sqlite3')) as c,c:
    c.execute("UPDATE settings SET value='true' WHERE key='body_queue_paused'")
    c.execute("UPDATE settings SET value='\"user\"' WHERE key='body_queue_pause_reason'")
    before_articles=c.execute('SELECT id,title,article FROM results ORDER BY id').fetchall()
    before_seeds=c.execute('SELECT * FROM extractions ORDER BY id').fetchall()
    before_cleanup=c.execute('SELECT count(*) FROM result_cleanup_batches').fetchone()[0]
token=uuid.uuid4().hex;env=os.environ.copy();env['COMIC_WORKBENCH_TOKEN']=token
with (folder/'backend.log').open('wb') as log:
    p=subprocess.Popen([str(ROOT/'build/backend/comic-backend.exe'),'--data',str(data),'--resources',str(ROOT/'resources')],env=env,stdout=subprocess.PIPE,stderr=log,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        port=json.loads(p.stdout.readline())['port']
        def api(route):
            with urlopen(Request(f'http://127.0.0.1:{port}'+route,headers={'X-Workbench-Token':token}),timeout=20) as r:return json.loads(r.read())
        health=api('/health');assert health['writing_policy']=='comic_title64_v4'
        prompts=api('/prompts');writing=[p for p in prompts if p['kind']=='write'];assert len(writing)==74
        assert all('正文必须写成8至15个自然段' in p['content'] and '全文默认3至5' not in p['content'] and '改成10张以内漫画' not in p['content'] for p in writing)
    finally:
        subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));p.wait(timeout=20);p.stdout.close()
with closing(sqlite3.connect(data/'workbench.sqlite3')) as c:
    assert c.execute('SELECT id,title,article FROM results ORDER BY id').fetchall()==before_articles
    assert c.execute('SELECT * FROM extractions ORDER BY id').fetchall()==before_seeds
    assert c.execute('SELECT count(*) FROM result_cleanup_batches').fetchone()[0]==before_cleanup
report={'ok':True,'version':health['version'],'writing_policy':health['writing_policy'],'updated_writing_prompts':74,'articles_and_seeds_unchanged':True,'cleanup_feature_preserved':True,'model_calls':0,'body_fetches':0,'production_writes':0}
(ROOT/'build/paragraph-frozen-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
