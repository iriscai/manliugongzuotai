import csv,json,sys,tempfile
from pathlib import Path
import openpyxl
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,content_key
from body_fetcher import BodyFetcher
from worker import Worker

with tempfile.TemporaryDirectory(prefix='comic-intake-') as tmp:
    tmp=Path(tmp);s=Store(tmp/'data',ROOT/'resources');source=tmp/'in.csv'
    rows=[['同题','','生活','https://example.com/1'],['同题','','财经','https://example.com/2'],['同题','','生活','https://example.com/3'],['另一标题','','生活','https://example.com/4'],['纯图','','摄影','https://example.com/5'],['有字图集','','摄影','https://example.com/6'],['失败','','生活','https://example.com/7'],['视频','','生活','https://example.com/8']]
    with source.open('w',encoding='utf8',newline='') as f:w=csv.writer(f);w.writerow(['标题','正文','领域','链接']);w.writerows(rows)
    imported=s.import_file({'path':str(source)});assert imported['added']==8 and imported['duplicates']==0
    assert s.stats()['counts']['qualified']==0
    worker=Worker(s)
    try:worker.start({'mode':'both','ids':[1,7],'limit':2});raise AssertionError('unqualified work accepted')
    except ValueError as exc:assert '合格' in str(exc)
    fetch=BodyFetcher(s);jid=fetch._new_job(fetch.select({'limit':8}),s.settings())
    with s.connect() as c:expected={r['material_id']:dict(r) for r in c.execute('SELECT * FROM body_items WHERE job_id=?',(jid,))}
    out=tmp/'out.xlsx';wb=openpyxl.Workbook();ws=wb.active;ws.append(['素材ID','标题','链接','正文','抓取类型'])
    for mid,body,media in [(2,'正文甲','文章'),(1,'正文甲','文章'),(3,'正文乙','文章'),(4,'正文甲','文章'),(5,'','图'),(6,'图集中确实存在的文字','图'),(7,'[抓取失败] 页面无效',''),(8,'','视频')]:
        r=expected[mid];ws.append([mid,r['title'],r['url'],body,media])
    wb.save(out);wb.close();fetch.ingest(jid,out,expected)
    stats=s.stats()['counts'];assert stats['qualified']==4 and stats['deduplicated']==1 and stats['image_deleted']==1,stats
    with s.connect() as c:
        assert not c.execute('SELECT id FROM materials WHERE id IN (1,5)').fetchone()
        assert c.execute('SELECT count(*) FROM occurrences WHERE material_id=2').fetchone()[0]==2
        assert c.execute('SELECT kept_id FROM body_items WHERE job_id=? AND material_id=1',(jid,)).fetchone()[0]==2
        assert c.execute("SELECT status FROM body_items WHERE job_id=? AND material_id=5",(jid,)).fetchone()[0]=='image_deleted'
        assert c.execute('SELECT content_key FROM materials WHERE id=2').fetchone()[0]==content_key('同题','正文甲')
    assert s.material(3)['qualification']=='qualified' and s.material(4)['qualification']=='qualified'
    assert s.material(6)['qualification']=='qualified' and s.material(6)['body']=='图集中确实存在的文字'
    assert s.material(7)['qualification']=='pending' and s.material(8)['qualification']=='pending'
    merged=s.save_body(3,'正文甲');assert merged['action']=='duplicate' and merged['kept_id']==2
    with source.open('w',encoding='utf8',newline='') as f:w=csv.writer(f);w.writerow(['标题','正文','领域','链接']);w.writerow(['同题','正文甲','生活','https://different.example.com/new'])
    repeated=s.import_file({'path':str(source)});assert repeated['duplicates']==1 and repeated['added']==0
    with source.open('w',encoding='utf8',newline='') as f:w=csv.writer(f);w.writerow(['标题','正文','领域','链接']);w.writerow(['新标题','新正文','生活','https://example.com/2'])
    unique=s.import_file({'path':str(source)});assert unique['added']==1 and unique['intake_ids'][0]>8
    restored=Store(tmp/'data',ROOT/'resources');assert restored.stats()['counts']['qualified']==4
    with restored.connect() as c:assert c.execute('PRAGMA foreign_key_check').fetchall()==[]
    report={'ok':True,'checks':['空正文不提前去重','未验收素材禁止调用模型','异链接同标题同正文合并并保留来源','同标题不同正文保留','不同标题相同正文保留','纯图片物理删除且有记录','带有效文字的图集保留','失败和视频无正文不合格','手改正文再次去重','相同链接不同内容保留','删除后素材ID不复用','重启后验收状态保留'],'model_calls':0,'browser_calls':0}
    (ROOT/'build/intake-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report,ensure_ascii=False))
