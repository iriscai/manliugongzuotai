"""Independent persisted availability for each extraction and writing prompt."""

def install_schema(c):
    cols={r[1] for r in c.execute('PRAGMA table_info(prompts)')}
    if 'enabled' not in cols:c.execute('ALTER TABLE prompts ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1')
    if 'status_updated_at' not in cols:c.execute("ALTER TABLE prompts ADD COLUMN status_updated_at TEXT NOT NULL DEFAULT ''")
    c.execute('CREATE TABLE IF NOT EXISTS prompt_status_history(id INTEGER PRIMARY KEY,prompt_id INTEGER,old_enabled INTEGER,new_enabled INTEGER,created_at TEXT)')

def enabled_rules(snapshot,category,kind):
    return [p for p in snapshot.get('prompts',[]) if p['category']==category and p['kind']==kind and p.get('enabled',1)]

def resolve_variant(snapshot,category,kind,requested):
    if 'prompts' not in snapshot:return requested
    available=enabled_rules(snapshot,category,kind)
    if not available:raise ValueError(category+'的'+('提炼规则' if kind=='extract' else '改写提示词')+'已全部停用，请先启用至少一个版本')
    if any(p['variant']==requested for p in available):return requested
    return sorted(available,key=lambda p:p['variant'])[0]['variant']

def active_categories(prompts,settings,mode):
    requested=settings.get('allowed_categories') or list(dict.fromkeys(p['category'] for p in prompts))
    snapshot={'prompts':prompts};kinds=['extract','write'] if mode=='both' else ['write'] if mode=='write' else ['extract']
    active=[cat for cat in requested if all(enabled_rules(snapshot,cat,k) for k in kinds)]
    return active,[cat for cat in requested if cat not in active]

def set_enabled(store,payload):
    from store import now
    import json,hashlib
    pid=payload.get('id');value=payload.get('enabled')
    trial=False
    if type(pid) is not int or pid<1 or type(value) is not bool:raise ValueError('规则编号和启用状态无效')
    with store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT id,category,kind,variant,enabled,revision,content FROM prompts WHERE id=?',(pid,)).fetchone()
        if not row:raise ValueError('规则不存在')
        if payload.get('trial_enable') is True and (row['category']!='搞笑' or row['variant']!='J'):raise ValueError('手动试用入口仅适用于搞笑J版')
        if 'expected_revision' in payload and payload['expected_revision']!=row['revision']:raise ValueError('规则内容已变化，请刷新后重试')
        if value and row['category']=='搞笑' and row['variant']=='I':
            import json
            from funny_singlecall import current_hash
            validation=c.execute("SELECT value FROM settings WHERE key='funny_singlecall_validation'").fetchone()
            validation=json.loads(validation[0]) if validation else {}
            if validation.get('status')!='approved' or validation.get('content_sha256')!=current_hash(c):raise ValueError('方案I尚未通过当前内容版本的90分试跑，不能启用')
        if value and row['category']=='搞笑' and row['variant']=='J':
            import json
            from funny_j_profile import current_hash
            validation=c.execute("SELECT value FROM settings WHERE key='funny_J_validation'").fetchone()
            validation=json.loads(validation[0]) if validation else {}
            if validation.get('status')!='approved' or validation.get('content_sha256')!=current_hash(c):
                if payload.get('trial_enable') is not True:raise ValueError('J版未通过90分验证；如需测试，请使用“试用启用J”入口')
                if type(payload.get('expected_revision')) is not int or payload['expected_revision']!=row['revision']:raise ValueError('请刷新J版内容后再手动试用')
                trial=True
        if 'expected_enabled' in payload and payload['expected_enabled']!=bool(row['enabled']):raise ValueError('规则状态已变化，请刷新后重试')
        changed=bool(row['enabled'])!=value
        if changed:
            c.execute('INSERT INTO prompt_status_history(prompt_id,old_enabled,new_enabled,created_at) VALUES(?,?,?,?)',(pid,row['enabled'],int(value),now()))
            c.execute('UPDATE prompts SET enabled=?,status_updated_at=? WHERE id=?',(int(value),now(),pid))
        if trial:
            stored=c.execute("SELECT value FROM settings WHERE key='funny_J_trial'").fetchone();records=json.loads(stored[0]) if stored else {}
            records[row['kind']]={'prompt_id':pid,'revision':row['revision'],'content_sha256':hashlib.sha256(row['content'].encode()).hexdigest(),'last_enabled_at':now(),'source':'manual_trial','quality_status':validation.get('status','pending')}
            c.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',('funny_J_trial',json.dumps(records,ensure_ascii=False)))
    if trial and changed:store.log(f'搞笑J版{row["kind"]}规则R{row["revision"]}由用户手动试用启用，90分验证状态仍为{validation.get("status","pending")}。','prompt-trial')
    return {'ok':True,'id':pid,'enabled':value,'changed':changed,'trial':trial,'note':'状态已保存，对新任务生效；已启动任务沿用原快照'}
