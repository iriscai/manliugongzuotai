from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime,date
import material_catalog as catalog
import pipeline_catalog as pipeline


def now(): return datetime.now().isoformat(timespec='seconds')
def dumps(obj): return json.dumps(obj, ensure_ascii=False)
def digest(text): return hashlib.sha256(text.encode('utf8')).hexdigest()
def content_key(title, body): return digest(dumps([str(title or '').strip(), str(body or '').strip()]))
def chars(text): return sum(not c.isspace() for c in str(text))


class Store:
    def __init__(self, root, resources):
        self.root, self.resources = Path(root), Path(resources)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'workbench.sqlite3'
        with self.connect() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY,file TEXT,file_hash TEXT,sheet TEXT,created_at TEXT,added INTEGER,duplicates INTEGER);
            CREATE TABLE IF NOT EXISTS materials(id INTEGER PRIMARY KEY,identity TEXT UNIQUE,title TEXT,body TEXT DEFAULT '',body_status TEXT DEFAULT 'missing',category TEXT,url TEXT,published_at TEXT,read_count REAL DEFAULT 0,state TEXT DEFAULT 'pending',phase TEXT DEFAULT '',error TEXT DEFAULT '',created_at TEXT,updated_at TEXT);
            CREATE TABLE IF NOT EXISTS occurrences(id INTEGER PRIMARY KEY,material_id INTEGER,import_id INTEGER,source_row INTEGER,raw_json TEXT,FOREIGN KEY(material_id) REFERENCES materials(id));
            CREATE TABLE IF NOT EXISTS prompts(id INTEGER PRIMARY KEY,category TEXT,kind TEXT,variant TEXT,name TEXT,content TEXT,revision INTEGER DEFAULT 1,updated_at TEXT,UNIQUE(category,kind,variant));
            CREATE TABLE IF NOT EXISTS prompt_history(id INTEGER PRIMARY KEY,prompt_id INTEGER,content TEXT,revision INTEGER,created_at TEXT);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,mode TEXT,state TEXT,total INTEGER,done INTEGER DEFAULT 0,errors INTEGER DEFAULT 0,current_id INTEGER,current_phase TEXT DEFAULT '',snapshot_json TEXT,created_at TEXT,updated_at TEXT);
            CREATE TABLE IF NOT EXISTS run_items(run_id TEXT,material_id INTEGER,state TEXT DEFAULT 'queued',error TEXT DEFAULT '',PRIMARY KEY(run_id,material_id));
            CREATE TABLE IF NOT EXISTS extractions(id INTEGER PRIMARY KEY,material_id INTEGER,category TEXT,angle TEXT,source_hash TEXT,rule_variant TEXT,prompt_text TEXT,data_json TEXT,current INTEGER DEFAULT 1,created_at TEXT);
            CREATE TABLE IF NOT EXISTS results(id INTEGER PRIMARY KEY,extraction_id INTEGER UNIQUE,material_id INTEGER,category TEXT,title TEXT,short_text TEXT,data_json TEXT,char_count INTEGER,frame_count INTEGER,current INTEGER DEFAULT 1,state TEXT DEFAULT '待审核',created_at TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,run_id TEXT,material_id INTEGER,phase TEXT,level TEXT,message TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS body_jobs(id TEXT PRIMARY KEY,state TEXT,total INTEGER,done INTEGER DEFAULT 0,ok INTEGER DEFAULT 0,failed INTEGER DEFAULT 0,no_text INTEGER DEFAULT 0,skipped INTEGER DEFAULT 0,current_id INTEGER,note TEXT DEFAULT '',folder TEXT DEFAULT '',settings_json TEXT,parent_run TEXT DEFAULT '',created_at TEXT,updated_at TEXT);
            CREATE TABLE IF NOT EXISTS body_items(job_id TEXT,material_id INTEGER,title TEXT,url TEXT,source_hash TEXT,status TEXT,body_chars INTEGER DEFAULT 0,media_type TEXT DEFAULT '',error TEXT DEFAULT '',result_text TEXT DEFAULT '',updated_at TEXT,PRIMARY KEY(job_id,material_id));
            CREATE TABLE IF NOT EXISTS removed_materials(id INTEGER PRIMARY KEY,material_id INTEGER,reason TEXT,kept_id INTEGER,payload_json TEXT,created_at TEXT);
            CREATE INDEX IF NOT EXISTS idx_removed_material ON removed_materials(material_id);
            CREATE INDEX IF NOT EXISTS idx_material_state ON materials(state,id);
            CREATE INDEX IF NOT EXISTS idx_material_category ON materials(category,id);
            CREATE INDEX IF NOT EXISTS idx_result_current ON results(current,id);
            CREATE INDEX IF NOT EXISTS idx_extract_material ON extractions(material_id,current);
            CREATE INDEX IF NOT EXISTS idx_event_run ON events(run_id,id);
            CREATE INDEX IF NOT EXISTS idx_body_item_status ON body_items(job_id,status);
            ''')
            from prompt_status import install_schema as install_prompt_status
            install_prompt_status(c)
            from library_deletion import install_schema as install_library_deletion
            install_library_deletion(c)
            columns={r[1] for r in c.execute('PRAGMA table_info(materials)')}
            for name in ['body_fetched_at','media_type','body_fetch_error']:
                if name not in columns:c.execute(f"ALTER TABLE materials ADD COLUMN {name} TEXT DEFAULT ''")
            if 'content_key' not in columns:c.execute("ALTER TABLE materials ADD COLUMN content_key TEXT DEFAULT ''")
            if 'qualification' not in columns:c.execute("ALTER TABLE materials ADD COLUMN qualification TEXT DEFAULT 'pending'")
            if 'qualified_at' not in columns:c.execute("ALTER TABLE materials ADD COLUMN qualified_at TEXT DEFAULT ''")
            unkeyed=c.execute("SELECT id,title,body FROM materials WHERE content_key='' OR content_key IS NULL").fetchall()
            c.executemany('UPDATE materials SET content_key=? WHERE id=?',[(content_key(r['title'],r['body']),r['id']) for r in unkeyed])
            c.execute('CREATE INDEX IF NOT EXISTS idx_material_content_key ON materials(content_key,id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_material_qualification ON materials(qualification,id)')
            catalog.install_schema(c)
            pipeline.install_schema(c)
            from multi_extraction import install_schema as install_multi_extraction
            install_multi_extraction(c)
            from article_flow import install_schema as install_article_schema
            install_article_schema(c)
            job_columns={r[1] for r in c.execute('PRAGMA table_info(body_jobs)')}
            for name in ['deduplicated','image_deleted']:
                if name not in job_columns:c.execute(f'ALTER TABLE body_jobs ADD COLUMN {name} INTEGER DEFAULT 0')
            item_columns={r[1] for r in c.execute('PRAGMA table_info(body_items)')}
            if 'kept_id' not in item_columns:c.execute('ALTER TABLE body_items ADD COLUMN kept_id INTEGER')
            c.execute("UPDATE runs SET state='interrupted',current_phase='上次执行已中断，可续跑' WHERE state IN ('running','pausing')")
            c.execute("UPDATE materials SET state='pending',phase='' WHERE state IN ('routing','extracting','writing')")
            c.execute("UPDATE materials SET state='needs_source',phase='' WHERE state='fetching' AND body=''")
            c.execute("UPDATE body_jobs SET state='interrupted',note='上次抓取已中断，可续跑' WHERE state IN ('running','pausing')")
            c.execute("UPDATE body_items SET status='pending' WHERE status='running'")
            c.execute("UPDATE run_items SET state='queued' WHERE state='running'")
            lib = json.loads((self.resources / 'prompt-library.json').read_text(encoding='utf8'))
            for row in lib['categories']:
                for key, kind in [('extraction_rules','extract'),('rewrite_prompts','write')]:
                    for p in row[key]:
                        c.execute('INSERT OR IGNORE INTO prompts(category,kind,variant,name,content,updated_at,enabled) VALUES(?,?,?,?,?,?,?)', (row['category'],kind,p['id'],p['name'],p['text'],now(),int(p.get('enabled',True))))
            from writing_prompts import migrate_stock_rules
            migrate_stock_rules(c,now())
            from funny_rules import migrate_funny_rules
            migrate_funny_rules(c,self.resources,now())
            from funny_singlecall import migrate as migrate_singlecall
            migrate_singlecall(c,self.resources,now())
            from funny_j_profile import migrate as migrate_funny_j
            migrate_funny_j(c,self.resources,now())
            from title_push import install_schema as install_push_schema
            install_push_schema(c)
            from result_cleanup import install_schema as install_cleanup_schema
            install_cleanup_schema(c)
            from workflow_management import install_schema as install_workflow_schema
            from usage_budget import install_schema as install_usage_schema
            install_workflow_schema(c);install_usage_schema(c)
            from article_quality import install_schema as install_quality_schema
            install_quality_schema(c)
            from article_quality import backfill as backfill_quality
            backfill_quality(c,self.resources)
            from data_integrity import install_schema as install_integrity_schema
            install_integrity_schema(c)
            from operations import install_schema as install_operations_schema
            install_operations_schema(c)
            from model_queue import install_schema as install_model_queue_schema
            install_model_queue_schema(c)
            from history_cleanup import install_schema as install_history_cleanup
            install_history_cleanup(c)
            from material_workflow import install_schema as install_material_workflow
            install_material_workflow(c)
            from usability import install_schema as install_usability
            install_usability(c)
            from score_jobs import install_schema as install_score_jobs
            install_score_jobs(c)
            for r in c.execute("SELECT id FROM runs WHERE state NOT IN ('running','pausing') AND summary_json='' ").fetchall():pipeline.freeze_summary(c,r['id'])
            for r in c.execute("SELECT id FROM materials WHERE body_status='image' AND deleted_at=\'\'").fetchall():self.remove_material_in(c,r['id'],'image_only')
            for r in c.execute("SELECT id FROM materials WHERE body<>'' AND qualification='pending' ORDER BY id").fetchall():self.qualify_in(c,r['id'])
        defaults = {'provider':'codex','codex_path':'','model':'','reasoning':'','api_base':'','api_model':'','api_protocol':'chat','api_key_encrypted':'','batch_size':5,'run_size':20,'extraction_mode':'multi','extract_variant':'alternate','write_variant':'alternate','allowed_categories':[],'timeout':900,'requirements':'','body_tool_path':'D:/BIGDATA/CODES/PyCharmFiles/Factorys/ArticleBodyScraper/dist_file_mode/正文抓取工具/正文抓取工具.exe','body_workers':2,'body_run_size':100,'body_chunk_size':50,'body_wait':40,'body_delay':1.5,'body_rest_every':40,'body_rest_seconds':45,'body_channel':'chrome','body_headful':False,'body_timeout':7200}
        with self.connect() as c:
            for k,v in defaults.items(): c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',(k,dumps(v)))
            c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('body_queue_paused','false'))
            c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('body_max_chars','800'))
            paused=json.loads(c.execute('SELECT value FROM settings WHERE key=?',('body_queue_paused',)).fetchone()[0])
            c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',('body_queue_pause_reason',dumps('user' if paused else '')))
            for key,value in {'api_temperature':.7,'api_timeout':300,'api_retry_count':1,'api_skip_tls_verify':False,'api_model_options':[]}.items():c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',(key,dumps(value)))
            for key in ['process_workers','write_workers']:c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',(key,'8'))
            for key,value in {'global_max_concurrency':16,'daily_request_limit':0,'daily_token_limit':0}.items():c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',(key,dumps(value)))
            for key in ['task_request_limit','task_article_limit','task_token_limit']:c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',(key,'0'))
            for key in ['funny_extract_variant','funny_write_variant']:c.execute('INSERT OR IGNORE INTO settings VALUES(?,?)',(key,dumps('A')))

    def remove_material_in(self,c,mid,reason,kept_id=None):
        row=c.execute('SELECT * FROM materials WHERE id=?',(mid,)).fetchone()
        if not row:return
        payload={'material':dict(row)}
        for table in ['occurrences','extractions','results','extraction_batches']:
            payload[table]=[dict(r) for r in c.execute(f'SELECT * FROM {table} WHERE material_id=?',(mid,))]
        c.execute('INSERT INTO removed_materials(material_id,reason,kept_id,payload_json,created_at) VALUES(?,?,?,?,?)',(mid,reason,kept_id,dumps(payload),now()))
        if kept_id:c.execute('UPDATE occurrences SET material_id=? WHERE material_id=?',(kept_id,mid))
        else:c.execute('DELETE FROM occurrences WHERE material_id=?',(mid,))
        c.execute('DELETE FROM results WHERE material_id=?',(mid,))
        c.execute('DELETE FROM extractions WHERE material_id=?',(mid,))
        c.execute('DELETE FROM extraction_batches WHERE material_id=?',(mid,))
        runs=[r[0] for r in c.execute("SELECT run_id FROM run_items WHERE material_id=? AND state IN ('queued','running')",(mid,))]
        c.execute("UPDATE run_items SET state='skipped',error=? WHERE material_id=? AND state IN ('queued','running')",('重复合并到#'+str(kept_id) if kept_id else '纯图片素材已删除',mid))
        for rid in runs:
            c.execute("UPDATE runs SET done=(SELECT count(*) FROM run_items WHERE run_id=? AND state IN ('completed','skipped')),updated_at=? WHERE id=?",(rid,now(),rid))
        c.execute('DELETE FROM materials WHERE id=?',(mid,))

    def qualify_in(self,c,mid):
        row=c.execute('SELECT * FROM materials WHERE id=?',(mid,)).fetchone()
        if not row or row['deleted_at']:return {'action':'missing','material_id':mid}
        title=str(row['title'] or '').strip();body=str(row['body'] or '').strip()
        if not title or not body or row['body_status'] not in ('provided','scraped','fetched') or body.startswith(('[抓取失败]','[无文字正文]')):
            c.execute("UPDATE materials SET qualification='pending',qualified_at='' WHERE id=?",(mid,))
            return {'action':'pending','material_id':mid}
        key=content_key(title,body)
        candidates=c.execute("SELECT id,title,body FROM materials WHERE content_key=? AND qualification='qualified' AND deleted_at=\'\' AND id<>? ORDER BY id",(key,mid)).fetchall()
        other=next((r for r in candidates if str(r['title'] or '').strip()==title and str(r['body'] or '').strip()==body),None)
        if other:
            self.remove_material_in(c,mid,'duplicate',other['id'])
            return {'action':'duplicate','material_id':mid,'kept_id':other['id']}
        c.execute("UPDATE materials SET content_key=?,qualification='qualified',qualified_at=CASE WHEN qualified_at='' THEN ? ELSE qualified_at END WHERE id=?",(key,now(),mid))
        return {'action':'qualified','material_id':mid}

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db, timeout=30)
        c.row_factory=sqlite3.Row
        from workflow_management import rule_hash
        from title_push import signature
        c.create_function('rule_fingerprint',4,rule_hash,deterministic=True)
        c.create_function('result_signature',3,lambda category,title,article:signature({'category':category,'title':title,'article':article,'short_text':article}),deterministic=True)
        from title_push import delivery_signature
        has_settings=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'").fetchone()
        routing={r['key']:json.loads(r['value']) for r in c.execute("SELECT key,value FROM settings WHERE key IN ('push_category_map','push_score_rules')")} if has_settings else {}
        mapping=routing.get('push_category_map',{});rules=routing.get('push_score_rules')
        c.create_function('result_delivery_signature',6,lambda category,title,article,score,status,hashed:delivery_signature({'category':category,'title':title,'article':article,'short_text':article,'score':score,'score_status':status,'score_content_hash':hashed},mapping,rules),deterministic=True)
        if has_settings:
            from material_workflow import register_functions
            register_functions(c)
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=30000')
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:c.close()

    def settings(self):
        with self.connect() as c: return {r['key']:json.loads(r['value']) for r in c.execute('SELECT * FROM settings')}

    def save_settings(self, values):
        with self.connect() as c:
            for k,v in values.items(): c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(k,dumps(v)))

    def log(self, message, phase='', run_id='', material_id=None, level='info'):
        with self.connect() as c: c.execute('INSERT INTO events(run_id,material_id,phase,level,message,created_at) VALUES(?,?,?,?,?,?)',(run_id,material_id,phase,level,message[:2000],now()))

    def prompts(self, category=None):
        with self.connect() as c:
            q='SELECT * FROM prompts'; args=[]
            if category: q+=' WHERE category=?'; args=[category]
            return [dict(r) for r in c.execute(q+' ORDER BY id',args)]

    def save_prompt(self, payload):
        content=str(payload.get('content','')).strip()
        if not content: raise ValueError('提示词不能为空')
        with self.connect() as c:
            old=c.execute('SELECT * FROM prompts WHERE id=?',(int(payload['id']),)).fetchone()
            if not old: raise ValueError('规则不存在')
            c.execute('INSERT INTO prompt_history(prompt_id,content,revision,created_at) VALUES(?,?,?,?)',(old['id'],old['content'],old['revision'],now()))
            c.execute('UPDATE prompts SET content=?,revision=revision+1,updated_at=? WHERE id=?',(content,now(),old['id']))
            if old['category']=='搞笑' and old['variant']=='I' and content!=old['content']:
                if old['enabled']:c.execute('INSERT INTO prompt_status_history(prompt_id,old_enabled,new_enabled,created_at) VALUES(?,?,0,?)',(old['id'],1,now()))
                c.execute('UPDATE prompts SET enabled=0,status_updated_at=? WHERE id=?',(now(),old['id']))
                c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('funny_singlecall_validation',dumps({'status':'needs_trial','note':'方案I内容已修改，需重新试跑评分达标后启用'})))
            if old['category']=='搞笑' and old['variant']=='J' and content!=old['content']:
                if old['enabled']:c.execute('INSERT INTO prompt_status_history(prompt_id,old_enabled,new_enabled,created_at) VALUES(?,?,0,?)',(old['id'],1,now()))
                c.execute('UPDATE prompts SET enabled=0,status_updated_at=? WHERE id=?',(now(),old['id']))
                c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('funny_J_validation',dumps({'status':'needs_trial','variant':'J','note':'方案J内容已修改，需按新内容试跑评分后启用'})))
        return {'ok':True,'note':'已保存工作台独立版本；未修改已安装SKILL或正在执行的规则快照'}

    @staticmethod
    def read_file(path, sheet=None):
        path=Path(path)
        if not path.is_file(): raise ValueError('找不到素材文件')
        suffix=path.suffix.lower()
        if suffix=='.xlsx':
            import openpyxl
            w=openpyxl.load_workbook(path,read_only=True,data_only=True)
            names=w.sheetnames
            if sheet and sheet not in names: w.close(); raise ValueError('工作表不存在')
            s=w[sheet or names[0]]; chosen=s.title
            it=s.iter_rows(values_only=True)
            headers=[str(x).strip() if x is not None else f'未命名列{i+1}' for i,x in enumerate(next(it,[]))]
            if len(set(headers))!=len(headers): w.close(); raise ValueError('表头有重复列名，请先区分后导入')
            rows=[(i,dict(zip(headers,[x.isoformat() if isinstance(x,(datetime,date)) else x for x in r]))) for i,r in enumerate(it,2) if any(x is not None and str(x).strip() for x in r)]
            w.close(); return names,chosen,headers,rows
        if suffix in ('.csv','.tsv'):
            text=None
            for enc in ['utf-8-sig','gb18030']:
                try: text=path.read_text(encoding=enc); break
                except UnicodeDecodeError: continue
            if text is None: raise ValueError('无法识别文本编码')
            import io
            reader=csv.DictReader(io.StringIO(text),delimiter='\t' if suffix=='.tsv' else ',')
            headers=reader.fieldnames or []
            if len(set(headers))!=len(headers): raise ValueError('表头列名不能重复')
            return ['数据'],'数据',headers,[(i,dict(r)) for i,r in enumerate(reader,2) if any(r.values())]
        if suffix=='.jsonl':
            rows=[(i,json.loads(t)) for i,t in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1) if t.strip()]
            if not all(isinstance(r,dict) for _,r in rows): raise ValueError('JSONL每行必须是对象')
            headers=list(dict.fromkeys(k for _,r in rows for k in r))
            return ['数据'],'数据',headers,rows
        raise ValueError('支持 XLSX、CSV、TSV、JSONL 文件')

    def preview_import(self, path, sheet=None):
        sheets,chosen,headers,rows=self.read_file(path,sheet)
        return {"path":str(path),"sheets":sheets,"sheet":chosen,"headers":headers,"count":len(rows),"preview":[{k:str(v)[:300] if v is not None else "" for k,v in r.items()} for _,r in rows[:4]],"suggested":catalog.suggested_mapping(headers)}

    def import_file(self, payload):
        path=Path(payload['path']); names,sheet,headers,rows=self.read_file(path,payload.get('sheet'))
        mapping={**catalog.suggested_mapping(headers),**(payload.get('mapping') or {})}
        if not mapping.get('title') and not mapping.get('body'): raise ValueError('至少映射标题或正文')
        for key in ['title','body','category','url','read_count','published_at']:
            if mapping.get(key) and mapping[key] not in headers: raise ValueError(f'列不存在：{mapping[key]}')
        file_hash=hashlib.sha256(path.read_bytes()).hexdigest(); added=duplicate=0;intake_ids=[]
        with self.connect() as c:
            iid=c.execute('INSERT INTO imports(file,file_hash,sheet,created_at,added,duplicates) VALUES(?,?,?,?,0,0)',(str(path),file_hash,sheet,now())).lastrowid
            next_id=max(c.execute('SELECT coalesce(max(id),0) FROM materials').fetchone()[0],c.execute('SELECT coalesce(max(material_id),0) FROM removed_materials').fetchone()[0])+1
            for rownum, raw in rows:
                def field(k):
                    v=raw.get(mapping.get(k,'')); return '' if v is None else str(v).strip()
                title,body,category,url=[field(k) for k in ['title','body','category','url']]
                if not title and not body: continue
                key=content_key(title,body)
                try: read=catalog.read_number(field('read_count'))
                except (ValueError,TypeError): read=0
                published=field('published_at');published_sort=catalog.publication(published)
                state='pending' if body and title else 'needs_source'
                mid=next_id;next_id+=1
                c.execute('INSERT INTO materials(id,identity,content_key,title,body,body_status,category,url,published_at,published_sort,published_day,read_count,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(mid,'material_'+uuid.uuid4().hex,key,title,body,'provided' if body else 'missing',category or '其他',url,published,published_sort,published_sort[:10],read,state,now(),now()))
                c.execute('INSERT INTO occurrences(material_id,import_id,source_row,raw_json) VALUES(?,?,?,?)',(mid,iid,rownum,dumps(raw)))
                outcome=self.qualify_in(c,mid)
                if outcome['action']=='duplicate':duplicate+=1
                else:added+=1;intake_ids.append(mid)
            c.execute('UPDATE imports SET added=?,duplicates=? WHERE id=?',(added,duplicate,iid))
        self.log(f'导入 {path.name}：接收{added}条，已有完整正文的重复{duplicate}条。缺正文素材先抓取，之后去重验收。','import')
        return {'added':added,'duplicates':duplicate,'import_id':iid,'intake_ids':intake_ids}

    def material(self, mid, include_workflow=True):
        with self.connect() as c:
            r=c.execute('SELECT * FROM materials WHERE id=?',(int(mid),)).fetchone()
            if not r: raise ValueError('素材不存在')
            item=dict(r)
            if include_workflow:
                from material_workflow import decorate as decorate_workflow
                flow=dict(c.execute('SELECT * FROM material_workflow WHERE material_id=?',(int(mid),)).fetchone())
                decorate_workflow([flow]);item['workflow']=flow
            item['extractions']=[dict(x) for x in c.execute('SELECT * FROM extractions WHERE material_id=? ORDER BY id DESC',(mid,))]
            item['results']=[dict(x) for x in c.execute("SELECT * FROM results WHERE material_id=? AND cleared_at='' AND deleted_at=\'\' ORDER BY id DESC",(mid,))]
            item['current_extraction_count']=sum(1 for x in item['extractions'] if x['current'])
            item['extraction_batches']=[dict(x) for x in c.execute('SELECT id,source_hash,rule_variant,category_count,target_count,created_at FROM extraction_batches WHERE material_id=? ORDER BY id DESC',(mid,))]
            item['origins']=[dict(x) for x in c.execute('SELECT i.file,i.sheet,o.source_row FROM occurrences o JOIN imports i ON i.id=o.import_id WHERE material_id=? ORDER BY o.id',(mid,))]
            return item

    def save_body(self, mid, body, fetched=False):
        body=str(body).strip()
        if not body: raise ValueError('正文不能为空')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM materials WHERE id=?',(int(mid),)).fetchone()
            if not old or old['deleted_at']: raise ValueError('素材不存在或已删除，请先恢复')
            if fetched and old['body']:return {'ok':True,'changed':False}
            if old['state'] in ('routing','extracting','writing','fetching'): raise ValueError('当前素材正在执行，请暂停后再修改')
            if old['body']==body: return {'ok':True,'changed':False}
            c.execute('UPDATE extractions SET current=0 WHERE material_id=?',(mid,))
            c.execute('UPDATE results SET current=0 WHERE material_id=?',(mid,))
            c.execute("UPDATE materials SET body=?,content_key=?,qualification='pending',qualified_at='',body_status=?,state='pending',phase='',error='',body_fetch_error='',updated_at=? WHERE id=?",(body,content_key(old['title'],body),'fetched' if fetched else 'provided',now(),mid))
            outcome=self.qualify_in(c,mid)
        return {'ok':True,'changed':True,**outcome}

    def list_materials(self, query):
        with self.connect() as c:return catalog.list_materials(c,query)

    def material_options(self):
        with self.connect() as c:return catalog.options(c)

    def list_results(self, query):
        from workflow_management import list_results
        return list_results(self,query)

    def stats(self):
        with self.connect() as c:
            counts={r[0]:r[1] for r in c.execute('SELECT state,count(*) FROM materials WHERE deleted_at=\'\' GROUP BY state')}
            totals={k:0 for k in ['pending','needs_source','routing','extracting','extracted','writing','written','failed','skipped','fetching','no_text']};totals.update(counts)
            totals['total']=sum(counts.values());totals['result_count']=c.execute("SELECT count(*) FROM results WHERE current=1 AND deleted_at=\'\' AND cleared_at=''").fetchone()[0]
            totals['extraction_count']=c.execute('SELECT count(*) FROM extractions WHERE current=1 AND material_id IN (SELECT id FROM materials WHERE deleted_at=\'\')').fetchone()[0]
            totals['body_ready']=c.execute("SELECT count(*) FROM materials WHERE deleted_at=\'\' AND body<>''").fetchone()[0]
            totals['body_failed']=c.execute("SELECT count(*) FROM materials WHERE deleted_at=\'\' AND body_status IN ('failed','truncated')").fetchone()[0]
            totals['qualified']=c.execute("SELECT count(*) FROM materials WHERE deleted_at=\'\' AND qualification='qualified'").fetchone()[0]
            totals['unqualified']=totals['total']-totals['qualified']
            totals['deduplicated']=c.execute("SELECT count(*) FROM removed_materials WHERE reason='duplicate'").fetchone()[0]
            totals['image_deleted']=c.execute("SELECT count(*) FROM removed_materials WHERE reason='image_only'").fetchone()[0]
            categories=[dict(r) for r in c.execute('SELECT category,count(*) count,sum(read_count) reads FROM materials WHERE deleted_at=\'\' GROUP BY category ORDER BY count DESC')]
            runs=[dict(r) for r in c.execute("SELECT id,mode,state,total,done,errors,current_id,current_phase,created_at,updated_at FROM runs ORDER BY CASE WHEN state IN ('running','pausing') THEN 0 ELSE 1 END,created_at DESC LIMIT 12")]
            for run in runs:
                run['progress']=pipeline.run_summary(c,run['id'])
                cfg=json.loads(c.execute('SELECT snapshot_json FROM runs WHERE id=?',(run['id'],)).fetchone()[0])['settings']
                run['process_workers']=cfg.get('process_workers',1);run['write_workers']=cfg.get('write_workers',1)
                run['extraction_scheme']=json.loads(c.execute('SELECT snapshot_json FROM runs WHERE id=?',(run['id'],)).fetchone()[0]).get('extraction_scheme','legacy')
                run['extraction_mode']=json.loads(c.execute('SELECT snapshot_json FROM runs WHERE id=?',(run['id'],)).fetchone()[0]).get('extraction_mode','multi')
            writing=pipeline.overview(c)
            events=[dict(r) for r in c.execute('SELECT * FROM events ORDER BY id DESC LIMIT 30')]
            recent=[dict(r) for r in c.execute('SELECT id,title,category,state,phase,updated_at FROM materials WHERE deleted_at=\'\' ORDER BY updated_at DESC,id DESC LIMIT 7')]
            imports=[dict(r) for r in c.execute('SELECT * FROM imports ORDER BY id DESC LIMIT 8')]
            from usage_budget import summary
            usage=summary(c)
        return {'counts':totals,'categories':categories,'runs':runs,'events':events,'recent':recent,'imports':imports,'db_path':str(self.db),'writing':writing,'usage':usage}

    def export(self, path, kind='results',ids=None,filters=None):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            if kind=='prompts': data=self.prompts()
            elif kind=='materials': data=[dict(r) for r in c.execute('SELECT * FROM materials WHERE deleted_at=\'\' ORDER BY id')]
            else:
                if ids is not None:
                    from workflow_management import selected_ids
                    ids=selected_ids(self,{'ids':ids})
                    rows=[dict(r) for r in c.execute('SELECT * FROM results WHERE current=1 AND id IN ('+','.join('?' for _ in ids)+') ORDER BY material_id,id',ids)]
                elif filters is not None:
                    from workflow_management import query_parts
                    join,args=query_parts(self,filters);rows=[dict(r) for r in c.execute('SELECT r.*'+join+' ORDER BY r.material_id,r.id',args)]
                else:rows=[dict(r) for r in c.execute("SELECT * FROM results WHERE current=1 AND deleted_at=\'\' AND cleared_at='' ORDER BY material_id,id")]
                from article_quality import decorate as quality_decorate
                routing=self.settings();quality_decorate(rows,routing.get('push_category_map',{}),routing.get('push_score_rules'))
                data=rows if kind=='results_full' else [{'赛道':r['category'],'标题':r['title'],'文章':r.get('article') or r['short_text'],'评分':r['score'],'评分类型':r['score_display_status'],'推送分类':r['push_category']} for r in rows]
        if path.suffix.lower()=='.json': path.write_text(dumps(data),encoding='utf8')
        elif path.suffix.lower()=='.csv':
            headers=list(data[0]) if data else ['赛道','标题','文章'] if kind=='results' else ['暂无记录']
            with path.open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=headers);writer.writeheader()
                for row in data:
                    writer.writerow({k:("'"+str(v) if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in row.items()})
        else: raise ValueError('导出支持JSON或CSV')
        return {'path':str(path),'count':len(data)}
