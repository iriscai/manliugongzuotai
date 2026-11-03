"""Prove one extraction response feeds several separately grounded articles."""
import copy,csv,json,sys,tempfile,threading,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,now,dumps
from worker import Worker
from schemas import MULTI_EXTRACT,ROUTE,EXTRACT,WRITE
from multi_extraction import compile_rules,make_prompt,validate_batch

BODY='社区图书角每天18时至20时开放。借书时登记书名和日期，还书后划掉对应记录。家长带孩子参加阅读活动。老师组织孩子轮流讲述书里的故事，家长负责记录孩子提出的问题。'
CATS=['生活','教育','育儿']
def answer():
    return {'evidence':[{'id':'E1','field':'body','quote':'每天18时至20时开放'},{'id':'E2','field':'body','quote':'老师组织孩子轮流讲述书里的故事'},{'id':'E3','field':'body','quote':'家长负责记录孩子提出的问题'}],
      'categories':[{'category':cat,'topic':['图书角借还登记安排','儿童阅读活动的组织','亲子共同参与阅读'][i],'angle':cat+'独立角度','reason':'对应规则适配','main_point':['借还登记流程与开放时段','老师如何组织孩子讲述故事','家长记录孩子提出的问题'][i],
       'elements':[{'name':'开放时间' if i==0 else '阅读参与','content':['每天18时至20时开放','老师组织孩子轮流讲述书里的故事','家长负责记录孩子提出的问题'][i],'evidence_ids':[['E1'],['E2'],['E3']][i]}],
       'omissions':[],'visual_nodes':['图书角','借书登记'],'needs_verification':[],'verified_additions':[]} for i,cat in enumerate(CATS)],'reason':''}

class Provider:
    def __init__(self,blocked=False,pause=False,bad=False,empty=False,fail_write=False):
        self.calls=[];self.lock=threading.Lock();self.worker=None;self.blocked=blocked;self.pause=pause;self.bad=bad;self.empty=empty;self.fail_write=fail_write;self.active={'extract':0,'write':0};self.peak={'extract':0,'write':0}
    def auth_status(self,_):return {'ok':True}
    def call(self,prompt,schema,settings,folder,on_event=None):
        stage='multi' if schema is MULTI_EXTRACT else 'write' if schema is WRITE else 'route' if schema is ROUTE else 'extract';kind='write' if schema is WRITE else 'extract'
        with self.lock:self.calls.append((stage,prompt));self.active[kind]+=1;self.peak[kind]=max(self.peak[kind],self.active[kind])
        try:
            time.sleep(.06)
            if schema is MULTI_EXTRACT:
                assert BODY in prompt and prompt.count(BODY)==1
                assert all('【'+cat+' / ' in prompt for cat in CATS)
                data=answer()
                if self.blocked:data['categories'][1]['needs_verification']=['核实参与年龄与活动安排']
                if self.bad:data['categories'][1]['elements'][0]['evidence_ids']=['OTHER_ROW']
                if self.empty:data={'evidence':[],'categories':[],'reason':'本行不适配'}
            elif schema is WRITE:
                assert '本篇目标分类：' in prompt
                if '"elements"' in prompt:assert '"evidence_ids"' in prompt and '"evidence"' in prompt
                with self.lock:fail=self.fail_write;self.fail_write=False
                if fail:raise RuntimeError('fixture one write failure')
                data={'title':'图书角阅读提示','short_text':'图书角每天18时至20时开放。家长带孩子参加阅读，借还书时登记。','frames':[{'number':1,'purpose':'开放时间','scene':'图书角','caption':'每天18时至20时开放','dialogue':[],'visible_labels':[],'image_prompt':'图书角借书示意图'}],'post_text':'','notice':'虚构功能测试','genre':'生活图解','adaptations':[]}
            elif schema is ROUTE:data={'routes':[{'category':'生活','angle':'开放时间','reason':'适配','quote':'每天18时至20时开放'}],'reason':''}
            elif schema is EXTRACT:data={'eligible':True,'reason':'支持','main_point':'开放时间','facts':[{'fact':'开放时间','quote':'每天18时至20时开放'}],'omissions':[],'visual_nodes':[],'needs_verification':[],'verified_additions':[]}
            else:raise AssertionError('Unexpected schema')
            p=Path(folder);p.mkdir(parents=True,exist_ok=True);(p/'answer.json').write_text(dumps(data),encoding='utf8')
            if schema is MULTI_EXTRACT and self.pause:self.pause=False;self.worker.pause()
            return data
        finally:
            with self.lock:self.active[kind]-=1
    def terminate(self):pass

def seed(root,n=1):
    s=Store(root/'data',ROOT/'resources');s.save_settings({'allowed_categories':CATS,'process_workers':4,'write_workers':8})
    p=root/'input.csv'
    with p.open('w',encoding='utf8',newline='') as f:
        w=csv.writer(f);w.writerow(['标题','正文','分类']);w.writerows([[f'图书角隔离素材{i}',BODY,'生活'] for i in range(n)])
    s.import_file({'path':str(p)});return s
def attach(s,p):w=Worker(s);w.provider=p;p.worker=w;return w
def wait(w):w.thread.join(30);assert not w.thread.is_alive(),'Worker stuck'
def count(p,stage):return sum(s==stage for s,_ in p.calls)

with tempfile.TemporaryDirectory(prefix='multi-extract-') as tmp:
    root=Path(tmp);s=seed(root/'base');p=Provider();w=attach(s,p);r=w.start({'mode':'both','limit':1});wait(w)
    assert count(p,'multi')==1 and count(p,'route')==0 and count(p,'extract')==0 and count(p,'write')==3,p.calls
    topics={(item['category'],item['topic']) for item in answer()['categories']}
    writing_pairs={(prompt.split('本篇目标分类：')[-1].splitlines()[0],prompt.split('本篇唯一主题：')[-1].splitlines()[0]) for stage,prompt in p.calls if stage=='write'}
    assert writing_pairs==topics,'Topic/category pairing changed between extraction and writing'
    m=s.material(1);assert len(m['extractions'])==3 and len(m['results'])==3 and len(m['extraction_batches'])==1
    assert all(json.loads(e['data_json'])['elements'] for e in m['extractions'])
    assert s.stats()['runs'][0]['progress']['multi_batches']==1
    # All source references must match the declared field, and saves are all-or-nothing.
    src={'title':'测试','body':BODY}
    for mutator in [lambda x:x['evidence'][0].update(quote='其他行内容'),lambda x:x['categories'][0].update(category='不存在分类'),lambda x:x['categories'].append(copy.deepcopy(x['categories'][0])),lambda x:x['categories'][0].update(elements=[]),lambda x:[v.update(topic=v['category']+'同一个主题') for v in x['categories']],lambda x:[v.update(main_point=v['category']+'同一重点') for v in x['categories']]]:
        bad=answer();mutator(bad)
        try:validate_batch(bad,src,CATS);raise AssertionError('Bad evidence/categories accepted')
        except ValueError:pass
    s=seed(root/'bad');p=Provider(bad=True);w=attach(s,p);w.start({'mode':'both','limit':1});wait(w)
    with s.connect() as c:assert c.execute('SELECT count(*) FROM extractions').fetchone()[0]==0 and c.execute('SELECT count(*) FROM extraction_batches').fetchone()[0]==0
    assert count(p,'write')==0 and s.stats()['runs'][0]['errors']==1
    s=seed(root/'blocked');p=Provider(blocked=True);w=attach(s,p);w.start({'mode':'both','limit':1});wait(w)
    assert count(p,'multi')==1 and count(p,'write')==2
    assert s.stats()['writing']['needs_review']==1 and s.stats()['counts']['result_count']==2
    s=seed(root/'resume');p=Provider(pause=True);w=attach(s,p);r=w.start({'mode':'both','limit':1});wait(w)
    assert len(s.material(1)['extractions'])==3 and s.stats()['runs'][0]['state']=='paused'
    w.resume(r['run_id']);wait(w);assert count(p,'multi')==1 and count(p,'write')==3 and len(s.material(1)['results'])==3
    s=seed(root/'write-only');p=Provider();w=attach(s,p);w.start({'mode':'extract','limit':1});wait(w)
    assert count(p,'multi')==1 and count(p,'write')==0
    w.start({'mode':'write','limit':1});wait(w);assert count(p,'multi')==1 and count(p,'write')==3
    s=seed(root/'retry');p=Provider(fail_write=True);w=attach(s,p);r=w.start({'mode':'both','limit':1});wait(w)
    assert s.stats()['counts']['result_count']==2
    w.retry(r['run_id']);wait(w);assert s.stats()['counts']['result_count']==3 and count(p,'multi')==1 and count(p,'write')==4
    s=seed(root/'empty');p=Provider(empty=True);w=attach(s,p);w.start({'mode':'extract','limit':1});wait(w)
    with s.connect() as c:c.execute("UPDATE materials SET state='pending' WHERE id=1")
    w.start({'mode':'extract','limit':1});wait(w);assert count(p,'multi')==1,'Empty valid response not cached'
    s=seed(root/'parallel',8);p=Provider();w=attach(s,p);w.start({'mode':'both','limit':8});wait(w)
    assert count(p,'multi')==8 and count(p,'write')==24 and s.stats()['counts']['result_count']==24
    assert 2<=p.peak['extract']<=4 and 2<=p.peak['write']<=8,p.peak
    peaks=p.peak.copy()
    # Pre-upgrade snapshots retain the legacy route/extract contract on resume.
    s=seed(root/'legacy');p=Provider();w=attach(s,p);rid=uuid.uuid4().hex[:12]
    snap={'settings':s.settings(),'prompts':s.prompts(),'skill':'','categories':json.loads((ROOT/'resources/categories.json').read_text(encoding='utf8'))}
    with s.connect() as c:
        c.execute('INSERT INTO runs(id,mode,state,total,snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(rid,'both','paused',1,dumps(snap),now(),now()))
        c.execute('INSERT INTO run_items(run_id,material_id) VALUES(?,?)',(rid,1))
    w.resume(rid);wait(w);assert [stage for stage,_ in p.calls]==['route','extract','write']
report={'ok':True,'three_distinct_topics_enforced':True,'topic_category_pairs_preserved':True,'three_categories':{'old_extraction_calls':4,'new_extraction_calls':1,'writing_calls':3,'old_total':7,'new_total':4},'shared_evidence_validated':True,'atomic_batch_save':True,'one_blocked_category_does_not_block_others':True,'pause_retry_and_write_only_reuse':True,'legacy_snapshot_compatible':True,'observed_peaks':peaks,'external_model_calls':0,'production_changes':0}
(ROOT/'build/multi-extraction-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(dumps(report))
