"""Local HTTP and saved-file fixtures: no paid inference, no production writes."""
from workbench_fixtures import *
import copy,sqlite3
from contextlib import closing,contextmanager
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from types import SimpleNamespace
from providers import Providers,ProviderLimit,protect,validate_model_result
from funny_singlecall import FUNNY_J_ARTICLE,audit_result
from funny_metadata import normalize,validation_record
from funny_response_recovery import recover
from article_flow import normalize_article
from retry_policy import delay_for
from relay_client import RelayError

scripts={};received={}
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        case=self.path.split('/')[1];i=received.get(case,0);received[case]=i+1
        kind=scripts[case][min(i,len(scripts[case])-1)]
        status=503 if kind=='503' else 429 if kind=='429' else 403 if kind in ('quota','403') else 400 if kind=='400' else 200
        ctype='application/json'
        if kind in ('503','429','quota','403','400','upstream','rate'):
            code={'quota':'insufficient_user_quota','upstream':'upstream_error','rate':'gateway_concurrency_limit'}.get(kind,kind)
            obj={'error':{'code':code,'message':'fixture-only-key '+('overloaded' if kind=='upstream' else code)}}
        else:
            value='bad JSON' if kind=='badjson' else json.dumps({'answer':'ok'})
            obj={'status':'completed','output':[{'content':[{'type':'output_text','text':value}]}],'usage':{'input_tokens':3,'output_tokens':2,'total_tokens':5}} if self.path.endswith('/responses') else {'choices':[{'message':{'content':value},'finish_reason':'stop'}],'usage':{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5}}
        if kind=='stream':
            ctype='text/event-stream';raw=b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
        else:raw=json.dumps(obj).encode()
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with tempfile.TemporaryDirectory(prefix='retry-audit-') as temp:
        root=Path(temp);settings={'provider':'api','api_base':'','api_model':'fixture','api_key_encrypted':protect('fixture-only-key'),'api_retry_count':1,'api_retry_transient_only':True,'api_timeout':5,'timeout':5}
        schema={'type':'object','properties':{'answer':{'type':'string'}},'required':['answer'],'additionalProperties':False}
        def case(name,steps,count=1,protocol='chat',error=None,attempts=None):
            scripts[name]=steps;events=[]
            def event(x):
                events.append(x)
                if isinstance(x,dict) and x.get('event')=='retry_wait':return True
            p=Providers();cfg={**settings,'api_base':f'http://127.0.0.1:{server.server_port}/{name}','api_retry_count':count,'api_protocol':protocol}
            try:
                result=p.api('fixture',schema,cfg,root,event)
                assert error is None and result=={'answer':'ok'}
            except (RuntimeError,ProviderLimit) as exc:
                assert error and isinstance(exc,error),(name,str(exc));assert 'fixture-only-key' not in str(exc)
            calls=received[name];assert calls==(attempts if attempts is not None else len(steps)),(name,calls)
            assert len([x for x in events if isinstance(x,dict) and x.get('event')=='request_start'])==calls
            assert len([x for x in events if isinstance(x,dict) and x.get('event')=='request_finish'])==calls
            return events
        events=case('overload',['503','ok']);assert events[-1]['usage']['total_tokens']==5
        case('jsonupstream',['upstream','ok']);case('streamdrop',['stream','ok'])
        case('noretry',['503'],count=0,error=RuntimeError)
        case('capped',['503'],count=8,error=RuntimeError,attempts=4)
        case('rateok',['429','ok']);case('ratepause',['429'],error=ProviderLimit,attempts=2)
        case('jsonrate',['rate','ok'])
        case('quota',['quota'],count=3,error=ProviderLimit)
        case('invalid',['badjson'],count=3,error=RuntimeError)
        case('permanent',['400'],count=3,error=RuntimeError);case('forbidden',['403'],count=3,error=RuntimeError)
        case('responsesretry',['503','ok'],protocol='responses')
        case('responsesquota',['quota'],protocol='responses',count=3,error=ProviderLimit)
        e=RelayError('overloaded',503);e.retry_after=55;assert 55<=delay_for(1,e)<=60

        answer=json.loads((ROOT/'outputs/funny-J-20261101/v2/110/answer.json').read_text(encoding='utf8'))
        answer['generation_audit']['t1_titles']=[title[:55+i] for i,title in enumerate(answer['generation_audit']['t1_titles'])]
        short=copy.deepcopy(answer);short['generation_audit']['t1_short_reasons']=[];short['generation_audit']['t1_choice']='1'
        normalized,changes=normalize(short);validate_model_result(short,FUNNY_J_ARTICLE)
        assert normalized['title']==answer['title'] and normalized['article']==answer['article'] and normalized['quality_score']==answer['quality_score']
        assert normalized['generation_audit']['t1_short_reasons']==['','']
        audit_result(normalized,'J',allow_missing_title_notes=True)
        assert validation_record(normalized,changes)['warnings'] and not validation_record(normalized,changes)['publication_text_changed']
        missing=copy.deepcopy(normalized);missing['generation_audit'].pop('t1_choice');missing['title']=missing['generation_audit']['t1_titles'][1]
        repaired,_=normalize(missing);assert repaired['generation_audit']['t1_choice']==2
        def reject(value):
            try:audit_result(value,'J',allow_missing_title_notes=True)
            except ValueError:return
            raise AssertionError('invalid creative artifact accepted')
        for titles in [[answer['title']],[answer['title'],answer['title']],['短标题',answer['title']],[{},answer['title']]]:
            broken=copy.deepcopy(normalized);broken['generation_audit']['t1_titles']=titles;reject(broken)
        broken=copy.deepcopy(normalized);broken['generation_audit']['ending_link']['trigger']='虚构的核对证据';reject(broken)
        for title in ['太短','长'*65]:
            broken=copy.deepcopy(normalized);broken['title']=title;reject(broken)
        too_long=copy.deepcopy(normalized);too_long['article']='字'*301
        try:normalize_article(too_long,'搞笑');raise AssertionError('long article passed')
        except ValueError:pass

        db=root/'fixture.sqlite3'
        @contextmanager
        def connect():
            with closing(sqlite3.connect(db)) as c:
                c.row_factory=sqlite3.Row
                yield c
                c.commit()
        snap={'writing_policy':'comic_title64_v4','settings':{'provider':'api','api_base':'https://fixture.invalid','api_model':'test','api_protocol':'chat','api_temperature':.7},'prompts':[{'category':'搞笑','kind':'write','variant':'J','content':'same rule','revision':1}]}
        rid='bbbbbbbbbbbb';oldid='aaaaaaaaaaaa';mid=3;eid=4
        with connect() as c:
            c.executescript('CREATE TABLE runs(id,snapshot_json);CREATE TABLE run_items(run_id,material_id,source_hash);CREATE TABLE run_writes(run_id,material_id,extraction_id,state,error,updated_at);')
            c.execute('INSERT INTO runs VALUES(?,?)',(oldid,dumps(snap)));c.executemany('INSERT INTO run_items VALUES(?,?,?)',[(oldid,mid,'hash'),(rid,mid,'hash')]);c.execute('INSERT INTO run_writes VALUES(?,?,?,?,?,?)',(oldid,mid,eid,'failed','T1短标题未说明具体原因','2026-11-03'));c.commit()
        store=SimpleNamespace(root=root,connect=connect,log=lambda *a:None);w=SimpleNamespace(store=store)
        prompt='rule\n本组种子：{"topic":"same"}\n本条原始素材：{"title":"original","body":"original body"}\n用户补充要求：'
        oldfolder=root/'runs'/oldid/f'{mid}-write-{eid}-abc';oldfolder.mkdir(parents=True)
        (oldfolder/'schema.json').write_text(dumps(FUNNY_J_ARTICLE),encoding='utf8')
        (oldfolder/'prompt.txt').write_text(prompt,encoding='utf8');(oldfolder/'raw-response-1.txt').write_text(dumps(normalized),encoding='utf8')
        saved=recover(w,root/'new',rid,mid,eid,snap,'J',prompt)
        assert saved and saved['title']==answer['title'] and saved['article']==answer['article'] and saved['recovered_response']['additional_model_calls']==0
        wrong_schema=copy.deepcopy(FUNNY_J_ARTICLE);wrong_schema['properties']['quality_score']['properties']['fun']['enum']=[1,2]
        (oldfolder/'schema.json').write_text(dumps(wrong_schema),encoding='utf8')
        assert recover(w,root/'reject',rid,mid,eid,snap,'J',prompt) is None
        (oldfolder/'schema.json').write_text(dumps(FUNNY_J_ARTICLE),encoding='utf8')
        for change in ['api_model','writing_policy','rule']:
            changed=copy.deepcopy(snap)
            if change=='api_model':changed['settings']['api_model']='other'
            elif change=='writing_policy':changed['writing_policy']='other'
            else:changed['prompts'][0]['content']='other'
            assert recover(w,root/'reject',rid,mid,eid,changed,'J',prompt) is None
        assert recover(w,root/'reject',rid,mid,eid,snap,'J',prompt+'changed requirements') is None
        with connect() as c:c.execute('UPDATE run_items SET source_hash=? WHERE run_id=?',('changed',rid))
        assert recover(w,root/'reject',rid,mid,eid,snap,'J',prompt) is None
    report={'ok':True,'bounded_transient_retries_chat_and_responses':True,'rate_retries_then_pause':True,'quota_never_retried':True,'content_errors_no_paid_retry':True,'per_attempt_usage':True,'no_fabricated_title_reason':True,'real_quality_guards_kept':True,'saved_response_reuse_requires_source_rule_model_seed_requirements_match':True,'external_model_calls':0,'production_changes':0}
    (ROOT/'build/retry-audit-checks.json').write_text(dumps(report),encoding='utf8');print(dumps(report))
finally:server.shutdown();server.server_close()
