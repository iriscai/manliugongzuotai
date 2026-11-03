import copy
import csv
import gc
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from store import Store,chars
from worker import Worker
from providers import protect
from schemas import ROUTE,EXTRACT,WRITE
from source_fetch import Text,clean


class FakeProvider:
    def __init__(self, pause_at=None):self.calls=[];self.pause_at=pause_at;self.worker=None
    def auth_status(self,_):return {'ok':True,'message':'fixture only'}
    def call(self,prompt,schema,settings,folder,on_event=None):
        self.calls.append(schema)
        if schema is ROUTE:result={'routes':[{'category':'生活','angle':'开放时间与借还步骤','reason':'生活服务信息','quote':'每天18时至20时开放'}],'reason':''}
        elif schema is EXTRACT:result={'eligible':True,'reason':'来源完整','main_point':'开放与借还登记','facts':[{'fact':'每天18时至20时开放','quote':'每天18时至20时开放'}],'omissions':[],'visual_nodes':['入口','借书','还书'],'needs_verification':[],'verified_additions':[]}
        elif schema is WRITE:result={'title':'图书角借还小提示','short_text':'图书角每天18时至20时开放。借书登记书名和日期，还书后划掉对应记录。','frames':[{'number':1,'purpose':'开放时间','scene':'入口','caption':'每天18时至20时开放。','dialogue':[],'visible_labels':[],'image_prompt':'图书角入口及时间说明'},{'number':2,'purpose':'登记','scene':'登记本','caption':'借书登记书名和日期，还书后划掉对应记录。','dialogue':[],'visible_labels':[],'image_prompt':'借还登记示意'}],'post_text':'','notice':'虚构示例','genre':'生活图解','adaptations':[]}
        else:raise AssertionError('unknown schema')
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);(folder/'answer.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf8')
        if self.pause_at is schema:self.worker.pause();self.pause_at=None
        return result
    def terminate(self):pass


def wait(worker):
    worker.thread.join(20)
    assert not worker.thread.is_alive(),'worker did not finish'


checks=[]
with tempfile.TemporaryDirectory(prefix='comic-workbench-tests-') as temp:
    temp=Path(temp);store=Store(temp/'data',ROOT/'resources')
    assert len(store.prompts())==148
    checks.append('37分类、74提炼规则、74写文提示词完整载入')
    source=temp/'fixture.csv'
    with source.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['标题','正文','领域','链接']);w.writerow(['图书角新时间','图书角每天18时至20时开放。借书登记书名和日期，还书后划掉对应记录。本条为虚构测试素材。','生活','https://example.com/fixture']);w.writerow(['仅标题，不能当全文','','生活','https://example.com/missing'])
    result=store.import_file({'path':str(source)})
    assert result['added']==2 and store.stats()['counts']['needs_source']==1
    repeated=store.import_file({'path':str(source)})
    assert repeated['duplicates']==1 and repeated['added']==1
    assert store.stats()['counts']['total']==3
    checks.append('有正文后按标题+正文去重，缺正文先保留待抓取；未将标题当作全文')
    mid=store.list_materials({'state':'pending'})['rows'][0]['id']
    worker=Worker(store);fake=FakeProvider(EXTRACT);fake.worker=worker;worker.provider=fake
    run=worker.start({'mode':'both','ids':[mid],'limit':1});wait(worker)
    assert store.stats()['runs'][0]['state']=='paused'
    assert store.stats()['counts']['extraction_count']==1
    assert store.stats()['counts']['result_count']==0
    assert len(fake.calls)==2
    checks.append('提炼后暂停真实停止写文，并保存提炼结果')
    worker.resume(run['run_id']);wait(worker)
    assert len(fake.calls)==3 and fake.calls[-1] is WRITE
    assert store.stats()['counts']['result_count']==1
    assert store.material(mid)['state']=='written'
    checks.append('续跑复用已保存提炼；未重发路由或提炼模型请求')
    result=store.list_results({})['rows'][0]
    data=json.loads(result['data_json']);assert data['actual_images']==0
    bad=copy.deepcopy(data);bad['frames'][0]['caption']='字'*301
    try:Worker.check_result(bad);raise AssertionError('overflow accepted')
    except ValueError:pass
    bad=copy.deepcopy(data);bad['frames']*=6
    try:Worker.check_result(bad);raise AssertionError('too many images accepted')
    except ValueError:pass
    checks.append('字数、分镜数量越界拒绝；分镜未冒充实际成图')
    original=store.prompts('生活')[0]
    store.save_prompt({'id':original['id'],'content':original['content']+'\n测试版本'})
    assert store.prompts('生活')[0]['revision']==2
    with store.connect() as c: snapshot=json.loads(c.execute('SELECT snapshot_json FROM runs WHERE id=?',(run['run_id'],)).fetchone()[0])
    assert next(x for x in snapshot['prompts'] if x['id']==original['id'])['revision']==1
    checks.append('规则修改版本化；已启动任务快照未被倒写')
    store.save_body(mid,'图书角改为每周日开放。本条为修订的虚构测试素材。')
    assert store.material(mid)['state']=='pending' and store.stats()['counts']['result_count']==0
    assert len(store.material(mid)['results'])==1
    checks.append('正文修改后旧结果保留为历史，新正文重新排队')
    key=protect('synthetic-test-key')
    assert key!='synthetic-test-key' and protect(key,True)=='synthetic-test-key'
    checks.append('Windows DPAPI密钥加密往返正确')
    parser=Text();parser.feed('<nav>广告</nav><article><p>正文一</p><div>正文二</div></article><div>推荐广告</div>')
    assert ''.join(parser.parts).strip()=='正文一\n\n正文二'
    assert '推荐广告' not in ''.join(parser.parts)
    checks.append('正文提取不会吞入article结束后的推荐区')
    store.export(temp/'results.json','results')
    assert json.loads((temp/'results.json').read_text(encoding='utf8'))==[]
    checks.append('结果导出仅包含当前版本')
    del store,worker;gc.collect()

print(json.dumps({'ok':True,'checks':checks,'model_usage':'No live inference in these tests; all generated fixture text is isolated from production data.'},ensure_ascii=False,indent=2))
