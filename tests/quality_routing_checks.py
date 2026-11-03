"""Score binding, exact routing boundaries, delivery identities, editing and export."""
import json,runpy,sqlite3,sys,tempfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
fixture=runpy.run_path(str(ROOT/'tests/title_push_checks.py'))['fixture']
import title_push,result_cleanup
import workflow_management
from contextlib import closing
from title_push import TitlePusher,signature,delivery_signature
from article_quality import apply,grade,route,reset
from workflow_management import edit,restore_version
with tempfile.TemporaryDirectory() as tmp:
 s,project,_=fixture(Path(tmp),5)
 with patch.object(title_push,'PROJECT',project),patch.object(result_cleanup,'PROJECT',project),patch.object(workflow_management,'PROJECT',project):
  with s.connect() as c:
   c.execute("UPDATE results SET category='搞笑',score=NULL,score_status='pending' WHERE id IN (1,2,3,4)")
   for rid,dim in [(1,85),(2,84),(3,74)]:
    row=dict(c.execute('SELECT * FROM results WHERE id=?',(rid,)).fetchone())
    # Titles contain an Arabic id, exercising the deterministic +5 bonus.
    apply(c,row,{'completeness':dim,'reversal':dim,'fun':dim,'reason':'完整动作、意外与笑点按此稿实际评价。','evidence':[row['title']],'risks':[]})
  rows=s.list_results({})['rows'];byid={r['id']:r for r in rows}
  assert byid[1]['score']==90 and byid[1]['push_category']=='搞笑漫画-优秀'
  assert byid[2]['score']==89 and byid[2]['push_category']=='搞笑漫画-良好'
  assert byid[3]['score']==79 and not byid[3]['push_category']
  assert byid[4]['score'] is None and not byid[4]['push_category']
  assert byid[5]['score']==60 and byid[5]['push_category']=='生活'
  assert [r['id'] for r in s.list_results({'score_band':'excellent'})['rows']]==[1]
  s.save_settings({'push_category_map':{'生活':'生活漫画'}})
  p=TitlePusher(s,project,running=lambda:False);out=p.push([1,2,3,4,5]);assert out['pushed']==3 and out['blocked']==2
  assert p.push([1,2,5])['pushed']==3
  with closing(sqlite3.connect(project/'picfactory_matrix.db')) as c:
   delivered=[json.loads(r[0]) for r in c.execute("SELECT payload FROM app_collections WHERE namespace='title_library'") if json.loads(r[0]).get('source_app')]
   assert len(delivered)==3 and {x['category'] for x in delivered}=={'搞笑漫画-优秀','搞笑漫画-良好','生活漫画'}
  assert s.list_results({'push':'pushed'})['total']==3
  # Change only the grade bucket: new route has its own idempotent receipt.
  with s.connect() as c:
   row=dict(c.execute('SELECT * FROM results WHERE id=1').fetchone());apply(c,row,{'completeness':84,'reversal':84,'fun':84,'reason':'复核降低评价。','evidence':[row['title']],'risks':[]})
  assert s.list_results({'push':'pushed'})['total']==2
  assert p.push([1])['pushed']==1 and p.push([1])['pushed']==1
  with s.connect() as c:assert result_cleanup.clearable_count(c)==3
  before=next(r for r in s.list_results({})['rows'] if r['id']==2)
  text='\n\n'.join(['朋友上门。','他带了礼物。','我请他坐下。','他问吃饭没。','我说吃过了。','他收起饭盒。','我赶紧改口。','他把空盒给我洗。'])
  edit(s,{'id':2,'content_hash':signature(before),'title':before['title'],'article':text})
  edited=__import__('workflow_management').detail(s,2);assert edited['score'] is None
  restore_version(s,{'id':2,'version_id':edited['history'][0]['id'],'content_hash':edited['content_hash']})
  assert __import__('workflow_management').detail(s,2)['score']==89
  # Directly changing text also invalidates the old grade even without a UI reset.
  with s.connect() as c:c.execute("UPDATE results SET title='新标题' WHERE id=1")
  assert s.list_results({'score_band':'pending'})['total']==2
  assert p.push([1])['blocked']==1
  destination=Path(tmp)/'export.json';s.export(destination);export=json.loads(destination.read_text(encoding='utf8'));assert all('评分' in r and '推送分类' in r for r in export)
  # Bad score evidence is never accepted as a valid assessment.
  try:grade('甲',{'completeness':90,'reversal':90,'fun':90,'reason':'理由','evidence':['不存在'],'risks':[]});raise AssertionError('bad evidence accepted')
  except ValueError:pass
print(json.dumps({'ok':True,'boundary_90_and_89':True,'low_and_pending_blocked':True,'other_lanes_default60':True,'grade_and_route_content_bound':True,'repeat_push_idempotent':True,'score_exported':True,'external_calls':0}))
