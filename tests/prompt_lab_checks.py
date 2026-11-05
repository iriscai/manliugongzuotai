"""Meaningful isolated lab lifecycle checks; no paid requests or production writes."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from store import Store,dumps
from worker import Worker
from prompt_lab import PromptLab,DIMENSIONS
from workbench_fixtures import TEXT


class Fake:
    def __init__(self):
        self.calls=[];self.fail_score=False;self.block=None;self.started=threading.Event();self.short=False
    def auth_status(self,_):return {'ok':True}
    def reset(self):pass
    def call(self,prompt,schema,settings,folder,on_event=None):
        self.calls.append((prompt,schema))
        if on_event:on_event({'event':'request_start'})
        ok=False
        try:
            props=schema['properties']
            assert 'categories' not in props and '本组种子：' not in prompt
            self.started.set()
            if self.block:assert self.block.wait(10)
            if self.fail_score:self.fail_score=False;raise RuntimeError('模拟写文失败')
            if 'content_status' in props:
                body='港区安排了两次船舶调度。后勤人员核对物资，船员按既定时间办理交接。'*14
                result={'category':'军事','content_status':'ready','title':'港区船舶如何安排调度','article':'<p>'+('调度记录。' if self.short else body)+'</p>','draft_title':'调度初稿','draft_article':'<p>'+body+'</p>','edit_notes':['按事件顺序写明交接'],'material_notes':[]}
            elif 'generation_audit' in props:
                title='本地测试用的搞笑标题，仅验证程序中的标题长度和字段传递，不能作为实际创作质量样例发出，具体内容只作测试。'
                story='周末同事约我吃饭，我说：“今天我请客。”他一口气点了三盘肉。我问：“你平时也吃这么多？”他摇头：“平时我请客。”'
                result={'category':'搞笑','title':title,'article':story,'quality_score':{'completeness':90,'reversal':90,'fun':90,'reason':'本地测试夹具，不是质量评价','evidence':['平时我请客'],'risks':[]},'generation_audit':{'draft':story,'r1_text':story,'r2_text':story,'r1_notes':['本地夹具稿件'],'r2_notes':['本地夹具稿件'],'t1_titles':[title,title.replace('本地','程序')],'t1_short_reasons':['程序测试标题','程序测试标题'],'t1_choice':1,'t1_article':story,'t2_notes':['本地夹具稿件'],'material_mode':'keep_joke','retained_core':'请客时点菜的反差','ending_link':{'setup':'今天我请客','trigger':'你平时也吃这么多','punchline':'平时我请客。”'}}}
            else:
                result={'category':'生活','title':'图书角借阅安排','article':'短稿' if self.short else TEXT}
            if 'assessment' in props:
                result['assessment']={**{k:90 for k in DIMENSIONS},'reason':'本机夹具评分','evidence':[result['title']],'risks':[]}
            Path(folder).mkdir(parents=True,exist_ok=True)
            (Path(folder)/'answer.json').write_text(dumps(result),encoding='utf8')
            ok=True;return result
        finally:
            if on_event:on_event({'event':'request_finish','ok':ok,'usage':{'input_tokens':100,'output_tokens':50,'total_tokens':150}})


def wait(w):w.thread.join(15);assert not w.thread.is_alive()
def payload(lab,category='生活'):
    d=lab.draft(category);source=lab.random({'category':category})
    return {**d,'material_id':source['source']['material_id'],'source_hash':source['source_hash'],'client_id':uuid.uuid4().hex}
def snap(s,table):
    with s.connect() as c:return [list(r) for r in c.execute('SELECT * FROM '+table+' ORDER BY 1')]


with tempfile.TemporaryDirectory(prefix='prompt-lab-check-') as temp:
    s=Store(Path(temp)/'data',ROOT/'resources');s.save_settings({'provider':'codex'})
    for category in ('生活','军事','搞笑'):
        f=Path(temp)/(category+'.csv');f.write_text('标题,正文,分类\n'+category+'图书角开放安排,图书角每天18时至20时开放。借书还书登记。,'+category+'\n',encoding='utf8');s.import_file({'path':str(f)})
    w=Worker(s);p=Fake();w.provider=p;lab=PromptLab(s,w)
    tables=('materials','results','extractions','runs','run_items','prompts','prompt_history','settings','result_pushes')
    before={t:snap(s,t) for t in tables}
    d=payload(lab);d['extract_rule']='测试提炼独有要求甲';d['write_rule']+='\n测试写文独有要求乙'
    saved=lab.save_draft(d);assert saved['revision']==1
    try:lab.save_draft(d);raise AssertionError('stale draft accepted')
    except ValueError:pass
    rid=lab.start(d)['id'];wait(w);r=lab.detail(rid)
    assert r['state']=='completed',r['error'];assert r['assessment']['final_total']==90
    assert r['usage']['requests']==1 and r['usage']['total_tokens']==150 and len(p.calls)==1
    assert '测试写文独有要求乙' in p.calls[0][0] and '测试提炼独有要求甲' not in p.calls[0][0]
    assert lab.start(d)=={'id':rid,'reused':True};assert len(p.calls)==1
    assert 'settings' not in r and 'api_key_encrypted' not in r
    plan=lab.save_plan({'id':rid});assert lab.save_plan({'id':rid})['id']==plan['id']
    assert lab.plans('生活')['rows'][0]['config']['write_rule']==d['write_rule']
    p.fail_score=True
    rid3=lab.start({**d,'client_id':uuid.uuid4().hex})['id'];wait(w)
    assert lab.detail(rid3)['state']=='failed'
    n=len(p.calls);lab.resume(rid3);wait(w)
    assert len(p.calls)==n+1 and lab.detail(rid3)['state']=='completed'
    # A pause while a response is in flight still saves its article and same-call score.
    p.block=threading.Event();p.started.clear();rid4=lab.start({**d,'client_id':uuid.uuid4().hex})['id'];assert p.started.wait(5)
    w.pause();n=len(p.calls);p.block.set();wait(w);p.block=None
    assert len(p.calls)==n and lab.detail(rid4)['state']=='completed'
    # Military profile/HTML policies survive the lab. Format failures stay visible and cannot be saved as successful plans.
    military=payload(lab,'军事');rid5=lab.start(military)['id'];wait(w);mr=lab.detail(rid5)
    assert mr['state']=='completed',mr['error'];assert mr['article']['writing_profile']=='military_ip_C_v2' and not mr['validation']
    assert 400<=mr['article']['char_count']<=600
    funny=payload(lab,'搞笑')
    for kind in ('extract','write'):
        funny[kind+'_variant']='J';funny[kind+'_rule']=next(p['content'] for p in s.prompts('搞笑') if p['variant']=='J' and p['kind']==kind)
    n=len(p.calls);ridfun=lab.start(funny)['id'];wait(w);fr=lab.detail(ridfun)
    assert fr['state']=='completed' and not fr['validation'],fr
    assert len(p.calls)==n+1 and fr['assessment']['final_total']==95 and fr['assessment']['method']=='生成响应内评分'
    p.short=True;rid6=lab.start({**d,'client_id':uuid.uuid4().hex})['id'];wait(w);invalid=lab.detail(rid6)
    assert invalid['article'] and invalid['validation'] and invalid['assessment']
    try:lab.save_plan({'id':rid6});raise AssertionError('invalid plan saved')
    except ValueError:pass
    for t in tables:assert snap(s,t)==before[t],t+' changed by lab'
    # Empty lanes and altered source snapshots are rejected before spending requests.
    try:lab.random({'category':'体育'});raise AssertionError('empty lane sampled')
    except ValueError:pass
    n=len(p.calls)
    try:lab.start({**d,'client_id':uuid.uuid4().hex,'source_hash':'old-source'});raise AssertionError('stale material accepted')
    except ValueError:pass
    assert len(p.calls)==n
    Store(s.root,ROOT/'resources');assert len(lab.plans('生活')['rows'])==1
    manual=lab.create_plan({**military,'name':'军事 C 测试草稿'})
    edited={**military,'write_rule':military['write_rule']+'\n测试方案修改'}
    lab.update_plan({**edited,'plan_id':manual['id'],'plan_revision':1})
    rows=lab.plans('军事')['rows']
    assert len(rows)==1 and rows[0]['id']==manual['id'] and rows[0]['score'] is None
    assert rows[0]['config']['write_rule']==edited['write_rule']
    assert snap(s,'prompts')==before['prompts']
    write_c=next(p for p in s.prompts('军事') if p['kind']=='write' and p['variant']=='C')
    formal={**military,'write_rule':military['write_rule']+'\n正式写文修改','formal_revision':write_c['revision']}
    lab.save_formal(formal)
    assert next(p for p in s.prompts('军事') if p['id']==write_c['id'])['content']==formal['write_rule']
    # An existing legacy extraction does not route this job or add a second model call.
    source=d['material_id']
    with s.connect() as c:
        c.execute("UPDATE prompts SET enabled=0 WHERE kind='extract'")
        c.execute("INSERT INTO extractions(material_id,category,angle,source_hash,data_json,current,extraction_mode) VALUES(?,'历史','旧主题',?,'{\"eligible\":true}',1,'multi')",(source,'legacy'))
    p.short=False;n=len(p.calls)
    preview=w.start({'mode':'both','preview':True,'extraction_mode':'multi','ids':[source]})
    assert preview['extraction_mode']=='direct' and preview['ids']==[source]
    run=w.start({'mode':'write','ids':[source]});wait(w)
    assert len(p.calls)==n+1
    with s.connect() as c:
        result=c.execute('SELECT id,category FROM results WHERE material_id=?',(source,)).fetchall()
        assert len(result)==1 and result[0]['category']=='生活'
        assert c.execute('SELECT stage FROM model_requests WHERE run_id=?',(run['run_id'],)).fetchone()[0]=='write'
    assert not w.start({'mode':'write','preview':True,'ids':[source]})['ids']
    n=len(p.calls);w.regenerate({'ids':[result[0]['id']]});wait(w);assert len(p.calls)==n+1
    with s.connect() as c:assert c.execute('SELECT count(*) FROM results WHERE material_id=?',(source,)).fetchone()[0]==1
    from model_queue import ModelQueue
    queue=ModelQueue(s,w)
    n=len(p.calls)
    queued=queue.enqueue({'mode':'write','scope':'selected','ids':[military['material_id']],'limit':1})
    queue.tick();wait(w);queue.tick();queue.tick()
    assert len(p.calls)==n+1
    assert queue.detail(queued['job_id'])['items'][0]['state']=='done'
    from store import now,digest
    mid=funny['material_id']
    with s.connect() as c:
        m=c.execute('SELECT title,body FROM materials WHERE id=?',(mid,)).fetchone()
        old={'settings':{**s.settings(),'funny_write_variant':'J'},'prompts':s.prompts(),'extraction_mode':'multi','output_mode':'article'}
        for rule in old['prompts']:
            if rule['category']=='搞笑' and rule['variant']=='J':rule['enabled']=1
        c.execute("INSERT INTO runs(id,mode,state,total,snapshot_json,created_at,updated_at) VALUES('old-run','both','paused',1,?,?,?)",(dumps(old),now(),now()))
        c.execute("INSERT INTO run_items(run_id,material_id,source_hash) VALUES('old-run',?,?)",(mid,digest(m['title']+'\n'+m['body'])))
    n=len(p.calls);w.resume('old-run');wait(w)
    assert len(p.calls)==n+1
    with s.connect() as c:
        assert c.execute("SELECT mode,state FROM runs WHERE id='old-run'").fetchone()[:]==('write','completed')
        article=c.execute('SELECT category FROM results WHERE material_id=?',(mid,)).fetchone()
        assert article and article[0]=='搞笑', c.execute("SELECT error FROM run_items WHERE run_id='old-run'").fetchone()[0]
print(dumps({'ok':True,'formal_one_call_per_source':True,'original_category_only':True,'lab_one_call_with_score':True,'no_extraction_rules_required':True,'external_calls':0}))
