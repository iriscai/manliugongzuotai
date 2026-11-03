from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import json
import threading

from store import now,dumps
from providers import ProviderLimit
from pipeline_catalog import concurrency,run_summary
from schemas import WRITE,ARTICLE
from article_flow import normalize_article

class StepPaused(Exception):pass

class ParallelExecution:
    def run_parallel(self,rid):
        s=self.store;self.halt_reason=''
        try:
            with s.connect() as c:
                run=dict(c.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone())
                all_items=c.execute('SELECT material_id,state FROM run_items WHERE run_id=? ORDER BY ordinal,material_id',(rid,)).fetchall()
            snapshot=json.loads(run['snapshot_json']);settings=snapshot['settings']
            processing=concurrency(settings.get('process_workers',1));writing=concurrency(settings.get('write_workers',1))
            self.processing_gate=threading.BoundedSemaphore(processing)
            self.global_gate=threading.BoundedSemaphore(max(1,min(64,int(settings.get('global_max_concurrency',16)))))
            items=iter((index,row['material_id']) for index,row in enumerate(all_items) if row['state']=='queued')
            s.log(f'本轮并发：分类提炼{processing}路，写文{writing}路；每条素材按依赖顺序执行。','queue',rid)
            with ThreadPoolExecutor(max_workers=writing,thread_name_prefix='comic-write') as writers,ThreadPoolExecutor(max_workers=processing,thread_name_prefix='comic-material') as processors:
                self.write_pool=writers;pending=set();exhausted=False
                while pending or not exhausted:
                    while not exhausted and not self.pause_flag.is_set() and len(pending)<processing:
                        try:index,mid=next(items)
                        except StopIteration:exhausted=True;break
                        pending.add(processors.submit(self._process_item,mid,rid,run['mode'],snapshot,index))
                    if not pending:break
                    done,pending=wait(pending,timeout=.2,return_when=FIRST_COMPLETED)
                    for future in done:future.result()
                    if self.pause_flag.is_set():exhausted=True
            with s.connect() as c:
                summary=run_summary(c,rid)
                remaining=c.execute("SELECT count(*) FROM run_items WHERE run_id=? AND state='queued'",(rid,)).fetchone()[0]
                state='blocked' if self.halt_reason else 'paused' if remaining else 'completed'
                if self.halt_reason:note=self.halt_reason
                elif remaining:note='已暂停，已返回步骤均已保存，可续跑'
                else:note=f'本轮结束：新生成{summary["write_completed"]}篇，复用{summary["reused"]}篇，写文失败{summary["write_failed"]}篇，剩余{summary["remaining"]}份'
                c.execute('UPDATE runs SET state=?,current_id=NULL,current_phase=?,updated_at=? WHERE id=?',(state,note,now(),rid))
                from pipeline_catalog import freeze_summary
                freeze_summary(c,rid)
            s.log(note,'finish',rid,level='warning' if self.halt_reason else 'info')
        except Exception as exc:
            with s.connect() as c:
                c.execute("UPDATE runs SET state='interrupted',current_phase=?,updated_at=? WHERE id=?",(str(exc)[:500],now(),rid))
                c.execute("UPDATE run_items SET state='queued',phase='' WHERE run_id=? AND state='running'",(rid,))
                c.execute("UPDATE run_writes SET state='queued' WHERE run_id=? AND state='writing'",(rid,))
            s.log(str(exc),'error',rid,level='error')
        finally:
            self.write_pool=None;self.processing_gate=None;self.global_gate=None;self.current_run=None

    def _recount_run(self,c,rid):
        c.execute("UPDATE runs SET done=(SELECT count(*) FROM run_items WHERE run_id=? AND state IN ('completed','skipped','needs_review')),errors=(SELECT count(*) FROM run_items WHERE run_id=? AND state='failed'),updated_at=? WHERE id=?",(rid,rid,now(),rid))

    def _process_item(self,mid,rid,mode,snapshot,index):
        s=self.store
        if self.pause_flag.is_set():return
        with s.connect() as c:c.execute("UPDATE run_items SET state='running',phase='preparing',error='' WHERE run_id=? AND material_id=?",(rid,mid))
        try:
            if self.pause_flag.is_set():raise StepPaused()
            if mode=='fetch':raise ValueError('旧版正文任务请从“正文抓取”页面领取')
            state=self.process(mid,rid,mode,snapshot,index) if self.qualified(mid) else 'skipped'
            with s.connect() as c:
                deleted=c.execute("SELECT 1 FROM materials WHERE id=? AND deleted_at<>''",(mid,)).fetchone()
                if deleted:c.execute("UPDATE run_writes SET state='skipped',error='素材已删除，跳过处理',updated_at=? WHERE run_id=? AND material_id=? AND state IN ('queued','writing','extracted','failed')",(now(),rid,mid))
                material=c.execute('SELECT error FROM materials WHERE id=?',(mid,)).fetchone()
                message=material[0] if material and state=='needs_review' else ''
                c.execute("UPDATE run_items SET state=?,phase='',error=? WHERE run_id=? AND material_id=?",(state,message,rid,mid));self._recount_run(c,rid)
        except (StepPaused,ProviderLimit) as exc:
            if isinstance(exc,ProviderLimit):
                self.halt_for_limit(rid,exc)
            with s.connect() as c:
                has=c.execute('SELECT count(*) FROM extractions WHERE material_id=? AND current=1',(mid,)).fetchone()[0]
                c.execute("UPDATE run_items SET state='queued',phase='',error=? WHERE run_id=? AND material_id=?",(str(exc),rid,mid))
                c.execute("UPDATE materials SET state=?,phase='',updated_at=? WHERE id=?",('extracted' if has else 'pending',now(),mid));self._recount_run(c,rid)
        except Exception as exc:
            message=str(exc)[:1800]
            with s.connect() as c:
                c.execute("UPDATE run_items SET state='failed',phase='',error=? WHERE run_id=? AND material_id=?",(message,rid,mid))
                c.execute("UPDATE run_writes SET state='failed',error=?,updated_at=? WHERE run_id=? AND material_id=? AND state IN ('queued','writing')",(message,now(),rid,mid))
                c.execute("UPDATE materials SET state='failed',phase='',error=?,updated_at=? WHERE id=?",(message,now(),mid));self._recount_run(c,rid)
            s.log(f'素材#{mid}：{message}','error',rid,mid,'error')
        with s.connect() as c:
            done=c.execute('SELECT done+errors FROM runs WHERE id=?',(rid,)).fetchone()[0]
        batch=max(1,int(snapshot['settings'].get('batch_size',5)))
        if done and done%batch==0:s.log(f'已处理{done}条素材，完成的每个步骤均已保存。','checkpoint',rid)

    def _write_task(self,x,prompt,source_hash,rid,mid,snapshot,variant):
        s=self.store;eid=x['id']
        try:
            if self.pause_flag.is_set():raise StepPaused()
            from operations import acquire_article
            acquire_article(self,rid,eid,snapshot)
            with s.connect() as c:c.execute("UPDATE run_writes SET state='queued',error='',updated_at=? WHERE run_id=? AND extraction_id=?",(now(),rid,eid))
            article_mode=snapshot.get('output_mode')=='article'
            self.update(rid,mid,'writing');s.log(f'素材#{mid} · {x["category"]} 开始生成文章（提示词{variant}）。','writing',rid,mid)
            from funny_singlecall import schema_for,audit_result,mode_for,MULTISTAGE_VARIANTS
            singlecall=article_mode and x['category']=='搞笑' and variant in MULTISTAGE_VARIANTS
            schema=schema_for(variant) if singlecall else ARTICLE if article_mode else WRITE
            if article_mode and x['category']=='搞笑' and not singlecall:
                from article_quality import scored_schema
                schema=scored_schema(schema,x['category'])
            result=self.call('write',prompt,schema,rid,mid,snapshot,f'-{eid}')
            if singlecall:
                from funny_metadata import normalize as normalize_metadata,validation_record
                result,changes=normalize_metadata(result)
                audit=audit_result(result,variant,allow_missing_title_notes=True)
                validation=validation_record(result,changes);result.pop('_metadata_normalization',None)
                if validation['changes'] or validation['warnings']:
                    result['validation_audit']=validation
                    s.log(f'素材#{mid} · 辅助记录已归一／留警告：{len(validation["changes"])}处格式归一，{len(validation["warnings"])}项缺失说明；标题与正文未改写。','format-audit',rid,mid,'warning')
            else:audit=None
            quality=result.get('quality_score')
            format_metadata={key:result[key] for key in ('validation_audit','recovered_response') if key in result}
            if article_mode:result,count,images=normalize_article(result,x['category'])
            else:count,images=self.check_result(result)
            result.update(format_metadata)
            if audit:result.update(generation_audit=audit,generation_mode=mode_for(variant))
            if quality:result['quality_score']=quality
            result.update({'material_id':mid,'extraction_id':eid,'category':x['category'],'topic':json.loads(x['data_json']).get('topic') or x['angle'],'angle':x['angle'],'write_variant':variant,'source_hash':source_hash,'actual_images':0,'stage':'文案与分镜已完成，尚未出图'})
            result['extraction_mode']=x.get('extraction_mode',snapshot.get('extraction_mode','multi'))
            seed_data=json.loads(x['data_json'])
            if seed_data.get('seed_origin')=='source_category_fallback':
                result.update(seed_origin=seed_data['seed_origin'],fallback_reason=seed_data.get('fallback_reason',''))
            with s.connect() as c:
                if article_mode:result['stage']='文章成品'
                from workflow_management import save_generated
                saved=save_generated(c,result,eid,mid,rid,count,images,snapshot,variant)
                c.execute("UPDATE run_article_slots SET state='completed' WHERE run_id=? AND extraction_id=?",(rid,eid))
                c.execute("UPDATE run_writes SET state=?,updated_at=? WHERE run_id=? AND extraction_id=?",('completed' if saved else 'reused',now(),rid,eid))
            s.log(f'素材#{mid} · {x["category"]} 已入结果库，标题和文章{count}/300字符。','written',rid,mid)
        except Exception as exc:
            state='queued' if isinstance(exc,(StepPaused,ProviderLimit)) else 'failed'
            if isinstance(exc,ProviderLimit):
                self.halt_for_limit(rid,exc)
            with s.connect() as c:
                c.execute("DELETE FROM run_article_slots WHERE run_id=? AND extraction_id=? AND state='reserved'",(rid,eid))
                c.execute('UPDATE run_writes SET state=?,error=?,updated_at=? WHERE run_id=? AND extraction_id=?',(state,str(exc)[:1800],now(),rid,eid))
            raise
