"""Scoped operator actions, delegating to the unchanged execution services."""
from workbench_fixtures import *
from usability import body_preview,body_start,workflow_summary,import_summary,push_preview,push_submit,push_progress,push_summary
from body_fetcher import BodyFetcher
from title_push import TitlePusher
import sqlite3
from contextlib import closing

def target_at(path):
    path.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(path/'picfactory_matrix.db')) as c:
        c.execute('CREATE TABLE app_collections(namespace TEXT,item_key TEXT,payload TEXT,sort_order INTEGER,PRIMARY KEY(namespace,item_key))');c.commit()

with tempfile.TemporaryDirectory(prefix='operator-checks-') as tmp:
    root=Path(tmp);s,w,fake=seed(root/'body',6)
    with s.connect() as c:
        c.execute("UPDATE materials SET body='',url='https://fixture.invalid/'||id,body_status='missing',qualification='pending',state='needs_source' WHERE id<=4")
        c.execute("UPDATE materials SET category='教育' WHERE id=3")
        c.execute("UPDATE materials SET deleted_at='2026-11-03' WHERE id=4")
    fetcher=BodyFetcher(s);calls=[]
    fetcher.engine_info=lambda settings=None:{'available':True,'workers':2,'max_chars':800,'message':'fixture'}
    fetcher.start=lambda payload:(calls.append(payload) or {'job_id':'fixture-body','total':len(payload['ids'])})
    p=body_preview(s,fetcher,{'scope':'filtered','filters':{'category':'教育'},'limit':100})
    assert [r['id'] for r in p['rows']]==[3] and not calls
    assert body_start(s,fetcher,{'id':p['id']})['total']==1 and calls[0]['ids']==[3]
    body_start(s,fetcher,{'id':p['id']});assert len(calls)==1,'double submit created another task'
    p=body_preview(s,fetcher,{'scope':'selected','ids':[1,3],'limit':1});assert p['total']==1
    with s.connect() as c:c.execute("UPDATE materials SET url='https://fixture.invalid/changed' WHERE id=1")
    try:body_start(s,fetcher,{'id':p['id']});raise AssertionError('changed source accepted')
    except ValueError:pass
    assert len(calls)==1
    p=body_preview(s,fetcher,{'scope':'filtered','filters':{'q':'不存在'},'limit':100});assert p['total']==0
    try:body_start(s,fetcher,{'id':p['id']});raise AssertionError('empty scope expanded to all')
    except ValueError:pass
    summary=workflow_summary(s);assert summary['total']==5
    for group in summary['groups']:
        assert s.list_materials({'workflow_node':group['code']})['total']==group['count']
    assert import_summary(s,1)['id']==1
    assert s.list_materials({'import_id':999999})['total']==0
    # 502 articles exercise >500 splitting; no model or actual image application is used.
    s,w,fake=seed(root/'push');target=root/'target';target_at(target);s.save_settings({'push_target_project':str(target)})
    with s.connect() as c:
        for i in range(502):
            eid=c.execute('INSERT INTO extractions(material_id,category,angle,source_hash,rule_variant,data_json,created_at) VALUES(?,?,?,?,?,?,?)',(1,'生活',str(i),'fixture','A',dumps({'eligible':True}), '2026-11-03T12:00:00')).lastrowid
            c.execute('INSERT INTO results(extraction_id,material_id,category,title,article,short_text,data_json,char_count,frame_count,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(eid,1,'生活','稿件'+str(i),TEXT,TEXT,'{}',100,8,'2026-11-03T12:00:00'))
    pusher=TitlePusher(s,project=target,running=lambda:False)
    plan=push_preview(s,{'filters':{'category':'生活'}});assert plan['total']==502 and plan['parts']==2
    first=push_submit(s,pusher,{'id':plan['id'],'cursor':0});assert first['submitted']==500 and first['pushed']==500
    with s.connect() as c:c.execute("UPDATE results SET title='此篇已修改',content_revision=content_revision+1 WHERE id=502")
    second=push_submit(s,pusher,{'id':plan['id'],'cursor':500})
    assert second['submitted']==502 and second['pushed']==501 and len(second['skipped'])==1
    again=push_submit(s,pusher,{'id':plan['id'],'cursor':0});assert again['pushed']==501
    with closing(sqlite3.connect(target/'picfactory_matrix.db')) as c:assert c.execute("SELECT count(*) FROM app_collections WHERE namespace='title_library'").fetchone()[0]==501
    plan2=push_preview(s,{'filters':{'category':'生活'}});assert plan2['total']==1
    # Explicit selection preserves the old idempotent ability to push an already delivered item.
    chosen=push_preview(s,{'ids':[1]});assert chosen['total']==1
    selected=push_submit(s,pusher,{'id':chosen['id'],'cursor':0});assert selected['pushed']==1
    with closing(sqlite3.connect(target/'picfactory_matrix.db')) as c:assert c.execute("SELECT count(*) FROM app_collections WHERE namespace='title_library'").fetchone()[0]==501
    s.save_settings({'push_target_project':str(root/'other-target')})
    try:push_submit(s,pusher,{'id':plan2['id'],'cursor':0});raise AssertionError('target changed without new preview')
    except ValueError:pass
    assert not fake.calls

report={'ok':True,'body_scope_exact':True,'empty_scope_not_expanded':True,'double_submit_idempotent':True,
        'changed_source_refused':True,'workflow_counts_match_filters':True,'import_scope':True,
        'push_502_split_500_and_2':True,'changed_article_skipped':True,'existing_push_idempotence_preserved':True,
        'changed_target_refused':True,'external_model_calls':0,'production_changes':0}
(ROOT/'build/usability-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
