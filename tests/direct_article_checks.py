"""Direct seed creation produces finished category/title/article rows, no review gate."""
import csv,json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,dumps,now,digest
from worker import Worker
from schemas import SEED_EXTRACT,ARTICLE
from article_flow import normalize_article
BODY='图书角每天18时至20时开放。\n老师让孩子轮流讲故事。\n家长记录孩子的问题。\n阅读区留出通行空间。'
CATS=['生活','教育','育儿','家居家装'];TOPICS=['开放时间','孩子轮流讲故事','家长记录问题','阅读区空间布置']
ARTICLE_TEXT='\n\n'.join(['图书角每天开放。','开放时间是18时至20时。','孩子在图书角讲故事。','老师让孩子轮流讲。','家长记录孩子的问题。','孩子的问题被记下来。','阅读区留出通行空间。','通道留给来往的人。'])
class Provider:
    def __init__(self,n=1,pause=False):self.n=n;self.pause=pause;self.calls=[];self.worker=None
    def auth_status(self,_):return {'ok':True}
    def call(self,prompt,schema,settings,folder,on_event=None):
        self.calls.append(schema);time.sleep(.02)
        if schema is SEED_EXTRACT:
            src=json.loads(prompt.split('\n统一输入素材：',1)[1])
            data={'categories':[{'category':CATS[i],'topic':TOPICS[i],'angle':TOPICS[i]+'的安排','reason':'适配','main_point':src['body'][i]['text'],'elements':[{'name':'主题元素','content':src['body'][i]['text'],'evidence_ids':[src['body'][i]['id']]}],'omissions':[],'visual_nodes':[]} for i in range(self.n)],'reason':'依素材确定N'}
        elif schema is ARTICLE:
            seed=json.loads(prompt.split('本组种子：',1)[1].split('\n本条原始素材：',1)[0]);assert 'needs_verification' not in seed
            assert seed['original_title']=='图书角活动'
            data={'category':seed['category'],'title':seed['topic'],'article':ARTICLE_TEXT}
        else:raise AssertionError('Unexpected legacy schema')
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);(folder/'answer.json').write_text(dumps(data),encoding='utf8')
        if schema is SEED_EXTRACT and self.pause:self.pause=False;self.worker.pause()
        return data
    def terminate(self):pass
def seed(root):
    s=Store(root/'data',ROOT/'resources');s.save_settings({'allowed_categories':CATS,'process_workers':4,'write_workers':8})
    p=root/'input.csv'
    with p.open('w',encoding='utf8',newline='') as f:w=csv.writer(f);w.writerow(['标题','正文','分类']);w.writerow(['图书角活动',BODY,'生活'])
    s.import_file({'path':str(p)});return s
def wait(w):w.thread.join(20);assert not w.thread.is_alive()
def attach(s,p):w=Worker(s);w.provider=p;p.worker=w;return w

observed=[]
with tempfile.TemporaryDirectory(prefix='direct-article-') as tmp:
    root=Path(tmp)
    for n in [0,1,2,4]:
        s=seed(root/str(n));p=Provider(n);w=attach(s,p);w.start({'mode':'both','limit':1});wait(w)
        assert p.calls.count(SEED_EXTRACT)==1 and p.calls.count(ARTICLE)==n
        rows=s.list_results({})['rows'];assert len(rows)==n
        for row in rows:
            assert row['state']=='成品' and row['article'] and row['frame_count']==0
            assert row['article']==ARTICLE_TEXT
            assert json.loads(row['data_json'])['paragraph_count']==8
            assert json.loads(row['data_json'])['output_kind']=='article'
        out=root/f'export-{n}.json';s.export(out,'results');data=json.loads(out.read_text(encoding='utf8'))
        assert all(set(row)=={'赛道','标题','文章'} for row in data)
        assert all(row['文章']==ARTICLE_TEXT for row in data)
        observed.append({'n':n,'article_calls':n,'finished_articles':len(rows)})
    # Historical verification notes remain in source records, but no longer prevent writing.
    s=seed(root/'old-notes');p=Provider();w=attach(s,p);m=s.material(1)
    data={'eligible':True,'main_point':'图书角活动','facts':[{'fact':'开放时间','quote':'每天18时至20时开放'}],'needs_verification':['旧版核实备注'],'verified_additions':[]}
    with s.connect() as c:
        c.execute('INSERT INTO extractions(material_id,category,angle,source_hash,rule_variant,prompt_text,data_json,created_at) VALUES(?,?,?,?,?,?,?,?)',(1,'生活','开放时间',digest(m['title']+'\n'+m['body']),'A','旧提炼',dumps(data),now()))
        c.execute("UPDATE materials SET state='needs_review' WHERE id=1")
    assert s.stats()['writing']['ready']==1 and s.stats()['writing']['needs_review']==0
    w.start({'mode':'write','limit':1});wait(w);assert p.calls==[ARTICLE] and s.material(1)['state']=='written'
    assert json.loads(s.material(1)['extractions'][0]['data_json'])['needs_verification']==['旧版核实备注']
    s=seed(root/'pause');p=Provider(4,pause=True);w=attach(s,p);r=w.start({'mode':'both','limit':1});wait(w)
    assert len(s.material(1)['extractions'])==4 and not s.material(1)['results']
    w.resume(r['run_id']);wait(w);assert p.calls.count(SEED_EXTRACT)==1 and p.calls.count(ARTICLE)==4
    try:normalize_article({'category':'其他','title':'测试','article':'正文'},'生活');raise AssertionError('Wrong category accepted')
    except ValueError:pass
    try:normalize_article({'category':'生活','title':'测试','article':'字'*301},'生活');raise AssertionError('Overlong article accepted')
    except ValueError:pass
report={'ok':True,'observed':observed,'old_verification_notes_do_not_block':True,'existing_extractions_reused':True,'output_fields':['赛道','标题','文章'],'state':'成品','frames_required':False,'external_model_calls':0}
(ROOT/'build/direct-article-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(dumps(report))
