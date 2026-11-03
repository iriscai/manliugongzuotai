"""Indexed material metadata and server-side catalog queries."""
from __future__ import annotations
from datetime import date,datetime
import math
import re

def suggested_mapping(headers):
    aliases={'title':['标题','title'],'body':['正文','全文','文章正文','body','content'],'category':['领域','分类','category'],'url':['链接','原文链接','url'],'read_count':['阅读量','阅读(播放)量','阅读（播放）量','阅读','read_count','播放量'],'published_at':['发布日期','发布时间','发布日','published_at','publish_time']}
    result={key:next((x for x in names if x in headers),'') for key,names in aliases.items()}
    if not result['title'] and headers:result['title']=headers[0]
    return result

def read_number(value):
    if isinstance(value,bool):raise ValueError('阅读量需为非负数字')
    text=str(value or '0').strip().lower().replace(',','').replace('，','').replace(' ','')
    match=re.fullmatch(r'(\d+(?:\.\d+)?)\s*([万亿千wkm]?)',text)
    if not match:raise ValueError('阅读量支持数字及万、亿，例如10000或1万')
    number=float(match.group(1))*{'':1,'万':10000,'w':10000,'亿':100000000,'千':1000,'k':1000,'m':1000000}[match.group(2)]
    if not math.isfinite(number):raise ValueError('阅读量超出有效范围')
    return number

def publication(value):
    if isinstance(value,datetime):return value.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(value,date):return value.isoformat()
    text=str(value or '').strip()
    normalized=text.replace('年','-').replace('月','-').replace('日','').replace('/','-').replace('T',' ')
    try:
        parsed=datetime.fromisoformat(normalized.replace('Z','+00:00'))
        return parsed.strftime('%Y-%m-%d %H:%M:%S') if (' ' in normalized) else parsed.date().isoformat()
    except ValueError:
        for pattern in ['%Y-%m-%d %H:%M','%Y-%m-%d %H:%M:%S','%Y-%m-%d','%Y%m%d']:
            try:return datetime.strptime(normalized,pattern).strftime('%Y-%m-%d %H:%M:%S') if '%H' in pattern else datetime.strptime(normalized,pattern).date().isoformat()
            except ValueError:pass
    return ''

def install_schema(c):
    columns={r[1] for r in c.execute('PRAGMA table_info(materials)')}
    count_new='extraction_count' not in columns
    dates_new='published_sort' not in columns or 'published_day' not in columns
    for name,kind in [('extraction_count','INTEGER NOT NULL DEFAULT 0'),('published_day',"TEXT DEFAULT ''"),('published_sort',"TEXT DEFAULT ''")]:
        if name not in columns:c.execute(f'ALTER TABLE materials ADD COLUMN {name} {kind}')
    if count_new:c.execute('UPDATE materials SET extraction_count=(SELECT count(*) FROM extractions e WHERE e.material_id=materials.id)')
    if dates_new:
        values=[]
        for row in c.execute('SELECT id,published_at FROM materials'):
            normalized=publication(row['published_at']);values.append((normalized,normalized[:10],row['id']))
        c.executemany('UPDATE materials SET published_sort=?,published_day=? WHERE id=?',values)
    for statement in [
        'CREATE INDEX IF NOT EXISTS idx_material_read ON materials(read_count,id)',
        'CREATE INDEX IF NOT EXISTS idx_material_publish_day ON materials(published_day,id)',
        'CREATE INDEX IF NOT EXISTS idx_material_publish_sort ON materials(published_sort,id)',
        'CREATE INDEX IF NOT EXISTS idx_material_extract_count ON materials(extraction_count,id)',
        'CREATE INDEX IF NOT EXISTS idx_material_body_length ON materials(length(body),id)',
        'CREATE INDEX IF NOT EXISTS idx_material_qualified_state ON materials(qualification,state,id)',
        '''CREATE TRIGGER IF NOT EXISTS material_extraction_insert AFTER INSERT ON extractions BEGIN
             UPDATE materials SET extraction_count=extraction_count+1 WHERE id=NEW.material_id; END''',
        '''CREATE TRIGGER IF NOT EXISTS material_extraction_delete AFTER DELETE ON extractions BEGIN
             UPDATE materials SET extraction_count=max(0,extraction_count-1) WHERE id=OLD.material_id; END''',
        '''CREATE TRIGGER IF NOT EXISTS material_extraction_move AFTER UPDATE OF material_id ON extractions
             WHEN OLD.material_id<>NEW.material_id BEGIN
             UPDATE materials SET extraction_count=max(0,extraction_count-1) WHERE id=OLD.material_id;
             UPDATE materials SET extraction_count=extraction_count+1 WHERE id=NEW.material_id; END'''
    ]:c.execute(statement)

def options(c,visibility='active'):
    if visibility not in ('active','deleted'):raise ValueError('未知素材位置')
    where=" WHERE deleted_at"+("<>''" if visibility=='deleted' else "=''")
    from material_workflow import options as workflow_options,NODE_MAP,MILESTONES
    return {'workflow_nodes':workflow_options(c,visibility),'workflow_milestones':[{'code':code,'label':label} for code,label,_ in MILESTONES],'categories':[dict(r) for r in c.execute('SELECT category name,count(*) count FROM materials'+where+' GROUP BY category ORDER BY count(*) DESC,category')],
            'states':[dict(r) for r in c.execute('SELECT state,count(*) count FROM materials'+where+' GROUP BY state ORDER BY state')],
            'total':c.execute('SELECT count(*) FROM materials'+where).fetchone()[0]}

def query_parts(query):
    visibility=query.get('visibility','active')
    if visibility not in ('active','deleted'):raise ValueError('未知素材位置')
    clauses=["m.deleted_at"+("<>''" if visibility=='deleted' else "=''")];args=[]
    scope=query.get('search_scope') or 'all';mode=query.get('match_mode') or 'contains'
    if scope not in ('all','title','body','url','id'):raise ValueError('未知检索字段')
    if mode not in ('contains','all','any','exact'):raise ValueError('未知关键词匹配方式')
    fields=['m.title','m.body'] if scope=='all' else ['m.'+scope]
    keyword=str(query.get('q') or '').strip()
    if len(keyword)>500:raise ValueError('检索关键词请控制在500字符以内')
    def like(text):return '%'+text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    if keyword:
        if scope=='id':
            if not keyword.isdigit():raise ValueError('按编号检索时请输入数字')
            clauses.append('m.id=?');args.append(int(keyword))
        else:
            terms=keyword.split() if mode in ('all','any') else [keyword]
            if len(terms)>20:raise ValueError('一次最多检索20个关键词')
            groups=[]
            for term in terms:
                groups.append('('+' OR '.join(field+(' = ?' if mode=='exact' else " LIKE ? ESCAPE '\\'") for field in fields)+')')
                args.extend([term if mode=='exact' else like(term)]*len(fields))
            clauses.append('('+(' OR ' if mode=='any' else ' AND ').join(groups)+')')
    excluded=str(query.get('exclude') or '').strip()
    if len(excluded)>500 or len(excluded.split())>20:raise ValueError('排除关键词过长，最多20个词、500字符')
    for term in excluded.split():
        clauses.append("NOT (m.title LIKE ? ESCAPE '\\' OR m.body LIKE ? ESCAPE '\\')");args.extend([like(term)]*2)
    for field in ['category','state','qualification']:
        if query.get(field):clauses.append('m.'+field+'=?');args.append(query[field])
    if query.get('workflow_node'):
        from material_workflow import filter_clause
        predicate,values=filter_clause(query['workflow_node'])
        clauses.append('m.id IN (SELECT f.material_id FROM material_workflow f WHERE '+predicate+')');args.extend(values)
    if query.get('import_id'):
        from usability import integer
        iid=integer(query['import_id'],1,10**12,'导入编号')
        clauses.append('EXISTS(SELECT 1 FROM occurrences io WHERE io.material_id=m.id AND io.import_id=?)');args.append(iid)
    body=query.get('body_filter') or ''
    if body:
        body_clauses={'present':"m.body<>''",'missing':"m.body=''",'failed':"m.body_status IN ('failed','truncated')",'no_text':"m.body_status IN ('video','no_text','gone')"}
        if body not in body_clauses:raise ValueError('未知正文筛选条件')
        clauses.append(body_clauses[body])
    for prefix,column,parser in [('read','m.read_count',read_number),('extract','m.extraction_count',int),('length','length(m.body)',int)]:
        bounds=[]
        for suffix,op in [('min','>='),('max','<=')]:
            raw=query.get(prefix+'_'+suffix)
            if raw is None or raw=='':bounds.append(None);continue
            try:
                if parser is int and (isinstance(raw,bool) or not str(raw).isdigit()):raise ValueError()
                value=parser(raw)
                if value<0:raise ValueError()
            except (ValueError,TypeError):raise ValueError({'read':'阅读量','extract':'提炼次数','length':'正文字数'}[prefix]+'区间请填写有效非负数字')
            clauses.append(column+op+'?');args.append(value);bounds.append(value)
        if all(x is not None for x in bounds) and bounds[0]>bounds[1]:raise ValueError('筛选区间的最小值不能大于最大值')
    dates=[]
    for key,op in [('published_from','>='),('published_to','<=')]:
        value=query.get(key)
        if not value:dates.append(None);continue
        try:value=date.fromisoformat(value).isoformat()
        except (ValueError,TypeError):raise ValueError('发布日期需为YYYY-MM-DD格式')
        clauses.append('m.published_day'+op+'?');args.append(value);dates.append(value)
    if all(dates) and dates[0]>dates[1]:raise ValueError('开始日期不能晚于结束日期')
    if query.get('date_unknown') in ('1',1,True):clauses.append("m.published_day=''")
    sorts={'id':'m.id','title':'m.title','category':'m.category','read_count':'m.read_count','published_at':'m.published_sort','extraction_count':'m.extraction_count','extraction_calls':"(SELECT count(*) FROM model_requests u WHERE u.material_id=m.id AND u.stage<>'write')",'article_count':'(SELECT count(*) FROM results r WHERE r.material_id=m.id AND r.current=1 AND r.deleted_at=\'\')','body_length':'length(m.body)','created_at':'m.created_at','updated_at':'m.updated_at'}
    sort=query.get('sort_by') or 'id';direction=str(query.get('sort_dir') or 'desc').lower()
    if sort not in sorts or direction not in ('asc','desc'):raise ValueError('未知排序字段或排序方向')
    where=' WHERE '+' AND '.join(clauses) if clauses else ''
    order=("(m.published_sort='') ASC," if sort=='published_at' else '')+sorts[sort]+' '+direction+(',m.id DESC' if sort!='id' else '')
    return where,args,order,sort,direction

def list_materials(c,query):
    try:page=max(1,int(query.get('page',1)));size=max(1,min(100,int(query.get('size',30))))
    except (ValueError,TypeError):raise ValueError('页码和每页条数需为整数')
    where,args,order,sort,direction=query_parts(query)
    total=c.execute('SELECT count(*) FROM materials m'+where,args).fetchone()[0]
    page=min(page,max(1,math.ceil(total/size)))
    sql='''SELECT m.id,m.title,substr(m.body,1,180) body_preview,length(m.body) body_length,m.category,m.url,
              m.state,m.phase,m.error,m.body_status,m.body_fetch_error,m.media_type,m.qualification,m.deleted_at,
              m.read_count,m.published_at,m.published_sort,m.published_day,m.extraction_count,m.created_at,m.updated_at,
              f.workflow_node,f.seed_count workflow_seed_count,f.generated_count workflow_generated_count,f.active_pushed_count workflow_pushed_count,
              f.deliverable_count workflow_deliverable_count,f.archived_count workflow_archived_count,f.write_failed_count workflow_write_failed_count,
              f.push_failed_count workflow_push_failed_count,f.push_blocked_count workflow_push_blocked_count,
              (SELECT count(*) FROM model_requests u WHERE u.material_id=m.id AND u.stage<>'write') extraction_calls,
              (SELECT count(*) FROM results r WHERE r.material_id=m.id AND r.current=1 AND r.deleted_at=\'\') article_count
           FROM materials m JOIN material_workflow f ON f.material_id=m.id'''+where+' ORDER BY '+order+' LIMIT ? OFFSET ?'
    rows=[dict(r) for r in c.execute(sql,args+[size,(page-1)*size])]
    from material_workflow import decorate
    decorate(rows)
    return {'rows':rows,'total':total,'all_total':c.execute("SELECT count(*) FROM materials WHERE deleted_at=''").fetchone()[0],'page':page,'size':size,'sort_by':sort,'sort_dir':direction}
