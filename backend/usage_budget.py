"""Atomic daily request reservations and reported (never guessed) token usage."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

def day():return datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
def now():return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')

def install_schema(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS model_requests(
      id INTEGER PRIMARY KEY,run_id TEXT,material_id INTEGER,stage TEXT,day TEXT NOT NULL,
      state TEXT NOT NULL,provider TEXT,model TEXT,input_tokens INTEGER,output_tokens INTEGER,total_tokens INTEGER,
      created_at TEXT,completed_at TEXT);
      CREATE INDEX IF NOT EXISTS idx_requests_day ON model_requests(day,id);
      CREATE INDEX IF NOT EXISTS idx_requests_run ON model_requests(run_id,id);''')
    c.execute("UPDATE model_requests SET state='interrupted',completed_at=? WHERE state='running'",(now(),))

def reserve(store,rid,mid,stage,settings,limits_run_override=None):
    from providers import ProviderLimit
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        limits={r['key']:json.loads(r['value']) for r in c.execute("SELECT key,value FROM settings WHERE key IN ('daily_request_limit','daily_token_limit')")}
        used=c.execute('SELECT COUNT(*) n,coalesce(SUM(total_tokens),0) tokens FROM model_requests WHERE day=?',(day(),)).fetchone()
        record=c.execute('SELECT snapshot_json FROM runs WHERE id=?',(rid,)).fetchone()
        limits_run=json.loads(record['snapshot_json']).get('task_budget',{}) if record else {}
        if limits_run_override is not None:limits_run=limits_run_override
        used_run=c.execute('SELECT count(*) n,coalesce(sum(total_tokens),0) tokens FROM model_requests WHERE run_id=?',(rid,)).fetchone()
        if limits_run.get('request_limit',0) and used_run['n']>=limits_run['request_limit']:raise ProviderLimit('已达到本轮请求上限，成果和种子已保留，可提高本轮上限续跑')
        if limits_run.get('token_limit',0) and used_run['tokens']>=limits_run['token_limit']:raise ProviderLimit('已达到本轮已报告Token上限，成果和种子已保留')
        if limits.get('daily_request_limit',0) and used['n']>=limits['daily_request_limit']:raise ProviderLimit('已达到今日请求额度；已完成内容保留，可调整额度或次日续跑')
        if limits.get('daily_token_limit',0) and used['tokens']>=limits['daily_token_limit']:raise ProviderLimit('已达到今日已报告Token额度；已完成内容保留，可调整额度或次日续跑')
        return c.execute('INSERT INTO model_requests(run_id,material_id,stage,day,state,provider,model,created_at) VALUES(?,?,?,?,?,?,?,?)',
          (rid,mid,stage,day(),'running',settings.get('provider'),settings.get('api_model') if settings.get('provider')=='api' else settings.get('model',''),now())).lastrowid

def finish(store,request_id,event):
    usage=event.get('usage') or {};inp=usage.get('input_tokens',usage.get('prompt_tokens'));out=usage.get('output_tokens',usage.get('completion_tokens'));total=usage.get('total_tokens')
    def valid(n):return n if type(n) is int and n>=0 else None
    inp,out,total=valid(inp),valid(out),valid(total)
    if total is None and inp is not None and out is not None:total=inp+out
    with store.connect() as c:c.execute('UPDATE model_requests SET state=?,input_tokens=?,output_tokens=?,total_tokens=?,completed_at=? WHERE id=?',
      ('completed' if event.get('ok') else 'failed',inp,out,total,now(),request_id))

def summary(c,rid=None):
    clause='run_id=?' if rid else 'day=?';arg=rid or day()
    r=c.execute('''SELECT COUNT(*) requests,coalesce(SUM(state='running'),0) active,
      coalesce(SUM(state='failed'),0) failed,coalesce(SUM(input_tokens),0) input_tokens,
      coalesce(SUM(output_tokens),0) output_tokens,coalesce(SUM(total_tokens),0) total_tokens,
      coalesce(SUM(total_tokens IS NULL),0) unknown_usage FROM model_requests WHERE '''+clause,(arg,)).fetchone()
    return dict(r)
