"""A single authorized live test; production material and rule data stay read-only."""
import hashlib,json,os,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,dumps

INSTALLED=Path('C:/Users/74319/Desktop/漫画文章工作台_V0.3.0')
SOURCE_ID=189
FOLDER=Path('C:/Users/74319/Desktop')/('自适应提炼测试_素材189_'+uuid.uuid4().hex[:6]);FOLDER.mkdir()
with sqlite3.connect((INSTALLED/'data/workbench.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
    c.row_factory=sqlite3.Row
    original=dict(c.execute('SELECT * FROM materials WHERE id=?',(SOURCE_ID,)).fetchone())
    assert original['qualification']=='qualified' and original['body']
    settings={r['key']:json.loads(r['value']) for r in c.execute('SELECT key,value FROM settings')}
    prompts=[dict(r) for r in c.execute('SELECT * FROM prompts')]
assert settings['provider']=='api','This live test requires the currently selected relay API.'
allowed=settings.get('allowed_categories') or [x['name'] for x in json.loads((INSTALLED/'resources/app/resources/categories.json').read_text(encoding='utf8'))['categories']]
max_attempts=1+len(allowed)
baseline=hashlib.sha256(dumps(original).encode('utf8')).hexdigest()
store=Store(FOLDER/'隔离数据',INSTALLED/'resources/app/resources')
# Copy only existing settings and rule records. Never print decrypted keys or request headers.
store.save_settings({**settings,'api_retry_count':0,'run_size':1})
with store.connect() as c:
    for row in prompts:c.execute('UPDATE prompts SET name=?,content=?,revision=? WHERE category=? AND kind=? AND variant=?',(row['name'],row['content'],row['revision'],row['category'],row['kind'],row['variant']))
source_path=FOLDER/'测试输入.jsonl'
source_path.write_text(dumps({'标题':original['title'],'正文':original['body'],'分类':original['category'],'链接':original['url']}),encoding='utf8')
mid=store.import_file({'path':str(source_path)})['intake_ids'][0]
token=uuid.uuid4().hex;env=os.environ.copy();env['COMIC_WORKBENCH_TOKEN']=token
report={'source_material_id':SOURCE_ID,'model':settings['api_model'],'api_base':settings['api_base'],'output_folder':str(FOLDER),'maximum_api_attempts':max_attempts,'automatic_retries':0,'run_id':None}
(FOLDER/'测试清单.json').write_text(dumps(report),encoding='utf8')
run=None;item=None;results=[];failure=''
with (FOLDER/'后端日志.txt').open('wb') as log:
    process=subprocess.Popen([str(INSTALLED/'resources/app/backend/comic-backend.exe'),'--data',str(store.root),'--resources',str(INSTALLED/'resources/app/resources')],env=env,stdout=subprocess.PIPE,stderr=log,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        ready=json.loads(process.stdout.readline());port=ready['port']
        def api(route,body=None):
            req=Request(f'http://127.0.0.1:{port}'+route,data=None if body is None else dumps(body).encode('utf8'),headers={'Content-Type':'application/json','X-Workbench-Token':token})
            with urlopen(req,timeout=30) as response:return json.loads(response.read())
        assert api('/health')['extraction_scheme']=='adaptive_topics_v1'
        job=api('/run/start',{'mode':'both','limit':1,'ids':[mid]});report['run_id']=job['run_id']
        (FOLDER/'测试清单.json').write_text(dumps(report),encoding='utf8')
        print(dumps({'phase':'live_test_started','source_material_id':SOURCE_ID,'model':settings['api_model'],'output_folder':str(FOLDER),'maximum_api_attempts':max_attempts}),flush=True)
        start=time.monotonic();last_notice=-30
        while time.monotonic()-start<680:
            stats=api('/stats');run=next(r for r in stats['runs'] if r['id']==job['run_id'])
            if run['state'] not in ('running','pausing'):break
            elapsed=int(time.monotonic()-start)
            if elapsed-last_notice>=25:
                p=run['progress'];print(dumps({'phase':run['current_phase'],'elapsed_seconds':elapsed,'extractions':p['extracted'],'written':p['written'],'verification_blocked':p['needs_review'],'writing':p['writing']}),flush=True);last_notice=elapsed
            time.sleep(1)
        else:raise TimeoutError('Live test exceeded its bounded execution time')
        item=api('/materials/'+str(mid));results=api('/results')['rows']
    except Exception as exc:failure=str(exc)
    finally:
        if process.poll() is None:subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        process.wait(timeout=25);process.stdout.close()

attempts=list((store.root/'runs').rglob('api-request-*.json'))
extract_attempts=[p for p in attempts if '-adaptive-extract-' in str(p.parent)]
write_attempts=[p for p in attempts if '-write-' in str(p.parent)]
assert len(attempts)<=max_attempts,'Exceeded the promised maximum API attempts'
with sqlite3.connect((INSTALLED/'data/workbench.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
    c.row_factory=sqlite3.Row;after=dict(c.execute('SELECT * FROM materials WHERE id=?',(SOURCE_ID,)).fetchone())
unchanged=hashlib.sha256(dumps(after).encode('utf8')).hexdigest()==baseline
if item is None:
    with store.connect() as c:
        row=c.execute('SELECT * FROM materials WHERE id=?',(mid,)).fetchone();item=dict(row) if row else {}
        item['extractions']=[dict(r) for r in c.execute('SELECT * FROM extractions WHERE material_id=? ORDER BY id',(mid,))]
        results=[dict(r) for r in c.execute('SELECT * FROM results WHERE current=1')]
extractions=[{**row,'data':json.loads(row['data_json'])} for row in item.get('extractions',[]) if row.get('current')]
decoded=[{**row,'data':json.loads(row['data_json'])} for row in results]
topics=[]
for row in extractions:
    data=row['data'];matched=next((r for r in decoded if r['extraction_id']==row['id']),None)
    topics.append({'category':row['category'],'topic':data.get('topic') or row['angle'],'elements':data.get('elements',[]),'needs_verification':data.get('needs_verification',[]),'written':bool(matched),'char_count':matched['char_count'] if matched else None,'frame_count':matched['frame_count'] if matched else None})
report.update({'run_state':run['state'] if run else 'error','error':failure or item.get('error',''),'actual_api_attempts':len(attempts),'extraction_api_attempts':len(extract_attempts),'writing_api_attempts':len(write_attempts),'extraction_count':len(extractions),'written_count':len(decoded),'topics':topics,'production_material_unchanged':unchanged,'model_selected_n':len(extractions),'eligible_for_writing':sum(not x['data'].get('needs_verification') for x in extractions),'writing_stage_exercised':len(write_attempts)>0,'adaptive_extraction_pass':len(extract_attempts)==1 and run is not None and run.get('errors',1)==0,'earlier_fixed_count_test_requests':1,'combined_api_attempts':len(attempts)+1})
assert unchanged,'Production material changed during isolated test'
(FOLDER/'测试结果.json').write_text(json.dumps({'report':report,'source':{k:original[k] for k in ['id','title','body','category','url']},'extractions':extractions,'articles':decoded},ensure_ascii=False,indent=2),encoding='utf8')
lines=['# 单次提炼与逐主题生文测试','',f'素材库编号：{SOURCE_ID}',f'实际模型：{settings["api_model"]}',f'实际调用：提炼{len(extract_attempts)}次，生文{len(write_attempts)}次，共{len(attempts)}次。',f'产出：{len(extractions)}组选题，{len(decoded)}篇文案。',f'前一版固定数量测试：1次提炼被引用校验拦下，未生文。',f'正式素材保持原样：{"是" if unchanged else "否"}。','','| 主题 | 所属赛道 | 写文状态 |','| --- | --- | --- |']
for t in topics:lines.append('| '+t['topic'].replace('|','／')+' | '+t['category']+' | '+('已生成' if t['written'] else '待核实暂缓' if t['needs_verification'] else '未完成')+' |')
if report['error']:lines+=['','执行说明：'+report['error']]
for i,row in enumerate(extractions,1):
    data=row['data'];lines+=['',f'## 选题{i}：{data.get("topic") or row["angle"]}',f'所属赛道：{row["category"]}','','提炼元素：']
    for element in data.get('elements',[]):lines.append('- '+element['name']+'：'+element['content'])
    if data.get('needs_verification'):lines+=['','待核实事项：']+['- '+v for v in data['needs_verification']]
    matched=next((r for r in decoded if r['extraction_id']==row['id']),None)
    if matched:
        article=matched['data'];lines+=['','生成标题：'+article['title'],'',article['short_text'],'',f'发布文字：{matched["char_count"]}/300字符；分镜：{matched["frame_count"]}/10张（未生成图片）。']
        filename=FOLDER/f'文案{i}_{row["category"]}.md'
        filename.write_text('# '+article['title']+'\n\n主题：'+(data.get('topic') or row['angle'])+'\n\n所属赛道：'+row['category']+'\n\n'+article['short_text']+'\n\n## 分镜\n\n'+'\n\n'.join('第'+str(f['number'])+'张：'+f['scene']+'\n\n'+f.get('caption','') for f in article['frames']),encoding='utf8')
(FOLDER/'测试报告.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
(ROOT/'build/adaptive-live-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(dumps({'phase':'live_test_complete',**report}),flush=True)
