import csv,json,sqlite3,sys,tempfile
from datetime import datetime
from pathlib import Path
import openpyxl
from catalog_fixture import seed,ROOT
from material_catalog import install_schema

with tempfile.TemporaryDirectory(prefix='catalog-checks-') as folder:
    folder=Path(folder);s,p=seed(folder)
    def ids(q):return [r['id'] for r in s.list_materials(q)['rows']]
    assert ids({'q':'图书角','search_scope':'title','sort_by':'id','sort_dir':'asc'})==[1,2]
    assert ids({'q':'周日','search_scope':'body'})==[1]
    assert ids({'q':'图书角 周日','match_mode':'all'})==[1]
    assert set(ids({'q':'周日 鲜花','match_mode':'any'}))=={1,3}
    assert ids({'q':'花艺课','search_scope':'title','match_mode':'exact'})==[3]
    assert ids({'q':'/4','search_scope':'url'})==[4]
    assert ids({'q':'2','search_scope':'id'})==[2]
    assert ids({'q':'%'})==[4] and ids({'q':'_'})==[4]
    assert ids({'q':"' OR 1=1 --"})==[]
    assert ids({'q':'图书角','exclude':'周日'})==[2]
    assert set(ids({'read_min':'1万','read_max':'30万'}))=={1,2}
    assert set(ids({'published_from':'2026-10-27','published_to':'2026-10-28'}))=={1,2}
    assert set(ids({'date_unknown':'1'}))=={3,5,6}
    assert ids({'category':'生活','read_min':'1万','extract_min':'2','published_from':'2026-10-27'})==[1]
    assert set(ids({'extract_max':'0'}))=={3,5,6}
    assert ids({'sort_by':'read_count'})==[3,2,1,4,6,5]
    assert ids({'sort_by':'extraction_count'})[:3]==[4,1,2]
    assert ids({'sort_by':'published_at','sort_dir':'asc'})[:3]==[4,1,2]
    assert ids({'body_filter':'missing'})==[6]
    assert ids({'length_min':'200'})==[1]
    assert s.list_materials({'page':2,'size':2})['page']==2
    assert s.list_materials({'page':999,'size':2})['page']==3
    row=s.list_materials({'q':'1','search_scope':'id'})['rows'][0]
    assert len(row['body_preview'])==180 and row['body_length']>180
    assert len(s.material(1)['body'])>len(row['body_preview'])
    assert any(r['name']=='自定义赛道' for r in s.material_options()['categories'])
    for bad in [{'sort_by':'read_count;DROP TABLE materials'},{'sort_dir':'bad'},{'read_min':'2万','read_max':'1万'},{'extract_min':'-1'},{'published_from':'2026-99-30'},{'published_from':'2026-10-29','published_to':'2026-10-28'},{'q':'abc','search_scope':'id'}]:
        try:s.list_materials(bad);raise AssertionError('invalid filter accepted: '+str(bad))
        except ValueError:pass
    with s.connect() as c:
        assert c.execute('SELECT extraction_count FROM materials WHERE id=1').fetchone()[0]==2
        c.execute('UPDATE extractions SET current=0 WHERE material_id=1')
        assert c.execute('SELECT extraction_count FROM materials WHERE id=1').fetchone()[0]==2
        eid=c.execute('SELECT min(id) FROM extractions WHERE material_id=1').fetchone()[0]
        c.execute('UPDATE extractions SET material_id=3 WHERE id=?',(eid,))
        assert c.execute('SELECT extraction_count FROM materials WHERE id=3').fetchone()[0]==1
        c.execute('DELETE FROM extractions WHERE id=?',(eid,))
        assert c.execute('SELECT extraction_count FROM materials WHERE id=3').fetchone()[0]==0
        assert any('idx_material_read' in str(tuple(r)) for r in c.execute('EXPLAIN QUERY PLAN SELECT id FROM materials WHERE read_count>=10000 ORDER BY read_count'))
    # Native Excel dates and alternative metric headers are mapped and preserved.
    wb=openpyxl.Workbook();ws=wb.active;ws.append(['标题','正文','分类','阅读量','发布日期']);ws.append(['Excel日期测试','提供的完整正文','生活','2.5万',datetime(2026,10,29,11,30)])
    xlsx=folder/'dates.xlsx';wb.save(xlsx);wb.close();imported=s.import_file({'path':str(xlsx)})
    x=s.material(imported['intake_ids'][0]);assert x['read_count']==25000 and x['published_day']=='2026-10-29'
    assert x['extraction_count']==0 and x['qualification']=='qualified'
    legacy=sqlite3.connect(':memory:');legacy.row_factory=sqlite3.Row
    legacy.executescript("CREATE TABLE materials(id INTEGER PRIMARY KEY,title TEXT,body TEXT,qualification TEXT,state TEXT,category TEXT,published_at TEXT,read_count REAL);CREATE TABLE extractions(id INTEGER PRIMARY KEY,material_id INTEGER,current INTEGER);INSERT INTO materials VALUES(1,'旧素材','旧正文','qualified','pending','生活','2026-10-28 12:30',10000);INSERT INTO extractions VALUES(1,1,1);INSERT INTO extractions VALUES(2,1,0);")
    install_schema(legacy);assert legacy.execute('SELECT extraction_count,published_day FROM materials').fetchone()[:]==(2,'2026-10-28');legacy.close()
report={'ok':True,'checks':['六字段与正文预览','标题/正文/链接/编号检索','全部/任一/精确匹配与排除词','百分号和下划线按字面检索','分类/阅读/日期/提炼次数组合筛选','多字段升降序与分页','正文状态及字数筛选','历史提炼次数自动维护','原有记录计数迁移','阅读单位与Excel日期导入','输入校验及参数化SQL','数据库索引可用'],'model_calls':0,'production_changes':0}
(ROOT/'build/catalog-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
