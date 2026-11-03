"""One isolated writing step via the frozen backend and the configured relay."""
import csv,json,os,subprocess,sys,time,uuid
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,digest,dumps,now
from providers import reference_settings
folder=ROOT/'build/relay-live-smoke'/uuid.uuid4().hex[:10];folder.mkdir(parents=True)
s=Store(folder/'data',ROOT/'resources');settings=reference_settings();settings.update({'api_retry_count':0,'api_timeout':180,'allowed_categories':['生活'],'requirements':'本条只做功能测试，题材为虚构的借书角说明。只规划2幅漫画，发布可见文字合计尽量不超过160字符，严格使用提炼的事实，不增加新的规定。'})
s.save_settings(settings)
source='图书角每天18时至20时开放。借书时登记书名和日期，还书后划掉对应记录。本条为虚构功能测试素材。'
p=folder/'input.csv'
with p.open('w',encoding='utf8',newline='') as f:w=csv.writer(f);w.writerow(['标题','正文','分类']);w.writerow(['图书角借还说明',source,'生活'])
mid=s.import_file({'path':str(p)})['intake_ids'][0];material=s.material(mid)
extraction={'eligible':True,'reason':'已给定的隔离测试提炼','main_point':'开放时间与借还登记','facts':[{'fact':'每天18时至20时开放','quote':'每天18时至20时开放'},{'fact':'借书登记书名和日期，归还后划掉记录','quote':'借书时登记书名和日期，还书后划掉对应记录'}],'omissions':[],'visual_nodes':['开放时间','借还登记'],'needs_verification':[],'verified_additions':[]}
with s.connect() as c:c.execute('INSERT INTO extractions(material_id,category,angle,source_hash,rule_variant,prompt_text,data_json,current,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(mid,'生活','开放时间与借还登记',digest(material['title']+'\n'+source),'A','隔离测试固定提炼，并非模型生成',dumps(extraction),1,now()))
token=uuid.uuid4().hex;env=os.environ.copy();env['COMIC_WORKBENCH_TOKEN']=token
with (folder/'backend.log').open('wb') as log:
    process=subprocess.Popen([str(ROOT/'build/backend/comic-backend.exe'),'--data',str(folder/'data'),'--resources',str(ROOT/'resources')],env=env,stdout=subprocess.PIPE,stderr=log,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        port=json.loads(process.stdout.readline())['port']
        def api(route,body=None):
            req=Request(f'http://127.0.0.1:{port}'+route,data=None if body is None else json.dumps(body).encode('utf8'),headers={'X-Workbench-Token':token,'Content-Type':'application/json'})
            with urlopen(req,timeout=30) as response:return json.loads(response.read())
        assert api('/health')['version']=='0.5.0'
        assert api('/settings')['api_key_count']>0
        job=api('/run/start',{'mode':'write','limit':1,'ids':[mid]});print(json.dumps({'phase':'live relay writing started','materials':1,'maximum_inference_attempts':1}),flush=True)
        start=time.monotonic();next_notice=20
        while time.monotonic()-start<220:
            runs=api('/stats')['runs'];run=next(x for x in runs if x['id']==job['run_id'])
            if run['state'] not in ('running','pausing'):break
            if time.monotonic()-start>=next_notice:print(json.dumps({'phase':'waiting for relay response','elapsed_seconds':int(time.monotonic()-start)}),flush=True);next_notice+=20
            time.sleep(1)
        item=api('/materials/'+str(mid));results=api('/results')['rows'];attempts=list((folder/'data/runs'/job['run_id']).rglob('api-request-*.json'))
        report={'ok':run['state']=='completed' and item['state']=='written' and len(results)==1,'model':settings['api_model'],'api_base':settings['api_base'],'actual_inference_attempts':len(attempts),'configured_key_count':api('/settings')['api_key_count'],'material_state':item['state'],'published_chars':results[0]['char_count'] if results else None,'frames':results[0]['frame_count'] if results else None,'error':item.get('error',''),'scope':'One writing step using fixed test extraction, isolated fixture database; production library unchanged.'}
        (folder/'report.json').write_text(dumps(report),encoding='utf8');(ROOT/'build/relay-live-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False));assert report['ok'],report['error']
    finally:
        if process.poll() is None:subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        process.wait(timeout=20);process.stdout.close()
