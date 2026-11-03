"""Lifecycle facts, partial work, receipt scope and query/preview agreement."""
from workbench_fixtures import *
from material_workflow import NODES,MILESTONES
from model_queue import preview as queue_preview
from category_distribution import distribution
from title_push import delivery_signature
from contextlib import closing
import sqlite3,uuid

with tempfile.TemporaryDirectory(prefix='material-workflow-') as tmp:
    s,w,p=seed(Path(tmp),len(NODES));stamp='2026-11-03T12:00:00'
    target=Path(tmp)/'unused-target';s.save_settings({'push_target_project':str(target)})
    expected={code:i for i,(code,*_) in enumerate(NODES,1)}
    task_snapshot=dumps({'settings':s.settings(),'prompts':s.prompts(),'extraction_scheme':'adaptive_topics_v1','extraction_mode':'multi'})
    with s.connect() as c:
        def task(mid,job_state,item_state,phase='',seeds=(),write_state=None):
            rid='flow-'+str(mid)
            c.execute('INSERT INTO runs(id,mode,state,total,snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(rid,'both',job_state,1,task_snapshot,stamp,stamp))
            c.execute('INSERT INTO run_items(run_id,material_id,state,phase,source_hash) VALUES(?,?,?,?,?)',(rid,mid,item_state,phase,'fixture'))
            for eid in seeds:
                c.execute('INSERT INTO run_writes(run_id,extraction_id,material_id,category,state,updated_at,base_revision) VALUES(?,?,?,?,?,?,?)',(rid,eid,mid,'生活',write_state,stamp,1))
        def seed_for(mid,eligible=True,cat='生活'):
            data=dumps({'eligible':eligible,'topic':'活动开放安排','main_point':'安排','facts':[]})
            return c.execute('INSERT INTO extractions(material_id,category,angle,source_hash,rule_variant,data_json,created_at) VALUES(?,?,?,?,?,?,?)',(mid,cat,'安排'+uuid.uuid4().hex,'fixture','A',data,stamp)).lastrowid
        def article(mid,eid,cat='生活'):
            return c.execute('INSERT INTO results(extraction_id,material_id,category,title,short_text,article,data_json,char_count,frame_count,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(eid,mid,cat,'测试'+str(eid),TEXT,TEXT,'{}',100,8,stamp)).lastrowid
        def receipt(rid,state,phase):
            r=dict(c.execute('SELECT * FROM results WHERE id=?',(rid,)).fetchone())
            c.execute('INSERT INTO result_pushes(result_id,target_path,content_hash,delivery_id,title,article,category,state,phase,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (rid,str(target.resolve()/'picfactory_matrix.db'),delivery_signature(r),uuid.uuid4().hex,r['title'],r['article'],r['category'],state,phase,stamp))
        for code,mid in expected.items():
            if code=='deleted':c.execute('UPDATE materials SET deleted_at=? WHERE id=?',(stamp,mid));continue
            if code=='source_missing':
                c.execute("UPDATE materials SET title='',body='',url='',qualification='pending' WHERE id=?",(mid,));continue
            if code.startswith('body_'):
                status={'body_failed':'failed','body_truncated':'truncated','body_unavailable':'gone'}.get(code,'missing')
                c.execute("UPDATE materials SET body='',url='https://fixture.invalid/body',qualification='pending',body_status=? WHERE id=?",(status,mid))
                if code in ('body_queued','body_fetching','body_paused'):
                    state={'body_queued':'queued','body_fetching':'running','body_paused':'paused'}[code];jid='body-'+str(mid)
                    c.execute('INSERT INTO body_jobs(id,state,total,created_at,updated_at) VALUES(?,?,?,?,?)',(jid,state,1,stamp,stamp))
                    c.execute('INSERT INTO body_items(job_id,material_id,status,updated_at) VALUES(?,?,?,?)',(jid,mid,'running' if code=='body_fetching' else 'pending',stamp))
                continue
            if code=='source_review':c.execute("UPDATE materials SET qualification='pending' WHERE id=?",(mid,));continue
            if code=='extract_pending':continue
            if code=='extract_queued':task(mid,'running','queued');continue
            if code=='extracting':task(mid,'running','running','extracting');continue
            if code=='extract_paused':task(mid,'blocked','queued');continue
            if code=='extract_failed':task(mid,'completed','failed');continue
            if code=='no_topics':seed_for(mid,False);continue
            cat='搞笑' if code=='push_blocked' else '生活'
            if cat=='搞笑':c.execute('UPDATE materials SET category=? WHERE id=?',(cat,mid))
            seeds=[seed_for(mid,cat=cat),seed_for(mid,cat=cat)]
            if code=='write_pending':continue
            if code in ('write_queued','writing','write_paused'):
                task(mid,'paused' if code=='write_paused' else 'running','queued',seeds=seeds,write_state='writing' if code=='writing' else 'queued');continue
            if code=='write_failed':
                article(mid,seeds[0]);task(mid,'completed','failed',seeds=[seeds[1]],write_state='failed');continue
            if code=='write_partial':article(mid,seeds[0]);continue
            articles=[article(mid,eid,cat) for eid in seeds]
            if code=='pushing':receipt(articles[0],'pending','waiting')
            if code=='push_failed':receipt(articles[0],'failed','failed')
            if code in ('push_partial','pushed'):receipt(articles[0],'pushed','verified')
            if code=='pushed':receipt(articles[1],'pushed','verified')
            if code=='outputs_archived':c.execute('UPDATE results SET deleted_at=? WHERE material_id=?',(stamp,mid))
    def flow(mid):
        with s.connect() as c:return dict(c.execute('SELECT * FROM material_workflow WHERE material_id=?',(mid,)).fetchone())
    for code,mid in expected.items():
        got=flow(mid);assert got['workflow_node']==code,(code,got)
        rows=s.list_materials({'workflow_node':code,'visibility':'deleted' if code=='deleted' else 'active'})['rows']
        assert [r['id'] for r in rows]==[mid],(code,[r['id'] for r in rows])
    options=s.material_options();assert sum(x['count'] for x in options['workflow_nodes'])==len(NODES)-1
    assert all(x['count']==1 for x in options['workflow_nodes'] if x['code']!='deleted')
    partial=flow(expected['write_partial']);assert partial['seed_count']==2 and partial['generated_count']==1
    assert s.list_materials({'workflow_node':'has_article'})['total']>s.list_materials({'workflow_node':'all_written'})['total']
    assert s.list_materials({'workflow_node':'has_body'})['total']>s.list_materials({'workflow_node':'has_extraction'})['total']
    assert s.list_materials({'workflow_node':'has_pushed'})['total']==2
    filtered={'workflow_node':'write_partial','category':'生活'}
    pre=w.start({'preview':True,'mode':'both','scope':'filtered','filters':filtered})
    assert pre['ids']==[expected['write_partial']]
    assert distribution(s,{'module':'materials','filters':dumps(filtered)})['total']==1
    assert queue_preview(s,{'scope':'filtered','filters':{'workflow_node':'body_pending'}})['ids']==[expected['body_pending']]
    try:s.list_materials({'workflow_node':"x' OR 1=1--"});raise AssertionError('invalid node accepted')
    except ValueError:pass
    # A persistent fixture supports actual renderer/API checks without model requests.
    ui=ROOT/'build'/('material-workflow-ui-'+uuid.uuid4().hex[:10]);ui.mkdir()
    with s.connect() as c,closing(sqlite3.connect(ui/'workbench.sqlite3')) as out:
        c.backup(out)
        out.execute("UPDATE settings SET value='true' WHERE key='body_queue_paused'")
        out.execute("UPDATE body_jobs SET state='paused' WHERE state IN ('queued','running','pausing')")
        out.execute("UPDATE result_pushes SET state='failed',phase='failed' WHERE state<>'pushed'")
        out.commit()
    (ROOT/'build/material-workflow-ui-fixture.json').write_text(dumps({'data':str(ui),'expected':expected}),encoding='utf8')
    # A changed title or target invalidates old receipt applicability immediately.
    mid=expected['pushed']
    with s.connect() as c:c.execute("UPDATE results SET title=title||'新版' WHERE material_id=? AND id=(SELECT min(id) FROM results WHERE material_id=?)",(mid,mid))
    assert flow(mid)['workflow_node']=='push_partial'
    s.save_settings({'push_target_project':str(target/'different')});assert flow(mid)['workflow_node']=='push_pending'
    # Cleared siblings remain generated, and do not block visible articles from finishing delivery.
    s.save_settings({'push_target_project':str(target)})
    mid=expected['push_pending']
    with s.connect() as c:
        ids=[r[0] for r in c.execute('SELECT id FROM results WHERE material_id=? ORDER BY id',(mid,))]
        c.execute('UPDATE results SET cleared_at=? WHERE id=?',(stamp,ids[0]))
        receipt(ids[1],'pushed','verified')
    assert flow(mid)['workflow_node']=='pushed' and flow(mid)['deliverable_count']==1
    # Existing valid text remains generated even after cleanup, without inventing missing writes.
    archived=flow(expected['outputs_archived']);assert archived['generated_count']==archived['seed_count']==2
    # Historical seeds do not inflate the current article denominator.
    with s.connect() as c:c.execute('UPDATE extractions SET current=0 WHERE material_id=? AND id=(SELECT max(id) FROM extractions WHERE material_id=?)',(expected['write_partial'],expected['write_partial']))
    assert flow(expected['write_partial'])['workflow_node']=='push_pending'
    assert not p.calls

report={'ok':True,'exact_nodes':len(NODES),'milestones':len(MILESTONES),'partial_generation_visible':True,
        'counts_filters_preview_and_distribution_agree':True,'current_seeds_only':True,
        'current_target_and_content_receipts_only':True,'archived_articles_not_pending':True,
        'external_model_calls':0,'production_changes':0}
(ROOT/'build/material-workflow-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
