"""Isolate only scores proven to originate from the invalid 1/2 schema. No inference."""
import argparse,json,sqlite3,sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from article_quality import restricted_grade_contract
from title_push import signature

def candidates(c,data,run_id):
    found=[]
    for row in c.execute("SELECT * FROM results WHERE batch_id=? AND category='搞笑' AND score_status='scored'",(run_id,)):
        row=dict(row)
        if row['score_content_hash']!=signature(row):continue
        try:
            review=json.loads(row['score_json'])
            if review.get('evaluator')!='生成模型同次响应' or review.get('content_hash')!=row['score_content_hash']:continue
            paths=list((data/'runs'/run_id).glob(f"{row['material_id']}-write-{row['extraction_id']}-*/schema.json"))
            if len(paths)!=1:continue
            schema_path=paths[0];schema=json.loads(schema_path.read_text(encoding='utf8'))
            reason=restricted_grade_contract(schema)
            if not reason:continue
            answer=json.loads((schema_path.parent/'answer.json').read_text(encoding='utf-8-sig'))
            article='\n'.join(line.strip() for line in answer['article'].splitlines() if line.strip())
            if answer['title'].strip()!=row['title'] or article!=row['article']:continue
            returned=answer['quality_score']
            if any(returned.get(k)!=review.get(k) for k in ('completeness','reversal','fun','reason','evidence','risks')):continue
            found.append((row,review,reason,schema_path.relative_to(data).as_posix()))
        except (OSError,ValueError,TypeError,KeyError):continue
    return found

def repair(data,run_id,apply=False):
    import re
    data=Path(data).resolve();db=data/'workbench.sqlite3'
    if not re.fullmatch('[a-f0-9]{12}',run_id) or not db.is_file():raise ValueError('请提供已存在的数据目录及12位任务编号')
    with closing(sqlite3.connect(db.as_uri()+('?mode=rw' if apply else '?mode=ro'),uri=True,timeout=30)) as c:
        c.row_factory=sqlite3.Row
        found=candidates(c,data,run_id)
        report={'run_id':run_id,'apply':apply,'affected':len(found),'ids':[x[0]['id'] for x in found],'model_calls':0,'article_text_changed':False}
        if not apply or not found:return report
        if c.execute("SELECT 1 FROM runs WHERE state IN ('running','pausing') LIMIT 1").fetchone():raise ValueError('仍有模型任务运行，请等待安全暂停或结束后处理评分')
        stamp=datetime.now(ZoneInfo('Asia/Shanghai'));backup=data/'backups'/('score-contract-'+stamp.strftime('%Y%m%d-%H%M%S-%f'));backup.mkdir(parents=True)
        with closing(sqlite3.connect(backup/'workbench.sqlite3')) as dest:c.backup(dest)
        try:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM runs WHERE state IN ('running','pausing') LIMIT 1").fetchone():raise ValueError('新任务已启动，未修改评分')
            for row,review,reason,path in found:
                invalid={**review,'error':'原评分约束错误，分数无效，待重新评分。'+reason+'；不得直接换算百分制。','validation_status':'invalid_contract','previous_final_total':row['score'],'invalidated_at':stamp.isoformat(timespec='seconds'),'invalid_schema_path':path}
                changed=c.execute("UPDATE results SET score=NULL,score_status='invalid_contract',score_json=? WHERE id=? AND score_status='scored' AND score_json=? AND content_revision=? AND title=? AND article=?",(json.dumps(invalid,ensure_ascii=False),row['id'],row['score_json'],row['content_revision'],row['title'],row['article'])).rowcount
                if changed!=1:raise ValueError('评分或原稿已变化，取消本次修复')
            c.commit()
        except Exception:c.rollback();raise
        report['backup']=str(backup)
        (backup/'repair.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--data',type=Path,required=True);parser.add_argument('--run-id',required=True);parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();print(json.dumps(repair(args.data,args.run_id,args.apply),ensure_ascii=False))
