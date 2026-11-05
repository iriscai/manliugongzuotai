"""Read-only lifecycle projection from source, seeds, tasks, articles and receipts."""
NODES=[
 ('source_missing','待补充标题／链接','正文','补齐标题；缺正文且没有链接时，补链接或手动补正文。'),
 ('body_pending','待正文抓取','正文','已有标题和链接，尚未取得合格正文。'),
 ('body_queued','正文抓取排队中','正文','已进入正文任务，等待抓取。'),
 ('body_fetching','正文抓取中','正文','抓取任务正在处理本条素材。'),
 ('body_paused','正文抓取已暂停','正文','本条仍待抓取，所属任务已暂停或中断。'),
 ('body_failed','正文抓取失败','正文','抓取失败，需重试或补正文。'),
 ('body_truncated','正文疑似截断','正文','正文不完整，未通过验收，需重新抓取或补充。'),
 ('body_unavailable','无有效正文／链接失效','正文','纯视频、无文字或失效链接无法生文。'),
 ('source_review','待正文验收','正文','已有文本但尚未通过标题、正文及去重验收。'),
 ('write_pending','正文就绪·待生文','生文','素材原赛道还没有文章成品。'),
 ('write_queued','生文排队中','生文','写文任务已排队，等待并发空位。'),
 ('writing','生文中','生文','至少一篇文章正在生成，含明确发起的重生成。'),
 ('write_paused','生文已暂停','生文','尚未完成的写文任务已暂停或中断。'),
 ('write_failed','生文失败／部分失败','生文','当前素材的最新写文失败；成功稿继续保留。'),
 ('write_partial','部分生文成功','生文','已有文章，但仍有当前有效主题未生成。'),
 ('push_pending','生文成功·待推送','推送','当前主题均已生成，仍有成品未推送到当前目标。'),
 ('pushing','推送中／等待重试','推送','投递已入队，等待回执或自动重试。'),
 ('push_failed','推送失败','推送','当前目标、当前内容的投递失败，需查看推送记录。'),
 ('push_blocked','推送条件未满足','推送','例如搞笑成品评分失效，或分数未匹配启用的推送区间。'),
 ('push_partial','部分推送成功','推送','当前成品只有一部分已确认推送到当前目标。'),
 ('pushed','全部推送成功','推送','当前成品均有当前目标、当前内容对应的成功回执。'),
 ('outputs_archived','成品已清除／删除','归档','文章曾生成，当前成品均已清除或删除；不自动补生。'),
 ('deleted','素材已删除','归档','素材在已删除列表，保留关联成品和处理记录。'),
]
NODE_MAP={code:{'code':code,'label':label,'group':group,'description':desc} for code,label,group,desc in NODES}
MILESTONES=[
 ('has_body','正文已验收（含后续节点）',"f.body_ready=1"),
 ('has_article','已有生文（含部分成功）',"f.generated_count>0"),
 ('all_written','全部主题已生文',"f.seed_count>0 AND f.generated_count=f.seed_count"),
 ('has_pushed','已有成功推送',"f.pushed_count>0"),
]

def register_functions(c):
    from push_targets import project_in
    from article_quality import route
    target=str(project_in(c)/'picfactory_matrix.db')
    c.create_function('workflow_push_target',0,lambda:target,deterministic=True)
    def allowed(category,title,article,score,status,hashed):
        row={'category':category,'title':title,'article':article,'short_text':article,
             'score':score,'score_status':status,'score_content_hash':hashed}
        return int(not route(row,mapping,rules)[1]) if category is not None else 0
    import json
    settings={r['key']:json.loads(r['value']) for r in c.execute("SELECT key,value FROM settings WHERE key IN ('push_category_map','push_score_rules')")}
    mapping=settings.get('push_category_map',{});rules=settings.get('push_score_rules')
    c.create_function('workflow_push_allowed',6,allowed,deterministic=True)

VIEW_SQL="""
CREATE VIEW material_workflow AS
WITH body_ranked AS (
 SELECT bi.material_id,bi.status body_item_state,bj.state body_job_state,
 row_number() OVER(PARTITION BY bi.material_id ORDER BY
  (bi.status IN ('pending','running') AND bj.state IN ('running','pausing','queued','paused','interrupted')) DESC,
  bj.created_at DESC,bi.rowid DESC) rank
 FROM body_items bi JOIN body_jobs bj ON bj.id=bi.job_id
), material_ranked AS (
 SELECT i.material_id,i.state item_state,i.phase item_phase,j.state job_state,j.mode job_mode,
 row_number() OVER(PARTITION BY i.material_id ORDER BY (j.state IN ('running','pausing')) DESC,j.updated_at DESC,i.rowid DESC) rank
 FROM run_items i JOIN runs j ON j.id=i.run_id
), queue_ranked AS (
 SELECT i.material_id,q.state queue_state,
 row_number() OVER(PARTITION BY i.material_id ORDER BY q.created_at DESC,i.rowid DESC) rank
 FROM model_queue_items i JOIN model_queue q ON q.id=i.job_id
 WHERE i.state='pending' AND q.state IN ('queued','waiting','running','paused')
), write_ranked AS (
 SELECT w.*,j.state write_job_state,
 row_number() OVER(PARTITION BY w.extraction_id ORDER BY (j.state IN ('running','pausing')) DESC,w.updated_at DESC,w.rowid DESC) rank
 FROM run_writes w JOIN runs j ON j.id=w.run_id
), seed_stats AS (
 SELECT e.material_id,count(*) current_seed_count,sum(e.eligible=1) seed_count,
 sum(r.category=sm.category) source_written_count,
 sum(e.eligible=1 AND r.id IS NOT NULL) generated_count,
 sum(e.eligible=1 AND r.id IS NOT NULL AND r.deleted_at='' AND r.cleared_at='') visible_count,
 sum(e.eligible=1 AND r.id IS NOT NULL AND r.deleted_at='' AND r.cleared_at='') deliverable_count,
 sum(e.eligible=1 AND r.id IS NOT NULL AND (r.cleared_at<>'' OR r.deleted_at<>'')) archived_count,
 sum(e.eligible=1 AND coalesce(r.deleted_at,'')='' AND w.state='writing' AND w.write_job_state IN ('running','pausing')) writing_count,
 sum(e.eligible=1 AND coalesce(r.deleted_at,'')='' AND w.state='queued' AND w.write_job_state IN ('running','pausing')) write_queued_count,
 sum(e.eligible=1 AND coalesce(r.deleted_at,'')='' AND w.state='failed' AND (r.id IS NULL OR r.content_revision<=max(1,w.base_revision))) write_failed_count,
 sum(e.eligible=1 AND coalesce(r.deleted_at,'')='' AND w.state='queued' AND w.write_job_state IN ('paused','blocked','interrupted') AND (r.id IS NULL OR r.content_revision<=max(1,w.base_revision))) write_paused_count,
 sum(e.eligible=1 AND r.id IS NOT NULL AND r.deleted_at='' AND p.state='pushed') pushed_count,
 sum(e.eligible=1 AND r.id IS NOT NULL AND r.deleted_at='' AND r.cleared_at='' AND p.state='pushed') active_pushed_count,
 sum(e.eligible=1 AND r.id IS NOT NULL AND r.deleted_at='' AND r.cleared_at='' AND p.state<>'pushed' AND p.phase IN ('queued','waiting','retry_wait')) pushing_count,
 sum(e.eligible=1 AND r.id IS NOT NULL AND r.deleted_at='' AND r.cleared_at='' AND p.state='failed' AND p.phase NOT IN ('queued','waiting','retry_wait')) push_failed_count,
 sum(e.eligible=1 AND r.id IS NOT NULL AND r.deleted_at='' AND r.cleared_at='' AND workflow_push_allowed(r.category,r.title,coalesce(nullif(r.article,''),r.short_text),r.score,r.score_status,r.score_content_hash)=0) push_blocked_count
 FROM extractions e JOIN materials sm ON sm.id=e.material_id
 LEFT JOIN results r ON r.extraction_id=e.id AND r.current=1
 LEFT JOIN write_ranked w ON w.extraction_id=e.id AND w.rank=1
 LEFT JOIN result_pushes p ON p.result_id=r.id AND p.target_path=workflow_push_target()
  AND p.content_hash=CASE WHEN r.id IS NOT NULL THEN result_delivery_signature(r.category,r.title,coalesce(nullif(r.article,''),r.short_text),r.score,r.score_status,r.score_content_hash) END
 WHERE e.current=1 AND (r.id IS NOT NULL OR e.extraction_mode='direct') GROUP BY e.material_id
), facts AS (
 SELECT m.id material_id,m.state raw_state,m.deleted_at,
 trim(m.title)='' title_missing,trim(m.body)='' body_missing,trim(m.url)='' url_missing,
 m.body_status,m.qualification='qualified' AND trim(m.title)<>'' AND trim(m.body)<>'' body_ready,
 coalesce(s.source_written_count,0) source_written_count,
 coalesce(s.current_seed_count,0) current_seed_count,coalesce(s.seed_count,0) seed_count,
 coalesce(s.generated_count,0) generated_count,coalesce(s.visible_count,0) visible_count,
 coalesce(s.deliverable_count,0) deliverable_count,coalesce(s.archived_count,0) archived_count,
 coalesce(s.writing_count,0) writing_count,coalesce(s.write_queued_count,0) write_queued_count,
 coalesce(s.write_failed_count,0) write_failed_count,coalesce(s.write_paused_count,0) write_paused_count,
 coalesce(s.pushed_count,0) pushed_count,coalesce(s.active_pushed_count,0) active_pushed_count,coalesce(s.pushing_count,0) pushing_count,
 coalesce(s.push_failed_count,0) push_failed_count,coalesce(s.push_blocked_count,0) push_blocked_count,
 b.body_item_state,b.body_job_state,j.item_state,j.item_phase,j.job_state,j.job_mode,q.queue_state
 FROM materials m LEFT JOIN seed_stats s ON s.material_id=m.id
 LEFT JOIN body_ranked b ON b.material_id=m.id AND b.rank=1
 LEFT JOIN material_ranked j ON j.material_id=m.id AND j.rank=1
 LEFT JOIN queue_ranked q ON q.material_id=m.id AND q.rank=1
)
SELECT *,CASE
 WHEN deleted_at<>'' THEN 'deleted'
 WHEN title_missing OR (body_missing AND url_missing) THEN 'source_missing'
 WHEN NOT body_ready THEN CASE
  WHEN body_item_state='running' AND body_job_state IN ('running','pausing') THEN 'body_fetching'
  WHEN body_item_state IN ('pending','running') AND (body_job_state IN ('paused','interrupted') OR
    (body_job_state='queued' AND coalesce((SELECT value FROM settings WHERE key='body_queue_paused'),'false')='true')) THEN 'body_paused'
  WHEN body_item_state='pending' AND body_job_state IN ('queued','running','pausing') THEN 'body_queued'
  WHEN body_status='truncated' THEN 'body_truncated'
  WHEN body_status IN ('image','video','no_text','gone') THEN 'body_unavailable'
  WHEN body_status='failed' THEN 'body_failed'
  WHEN NOT body_missing THEN 'source_review'
  ELSE 'body_pending' END
 WHEN writing_count>0 OR (item_state='running' AND job_state IN ('running','pausing') AND item_phase='writing') THEN 'writing'
 WHEN write_queued_count>0 OR (item_state='queued' AND job_state IN ('running','pausing')) OR queue_state IN ('queued','waiting','running') THEN 'write_queued'
 WHEN write_paused_count>0 OR ((item_state IN ('queued','running') AND job_state IN ('paused','blocked','interrupted')) OR queue_state='paused') THEN 'write_paused'
 WHEN write_failed_count>0 OR (source_written_count=0 AND (item_state='failed' OR raw_state='failed')) THEN 'write_failed'
 WHEN source_written_count=0 THEN 'write_pending'
 WHEN deliverable_count>0 AND active_pushed_count=deliverable_count THEN 'pushed'
 WHEN pushing_count>0 THEN 'pushing'
 WHEN push_failed_count>0 THEN 'push_failed'
 WHEN active_pushed_count>0 THEN 'push_partial'
 WHEN visible_count=0 THEN 'outputs_archived'
 WHEN push_blocked_count>0 THEN 'push_blocked'
 ELSE 'push_pending' END workflow_node FROM facts
"""

def install_schema(c):
    for sql in [
      'CREATE INDEX IF NOT EXISTS idx_body_material_workflow ON body_items(material_id,job_id,status)',
      'CREATE INDEX IF NOT EXISTS idx_run_material_workflow ON run_items(material_id,run_id,state)',
      'CREATE INDEX IF NOT EXISTS idx_result_seed_workflow ON results(extraction_id,current)',
      'CREATE INDEX IF NOT EXISTS idx_queue_material_workflow ON model_queue_items(material_id,job_id,state)',
    ]:c.execute(sql)
    c.execute('DROP VIEW IF EXISTS material_workflow');c.execute(VIEW_SQL)

GROUPS=[
 {'code':'todo_body','label':'待抓正文','nodes':['body_pending']},
 {'code':'todo_write','label':'待生文','nodes':['write_pending','write_partial']},
 {'code':'todo_push','label':'待推送','nodes':['push_pending','push_partial']},
 {'code':'done_push','label':'已推送','nodes':['pushed']},
 {'code':'workflow_failed','label':'失败待处理','nodes':['body_failed','body_truncated','write_failed','push_failed']},
 {'code':'workflow_paused','label':'已暂停','nodes':['body_paused','write_paused']},
 {'code':'workflow_active','label':'排队／执行中','nodes':['body_queued','body_fetching','write_queued','writing','pushing']},
]

def filter_clause(value):
    value={'todo_extract':'todo_write','extract_pending':'write_pending','extract_queued':'write_queued','extracting':'writing','extract_paused':'write_paused','extract_failed':'write_failed','no_topics':'write_pending','has_extraction':'has_body'}.get(value,value)
    for group in GROUPS:
        if value==group['code']:return 'f.workflow_node IN ('+','.join('?' for _ in group['nodes'])+')',group['nodes']
    if value in NODE_MAP:return 'f.workflow_node=?',[value]
    for code,_,predicate in MILESTONES:
        if value==code:return predicate,[]
    raise ValueError('未知处理节点筛选')

def options(c,visibility):
    rows={r['workflow_node']:r['n'] for r in c.execute("SELECT workflow_node,count(*) n FROM material_workflow WHERE deleted_at"+("<>''" if visibility=='deleted' else "=''")+' GROUP BY workflow_node')}
    return [dict(item,count=rows.get(code,0)) for code,item in NODE_MAP.items()]

def decorate(rows):
    for row in rows:
        row['workflow_label']=NODE_MAP[row['workflow_node']]['label']
        row['workflow_description']=NODE_MAP[row['workflow_node']]['description']
