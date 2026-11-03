"""Funny-lane profiles. Other categories always retain their original variant."""
import json

RELEASE_KEY='funny_1005_20261031_v1'
VARIANTS=tuple('ABCDEFGHIJ')

def selected_variant(snapshot,category,kind,fallback):
    selected=fallback
    if category=='搞笑':
        configured=snapshot['settings'].get('funny_'+kind+'_variant','follow')
        if configured!='follow':
            if configured not in VARIANTS:raise ValueError('搞笑赛道方案需为A至J或跟随全局')
            selected=configured
    from prompt_status import resolve_variant
    return resolve_variant(snapshot,category,kind,selected)

def migrate_funny_rules(c,resources,timestamp):
    c.execute('CREATE TABLE IF NOT EXISTS prompt_library_updates(key TEXT PRIMARY KEY,applied_at TEXT)')
    if c.execute('SELECT 1 FROM prompt_library_updates WHERE key=?',(RELEASE_KEY,)).fetchone():return
    library=json.loads((resources/'prompt-library.json').read_text(encoding='utf8'))
    funny=next(x for x in library['categories'] if x['category']=='搞笑')
    # Legacy resources must not silently mark this migration as completed.
    if not set('ABCDEFGHI').issubset({p['id'] for p in funny['rewrite_prompts']}):return
    for key,kind in [('extraction_rules','extract'),('rewrite_prompts','write')]:
        for rule in funny[key]:
            row=c.execute("SELECT id,content,revision,name FROM prompts WHERE category='搞笑' AND kind=? AND variant=?",(kind,rule['id'])).fetchone()
            if not row:
                c.execute('INSERT INTO prompts(category,kind,variant,name,content,updated_at) VALUES(?,?,?,?,?,?)',('搞笑',kind,rule['id'],rule['name'],rule['text'],timestamp))
            elif row['content']!=rule['text'] or row['name']!=rule['name']:
                c.execute('INSERT INTO prompt_history(prompt_id,content,revision,created_at) VALUES(?,?,?,?)',(row['id'],row['content'],row['revision'],timestamp))
                c.execute('UPDATE prompts SET name=?,content=?,revision=revision+1,updated_at=? WHERE id=?',(rule['name'],rule['text'],timestamp,row['id']))
    c.execute('INSERT INTO prompt_library_updates VALUES(?,?)',(RELEASE_KEY,timestamp))
