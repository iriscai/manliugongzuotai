"""Editable score bands drive preview, delivery, receipts, export and cleanup together."""
import json,runpy,sys,tempfile,sqlite3
from pathlib import Path
from unittest.mock import patch
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
fixture=runpy.run_path(str(ROOT/'tests/title_push_checks.py'))['fixture']
import title_push,result_cleanup,workflow_management
from title_push import TitlePusher,save_mapping,category_mapping
from article_quality import apply,route,validate_score_rules
with tempfile.TemporaryDirectory() as tmp:
 s,project,_=fixture(Path(tmp),5)
 with patch.object(title_push,'PROJECT',project),patch.object(result_cleanup,'PROJECT',project),patch.object(workflow_management,'PROJECT',project):
  with s.connect() as c:
   c.execute("UPDATE results SET category='搞笑',score=NULL,score_status='pending' WHERE id IN (1,2,3,4)")
   for rid,dim in [(1,85),(2,84),(3,74)]:
    row=dict(c.execute('SELECT * FROM results WHERE id=?',(rid,)).fetchone());apply(c,row,{'completeness':dim,'reversal':dim,'fun':dim,'reason':'本篇具体评价','evidence':[row['title']],'risks':[]})
  initial=category_mapping(s,project)
  rules=[{'min_score':96,'max_score':100,'target':'自定精品','enabled':True},{'min_score':90,'max_score':95,'target':'自定优秀','enabled':True},{'min_score':0,'max_score':89,'target':'自定良好','enabled':True},{'min_score':30,'max_score':50,'target':'','enabled':False}]
  save_mapping(s,{'mapping':{'生活':'职场'},'score_rules':rules,'expected_revision':initial['revision']})
  saved=s.settings()
  for invalid in [[{'min_score':90,'max_score':100,'target':'甲'},{'min_score':89,'max_score':90,'target':'乙'}],[{'min_score':101,'max_score':102,'target':'甲'}],[{'min_score':90.5,'max_score':100,'target':'甲'}],[{'min_score':90,'max_score':100,'target':''}]]:
   try:save_mapping(s,{'mapping':{},'score_rules':invalid});raise AssertionError('invalid bands accepted')
   except ValueError:pass
   assert s.settings()==saved,'invalid configuration partially changed settings'
  try:save_mapping(s,{'mapping':{},'expected_revision':initial['revision']});raise AssertionError('stale mapping overwritten')
  except ValueError:pass
  rows={r['id']:r for r in s.list_results({})['rows']}
  assert rows[1]['push_category']=='自定优秀' and rows[2]['push_category']=='自定良好' and rows[3]['push_category']=='自定良好'
  assert not rows[4]['push_category'] and rows[5]['push_category']=='职场'
  p=TitlePusher(s,project,running=lambda:False);out=p.push([1,2,3,4,5]);assert out['pushed']==4 and out['blocked']==1
  assert p.push([1,2,3,5])['pushed']==4
  assert s.list_results({'push':'pushed'})['total']==4
  with s.connect() as c:assert result_cleanup.clearable_count(c)==4
  path=Path(tmp)/'export.json';s.export(path);assert any(r['推送分类']=='自定优秀' for r in json.loads(path.read_text(encoding='utf8')))
  # Disabled rules create intentional gaps rather than falling back to hard-coded routing.
  rules[2]['enabled']=False;save_mapping(s,{'mapping':{'生活':'职场'},'score_rules':rules})
  assert p.push([2,3,4])['blocked']==3
  assert s.list_results({'push':'pushed'})['total']==2
  with s.connect() as c:assert result_cleanup.clearable_count(c)==2
  rules[0]['min_score']=95;rules[1]['max_score']=94;rules[1]['target']='另一个优秀';save_mapping(s,{'mapping':{'生活':'职场'},'score_rules':rules})
  assert s.list_results({'push':'pushed'})['total']==1
  assert p.push([1])['pushed']==1 and p.push([1])['pushed']==1
  save_mapping(s,{'mapping':{'生活':'生活'}});assert s.settings()['push_score_rules']==rules,'ordinary mapping update reset score bands'
  save_mapping(s,{'mapping':{},'score_rules':[]});assert p.push([1,2,3,4])['blocked']==4
print(json.dumps({'ok':True,'custom_boundaries_and_targets':True,'disabled_and_gaps_blocked':True,'overlap_and_stale_refused':True,'atomic_save':True,'receipt_export_cleanup_consistent':True,'unscored_never_pushed':True,'external_calls':0,'production_changes':0}))
