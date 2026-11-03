"""Shared isolated workbench fixtures; never call an external model."""
import csv,json,sys,tempfile,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,dumps
from worker import Worker
from schemas import SEED_EXTRACT,ARTICLE
from pipeline_catalog import writing_detail,run_summary
from workflow_management import detail,edit,restore_version,restore_cleared,selected_ids
from usage_budget import summary
from title_push import signature,PROJECT,decorate
from result_cleanup import clear_pushed
TEXT='\n\n'.join(['孩子走进图书角。','先看看开放时间。','每天18时至20时开放。','借书时登记书名。','还书时也要登记。','老师让孩子轮流讲故事。','家长记下孩子的问题。','走道留出通行空间。'])
class Fake:
    def __init__(self):self.calls=[];self.fail=False;self.edition=1;self.lock=threading.Lock();self.active=0;self.peak=0;self.started=threading.Event();self.release=None
    def auth_status(self,_):return {'ok':True}
    def call(self,prompt,schema,settings,folder,on_event=None):
        if on_event:on_event({'event':'request_start'})
        with self.lock:self.active+=1;self.peak=max(self.peak,self.active);self.calls.append(schema)
        ok=False
        try:
            if schema is SEED_EXTRACT:
                src=json.loads(prompt.split('\n统一输入素材：',1)[1]);e=src['body'][0]
                out={'categories':[{'category':cat,'topic':('开放时间' if cat=='生活' else '轮流讲故事'),'angle':('开放时间' if cat=='生活' else '轮流讲故事'),'reason':'适配','main_point':('每天18时至20时开放' if cat=='生活' else '老师让孩子轮流讲故事'),'elements':[{'name':'登记','content':e['text'],'evidence_ids':[e['id']]}],'omissions':[],'visual_nodes':[]} for cat in ['生活','教育']],'reason':'适配两类'}
            else:
                assert schema is ARTICLE;self.started.set()
                if self.release:self.release.wait(8)
                if self.fail:raise RuntimeError('模拟本篇生成失败')
                seed=json.loads(prompt.split('本组种子：',1)[1].split('\n本条原始素材：',1)[0]);out={'category':seed['category'],'title':seed['category']+'图书角第'+str(self.edition)+'版','article':TEXT}
            time.sleep(.035);ok=True;return out
        finally:
            with self.lock:self.active-=1
            if on_event:on_event({'event':'request_finish','ok':ok,'usage':{'input_tokens':100,'output_tokens':50,'total_tokens':150}})
    def reset(self):pass
def wait(w):w.thread.join(20);assert not w.thread.is_alive()
def seed(path,n=1):
    s=Store(path/'data',ROOT/'resources');s.save_settings({'allowed_categories':['生活','教育'],'process_workers':4,'write_workers':8,'global_max_concurrency':2})
    file=path/'input.csv'
    with file.open('w',encoding='utf8',newline='') as f:
        writer=csv.writer(f);writer.writerow(['标题','正文','分类']);writer.writerows([[f'图书角{i}','图书角每天18时至20时开放。老师让孩子轮流讲故事。编号'+str(i),'生活'] for i in range(n)])
    s.import_file({'path':str(file)});w=Worker(s);p=Fake();w.provider=p;return s,w,p
