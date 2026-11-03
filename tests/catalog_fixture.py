import csv,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from store import Store,now

def seed(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);s=Store(folder/'data',ROOT/'resources');p=folder/'catalog.csv'
    rows=[['春天图书角','图书角 周日 借书流程。'+'完整正文内容需保留。'*40,'生活','1.2万','2026-10-27 09:00','https://fixture.example/1'],['图书角值班表','周一按表值班，记录借阅时间。','教育','200,000','2026-10-28T10:30','https://fixture.example/2'],['花艺课','鲜花修剪与花瓶的搭配。','自定义赛道','3亿','','https://fixture.example/3'],['100%真实_案例','标点%和_是原始文字。','生活','1.5千','2026年10月26日','https://fixture.example/4'],['天气笔记','观测风向和云层变化。','自定义赛道','0','未公布','https://fixture.example/5'],['待抓取素材','','生活','10','','https://fixture.example/6']]
    with p.open('w',encoding='utf8',newline='') as f:w=csv.writer(f);w.writerow(['标题','正文','分类','阅读量','发布日期','链接']);w.writerows(rows)
    s.import_file({'path':str(p)})
    with s.connect() as c:
        for mid,current in [(1,1),(1,0),(2,1),(4,1),(4,0),(4,0)]:c.execute('INSERT INTO extractions(material_id,category,data_json,current,created_at) VALUES(?,?,?,?,?)',(mid,'生活','{}',current,now()))
    return s,p

if __name__=='__main__':
    s,p=seed(sys.argv[1]);print(json.dumps({'data':str(s.root),'file':str(p)},ensure_ascii=False))
