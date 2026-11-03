"""Persist the per-run topic scope independently from the global default."""
DEFAULT='multi'
LABELS={'single':'1→1 同赛道','multi':'1→N 多赛道'}

def normalize(value):
    if not isinstance(value,str) or value not in LABELS:
        raise ValueError('提炼模式需为single（1→1 同赛道）或multi（1→N 多赛道）')
    return value

def resolve(payload,settings):
    return normalize(payload.get('extraction_mode',settings.get('extraction_mode',DEFAULT)))

def for_snapshot(snapshot):
    # Missing historical values always mean the original multi-lane behavior.
    return normalize(snapshot.get('extraction_mode',DEFAULT))

def seed_scope(mode,seed='e',material='materials'):
    normalize(mode)
    clause=f"{seed}.extraction_mode='{mode}'"
    if mode=='single':clause+=f' AND {seed}.category={material}.category'
    return clause
