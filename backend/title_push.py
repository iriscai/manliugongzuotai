"""Durable, idempotent delivery to ReferenceImageBatchFactory's title library."""
import hashlib,json,os,sqlite3,subprocess,threading,time,uuid
from contextlib import closing
from pathlib import Path

PROJECT=Path(os.environ.get('COMIC_PUSH_TARGET_PROJECT','D:/BIGDATA/CODES/PyCharmFiles/Factorys/ReferenceImageBatchFactory'))
INBOX_SQL='''CREATE TABLE IF NOT EXISTS comic_article_inbox(delivery_id TEXT PRIMARY KEY,payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',target_key TEXT DEFAULT '',error TEXT DEFAULT '',created_at REAL NOT NULL,completed_at REAL)'''

def signature(row):
    return hashlib.sha256(json.dumps([row['category'],row['title'],row.get('article') or row['short_text']],ensure_ascii=False,separators=(',',':')).encode('utf8')).hexdigest()

def delivery_signature(row,mapping=None,rules=None):
    from article_quality import route
    destination,_=route(row,mapping,rules)
    original=signature(row)
    return original if destination==row['category'] else hashlib.sha256(json.dumps([original,destination],ensure_ascii=False).encode('utf8')).hexdigest()

def category_mapping(store,project=None):
    from push_targets import project_for
    project=Path(project) if project is not None else project_for(store)
    from article_quality import score_rules
    settings=store.settings();configured=settings.get('push_category_map',{});rules=score_rules(settings.get('push_score_rules'));target=Path(project)/'picfactory_matrix.db';choices=set()
    if target.is_file():
        with closing(sqlite3.connect(target,timeout=5)) as c:
            for namespace,encoded in c.execute("SELECT namespace,payload FROM app_collections WHERE namespace IN ('title_library','accounts')"):
                try:
                    item=json.loads(encoded);category=item.get('category') if namespace=='title_library' else item.get('title_category')
                    if category:choices.add(category)
                except (ValueError,AttributeError):continue
    names=[r['name'] for r in json.loads((store.resources/'categories.json').read_text(encoding='utf8'))['categories']]
    return {'rows':[{'source':n,'target':configured.get(n,n)} for n in names if n!='搞笑'],
            'target_categories':sorted(choices),'score_rules':rules,'default_score_rules':score_rules(),'revision':mapping_revision(configured,rules),
            'funny_rules':[{'range':str(r['min_score'])+'—'+str(r['max_score']),'target':r['target']} for r in rules if r['enabled']]}

def mapping_revision(mapping,rules):return hashlib.sha256(json.dumps([mapping,rules],ensure_ascii=False,sort_keys=True).encode('utf8')).hexdigest()

def save_mapping(store,payload):
    from article_quality import score_rules,validate_score_rules
    values=payload.get('mapping')
    if not isinstance(values,dict) or len(values)>100 or any(not isinstance(k,str) or not isinstance(v,str) or not k.strip() or not v.strip() or len(v)>80 for k,v in values.items()):raise ValueError('分类匹配格式无效，目标分类不能为空且最多80字符')
    if any(k.strip()=='搞笑' for k in values):raise ValueError('搞笑按分数自动匹配，不使用普通分类覆盖')
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        settings={r['key']:json.loads(r['value']) for r in c.execute("SELECT key,value FROM settings WHERE key IN ('push_category_map','push_score_rules')")}
        old_rules=score_rules(settings.get('push_score_rules'))
        if payload.get('expected_revision') and payload['expected_revision']!=mapping_revision(settings.get('push_category_map',{}),old_rules):raise ValueError('推送配置已变化，请重新打开后修改')
        rules=validate_score_rules(payload['score_rules']) if 'score_rules' in payload else old_rules
        for key,value in [('push_category_map',{k.strip():v.strip() for k,v in values.items()}),('push_score_rules',rules)]:c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False)))
    return {'ok':True}

def install_schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS result_pushes(result_id INTEGER NOT NULL,target_path TEXT NOT NULL,content_hash TEXT NOT NULL,delivery_id TEXT NOT NULL,title TEXT NOT NULL,article TEXT NOT NULL,category TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',target_key TEXT DEFAULT '',error TEXT DEFAULT '',updated_at TEXT NOT NULL,PRIMARY KEY(result_id,target_path,content_hash))''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_result_pushes_state ON result_pushes(state,result_id)')
    from push_delivery import schema
    schema(c)

def resolve_record(c,payload):
    """Match full content, preserving an existing row's enabled/consumed state."""
    for row in c.execute("SELECT item_key,payload FROM app_collections WHERE namespace='title_library'"):
        existing=json.loads(row[1])
        if all(str(existing.get(k,'')).strip()==str(payload[k]).strip() for k in ('title','body','category')):
            return row[0],False
    if c.execute("SELECT 1 FROM app_collections WHERE namespace='title_library' AND item_key=?",(payload['uuid'],)).fetchone():payload=dict(payload,uuid=str(uuid.uuid4()))
    order=c.execute("SELECT coalesce(max(sort_order),-1)+1 FROM app_collections WHERE namespace='title_library'").fetchone()[0]
    c.execute("INSERT INTO app_collections(namespace,item_key,payload,sort_order) VALUES('title_library',?,?,?)",(payload['uuid'],json.dumps(payload,ensure_ascii=False),order))
    return payload['uuid'],True

class TitlePusher:
    def __init__(self,store,project=None,running=None):
        self.store=store;self._explicit_project=Path(project).resolve() if project is not None else None;self._running_override=running
        self.lock=threading.RLock();self.last_error='';self.refresh_project();self.running=running or self.target_running

    def refresh_project(self):
        from push_targets import project_for
        self.project=self._explicit_project or project_for(self.store);self.db=self.project/'picfactory_matrix.db'

    def target_running(self):
        from push_delivery import running_for
        return running_for(self,self.db)

    def target(self):
        from push_targets import check_db
        check_db(self.db);c=sqlite3.connect(self.db,timeout=1);c.execute(INBOX_SQL);c.commit();return c

    def sync(self,check_all=False):
        from push_delivery import reconcile
        with self.lock:self.refresh_project();reconcile(self,check_all)

    def start_dispatcher(self):
        from push_delivery import start
        start(self)

    def push(self,ids):
        from push_delivery import queue,dispatch,response
        if not isinstance(ids,list) or not ids or len(ids)>500 or any(type(x) is not int or x<1 for x in ids):raise ValueError('请勾选1至500篇文章')
        with self.lock:
            ids=list(dict.fromkeys(ids));self.refresh_project();self.sync(True)
            with self.store.connect() as c:
                rows=[dict(r) for r in c.execute("SELECT * FROM results WHERE current=1 AND deleted_at='' AND cleared_at='' AND id IN ("+','.join('?' for _ in ids)+') ORDER BY id',ids)]
                active=c.execute("SELECT 1 FROM results r JOIN run_items i ON i.material_id=r.material_id JOIN runs j ON j.id=i.run_id WHERE r.id IN ("+','.join('?' for _ in ids)+") AND i.state IN ('queued','running') AND j.state IN ('running','pausing') LIMIT 1",ids).fetchone()
            if active:raise ValueError('所选文章正在生成，请待当前步骤保存后推送')
            if len(rows)!=len(ids):raise ValueError('部分文章已变化或不存在，请刷新后重新勾选')
            from article_quality import route,valid_score
            settings=self.store.settings();mapping=settings.get('push_category_map',{});rules=settings.get('push_score_rules');entries=[];blocked=[]
            for row in rows:
                destination,reason=route(row,mapping,rules);body=row.get('article') or row['short_text']
                if not row['title'].strip() or not body.strip():reason='标题或正文为空'
                if reason:blocked.append({'result_id':row['id'],'reason':reason});continue
                payload={'title':row['title'],'body':body,'category':destination,'score':valid_score(row),'source_category':row['category'],'status':'启用','used':False,'used_at':'','note':f'漫画文章工作台 · 素材#{row["material_id"]} · 结果#{row["id"]} · {valid_score(row)}分','updated_at':time.strftime('%Y-%m-%d %H:%M:%S'),'source_app':'material-comic-workbench','source_result_id':row['id'],'source_content_hash':signature(row),'source_delivery_hash':delivery_signature(row,mapping,rules)}
                entries.append((row['id'],delivery_signature(row,mapping,rules),payload))
            bid=queue(self,entries,blocked);dispatch(self,bid);deadline=time.monotonic()+4
            while time.monotonic()<deadline:
                self.sync();result=response(self,bid)
                if not result['pending']:return result
                time.sleep(.15)
            return response(self,bid)


def decorate(c,rows):
    settings={r['key']:json.loads(r['value']) for r in c.execute("SELECT key,value FROM settings WHERE key IN ('push_category_map','push_score_rules')")};mapping=settings.get('push_category_map',{});rules=settings.get('push_score_rules')
    from push_targets import project_in
    target=project_in(c)/'picfactory_matrix.db'
    for row in rows:
        record=c.execute('SELECT state,target_key,error,updated_at FROM result_pushes WHERE result_id=? AND target_path=? AND content_hash=?',(row['id'],str(target),delivery_signature(row,mapping,rules))).fetchone()
        row.update(push_state=record['state'] if record else 'not_pushed',push_target_key=record['target_key'] if record else '',push_error=record['error'] if record else '',pushed_at=record['updated_at'] if record and record['state']=='pushed' else '')
