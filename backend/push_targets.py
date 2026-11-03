"""Resolve the actual database used by a packaged factory, not a path prefix."""
import json,os,sqlite3,subprocess
from pathlib import Path
from contextlib import closing

def project_for(store):
    from title_push import PROJECT
    return Path(store.settings().get('push_target_project') or PROJECT).resolve()

def project_in(c):
    from title_push import PROJECT
    row=c.execute("SELECT value FROM settings WHERE key='push_target_project'").fetchone()
    return Path(json.loads(row[0]) if row and json.loads(row[0]) else PROJECT).resolve()

def runtime_project(executable):
    runtime=Path(executable).resolve().parent
    candidate=runtime.parent.parent
    return candidate if (candidate/'picfactory_matrix.db').is_file() else runtime

def running_factories(project):
    if os.name!='nt':return []
    from title_push import PROJECT
    command="Get-CimInstance Win32_Process -Filter \"Name='PicFactoryGUI.exe'\" | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"
    r=subprocess.run(['powershell','-NoProfile','-Command',command],capture_output=True,text=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if r.returncode:raise ValueError('无法确认生图软件进程，请稍后检查目标连接')
    data=json.loads(r.stdout.strip() or '[]');data=[data] if isinstance(data,dict) else data
    roots=[Path(PROJECT).resolve(),Path(project).resolve()];out=[]
    for row in data:
        if not row.get('ExecutablePath'):continue
        exe=Path(row['ExecutablePath']).resolve()
        if not any(exe.is_relative_to(root) for root in roots):continue
        p=runtime_project(exe)
        out.append({'pid':row['ProcessId'],'executable':str(exe),'project':str(p),'db':str(p/'picfactory_matrix.db')})
    return out

def check_db(path):
    p=Path(path)
    if not p.is_file():raise ValueError('目标标题库不存在：'+str(p))
    with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=1)) as c:
        cols={r[1] for r in c.execute('PRAGMA table_info(app_collections)')}
        if not {'namespace','item_key','payload','sort_order'}<=cols:raise ValueError('目标不是支持的生图工具标题库')

def status(store):
    project=project_for(store);db=project/'picfactory_matrix.db';error='';runtime=[];heartbeat=None
    try:
        check_db(db);runtime=running_factories(project)
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=1)) as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='comic_bridge_runtime'").fetchone():
                c.row_factory=sqlite3.Row;row=c.execute('SELECT * FROM comic_bridge_runtime ORDER BY heartbeat DESC LIMIT 1').fetchone();heartbeat=dict(row) if row else None
    except (ValueError,sqlite3.Error,subprocess.SubprocessError,OSError) as exc:error=str(exc)
    matches=[r for r in runtime if Path(r['db']).resolve()==db.resolve()]
    mismatch=bool(runtime) and not matches
    if mismatch:error='当前生图软件读取另一份标题库，请先绑定正在运行的软件，未向旧库继续发送。'
    return {'project':str(project),'db':str(db),'running':runtime,'matching_processes':matches,'mismatch':mismatch,'error':error,'receiver':heartbeat}

def save(store,payload):
    path=Path(str(payload.get('project',''))).resolve();check_db(path/'picfactory_matrix.db')
    # The user either selects a database directory or chooses a discovered running instance.
    store.save_settings({'push_target_project':str(path)})
    store.log('推送目标已绑定：'+str(path/'picfactory_matrix.db'),'push-target')
    return status(store)
