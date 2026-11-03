"""Adapter for the user's ArticleBodyScraper file-mode executable."""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid
import zipfile

import openpyxl
from store import now,dumps,digest,content_key

DEFAULT_ENGINE='D:/BIGDATA/CODES/PyCharmFiles/Factorys/ArticleBodyScraper/dist_file_mode/正文抓取工具/正文抓取工具.exe'
TERMINAL={'ok','failed','no_text','skipped','duplicate','image_deleted'}

def run_limit(value):
    if isinstance(value,bool) or not str(value).strip().isdigit() or not 1<=int(value)<=10000:
        raise ValueError('单次处理条数需为1至10000的整数')
    return int(value)


def browser_workers(value):
    if isinstance(value,bool) or not str(value).strip().isdigit() or int(value) not in (1,2,4,8):
        raise ValueError('浏览器并发数仅支持1、2、4、8')
    return int(value)


class BodyFetcher:
    def __init__(self,store):
        self.store=store;self.lock=threading.RLock();self.active_id=None;self.parent_run=None
        self.thread=None;self.process=None;self.stop_event=threading.Event();self.drain_event=threading.Event();self.shutdown_event=threading.Event();self.dispatcher=None

    def start_dispatcher(self,worker):
        def dispatch():
            while not self.shutdown_event.wait(.5):
                try:
                    with worker.lock,self.lock:
                        if self.active_id or self.store.settings().get('body_queue_paused'):continue
                        with self.store.connect() as c:job=c.execute("SELECT id FROM body_jobs WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
                        if job:self._launch_queued(job['id'])
                except Exception as exc:
                    self.store.log('自动正文队列暂缓：'+str(exc),'body',level='error');self.shutdown_event.wait(5)
        self.dispatcher=threading.Thread(target=dispatch,daemon=True);self.dispatcher.start()

    def _launch_queued(self,jid):
        with self.store.connect() as c:
            job=dict(c.execute('SELECT * FROM body_jobs WHERE id=?',(jid,)).fetchone())
            pending=[r[0] for r in c.execute("SELECT material_id FROM body_items WHERE job_id=? AND status IN ('pending','running') ORDER BY material_id",(jid,))]
        limit=run_limit(self.store.settings().get('body_run_size',100))
        if len(pending)>limit:
            settings=json.loads(job['settings_json']);settings['body_run_size']=limit
            rows=self.select({'ids':pending,'limit':limit,'include_held':True})
            if not rows:
                with self.store.connect() as c:
                    c.execute("UPDATE body_items SET status='skipped',error='已补齐正文或素材已不存在',updated_at=? WHERE job_id=? AND status IN ('pending','running')",(now(),jid))
                    c.execute("UPDATE body_jobs SET state='completed',note='没有尚需抓取的素材',updated_at=? WHERE id=?",(now(),jid))
                self._counts(jid);self.store.save_settings({'body_queue_paused':True,'body_queue_pause_reason':'single_run_done'});return
            jid=self._new_job(rows,settings)
        with self.store.connect() as c:c.execute("UPDATE body_jobs SET state='running',updated_at=? WHERE id=?",(now(),jid))
        self.active_id=jid;self.parent_run=None;self.stop_event.clear();self.drain_event.clear()
        self.thread=threading.Thread(target=self._execute,args=(jid,),daemon=True);self.thread.start()

    def enqueue_import(self,ids):
        with self.lock:
            rows=[]
            for offset in range(0,len(ids),200):rows.extend(self.select({'ids':ids[offset:offset+200],'limit':200}))
            if not rows:return None
            settings=self.store.settings();limit=run_limit(settings.get('body_run_size',100));total=len(rows)
            rows=rows[:limit];jid=self._new_job(rows,settings,state='queued')
            if not self.active_id and settings.get('body_queue_pause_reason','')!='user':
                self.store.save_settings({'body_queue_paused':False,'body_queue_pause_reason':''})
            return {'job_id':jid,'total':len(rows),'remaining':total-len(rows),'state':'queued'}

    def continue_queue(self,payload=None):
        result=self.start(payload or {});result['message']=f'已开始单次抓取{result["total"]}条，完成后停止'
        return result

    def engine_info(self,settings=None):
        settings=settings or self.store.settings();p=Path(settings.get('body_tool_path') or DEFAULT_ENGINE)
        valid=p.is_file() and (p.parent/'_internal').is_dir()
        return {'path':str(p),'available':valid,'name':'ArticleBodyScraper · 文件模式','max_chars':int(settings.get('body_max_chars',800)),'workers':int(settings.get('body_workers',2)),'message':'已连接正文抓取工具' if valid else '未找到完整工具目录，请选择包含_internal的正文抓取工具.exe'}

    def select(self,payload):
        limit=run_limit(payload.get('limit',self.store.settings().get('body_run_size',100)))
        clauses=["deleted_at=\'\'","body=''","url<>''","state NOT IN ('routing','extracting','writing','fetching')"]
        held_states="'running','pausing'" if payload.get('include_held') else "'queued','running','pausing','paused','interrupted'"
        clauses.append("NOT EXISTS (SELECT 1 FROM body_items bi JOIN body_jobs bj ON bj.id=bi.job_id WHERE bi.material_id=materials.id AND bi.status IN ('pending','running') AND bj.state IN ("+held_states+"))")
        args=[]
        if not payload.get('include_no_text'):clauses.append("body_status NOT IN ('image','video','no_text','gone')")
        if payload.get('ids'):
            ids=list(dict.fromkeys(int(x) for x in payload['ids']));clauses.append('id IN ('+','.join('?' for _ in ids)+')');args.extend(ids)
        if payload.get('category'):clauses.append('category=?');args.append(payload['category'])
        if payload.get('scope_filters'):
            from material_catalog import query_parts
            scope_where,scope_args,*_=query_parts(payload['scope_filters'])
            clauses.append('('+scope_where.removeprefix(' WHERE ').replace('m.','materials.')+')');args.extend(scope_args)
        if payload.get('only_failed'):clauses.append("body_status IN ('failed','truncated')")
        with self.store.connect() as c:
            return [dict(r) for r in c.execute("SELECT id,title,url,category FROM materials WHERE "+' AND '.join(clauses)+" ORDER BY CASE WHEN body_status IN ('failed','truncated') THEN 1 ELSE 0 END,id LIMIT ?",args+[limit])]

    def _new_job(self,rows,settings,parent=None,state='running'):
        rows=rows[:run_limit(settings.get('body_run_size',100))]
        if not rows:raise ValueError('没有需要抓取的正文。已有正文、纯图/视频和已确认失效项默认跳过。')
        engine=self.engine_info(settings)
        if not engine['available']:raise ValueError(engine['message'])
        jid='body_'+uuid.uuid4().hex[:12]
        previous=set()
        with self.store.connect() as c:
            c.execute('INSERT INTO body_jobs(id,state,total,settings_json,parent_run,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(jid,state,len(rows),dumps(settings),parent or '',now(),now()))
            for r in rows:
                held=[x[0] for x in c.execute("SELECT bi.job_id FROM body_items bi JOIN body_jobs bj ON bj.id=bi.job_id WHERE bi.material_id=? AND bi.status IN ('pending','running') AND bj.state IN ('queued','paused','interrupted')",(r['id'],))]
                for old in held:
                    previous.add(old)
                    c.execute("UPDATE body_items SET status='skipped',error=?,updated_at=? WHERE job_id=? AND material_id=?",(f'未重复抓取：转入单次任务{jid}',now(),old,r['id']))
                c.execute('INSERT INTO body_items(job_id,material_id,title,url,source_hash,status,updated_at) VALUES(?,?,?,?,?,?,?)',(jid,r['id'],r['title'],r['url'],digest(r['title']+'\n'+r['url']),'pending',now()))
            for old in previous:
                remaining=c.execute("SELECT count(*) FROM body_items WHERE job_id=? AND status IN ('pending','running')",(old,)).fetchone()[0]
                c.execute('UPDATE body_jobs SET state=?,note=?,updated_at=? WHERE id=?',('paused' if remaining else 'completed',f'已将部分素材转入单次任务，尚余{remaining}条待执行',now(),old))
        for old in previous:self._counts(old)
        if state=='running':self.active_id=jid;self.parent_run=parent;self.stop_event.clear();self.drain_event.clear()
        self.store.log(f'正文单次任务：{len(rows)}条，使用指定ArticleBodyScraper工具，完成后停止。','body',parent or jid)
        return jid

    def start(self,payload):
        with self.lock:
            if self.active_id:raise ValueError('已有正文抓取任务正在运行，请暂停或等待结束')
            limit=run_limit(payload.get('limit',self.store.settings().get('body_run_size',100)))
            rows=self.select({**payload,'limit':limit,'include_held':True})
            if not rows:raise ValueError('没有需要抓取的正文，剩余素材已完成或不符合当前筛选条件')
            self.store.save_settings({'body_run_size':limit,'body_queue_paused':True,'body_queue_pause_reason':'single_run'})
            jid=self._new_job(rows,self.store.settings())
            self.thread=threading.Thread(target=self._execute,args=(jid,),daemon=True);self.thread.start()
            return {'run_id':jid,'job_id':jid,'kind':'body','total':len(rows)}

    def fetch_sync(self,ids,parent_run,stop_event):
        with self.lock:
            if self.active_id:raise ValueError('另一个正文任务正在运行，请先等待正文抓取完成')
            limit=min(len(ids),run_limit(self.store.settings().get('body_run_size',100)))
            rows=self.select({'ids':ids,'limit':limit});jid=self._new_job(rows,self.store.settings(),parent_run)
        self._execute(jid,stop_event)
        return jid

    def resume(self,jid,limit=None):
        with self.lock:
            if self.active_id:raise ValueError('已有正文任务正在运行')
            with self.store.connect() as c:
                job=c.execute('SELECT * FROM body_jobs WHERE id=?',(jid,)).fetchone()
                if not job or job['state'] not in ('queued','paused','interrupted'):raise ValueError('此任务不可续跑')
                if job['parent_run']:raise ValueError('此正文任务属于写文流程，请从处理队列续跑原任务')
                settings=json.loads(job['settings_json'])
                if not self.engine_info(settings)['available']:raise ValueError('原任务的抓取工具路径不可用')
                ids=[r[0] for r in c.execute("SELECT material_id FROM body_items WHERE job_id=? AND status IN ('pending','running') ORDER BY material_id",(jid,))]
            limit=run_limit(limit if limit is not None else self.store.settings().get('body_run_size',100))
            rows=self.select({'ids':ids,'limit':limit,'include_held':True}) if ids else []
            if not rows:raise ValueError('此任务没有尚需抓取的素材')
            self.store.save_settings({'body_run_size':limit,'body_queue_paused':True,'body_queue_pause_reason':'single_run'})
            settings['body_run_size']=limit;new_id=self._new_job(rows,settings)
            self.thread=threading.Thread(target=self._execute,args=(new_id,),daemon=True);self.thread.start()
            return {'ok':True,'job_id':new_id,'total':len(rows),'kind':'body'}

    def pause(self,parent=None):
        if parent is not None and self.parent_run!=parent:return {'ok':True,'message':'没有归属当前流程的正文任务'}
        self.store.save_settings({'body_queue_paused':True,'body_queue_pause_reason':'user'})
        self.stop_event.set()
        with self.store.connect() as c:
            if self.active_id:c.execute("UPDATE body_jobs SET state='pausing',note='正在停止，已入库正文保留',updated_at=? WHERE id=?",(now(),self.active_id))
        self.terminate()
        return {'ok':True,'message':'已暂停抓取，成功正文保留，续跑仅领取未完成项'}

    def drain(self):
        with self.lock:
            self.store.save_settings({'body_queue_paused':True,'body_queue_pause_reason':'user'})
            self.drain_event.set()
        return {'ok':True,'message':'当前抓取批次保存后停止'}

    def terminate(self):
        process=self.process
        if process is not None and process.poll() is None:
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            else:process.kill()

    def stats(self):
        with self.store.connect() as c:
            resumable=[dict(r) for r in c.execute("""SELECT j.id,j.state,j.total,j.done,j.note,j.parent_run,j.created_at,
                count(i.material_id) remaining,
                sum(CASE WHEN m.deleted_at='' AND m.body='' AND m.url<>''
                    AND m.state NOT IN ('routing','extracting','writing','fetching')
                    AND m.body_status NOT IN ('image','video','no_text','gone') THEN 1 ELSE 0 END) eligible_remaining
                FROM body_jobs j JOIN body_items i ON i.job_id=j.id AND i.status IN ('pending','running')
                LEFT JOIN materials m ON m.id=i.material_id
                WHERE j.state IN ('queued','paused','interrupted') AND coalesce(j.parent_run,'')=''
                GROUP BY j.id ORDER BY CASE WHEN j.state='queued' THEN 0 ELSE 1 END,j.created_at DESC,j.id DESC""")]
            remaining_by_job={r['id']:r['remaining'] for r in resumable}
            jobs=[dict(r) for r in c.execute("SELECT id,state,total,done,ok,failed,no_text,skipped,deduplicated,image_deleted,current_id,note,parent_run,created_at,updated_at,settings_json FROM body_jobs ORDER BY CASE WHEN state IN ('running','pausing') THEN 0 WHEN state='queued' THEN 1 ELSE 2 END,rowid DESC LIMIT 20")]
            for job in jobs:
                snapshot=json.loads(job.pop('settings_json'))
                job['max_chars']=int(snapshot.get('body_max_chars',0));job['workers']=int(snapshot.get('body_workers',2))
                job['remaining']=remaining_by_job.get(job['id'],0)
            counts={r[0]:r[1] for r in c.execute('SELECT body_status,count(*) FROM materials WHERE deleted_at=\'\' GROUP BY body_status')}
            ready=c.execute("SELECT count(*) FROM materials WHERE deleted_at=\'\' AND body<>''").fetchone()[0]
            missing=c.execute("SELECT count(*) FROM materials WHERE deleted_at=\'\' AND body='' AND body_status NOT IN ('image','video','no_text','gone')").fetchone()[0]
            qualified=c.execute("SELECT count(*) FROM materials WHERE deleted_at=\'\' AND qualification='qualified'").fetchone()[0]
            removed={r[0]:r[1] for r in c.execute('SELECT reason,count(*) FROM removed_materials GROUP BY reason')}
        settings=self.store.settings()
        return {'jobs':jobs,'resume_jobs':resumable,'counts':counts,'ready':ready,'qualified':qualified,'missing':missing,'removed':removed,'engine':self.engine_info(),'active_id':self.active_id,'queue_paused':settings.get('body_queue_paused',False),'queue_pause_reason':settings.get('body_queue_pause_reason',''),'run_size':settings.get('body_run_size',100)}

    def detail(self,jid):
        with self.store.connect() as c:
            row=c.execute('SELECT id,state,total,done,ok,failed,no_text,skipped,deduplicated,image_deleted,note,folder,created_at,updated_at,settings_json FROM body_jobs WHERE id=?',(jid,)).fetchone()
            if not row:raise ValueError('正文任务不存在')
            items=[dict(r) for r in c.execute('SELECT material_id,title,status,body_chars,media_type,error,kept_id,updated_at FROM body_items WHERE job_id=? ORDER BY material_id',(jid,))]
        job=dict(row);snapshot=json.loads(job.pop('settings_json'))
        job['max_chars']=int(snapshot.get('body_max_chars',0));job['workers']=int(snapshot.get('body_workers',2))
        return {'job':job,'items':items}

    def _counts(self,jid):
        with self.store.connect() as c:
            counts={r[0]:r[1] for r in c.execute('SELECT status,count(*) FROM body_items WHERE job_id=? GROUP BY status',(jid,))}
            done=sum(counts.get(k,0) for k in TERMINAL)
            c.execute('UPDATE body_jobs SET done=?,ok=?,failed=?,no_text=?,skipped=?,deduplicated=?,image_deleted=?,updated_at=? WHERE id=?',(done,counts.get('ok',0),counts.get('failed',0),counts.get('no_text',0),counts.get('skipped',0),counts.get('duplicate',0),counts.get('image_deleted',0),now(),jid))

    def _input(self,path,items):
        wb=openpyxl.Workbook();ws=wb.active;ws.title='正文任务'
        ws.append(['素材ID','标题','链接','正文','抓取类型','原始领域'])
        for row in items:
            ws.append([row['material_id'],row['title'],row['url'],'','',''])
            for col in [2,3,4,5,6]:ws.cell(ws.max_row,col).data_type='s'
        wb.save(path);wb.close()

    def ingest(self,jid,output,expected):
        try:
            wb=openpyxl.load_workbook(io.BytesIO(Path(output).read_bytes()),read_only=True,data_only=True);ws=wb.active;it=ws.iter_rows(values_only=True);headers=list(next(it,[]))
            rows=[dict(zip(headers,row)) for row in it];wb.close()
        except Exception:return 0  # The external tool saves XLSX in place; a mid-save snapshot is retried.
        required=['素材ID','标题','链接','正文','抓取类型']
        if any(x not in headers for x in required):raise ValueError('抓取结果缺少素材ID、链接或正文列，不能匹配入库')
        changed=0;seen=set()
        with self.store.connect() as c:
            for row in rows:
                try:mid=int(row.get('素材ID'))
                except (TypeError,ValueError):continue
                if mid in seen:raise ValueError('抓取结果出现重复素材ID，停止接收该结果文件')
                seen.add(mid)
                if mid not in expected:continue
                src=expected[mid]
                if str(row.get('链接') or '').strip()!=src['url'].strip() or str(row.get('标题') or '')!=src['title']:raise ValueError(f'素材#{mid}结果链接/标题与输入不一致，未按行序猜测匹配')
                item=c.execute('SELECT status FROM body_items WHERE job_id=? AND material_id=?',(jid,mid)).fetchone()
                if not item or item['status'] in TERMINAL:continue
                body=str(row.get('正文') or '').strip();media=str(row.get('抓取类型') or '').strip()
                if not body and media not in ('图','视频'):continue
                error='';status='ok';body_status='scraped';kept_id=None
                if media in ('图','视频') and (not body or body.startswith(('[抓取失败]','[无文字正文]'))):
                    status='no_text';body_status='image' if media=='图' else 'video';error='原链接为纯'+media+'，没有可抓取的文字正文';body=''
                elif body.startswith(('[抓取失败]','[无文字正文]')):
                    error=body;status='failed';body_status='gone' if '失效' in body or '不存在' in body or '删除' in body else 'failed'
                elif len(body)>=32767:
                    error='抓取结果达到Excel单元格上限，可能截断，未当作完整正文送去写文';status='failed';body_status='truncated'
                current=c.execute('SELECT * FROM materials WHERE id=?',(mid,)).fetchone()
                if not current or current['deleted_at']:status='skipped';error='素材不存在或已删除'
                elif digest(current['title']+'\n'+current['url'])!=src['source_hash'] or current['body']:
                    status='skipped';error='素材来源已变化或已补入正文，保留当前正文'
                elif media=='图' and status=='no_text':
                    s=self.store;s.remove_material_in(c,mid,'image_only');status='image_deleted';error='仅能取得图片，已从素材库删除'
                elif status=='ok':
                    c.execute("UPDATE materials SET body=?,content_key=?,body_status='scraped',state='pending',phase='',error='',body_fetch_error='',body_fetched_at=?,media_type=?,updated_at=? WHERE id=?",(body,content_key(current['title'],body),now(),media or '文章',now(),mid))
                    outcome=self.store.qualify_in(c,mid)
                    if outcome['action']=='duplicate':status='duplicate';kept_id=outcome['kept_id'];error=f'标题与正文相同，已合并到素材#{kept_id}'
                    elif outcome['action']!='qualified':
                        status='failed';error='标题或有效正文缺失，未通过合格素材验收'
                        c.execute("UPDATE materials SET state='needs_source',error=?,body_fetch_error=? WHERE id=?",(error,error,mid))
                else:
                    c.execute("UPDATE materials SET body_status=?,state=?,phase='',error=?,body_fetch_error=?,media_type=?,updated_at=? WHERE id=?",(body_status,'no_text' if status=='no_text' else 'needs_source',error,error,media,now(),mid))
                c.execute('UPDATE body_items SET status=?,body_chars=?,media_type=?,error=?,result_text=?,kept_id=?,updated_at=? WHERE job_id=? AND material_id=?',(status,len(body) if status in ('ok','duplicate') else 0,media,error,body,kept_id,now(),jid,mid))
                changed+=1
        if changed:self._counts(jid)
        return changed

    def _execute(self,jid,external_stop=None):
        s=self.store
        with s.connect() as c:job=dict(c.execute('SELECT * FROM body_jobs WHERE id=?',(jid,)).fetchone())
        settings=json.loads(job['settings_json']);engine=self.engine_info(settings)['path']
        folder=s.root/'body_fetch'/jid;folder.mkdir(parents=True,exist_ok=True)
        runtime=s.root/'body_engine_runtime';runtime.mkdir(exist_ok=True)
        profile=runtime/'正文抓取工具'/'browser_profile'
        profile.parent.mkdir(parents=True,exist_ok=True)
        with s.connect() as c:c.execute('UPDATE body_jobs SET folder=? WHERE id=?',(str(folder),jid))
        def stopped():return self.stop_event.is_set() or (external_stop is not None and external_stop.is_set())
        try:
            max_chars=int(settings.get('body_max_chars',0)) # Pre-0.3.2 snapshots used unlimited length.
            if not 0<=max_chars<=32766:raise ValueError('正文抓取字数上限超出0至32766范围')
            workers=browser_workers(settings.get('body_workers',2))
            chunk_size=max(1,min(200,int(settings.get('body_chunk_size',50))))
            while not stopped() and not self.drain_event.is_set():
                with s.connect() as c:items=[dict(r) for r in c.execute("SELECT * FROM body_items WHERE job_id=? AND status IN ('pending','running') ORDER BY material_id LIMIT ?",(jid,chunk_size))]
                if not items:break
                expected={x['material_id']:x for x in items}
                for x in items:
                    with s.connect() as c:
                        current=c.execute('SELECT body,state,deleted_at FROM materials WHERE id=?',(x['material_id'],)).fetchone()
                        if not current or current['deleted_at'] or current['body'] or current['state'] in ('routing','extracting','writing'):
                            c.execute("UPDATE body_items SET status='skipped',error='已有正文或正在写文，已跳过',updated_at=? WHERE job_id=? AND material_id=?",(now(),jid,x['material_id']))
                            expected.pop(x['material_id'],None)
                        else:
                            c.execute("UPDATE materials SET state='fetching',phase='fetching',updated_at=? WHERE id=?",(now(),x['material_id']))
                            c.execute("UPDATE body_items SET status='running',updated_at=? WHERE job_id=? AND material_id=?",(now(),jid,x['material_id']))
                if not expected:self._counts(jid);continue
                attempt=folder/('batch_'+uuid.uuid4().hex[:8]);attempt.mkdir()
                inp=attempt/'input.xlsx';out=attempt/'output.xlsx';self._input(inp,list(expected.values()))
                cmd=[engine,str(inp),'-o',str(out),'--url-col','链接','--body-col','正文','--cat-col','抓取类型','--max-chars',str(max_chars),'--only-failed','--no-title-dedupe','--workers',str(workers),'--wait',str(settings.get('body_wait',40)),'--delay',str(settings.get('body_delay',1.5)),'--rest-every',str(settings.get('body_rest_every',40)),'--rest-seconds',str(settings.get('body_rest_seconds',45)),'--profile',str(profile),'--channel',settings.get('body_channel','chrome')]
                if settings.get('body_headful'):cmd.append('--headful')
                (attempt/'command.json').write_text(dumps(cmd),encoding='utf8')
                env=os.environ.copy();env['LOCALAPPDATA']=str(runtime);env['PYINSTALLER_RESET_ENVIRONMENT']='1'
                with (attempt/'engine-output.log').open('wb') as log:
                    self.process=subprocess.Popen(cmd,cwd=attempt,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    start=time.monotonic();last_sig=None;last_note=''
                    while self.process.poll() is None:
                        if stopped():
                            if out.exists():self.ingest(jid,out,expected)
                            self.terminate();break
                        if time.monotonic()-start>int(settings.get('body_timeout',7200)):
                            self.terminate();raise TimeoutError('正文抓取超过本批最长等待时间，已完成正文保留')
                        if out.exists():
                            sig=(out.stat().st_mtime_ns,out.stat().st_size)
                            if sig!=last_sig:
                                try:self.ingest(jid,out,expected);last_sig=sig
                                except (OSError,zipfile.BadZipFile,EOFError):pass
                        tool_log=runtime/'正文抓取工具/run.log'
                        if tool_log.is_file():
                            with tool_log.open('rb') as handle:
                                handle.seek(max(0,tool_log.stat().st_size-5000));tail=handle.read().decode('utf8','replace')
                            lines=[x.strip() for x in tail.splitlines() if x.strip()]
                            note=next((x for x in reversed(lines) if not x.startswith(('http://','https://'))),'正在抓取正文')[:600]
                            matches=list(re.finditer(r'\[\d+/\d+\]\s*第(\d+)行',tail))
                            current=None
                            if matches:
                                i=int(matches[-1].group(1))-2
                                if 0<=i<len(expected):current=list(expected)[i]
                            if note!=last_note:
                                with s.connect() as c:
                                    c.execute('UPDATE body_jobs SET current_id=?,note=?,updated_at=? WHERE id=?',(current,note,now(),jid))
                                    if job['parent_run']:c.execute('UPDATE runs SET current_id=?,current_phase=?,updated_at=? WHERE id=?',(current,'正文抓取：'+note,now(),job['parent_run']))
                                last_note=note
                        time.sleep(.65)
                    self.process.wait(timeout=15)
                if out.exists():self.ingest(jid,out,expected)
                if stopped():break
                with s.connect() as c:
                    for mid in expected:
                        c.execute("UPDATE body_items SET status='failed',error='抓取工具未写回有效结果，可重试；执行记录已保留',updated_at=? WHERE job_id=? AND material_id=? AND status='running'",(now(),jid,mid))
                        c.execute("UPDATE materials SET state='needs_source',phase='',body_status='failed',body_fetch_error='抓取工具未写回有效结果，可重试',error='抓取工具未写回有效结果，可重试',updated_at=? WHERE id=? AND state='fetching' AND body=''",(now(),mid))
                self._counts(jid)
            with s.connect() as c:
                remaining=c.execute("SELECT count(*) FROM body_items WHERE job_id=? AND status IN ('pending','running')",(jid,)).fetchone()[0]
                c.execute("UPDATE body_jobs SET state=?,current_id=NULL,note=?,updated_at=? WHERE id=?",('paused' if remaining else 'completed','已暂停，已抓取正文保留' if remaining else '正文抓取结束',now(),jid))
        except Exception as exc:
            self.terminate()
            with s.connect() as c:c.execute("UPDATE body_jobs SET state='interrupted',note=?,updated_at=? WHERE id=?",(str(exc)[:1500],now(),jid))
            s.log('正文抓取中断：'+str(exc),'body',job['parent_run'] or jid,level='error')
            if external_stop is not None:external_stop.set()
        finally:
            with s.connect() as c:
                c.execute("UPDATE materials SET state='needs_source',phase='' WHERE state='fetching' AND id IN (SELECT material_id FROM body_items WHERE job_id=?)",(jid,))
                c.execute("UPDATE body_items SET status='pending' WHERE job_id=? AND status='running'",(jid,))
            self._counts(jid);self.process=None
            with self.lock:
                self.store.save_settings({'body_queue_paused':True,'body_queue_pause_reason':'user' if stopped() or self.drain_event.is_set() else 'single_run_done'})
                self.active_id=None;self.parent_run=None

