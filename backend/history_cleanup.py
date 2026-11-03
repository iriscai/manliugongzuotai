"""Previewed, backed-up cleanup of old execution history; libraries are untouched."""
import calendar,hashlib,json,os,re,sqlite3,uuid,zipfile
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ=ZoneInfo('Asia/Shanghai')
def clock():return datetime.now(TZ)
def encoded(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))

def install_schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS history_cleanup_previews(id TEXT PRIMARY KEY,options_json TEXT,cutoff TEXT,digest TEXT,expires_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history_cleanup_batches(id TEXT PRIMARY KEY,created_at TEXT,cutoff TEXT,options_json TEXT,counts_json TEXT,backup_path TEXT,state TEXT,warnings_json TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at,id)')

def options(payload):
    period=payload.get('period','month')
    if period not in ('7d','month'):raise ValueError('请选择7天前或一个月前')
    result={'period':period}
    for key in ['records','logs','files']:
        value=payload.get(key,True)
        if type(value) is not bool:raise ValueError('清理范围必须为勾选项')
        result[key]=value
    if not (result['records'] or result['logs']):raise ValueError('请至少选择执行记录或日志')
    return result

def cutoff_for(period,current=None):
    current=current or clock()
    if period=='7d':return current-timedelta(days=7)
    year,month=(current.year-1,12) if current.month==1 else (current.year,current.month-1)
    return current.replace(year=year,month=month,day=min(current.day,calendar.monthrange(year,month)[1]))

def older(column):
    # Legacy timestamps without an offset were stored as local Beijing time.
    return "julianday(CASE WHEN substr("+column+",20) GLOB '*[+-]*' OR substr("+column+",-1) IN ('Z','z') THEN "+column+" ELSE "+column+"||'+08:00' END)<julianday(?)"

def in_ids(column,ids):return column+' IN (SELECT value FROM json_each(?))',[encoded(ids)]

def protected_run():
    return "(j.state<>'completed' OR coalesce(j.errors,0)>0 OR EXISTS(SELECT 1 FROM run_items x WHERE x.run_id=j.id AND x.state IN ('queued','running','failed','needs_review')) OR EXISTS(SELECT 1 FROM run_writes x WHERE x.run_id=j.id AND x.state IN ('queued','writing','failed','needs_review')) OR EXISTS(SELECT 1 FROM model_queue_runs x JOIN model_queue mq ON mq.id=x.job_id WHERE x.run_id=j.id AND mq.state<>'completed'))"

def is_link(path):return path.is_symlink() or bool(getattr(path,'is_junction',lambda:False)())

def safe_file(root,path):
    root=root.resolve();path=Path(path).absolute()
    try:
        absolute=path.resolve(strict=True)
        if not absolute.is_relative_to(root) or is_link(path) or not absolute.is_file():return None
        parent=path.parent
        while parent!=root:
            if not parent.is_relative_to(root) or is_link(parent):return None
            parent=parent.parent
        stat=absolute.stat()
        return {'path':absolute.relative_to(root).as_posix(),'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}
    except (OSError,ValueError):return None

def cleanup_files(store,c,run_ids,body_ids,opts,cutoff):
    root=store.root.resolve();found={};limit=datetime.fromisoformat(cutoff).timestamp()
    def add(path):
        item=safe_file(root,path)
        if item and item['mtime_ns']/1e9<limit:found[item['path']]=item
    if opts['files'] and opts['records']:
        for folder,table,selected in [('runs','runs',set(run_ids)),('body_fetch','body_jobs',set(body_ids))]:
            base=root/folder
            if not base.is_dir() or is_link(base):continue
            retained={r[0] for r in c.execute('SELECT id FROM '+table)}-selected
            for directory in base.iterdir():
                if not directory.is_dir() or is_link(directory) or directory.name in retained or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',directory.name):continue
                if directory.name not in selected and not re.fullmatch(r'[0-9a-f]{12}' if folder=='runs' else r'body_[0-9a-f]{12}',directory.name):continue
                for current,dirs,files in os.walk(directory,followlinks=False):
                    dirs[:]=[n for n in dirs if not is_link(Path(current)/n)]
                    for name in files:add(Path(current)/name)
    if opts['logs']:
        for path in root.iterdir():
            if re.fullmatch(r'[A-Za-z0-9_-]+\.log(?:\.[A-Za-z0-9_-]+)?',path.name):add(path)
    return sorted(found.values(),key=lambda r:r['path'])

def selection(store,c,opts,cutoff):
    specs={};run_ids=[];body_ids=[];queue_ids=[]
    protected=protected_run()
    run_time="coalesce(nullif(j.updated_at,''),j.created_at)"
    if opts['records']:
        run_ids=[r[0] for r in c.execute('SELECT j.id FROM runs j WHERE NOT '+protected+' AND '+older(run_time)+' ORDER BY j.id',(cutoff,))]
        body_ids=[r[0] for r in c.execute("SELECT b.id FROM body_jobs b WHERE b.state='completed' AND NOT EXISTS(SELECT 1 FROM runs j WHERE j.id=b.parent_run AND "+protected+') AND '+older("coalesce(nullif(b.updated_at,''),b.created_at)")+' ORDER BY b.id',(cutoff,))]
        queue_ids=[r[0] for r in c.execute("SELECT id FROM model_queue WHERE state='completed' AND "+older("coalesce(nullif(updated_at,''),created_at)")+' ORDER BY id',(cutoff,))]
        for table,column,ids in [('run_items','run_id',run_ids),('run_writes','run_id',run_ids),('run_article_slots','run_id',run_ids),('runs','id',run_ids),('body_items','job_id',body_ids),('body_jobs','id',body_ids),('model_queue_items','job_id',queue_ids),('model_queue','id',queue_ids)]:specs[table]=in_ids(column,ids)
        specs['model_queue_runs']=("job_id IN (SELECT value FROM json_each(?)) OR run_id IN (SELECT value FROM json_each(?))",[encoded(queue_ids),encoded(run_ids)])
        specs['model_requests']=("state<>'running' AND "+older("coalesce(nullif(completed_at,''),created_at)")+" AND (run_id IN (SELECT value FROM json_each(?)) OR (NOT EXISTS(SELECT 1 FROM runs j WHERE j.id=model_requests.run_id) AND NOT EXISTS(SELECT 1 FROM model_queue_runs qr JOIN model_queue q ON q.id=qr.job_id WHERE qr.run_id=model_requests.run_id AND q.state<>'completed')))",[cutoff,encoded(run_ids)])
    if opts['logs']:
        specs['events']=(older('created_at')+" AND NOT EXISTS(SELECT 1 FROM runs j WHERE j.id=events.run_id AND "+protected+") AND NOT EXISTS(SELECT 1 FROM body_jobs b WHERE b.id=events.run_id AND b.state<>'completed') AND NOT EXISTS(SELECT 1 FROM model_queue q WHERE q.id=events.run_id AND q.state<>'completed')",[cutoff])
    counts={};fingerprint=hashlib.sha256()
    for table,(where,args) in sorted(specs.items()):
        fingerprint.update(table.encode());count=0
        for row in c.execute('SELECT * FROM '+table+' WHERE '+where+' ORDER BY rowid',args):
            fingerprint.update(encoded(list(row)).encode('utf8'));fingerprint.update(b'\n');count+=1
        counts[table]=count
    files=cleanup_files(store,c,run_ids,body_ids,opts,cutoff);fingerprint.update(encoded(files).encode('utf8'))
    protected_count=c.execute('SELECT count(*) FROM runs j WHERE '+protected+' AND '+older(run_time),(cutoff,)).fetchone()[0]
    protected_count+=c.execute("SELECT count(*) FROM body_jobs WHERE state<>'completed' AND "+older("coalesce(nullif(updated_at,''),created_at)"),(cutoff,)).fetchone()[0]
    protected_count+=c.execute("SELECT count(*) FROM model_queue WHERE state<>'completed' AND "+older("coalesce(nullif(updated_at,''),created_at)"),(cutoff,)).fetchone()[0]
    return {'specs':specs,'counts':counts,'files':files,'digest':fingerprint.hexdigest(),'protected_tasks':protected_count}

def busy(c):
    return any(c.execute('SELECT 1 FROM '+table+" WHERE state IN ('running','pausing') LIMIT 1").fetchone() for table in ['runs','body_jobs']) or bool(c.execute("SELECT 1 FROM model_queue WHERE state IN ('queued','waiting','running') LIMIT 1").fetchone())

def preview(store,payload):
    opts=options(payload);current=clock();cutoff=cutoff_for(opts['period'],current).isoformat(timespec='seconds')
    with store.connect() as c:
        plan=selection(store,c,opts,cutoff);pid=uuid.uuid4().hex
        c.execute('INSERT INTO history_cleanup_previews VALUES(?,?,?,?,?)',(pid,encoded(opts),cutoff,plan['digest'],(current+timedelta(minutes=30)).isoformat()))
        c.execute('DELETE FROM history_cleanup_previews WHERE expires_at<?',((current-timedelta(days=1)).isoformat(),))
        return {'preview_id':pid,'digest':plan['digest'],'options':opts,'cutoff':cutoff,'counts':plan['counts'],'total_records':sum(plan['counts'].values()),'files':len(plan['files']),'file_bytes':sum(r['size'] for r in plan['files']),'protected_tasks':plan['protected_tasks'],'busy':busy(c),'preserved':['素材库','结果库','提炼种子','评分','文章历史版本','推送回执']}

def apply(store,payload):
    batch='history_'+uuid.uuid4().hex[:12];warnings=[]
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        previous=c.execute('SELECT * FROM history_cleanup_previews WHERE id=?',(str(payload.get('preview_id','')),)).fetchone()
        if not previous or datetime.fromisoformat(previous['expires_at'])<clock():raise ValueError('清理预览已失效，请重新预览')
        if busy(c):raise ValueError('有任务执行或排队中，请先暂停并等待当前步骤保存后再清理')
        opts=json.loads(previous['options_json']);plan=selection(store,c,opts,previous['cutoff'])
        if payload.get('digest')!=previous['digest'] or plan['digest']!=previous['digest']:raise ValueError('历史记录或文件已变化，请重新预览后清理')
        if not any(plan['counts'].values()) and not plan['files']:raise ValueError('当前时间范围没有可清理的历史记录或日志')
        folder=store.root/'history_cleanup_backups';folder.mkdir(exist_ok=True)
        path=folder/(clock().strftime('%Y%m%d-%H%M%S')+'_'+batch+'.zip');temporary=path.with_suffix('.tmp')
        manifest={'batch':batch,'created_at':clock().isoformat(),'cutoff':previous['cutoff'],'options':opts,'counts':plan['counts'],'files':plan['files'],'preserved':['materials','results','extractions','extraction_batches','result_versions','result_pushes','article_score_history']}
        try:
            with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,strict_timestamps=False) as archive:
                archive.writestr('manifest.json',encoded(manifest))
                for table,(where,args) in plan['specs'].items():
                    with archive.open('records/'+table+'.jsonl','w') as out:
                        for row in c.execute('SELECT * FROM '+table+' WHERE '+where+' ORDER BY rowid',args):out.write((encoded(dict(row))+'\n').encode('utf8'))
                for item in plan['files']:
                    source=store.root.resolve()/item['path']
                    if safe_file(store.root,source)!=item:raise ValueError('运行文件已变化，请重新预览')
                    archive.write(source,'files/'+item['path'])
                    if safe_file(store.root,source)!=item:raise ValueError('备份期间运行文件已变化，本次未清理')
            temporary.replace(path)
        except Exception:
            if temporary.exists():temporary.unlink()
            raise
        # Only the explicit history-table allowlist can be deleted.
        for table in ['events','model_requests','run_article_slots','run_writes','run_items','body_items','model_queue_items','model_queue_runs','body_jobs','model_queue','runs']:
            if table in plan['specs']:
                where,args=plan['specs'][table];c.execute('DELETE FROM '+table+' WHERE '+where,args)
        c.execute('DELETE FROM history_cleanup_previews WHERE id=?',(previous['id'],))
        c.execute('INSERT INTO history_cleanup_batches VALUES(?,?,?,?,?,?,?,?)',(batch,clock().isoformat(),previous['cutoff'],encoded(opts),encoded(plan['counts']),str(path),'database_cleaned','[]'))
    removed=removed_bytes=0;parents=set()
    for item in plan['files']:
        source=store.root.resolve()/item['path']
        try:
            if safe_file(store.root,source)!=item:raise ValueError('文件已有更新，已保留')
            source.unlink();removed+=1;removed_bytes+=item['size'];parents.add(source.parent)
        except (OSError,ValueError) as exc:warnings.append(item['path']+'：'+str(exc))
    # Remove only empty folders under the two known cache roots, never recursively.
    bases={store.root.resolve()/'runs',store.root.resolve()/'body_fetch'}
    for parent in sorted(parents,key=lambda p:len(p.parts),reverse=True):
        while parent not in bases and any(parent.is_relative_to(base) for base in bases):
            try:parent.rmdir()
            except OSError:break
            parent=parent.parent
    with store.connect() as c:c.execute('UPDATE history_cleanup_batches SET state=?,warnings_json=? WHERE id=?',('completed_with_warnings' if warnings else 'completed',encoded(warnings),batch))
    store.log('历史清理完成：'+str(sum(plan['counts'].values()))+'条记录，'+str(removed)+'个历史文件；备份 '+str(path),'cleanup')
    return {'ok':True,'batch_id':batch,'counts':plan['counts'],'total_records':sum(plan['counts'].values()),'files_removed':removed,'file_bytes_removed':removed_bytes,'backup_path':str(path),'warnings':warnings}
