import csv
import json
from pathlib import Path
import sys
import tempfile
import openpyxl
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store
from body_fetcher import BodyFetcher

checks=[]
with tempfile.TemporaryDirectory(prefix='body-adapter-checks-') as tmp:
    tmp=Path(tmp);s=Store(tmp/'data',ROOT/'resources');fetch=BodyFetcher(s)
    inp=tmp/'in.csv'
    with inp.open('w',encoding='utf8',newline='') as f:
        w=csv.writer(f);w.writerow(['标题','链接','领域'])
        for i in range(1,6):w.writerow([f'素材{i}',f'https://example.com/{i}','财经'])
    s.import_file({'path':str(inp)});rows=fetch.select({'limit':5});jid=fetch._new_job(rows,s.settings())
    with s.connect() as c:expected={r['material_id']:dict(r) for r in c.execute('SELECT * FROM body_items WHERE job_id=?',(jid,))}
    out=tmp/'out.xlsx';wb=openpyxl.Workbook();ws=wb.active;ws.append(['素材ID','标题','链接','正文','抓取类型'])
    long_body='完整原文'+''.join(f'第{i}条事实说明保留对应顺序与数字用途。' for i in range(100))
    for mid,body,kind in [(3,'','图'),(1,long_body,'文章'),(2,'[抓取失败] 网站暂时不可访问',''),(4,'[无文字正文] 链接已失效',''),(5,'字'*32767,'文章')]:
        r=expected[mid];ws.append([mid,r['title'],r['url'],body,kind])
    wb.save(out);wb.close();assert fetch.ingest(jid,out,expected)==5
    assert s.material(1)['body']==long_body and len(long_body)>800
    assert s.material(1)['state']=='pending'
    assert s.material(2)['body']=='' and s.material(2)['body_status']=='failed'
    with s.connect() as c:
        assert not c.execute('SELECT id FROM materials WHERE id=3').fetchone()
        removed=json.loads(c.execute("SELECT payload_json FROM removed_materials WHERE material_id=3 AND reason='image_only'").fetchone()[0])
        assert removed['material']['category']=='财经'
    assert s.material(4)['body_status']=='gone' and s.material(4)['body']==''
    assert s.material(5)['body']=='' and s.material(5)['body_status']=='truncated'
    assert fetch.ingest(jid,out,expected)==0
    checks+=['按素材ID匹配乱序输出，不靠行序','超过800字正文完整入库','失败提示不作为正文','纯图片从素材库删除，原领域留在执行记录','失效链接单独记录','Excel上限疑似截断不进入写文','已成功结果不重复回写']
    wb=openpyxl.load_workbook(out);ws=wb.active;ws.cell(2,3,'https://wrong.example.com/mismatched');bad=tmp/'bad.xlsx';wb.save(bad);wb.close()
    try:fetch.ingest(jid,bad,expected);raise AssertionError('mismatched URL accepted')
    except ValueError:pass
    checks.append('结果链接与源行不一致时拒收')
    with s.connect() as c:c.execute("UPDATE materials SET body='',body_status='missing',state='needs_source' WHERE id=2")
    fetch.active_id=None
    ready=fetch.select({'limit':100});assert {x['id'] for x in ready}=={2,5}
    checks.append('已完成和无文字正文素材自动跳过')
print(json.dumps({'ok':True,'checks':checks,'external_browser_calls':0},ensure_ascii=False,indent=2))
