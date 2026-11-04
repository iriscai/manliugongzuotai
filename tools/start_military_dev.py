"""Open an unpackaged source preview against an isolated, non-dispatching database copy."""
import json,os,sqlite3,subprocess,sys
from contextlib import closing
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'build/military-development';DATA=BASE/'data'
production=Path(os.environ.get('COMIC_PRODUCTION_HOME',str(ROOT.parents[1]/'程序')))
if not (production/'data/workbench.sqlite3').is_file():production=Path('C:/Users/74319/Desktop/漫画文章工作台_V0.3.0')
SOURCE=production/'data/workbench.sqlite3'
ELECTRON=Path('E:/日程提醒/node_modules/electron/dist/electron.exe')

def prepare():
    BASE.mkdir(parents=True,exist_ok=True);DATA.mkdir(exist_ok=True)
    target=DATA/'workbench.sqlite3';created=not target.exists()
    if created:
        with closing(sqlite3.connect(SOURCE.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(target)) as dst:src.backup(dst)
        with closing(sqlite3.connect(target)) as c:
            c.execute("UPDATE runs SET state='interrupted',current_phase='军事开发副本，未自动执行' WHERE state IN ('running','pausing')")
            c.execute("UPDATE body_jobs SET state='paused' WHERE state IN ('running','pausing')")
            c.execute("UPDATE score_jobs SET state='paused' WHERE state IN ('running','pausing')")
            c.execute("UPDATE model_queue SET state='paused',user_paused=1,error='开发副本仅供手动测试' WHERE state IN ('queued','waiting','running')")
            # Reset only military work in this disposable copy, keeping the production history intact.
            c.execute("UPDATE extractions SET current=0 WHERE category='军事'")
            c.execute("UPDATE results SET current=0 WHERE category='军事'")
            c.execute("UPDATE materials SET state=CASE WHEN body<>'' THEN 'pending' ELSE 'needs_source' END,phase='',error='' WHERE category='军事'")
            for table in ['push_batch_items','push_batches','result_pushes']:
                c.execute('DELETE FROM '+table)
            receiver=BASE/'isolated-receiver';receiver.mkdir(exist_ok=True)
            settings={'allowed_categories':['军事'],'extraction_mode':'single','military_extract_variant':'C','military_write_variant':'C','body_queue_paused':True,'body_queue_pause_reason':'user','push_target_project':str(receiver),'military_dev_source':str(SOURCE)}
            for key,value in settings.items():c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False)))
            c.commit()
    return {'source':str(SOURCE),'data':str(DATA),'created':created,'receiver':str(BASE/'isolated-receiver'),'packaged':False,'auto_model_requests':False}

if __name__=='__main__':
    info=prepare();(BASE/'preview.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf8')
    env=os.environ.copy();env.pop('ELECTRON_RUN_AS_NODE',None)
    env.update(COMIC_DATA_DIR=str(DATA),COMIC_PUSH_TARGET_PROJECT=info['receiver'],COMIC_SOURCE_ONLY='1',COMIC_PYTHON=sys.executable,COMIC_DEV_LABEL='军事C开发测试版')
    process=subprocess.Popen([str(ELECTRON),str(ROOT)],cwd=ROOT,env=env,stdout=(BASE/'electron.stdout.log').open('ab'),stderr=(BASE/'electron.stderr.log').open('ab'))
    info['pid']=process.pid;print(json.dumps(info,ensure_ascii=False))
