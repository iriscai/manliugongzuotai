"""Reuse a saved failed response only when source, rule, model and output policy still match."""
import copy,json,re
from pathlib import Path
from funny_metadata import normalize
from funny_singlecall import audit_result
from article_flow import normalize_article

def identity(snapshot):
    s=snapshot['settings']
    keys=['provider','api_base','api_model','api_protocol','api_temperature'] if s.get('provider')=='api' else ['provider','model','reasoning']
    return {k:s.get(k) for k in keys}

def recover(worker,folder,rid,mid,eid,snapshot,variant,current_prompt):
    from workflow_management import rule_metadata
    s=worker.store
    with s.connect() as c:
        expected=c.execute('SELECT source_hash FROM run_items WHERE run_id=? AND material_id=?',(rid,mid)).fetchone()
        if not expected or not expected[0]:return None
        candidates=c.execute("SELECT w.run_id,w.error,j.snapshot_json,i.source_hash FROM run_writes w JOIN runs j ON j.id=w.run_id JOIN run_items i ON i.run_id=w.run_id AND i.material_id=w.material_id WHERE w.extraction_id=? AND w.state='failed' AND w.run_id<>? ORDER BY w.updated_at DESC,w.rowid DESC LIMIT 12",(eid,rid)).fetchall()
    current_rule=rule_metadata(snapshot,'搞笑',variant)['rule_hash']
    for candidate in candidates:
        error=candidate['error']
        if not any(x in error for x in ('T1','t1_short_reasons','t1_choice')):continue
        old_id=candidate['run_id']
        if not re.fullmatch(r'[0-9a-f]{12}',old_id) or candidate['source_hash']!=expected[0]:continue
        try:
            old=json.loads(candidate['snapshot_json'])
            if old.get('writing_policy')!=snapshot.get('writing_policy') or identity(old)!=identity(snapshot):continue
            if rule_metadata(old,'搞笑',variant)['rule_hash']!=current_rule:continue
        except (ValueError,KeyError,StopIteration):continue
        folders=list((s.root/'runs'/old_id).glob(f'{mid}-write-{eid}-*'))
        if len(folders)!=1:continue
        from article_quality import restricted_grade_contract
        try:
            if restricted_grade_contract(json.loads((folders[0]/'schema.json').read_text(encoding='utf8'))):continue
        except (OSError,ValueError):continue
        # Match the actual seed, original source and user requirements as well as snapshots.
        marker='\n本组种子：'
        try:old_prompt=(folders[0]/'prompt.txt').read_text(encoding='utf8')
        except OSError:continue
        if marker not in old_prompt or marker not in current_prompt:continue
        if old_prompt.split(marker,1)[1]!=current_prompt.split(marker,1)[1]:continue
        files=[folders[0]/'answer.json']
        if not files[0].is_file():files=sorted(folders[0].glob('raw-response-*.txt'),reverse=True)
        for path in files:
            try:
                from providers import parse_json
                answer=parse_json(path.read_text(encoding='utf-8-sig'))
                result,changes=normalize(answer)
                from providers import validate_schema
                from funny_singlecall import schema_for
                result.pop('_metadata_normalization',None)
                validate_schema(result,schema_for(variant))
                audit_result(result,variant,allow_missing_title_notes=True)
                normalize_article(copy.deepcopy(result),'搞笑')
            except (OSError,ValueError,TypeError,KeyError):continue
            result['_metadata_normalization']=changes
            result['recovered_response']={'origin':'saved_failed_response','run_id':old_id,'extraction_id':eid,
                'path':path.relative_to(s.root).as_posix(),'source_rule_model_checked':True,'additional_model_calls':0}
            folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
            (folder/'answer.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            (folder/'reuse.json').write_text(json.dumps(result['recovered_response'],ensure_ascii=False,indent=2),encoding='utf8')
            s.log(f'素材#{mid} · 种子#{eid} 复用原失败响应：来源、规则及模型一致；不新增生文请求。','response-recovery',rid,mid)
            return result
    return None
