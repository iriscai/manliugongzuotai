from __future__ import annotations
import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit,parse_qs

from store import Store,dumps
from worker import Worker
from providers import protect,reference_settings
from relay_client import normalize_keys
from body_fetcher import BodyFetcher,browser_workers
from pipeline_catalog import concurrency,run_detail,writing_detail
from title_push import TitlePusher
from result_cleanup import clear_pushed
from writing_prompts import POLICY_VERSION
import workflow_management as management
from usage_budget import summary as usage_summary
import operations
from model_queue import ModelQueue,preview as queue_preview
from category_distribution import distribution
import history_cleanup

APP_VERSION='0.25.0'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',required=True);parser.add_argument('--resources',required=True);parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--relay-diagnostics',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.relay_diagnostics:
        import certifi,traceback
        from relay_client import httpx
        info={'ca_path':certifi.where(),'ca_exists':Path(certifi.where()).is_file(),'httpx':httpx.__version__}
        try:
            with httpx.Client(timeout=20) as client:
                info['client_init']='ok';info['anonymous_https_status']=client.get('https://api.yituohub.com/v1/models').status_code
        except Exception:info['traceback']=traceback.format_exc()
        print(json.dumps(info,ensure_ascii=False),flush=True);return
    store=Store(args.data,args.resources);body_fetcher=BodyFetcher(store);worker=Worker(store,body_fetcher);pusher=TitlePusher(store)
    from score_jobs import ScoreJobs,select_pending as select_pending_scores
    scorer=ScoreJobs(store,worker)
    model_queue=ModelQueue(store,worker);model_queue.start()
    (store.root/'runtime_state.json').write_text(dumps({'version':APP_VERSION,'writing_policy':POLICY_VERSION}),encoding='utf8')
    token=os.environ.get('COMIC_WORKBENCH_TOKEN','')
    if not token:raise RuntimeError('Missing local bridge token')
    body_fetcher.start_dispatcher(worker)
    pusher.start_dispatcher()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,obj):
            raw=dumps(obj).encode('utf8');self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
        def do_GET(self):self.handle_api('GET')
        def do_POST(self):self.handle_api('POST')
        def do_PUT(self):self.handle_api('PUT')
        def handle_api(self,method):
            if self.headers.get('X-Workbench-Token')!=token:return self.send(401,{'error':'未授权的本机请求'})
            try:
                parts=urlsplit(self.path);path=parts.path;q={k:v[0] for k,v in parse_qs(parts.query).items()}
                data={}
                if method!='GET':
                    n=int(self.headers.get('Content-Length',0))
                    if n>4*1024*1024:raise ValueError('请求内容过大')
                    data=json.loads(self.rfile.read(n) or b'{}')
                    if not isinstance(data,dict):raise ValueError('请求必须为对象')
                if model_queue.draining and method=='POST' and path in ('/run/start','/run/enqueue','/run/resume','/run/retry','/run/retry-seeds','/results/regenerate','/run/queue-resume','/body/start','/body/retry','/body/resume','/body/continue-queue','/results/score-start','/results/score-resume','/results/score-retry'):raise ValueError('正在保存当前步骤后退出，暂不接受新任务；重新打开工作台后可继续')
                if method=='GET' and path=='/health':out={'ok':True,'version':APP_VERSION,'import_dedup':'title_and_body','extraction_scheme':'adaptive_topics_v1','output_mode':'article','verification_policy':'direct_seed','writing_policy':POLICY_VERSION}
                elif method=='GET' and path=='/stats':out=store.stats();out['scoring']=scorer.list()
                elif method=='GET' and path=='/stats/distribution':out=distribution(store,q)
                elif method=='GET' and path=='/run/detail':out=run_detail(store,q)
                elif method=='GET' and path=='/run/writing':out=writing_detail(store,q)
                elif method=='GET' and path=='/run/history':out=operations.history(store,q)
                elif method=='POST' and path=='/run/cleanup-preview':out=history_cleanup.preview(store,data)
                elif method=='POST' and path=='/run/cleanup-history':
                    with worker.lock,body_fetcher.lock,model_queue.lock,pusher.lock:out=history_cleanup.apply(store,data)
                elif method=='GET' and path=='/run/info':out=operations.run_info(store,q['id'])
                elif method=='GET' and path=='/run/model-queue':out=model_queue.stats()
                elif method=='GET' and path=='/run/model-queue/detail':out=model_queue.detail(q['id'])
                elif method=='GET' and path=='/run/activity':out={'model_active':bool(worker.thread and worker.thread.is_alive()),'body_active':bool(body_fetcher.active_id),'draining':model_queue.draining}
                elif method=='POST' and path=='/run/drain':
                    model_queue.drain();worker.pause();body_fetcher.drain();out={'ok':True}
                elif method=='POST' and path=='/run/preview':out=worker.start({**data,'preview':True})
                elif method=='POST' and path=='/run/queue-preview':out=queue_preview(store,data)
                elif method=='POST' and path=='/run/enqueue':
                    out=model_queue.enqueue(data)
                    with store.connect() as c:ids=[r[0] for r in c.execute('SELECT material_id FROM model_queue_items WHERE job_id=?',(out['job_id'],))]
                    try:out['body_job']=body_fetcher.enqueue_import(ids)
                    except Exception as e:out['body_error']=str(e);store.log('队列已保存，正文抓取未启动：'+str(e),'body',level='warning')
                elif method=='POST' and path=='/run/queue-pause':out=model_queue.pause(data['id'])
                elif method=='POST' and path=='/run/queue-resume':out=model_queue.resume(data['id'],data)
                elif method=='POST' and path=='/materials/workflow-summary':out=__import__('usability').workflow_summary(store,data.get('filters',{}))
                elif method=='GET' and path=='/materials/import-summary':out=__import__('usability').import_summary(store,q['id'])
                elif method=='GET' and path=='/materials/pending-modes':out=__import__('usability').pending_modes(store,q['id'])
                elif method=='POST' and path=='/body/scoped-preview':
                    with body_fetcher.lock:out=__import__('usability').body_preview(store,body_fetcher,data)
                elif method=='POST' and path=='/body/scoped-start':
                    if model_queue.draining:raise ValueError('正在保存后退出，暂不接受新任务')
                    with worker.lock,body_fetcher.lock:out=__import__('usability').body_start(store,body_fetcher,data)
                elif method=='POST' and path=='/results/scoped-push-preview':
                    with pusher.lock:out=__import__('usability').push_preview(store,data)
                elif method=='POST' and path=='/results/scoped-push-submit':
                    if model_queue.draining:raise ValueError('正在保存后退出，暂不接受新投递')
                    with worker.lock,pusher.lock:out=__import__('usability').push_submit(store,pusher,data)
                elif method=='GET' and path=='/results/scoped-push-progress':out=__import__('usability').push_progress(store,q['id'])
                elif method=='GET' and path=='/results/push-summary':out=__import__('usability').push_summary(store,pusher)
                elif method=='GET' and path=='/materials':out=store.list_materials(q)
                elif method=='POST' and path in ('/materials/delete-preview','/materials/delete','/materials/restore','/results/delete-preview','/results/delete','/results/restore'):
                    import library_deletion
                    data['kind']='materials' if path.startswith('/materials/') else 'results'
                    if not path.endswith('delete-preview'):data['action']='restore' if path.endswith('/restore') else 'delete'
                    with worker.lock,body_fetcher.lock,pusher.lock:
                        out=library_deletion.plan(store,data) if path.endswith('delete-preview') else library_deletion.apply(store,data)
                elif method=='GET' and path=='/materials/options':
                    with store.connect() as c:out=__import__('material_catalog').options(c,q.get('visibility','active'))
                elif method=='GET' and path.startswith('/materials/'):out=store.material(int(path.split('/')[-1]))
                elif method=='GET' and path=='/results':pusher.sync();out=store.list_results(q)
                elif method=='GET' and path=='/results/options':out=management.options(store)
                elif method=='GET' and path=='/results/push-target':out=__import__('push_targets').status(store)
                elif method=='POST' and path=='/results/push-target':
                    with pusher.lock:out=__import__('push_targets').save(store,data);pusher.refresh_project()
                elif method=='GET' and path=='/results/push-history':out=__import__('push_delivery').history(pusher,q)
                elif method=='GET' and path=='/results/push-detail':out=__import__('push_delivery').detail(pusher,q['id'])
                elif method=='POST' and path=='/results/push-sync':pusher.sync(True);out={'ok':True}
                elif method=='POST' and path=='/results/push-retry':
                    with pusher.lock:out=__import__('push_delivery').retry(pusher,data.get('id'))
                elif method=='POST' and path=='/results/push-replay':
                    with pusher.lock:out=__import__('push_delivery').replay(pusher,data['id'])
                elif method=='GET' and path=='/results/push-mapping':out=__import__('title_push').category_mapping(store)
                elif method=='POST' and path=='/results/push-mapping':
                    with worker.lock,pusher.lock:out=__import__('title_push').save_mapping(store,data)
                elif method=='POST' and path=='/results/score':
                    with worker.lock,pusher.lock:out=__import__('article_quality').set_score(store,data)
                elif method=='POST' and path=='/results/score-select':out=select_pending_scores(store,data.get('filters',{}))
                elif method=='POST' and path=='/results/score-preview':out=scorer.preview(data)
                elif method=='POST' and path=='/results/score-start':out=scorer.start(data['id'])
                elif method=='GET' and path=='/results/score-jobs':out=scorer.list()
                elif method=='GET' and path=='/results/score-job':out=scorer.detail(q['id'])
                elif method=='POST' and path=='/results/score-pause':out=scorer.pause(data['id'])
                elif method=='POST' and path=='/results/score-resume':out=scorer.resume(data['id'])
                elif method=='POST' and path=='/results/score-retry':out=scorer.resume(data['id'],True)
                elif method=='GET' and path.startswith('/results/detail/'):
                    pusher.sync();out=management.detail(store,int(path.split('/')[-1]))
                elif method=='GET' and path=='/run/usage':
                    with store.connect() as c:out=usage_summary(c,q.get('id'))
                elif method=='POST' and path=='/results/select':out={'ids':management.selected_ids(store,data)}
                elif method=='POST' and path=='/results/selection':out=operations.selection(store,data)
                elif method=='POST' and path=='/results/regenerate':out=worker.regenerate(data)
                elif method=='POST' and path=='/results/edit':
                    with worker.lock:out=management.edit(store,data)
                elif method=='POST' and path=='/results/restore-version':
                    with worker.lock:out=management.restore_version(store,data)
                elif method=='POST' and path=='/results/restore-cleared':
                    with worker.lock:out=management.restore_cleared(store,data)
                elif method=='POST' and path=='/results/push':
                    with worker.lock:out=pusher.push(data.get('ids'))
                elif method=='POST' and path=='/results/clear-pushed':
                    with pusher.lock:
                        if data.get('expected_target') and data['expected_target']!=__import__('usability').push_context(store)[0]:raise ValueError('推送目标已变化，请重新核对归档范围')
                        pusher.sync();out=clear_pushed(store)
                elif method=='GET' and path=='/prompts':out=store.prompts(q.get('category'))
                elif method=='POST' and path=='/prompts/status':
                    from prompt_status import set_enabled
                    with worker.lock:out=set_enabled(store,data)
                elif method=='PUT' and path=='/prompts':out=store.save_prompt(data)
                elif method=='GET' and path=='/settings':
                    out=store.settings();status=worker.provider.status(out);out.pop('api_key_encrypted',None);out.update(status)
                elif method=='POST' and path=='/settings':
                    allowed={'provider','codex_path','model','reasoning','api_base','api_model','api_protocol','batch_size','run_size','extract_variant','write_variant','allowed_categories','timeout','requirements','body_tool_path','body_workers','body_run_size','body_chunk_size','body_wait','body_delay','body_rest_every','body_rest_seconds','body_channel','body_headful','body_timeout','body_max_chars'}
                    values={k:v for k,v in data.items() if k in allowed}
                    if 'extraction_mode' in data:
                        from extraction_modes import normalize
                        values['extraction_mode']=normalize(data['extraction_mode'])
                    for key in ['funny_extract_variant','funny_write_variant']:
                        if key in data:
                            from funny_rules import VARIANTS
                            if data[key] not in (*VARIANTS,'follow'):raise ValueError('搞笑赛道方案需为A至J或跟随全局')
                            values[key]=data[key]
                    for key in ['military_extract_variant','military_write_variant']:
                        if key in data:
                            if data[key] not in ('A','B','C','follow'):raise ValueError('军事方案需为A、B、C或跟随全局')
                            values[key]=data[key]
                    for key in ['process_workers','write_workers']:
                        if key in data:values[key]=concurrency(data[key])
                    if any(k in data for k in ['task_request_limit','task_article_limit','task_token_limit']):
                        parsed=operations.budget({k:data.get('task_'+k,store.settings().get('task_'+k,0)) for k in ['request_limit','article_limit','token_limit']})
                        values.update({'task_'+k:v for k,v in parsed.items()})
                    for key,lo,hi in [('global_max_concurrency',1,64),('daily_request_limit',0,1000000),('daily_token_limit',0,1000000000)]:
                        if key in data:
                            if type(data[key]) is bool or not str(data[key]).isdigit() or not lo<=int(data[key])<=hi:raise ValueError(key+'超出允许范围')
                            values[key]=int(data[key])
                    for key,low,high in [('api_timeout',30,3600),('api_retry_count',0,3)]:
                        if key in data:
                            if isinstance(data[key],bool) or not str(data[key]).isdigit():raise ValueError(key+'需为整数')
                            value=int(data[key])
                            if not low<=value<=high:raise ValueError(f'{key}需在{low}至{high}之间')
                            values[key]=value
                    if 'api_temperature' in data:
                        value=float(data['api_temperature'])
                        if not 0<=value<=2:raise ValueError('Temperature需在0至2之间')
                        values['api_temperature']=value
                    if 'api_skip_tls_verify' in data:
                        if type(data['api_skip_tls_verify']) is not bool:raise ValueError('证书兼容选项需为布尔值')
                        values['api_skip_tls_verify']=data['api_skip_tls_verify']
                    if 'body_max_chars' in values:
                        value=values['body_max_chars']
                        if isinstance(value,bool) or not str(value).strip().isdigit():raise ValueError('正文抓取字数上限需为0至32766的整数，0表示不限')
                        values['body_max_chars']=int(value)
                        if not 0<=values['body_max_chars']<=32766:raise ValueError('正文抓取字数上限需为0至32766的整数，0表示不限')
                    if 'body_workers' in values:values['body_workers']=browser_workers(values['body_workers'])
                    for key,lo,hi in [('batch_size',1,50),('run_size',1,1000),('timeout',60,3600),('body_run_size',1,10000),('body_chunk_size',1,200),('body_wait',10,180),('body_rest_every',0,500),('body_rest_seconds',0,3600),('body_timeout',60,43200)]:
                        if key in values:
                            values[key]=int(values[key])
                            if not lo<=values[key]<=hi:raise ValueError(f'{key}需在{lo}至{hi}之间')
                    if values.get('provider','codex') not in ('codex','api'):raise ValueError('未知执行方式')
                    if values.get('api_protocol','chat') not in ('chat','responses'):raise ValueError('未知API协议')
                    if values.get('body_channel','chrome') not in ('chrome','msedge'):raise ValueError('浏览器仅支持Chrome或Edge')
                    if 'body_headful' in values and type(values['body_headful']) is not bool:raise ValueError('显示浏览器选项需为布尔值')
                    if 'body_delay' in values:
                        values['body_delay']=float(values['body_delay'])
                        if not 0<=values['body_delay']<=60:raise ValueError('抓取间隔需在0至60秒之间')
                    for key in ['extract_variant','write_variant']:
                        if key in values and values[key] not in ('A','B','alternate'):raise ValueError('规则版本仅支持A、B或交替')
                    raw_keys=data.get('api_keys',data.get('api_key'))
                    if raw_keys:
                        if not isinstance(raw_keys,(str,list)) or isinstance(raw_keys,list) and not all(isinstance(x,str) for x in raw_keys):raise ValueError('API Keys需为多行文本或文本列表')
                        keys=normalize_keys(raw_keys)
                        if keys:values['api_key_encrypted']=protect('\n'.join(keys))
                    if data.get('clear_api_key'):values['api_key_encrypted']=''
                    store.save_settings(values);out={'ok':True}
                elif method=='POST' and path=='/provider/check':out=worker.provider.auth_status(store.settings()) if store.settings()['provider']=='codex' else worker.provider.api_test(store.settings())
                elif method=='POST' and path=='/provider/models':
                    out=worker.provider.api_models(store.settings());store.save_settings({'api_model_options':out['models']})
                elif method=='POST' and path=='/provider/import-reference':
                    values=reference_settings();store.save_settings(values);safe=worker.provider.status(values)
                    out={'ok':True,'message':'已导入参考项目配置，API Keys已加密保存','api_base':values['api_base'],'api_model':values['api_model'],'key_count':safe['api_key_count']}
                elif method=='POST' and path=='/import/preview':out=store.preview_import(data['path'],data.get('sheet'))
                elif method=='POST' and path=='/import':
                    with worker.lock:
                        out=store.import_file(data)
                        try:out['auto_body']=body_fetcher.enqueue_import(out['intake_ids'])
                        except Exception as exc:out['auto_body_error']=str(exc)
                        out.pop('intake_ids',None)
                elif method=='POST' and path=='/materials/body':
                    with worker.lock:out=store.save_body(int(data['id']),data['body'])
                elif method=='GET' and path=='/body/stats':out=body_fetcher.stats()
                elif method=='GET' and path.startswith('/body/jobs/'):out=body_fetcher.detail(path.split('/')[-1])
                elif method=='POST' and path=='/body/check':out=body_fetcher.engine_info()
                elif method=='POST' and path in ('/body/start','/body/retry'):
                    with worker.lock:
                        if path=='/body/retry':
                            with store.connect() as c:data['ids']=[r[0] for r in c.execute("SELECT material_id FROM body_items WHERE job_id=? AND status='failed'",(data['id'],))]
                            if not data['ids']:raise ValueError('没有失败项可重试')
                            data.setdefault('limit',store.settings().get('body_run_size',100))
                        out=body_fetcher.start(data)
                elif method=='POST' and path=='/body/pause':out=worker.pause() if body_fetcher.parent_run else body_fetcher.pause()
                elif method=='POST' and path=='/body/continue-queue':
                    with worker.lock:
                        out=body_fetcher.continue_queue(data)
                elif method=='POST' and path=='/body/resume':
                    with worker.lock:
                        out=body_fetcher.resume(data['id'],data.get('limit'))
                elif method=='POST' and path=='/run/start':
                    with worker.lock:
                        if data.get('mode')=='fetch':
                            out=body_fetcher.start(data)
                        else:out=worker.start(data)
                elif method=='POST' and path=='/run/pause':
                    with worker.lock,model_queue.lock:
                        rid=data.get('id') or worker.current_run
                        if rid is not None and not isinstance(rid,str):raise ValueError('任务ID无效')
                        with store.connect() as c:job=c.execute("SELECT id FROM model_queue WHERE run_id=? AND state='running'",(rid or '',)).fetchone()
                        if job:model_queue.pause(job['id']);out={'ok':True,'message':'已暂停独立队列，等待在途响应保存，不再领取新素材'}
                        else:out=worker.pause(rid)
                elif method=='POST' and path=='/run/resume':out=worker.resume(data['id'],data)
                elif method=='POST' and path=='/run/retry':out=worker.retry(data['id'])
                elif method=='POST' and path=='/run/retry-seeds':out=worker.retry_seeds(data.get('ids',[]))
                elif method=='POST' and path=='/export':out=store.export(data['path'],data.get('kind','results'),data.get('ids'),data.get('filters'))
                else:return self.send(404,{'error':'接口不存在'})
                return self.send(200,out)
            except (ValueError,KeyError,TypeError) as exc:return self.send(400,{'error':str(exc)})
            except Exception as exc:return self.send(500,{'error':str(exc)[:1500]})
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(json.dumps({'ready':True,'port':server.server_address[1]}),flush=True)
    try:server.serve_forever()
    finally:model_queue.stop.set();worker.pause_flag.set();body_fetcher.shutdown_event.set();body_fetcher.stop_event.set();body_fetcher.terminate();worker.provider.terminate();server.server_close()


if __name__=='__main__':main()
