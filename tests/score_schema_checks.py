"""Exercise the serialized percentage-score contract without paid model calls."""
import copy,json,subprocess,sys,tempfile,threading,sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from schemas import I,ARTICLE,WRITE
from article_quality import GRADE_SCHEMA,validate_grade_contract,grade,scored_schema
from funny_singlecall import FUNNY_ARTICLE,FUNNY_J_ARTICLE
from providers import Providers,protect

for schema in (FUNNY_ARTICLE,FUNNY_J_ARTICLE,scored_schema(ARTICLE,'搞笑')):
    validate_grade_contract(schema)
    dims=schema['properties']['quality_score']['properties']
    for field in ('completeness','reversal','fun'):
        assert dims[field]['type']=='integer' and dims[field]['minimum']==0 and dims[field]['maximum']==100 and 'enum' not in dims[field]
    assert len({id(dims[k]) for k in ('completeness','reversal','fun')})==3
for schema in (FUNNY_ARTICLE,FUNNY_J_ARTICLE):
    assert schema['properties']['generation_audit']['properties']['t1_choice']=={'type':'integer','enum':[1,2]}
assert I=={'type':'integer'} and WRITE['properties']['frames']['items']['properties']['number']==I

# Test both real import orders: a same-process fake provider cannot detect a wrong schema.
for order in ('import article_quality; import funny_singlecall','import funny_singlecall; import article_quality'):
    code="import sys; sys.path.insert(0,sys.argv[1]); "+order+"; from article_quality import validate_grade_contract; from funny_singlecall import FUNNY_ARTICLE,FUNNY_J_ARTICLE; validate_grade_contract(FUNNY_ARTICLE); validate_grade_contract(FUNNY_J_ARTICLE)"
    subprocess.run([sys.executable,'-c',code,str(ROOT/'backend')],check=True,capture_output=True)

received=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));received.append(payload)
        contract=json.loads(payload['messages'][0]['content'].split('\n',1)[1])
        validate_grade_contract(contract)
        assert contract['properties']['quality_score']['properties']['fun']['maximum']==100
        answer={'quality_score':{'completeness':94,'reversal':86,'fun':87,'reason':'测试按百分制返回；不把候选编号当作分数。','evidence':['朋友借我10元。'],'risks':[]}}
        raw=json.dumps({'choices':[{'message':{'content':json.dumps(answer,ensure_ascii=False)},'finish_reason':'stop'}]}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with tempfile.TemporaryDirectory(prefix='score-schema-') as tmp:
        schema={'type':'object','properties':{'quality_score':copy.deepcopy(GRADE_SCHEMA)},'required':['quality_score'],'additionalProperties':False}
        provider=Providers();settings={'provider':'api','api_base':f'http://127.0.0.1:{server.server_port}/v1','api_model':'fixture','api_key_encrypted':protect('fixture-key'),'api_retry_count':0}
        answer=provider.call('仅评分',schema,settings,Path(tmp)/'valid')
        assert grade('朋友借我10元。',answer['quality_score'])['final_total']==94 and len(received)==1
        for key in ('completeness','reversal','fun'):
            broken=copy.deepcopy(schema);broken['properties']['quality_score']['properties'][key]['enum']=[1,2]
            try:provider.call('不能发送',broken,settings,Path(tmp)/'invalid');raise AssertionError('bad score contract sent')
            except ValueError as exc:assert '评分输出约束异常' in str(exc)
        assert len(received)==1
    sys.path.insert(0,str(ROOT/'tools'))
    from invalidate_score_contract import repair
    from title_push import signature
    with tempfile.TemporaryDirectory(prefix='score-contract-repair-') as tmp:
        data=Path(tmp);run_id='aaaaaaaaaaaa';db=data/'workbench.sqlite3'
        with closing(sqlite3.connect(db)) as c:
            c.executescript('CREATE TABLE runs(id,state);CREATE TABLE results(id,extraction_id,material_id,category,title,article,short_text,batch_id,score,score_status,score_content_hash,score_json,content_revision);CREATE TABLE article_score_history(result_id,score);')
            c.execute('INSERT INTO runs VALUES(?,?)',(run_id,'completed'))
            for n in (1,2,3):
                row={'id':n,'category':'搞笑','title':'测试标题'+str(n),'article':'朋友借我10元。','short_text':'朋友借我10元。'}
                hashed=signature(row);review={'completeness':2,'reversal':2,'fun':2,'reason':'保留原始记录','evidence':['朋友借我10元。'],'risks':[],'evaluator':'人工复核' if n==3 else '生成模型同次响应','content_hash':hashed,'final_total':7}
                c.execute('INSERT INTO results VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(n,n,n,'搞笑',row['title'],row['article'],row['short_text'],run_id,7,'scored',hashed,json.dumps(review,ensure_ascii=False),1))
                c.execute('INSERT INTO article_score_history VALUES(?,?)',(n,7))
                folder=data/'runs'/run_id/f'{n}-write-{n}-abc';folder.mkdir(parents=True)
                saved_schema=copy.deepcopy(FUNNY_J_ARTICLE)
                if n!=2:
                    for key in ('completeness','reversal','fun'):saved_schema['properties']['quality_score']['properties'][key]['enum']=[1,2]
                (folder/'schema.json').write_text(json.dumps(saved_schema,ensure_ascii=False),encoding='utf8')
                (folder/'answer.json').write_text(json.dumps({'title':row['title'],'article':row['article'],'quality_score':{k:review[k] for k in ('completeness','reversal','fun','reason','evidence','risks')}},ensure_ascii=False),encoding='utf8')
            c.commit()
            original=c.execute('SELECT id,title,article,content_revision FROM results ORDER BY id').fetchall()
        assert repair(data,run_id)['ids']==[1]
        report=repair(data,run_id,True);assert report['ids']==[1] and Path(report['backup'],'workbench.sqlite3').is_file()
        with closing(sqlite3.connect(db)) as c:
            assert c.execute('SELECT id,title,article,content_revision FROM results ORDER BY id').fetchall()==original
            assert c.execute('SELECT score,score_status FROM results WHERE id=1').fetchone()==(None,'invalid_contract')
            assert c.execute('SELECT score,score_status FROM results WHERE id=2').fetchone()==(7,'scored')
            assert c.execute('SELECT score,score_status FROM results WHERE id=3').fetchone()==(7,'scored')
            assert c.execute('SELECT count(*) FROM article_score_history').fetchone()[0]==3
        assert repair(data,run_id,True)['affected']==0
    print(json.dumps({'ok':True,'I_and_J_percentage_scores':True,'title_choice_still_1_or_2':True,'shared_integer_and_frame_schema_unchanged':True,'import_order_independent':True,'real_serialized_request_0_to_100':True,'bad_contract_blocked_before_request':True,'only_proven_bad_scores_invalidated':True,'genuine_low_and_manual_scores_kept':True,'backup_and_original_articles_preserved':True,'external_model_calls':0},ensure_ascii=False))
finally:server.shutdown();server.server_close()
