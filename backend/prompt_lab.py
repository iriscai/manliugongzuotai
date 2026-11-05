"""Isolated prompt experiments using the production model bridge and usage ledger."""
import copy
import json
import threading
import time
import uuid

from store import now, dumps, digest, chars
from providers import ProviderLimit
from parallel_worker import StepPaused
from schemas import ARTICLE, obj, arr, S

DIMENSIONS = {'accuracy': '事实与原文一致性', 'fit': '赛道与主题适配', 'structure': '叙述完整与重点',
              'language': '语言自然与可读性', 'title': '标题与正文匹配'}
ASSESSMENT = obj({'assessment': obj({
    **{key: {'type': 'integer', 'minimum': 0, 'maximum': 100} for key in DIMENSIONS},
    'reason': S, 'evidence': arr(S), 'risks': arr(S)})})
ACTIVE = ('running', 'pausing')
PLAN_FIELDS = ('category', 'write_variant', 'write_rule', 'requirements')
PLAN_COLUMNS = '''(
    id INTEGER PRIMARY KEY,test_id TEXT UNIQUE,category TEXT NOT NULL,name TEXT NOT NULL,
    config_json TEXT NOT NULL,score INTEGER,created_at TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1
)'''


def install_schema(c):
    c.executescript('''
      CREATE TABLE IF NOT EXISTS prompt_test_drafts(
        category TEXT PRIMARY KEY,extract_variant TEXT NOT NULL,write_variant TEXT NOT NULL,
        extract_rule TEXT NOT NULL,write_rule TEXT NOT NULL,requirements TEXT NOT NULL DEFAULT '',
        material_id INTEGER,source_hash TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS prompt_tests(
        id TEXT PRIMARY KEY,client_id TEXT UNIQUE NOT NULL,category TEXT NOT NULL,material_id INTEGER NOT NULL,
        state TEXT NOT NULL,phase TEXT NOT NULL,snapshot_json TEXT NOT NULL,
        extraction_json TEXT NOT NULL DEFAULT '',response_json TEXT NOT NULL DEFAULT '',
        article_json TEXT NOT NULL DEFAULT '',assessment_json TEXT NOT NULL DEFAULT '',
        validation_json TEXT NOT NULL DEFAULT '[]',error TEXT NOT NULL DEFAULT '',
        reused_from TEXT NOT NULL DEFAULT '',elapsed_ms INTEGER NOT NULL DEFAULT 0,
        active_started_at TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS idx_prompt_tests_category ON prompt_tests(category,created_at DESC,id);
    ''')
    c.execute('BEGIN IMMEDIATE')
    c.execute('CREATE TABLE IF NOT EXISTS prompt_test_plans' + PLAN_COLUMNS)
    columns = {row[1] for row in c.execute('PRAGMA table_info(prompt_test_plans)')}
    if 'revision' not in columns:
        c.execute('ALTER TABLE prompt_test_plans RENAME TO prompt_test_plans_old')
        c.execute('CREATE TABLE prompt_test_plans' + PLAN_COLUMNS)
        c.execute('''INSERT INTO prompt_test_plans(id,test_id,category,name,config_json,score,created_at)
                     SELECT id,test_id,category,name,config_json,score,created_at FROM prompt_test_plans_old''')
        c.execute('DROP TABLE prompt_test_plans_old')
    c.execute("UPDATE prompt_tests SET state='paused',active_started_at='',error='上次测试中断，已保存的步骤可继续' WHERE state IN ('running','pausing')")


def tier(score):
    return '精品' if score >= 96 else '优秀' if score >= 90 else '良好' if score >= 80 else '合格' if score >= 60 else '待改进'


class PromptLab:
    def __init__(self, store, worker):
        self.store, self.worker = store, worker
        worker.prompt_lab = self

    def categories(self):
        return [r['name'] for r in json.loads((self.store.resources / 'categories.json').read_text(encoding='utf8'))['categories']]

    def category(self, value):
        if value not in self.categories():
            raise ValueError('请选择有效的测试赛道')
        return value

    def options(self):
        with self.store.connect() as c:
            counts = dict(c.execute("SELECT category,count(*) FROM materials WHERE qualification='qualified' AND deleted_at='' AND trim(title)<>'' AND trim(body)<>'' GROUP BY category"))
            active = c.execute("SELECT id,category FROM prompt_tests WHERE state IN ('running','pausing') ORDER BY created_at DESC LIMIT 1").fetchone()
        settings = self.store.settings()
        return {'categories': [{'name': cat, 'count': counts.get(cat, 0)} for cat in self.categories()],
                'prompts': [{k: p[k] for k in ('category', 'kind', 'variant', 'name', 'content', 'enabled', 'revision')} for p in self.store.prompts() if p['kind']=='write'],
                'active': dict(active) if active else None,
                'provider': settings['provider'], 'model': self.model(settings)}

    @staticmethod
    def model(settings):
        if settings.get('provider') == 'api':
            return settings.get('api_model', '')
        from providers import local_config
        return settings.get('model') or local_config().get('model') or '本机Codex配置'

    def draft(self, category):
        self.category(category)
        with self.store.connect() as c:
            row = c.execute('SELECT * FROM prompt_test_drafts WHERE category=?', (category,)).fetchone()
        if row:
            return dict(row)
        settings = self.store.settings()
        prompts = self.store.prompts(category)
        result = {'category': category, 'requirements': settings.get('requirements',''), 'material_id': None, 'source_hash': '', 'revision': 0}
        for kind in ('write',):
            rows = [p for p in prompts if p['kind'] == kind]
            preferred = settings.get(('military_' if category == '军事' else 'funny_') + kind + '_variant') if category in ('军事', '搞笑') else settings.get(kind + '_variant')
            chosen = next((p for p in rows if p['variant'] == preferred), None) or next((p for p in rows if p['enabled']), None) or rows[0]
            result[kind + '_variant'] = chosen['variant']
            result[kind + '_rule'] = chosen['content']
        return result

    def clean_draft(self, payload):
        category = self.category(payload.get('category'))
        out = {'category': category, 'extract_variant':'', 'extract_rule':''}
        prompts = self.store.prompts(category)
        for kind in ('write',):
            variant, text = payload.get(kind + '_variant'), payload.get(kind + '_rule')
            if not any(p['kind'] == kind and p['variant'] == variant for p in prompts):
                raise ValueError('请选择已有的提炼或写文版本作为测试基础')
            if not isinstance(text, str) or not text.strip() or len(text) > 120000:
                raise ValueError('提炼规则与写文提示词不能为空，单份最多12万字符')
            out[kind + '_variant'], out[kind + '_rule'] = variant, text
        requirements = payload.get('requirements', '')
        if not isinstance(requirements, str) or len(requirements) > 12000:
            raise ValueError('测试补充要求最多12000字符')
        out.update(requirements=requirements, material_id=payload.get('material_id'), source_hash=str(payload.get('source_hash', '')))
        if out['material_id'] is not None and (type(out['material_id']) is not int or out['material_id'] <= 0):
            raise ValueError('测试素材编号无效')
        return out

    def save_draft(self, payload):
        draft = self.clean_draft(payload)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT revision FROM prompt_test_drafts WHERE category=?', (draft['category'],)).fetchone()
            if 'revision' in payload and payload['revision'] != (old[0] if old else 0):
                raise ValueError('测试草稿已在其他页面更新，请重新进入测试页后编辑')
            revision = (old[0] if old else 0) + 1
            keys = list(draft) + ['revision', 'updated_at']
            c.execute('INSERT OR REPLACE INTO prompt_test_drafts(' + ','.join(keys) + ') VALUES(' + ','.join('?' for _ in keys) + ')',
                      [*draft.values(), revision, now()])
        return {'ok': True, 'revision': revision}

    def material(self, mid, category):
        self.category(category)
        with self.store.connect() as c:
            row = c.execute("SELECT id,title,body,category,url,published_at,read_count FROM materials WHERE id=? AND category=? AND qualification='qualified' AND deleted_at='' AND trim(title)<>'' AND trim(body)<>''", (mid, category)).fetchone()
        if not row:
            raise ValueError('本赛道没有这条合格素材，请重新随机抽取')
        source = {'material_id': row['id'], 'title': row['title'], 'body': row['body'], 'source_category': row['category'],
                  'url': row['url'], 'published_at': row['published_at'], 'read_count': row['read_count']}
        return {'source': source, 'source_hash': digest(dumps(source))}

    def random(self, payload):
        category = self.category(payload.get('category'))
        with self.store.connect() as c:
            rows = c.execute("SELECT id FROM materials WHERE category=? AND qualification='qualified' AND deleted_at='' AND trim(title)<>'' AND trim(body)<>'' ORDER BY random() LIMIT 2", (category,)).fetchall()
        if not rows:
            raise ValueError('该赛道暂无已抓到正文并通过验收的素材，请先导入或抓取正文')
        mid = next((r[0] for r in rows if r[0] != payload.get('exclude_id')), rows[0][0])
        return self.material(mid, category)

    def active(self):
        return bool(self.worker.current_run and self.worker.current_run.startswith('pt_') and self.worker.thread and self.worker.thread.is_alive())

    def idle(self):
        if self.worker.thread and self.worker.thread.is_alive():
            raise ValueError('已有提炼、生文、评分或提示词测试在执行，请等待完成或保存步骤后暂停')

    def start(self, payload):
        draft = self.clean_draft(payload)
        client = payload.get('client_id')
        if not isinstance(client, str) or not 8 <= len(client) <= 100:
            raise ValueError('测试请求编号无效，请刷新后重试')
        with self.worker.lock:
            with self.store.connect() as c:
                existing = c.execute('SELECT id,snapshot_json FROM prompt_tests WHERE client_id=?', (client,)).fetchone()
            if existing:
                if json.loads(existing['snapshot_json'])['draft'] != draft:
                    raise ValueError('测试请求编号已用于不同配置，请重新发起测试')
                return {'id': existing[0], 'reused': True}
            self.idle()
            selected = self.material(draft['material_id'], draft['category'])
            if draft['source_hash'] != selected['source_hash']:
                raise ValueError('所选素材内容已变化，请重新抽取后测试')
            settings = self.store.settings()
            if settings['provider'] == 'api' and not all(settings.get(k) for k in ('api_base', 'api_model', 'api_key_encrypted')):
                raise ValueError('请先在执行设置中补全中转API配置')
            if settings['provider'] == 'codex':
                status = self.worker.provider.auth_status(settings)
                if not status['ok']:
                    raise ValueError(status['message'])
            snapshot = {'source': selected['source'], 'source_hash': selected['source_hash'], 'draft': draft, 'settings': settings}
            rid, stamp = 'pt_' + uuid.uuid4().hex[:12], now()
            with self.store.connect() as c:
                c.execute('INSERT INTO prompt_tests(id,client_id,category,material_id,state,phase,snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                          (rid, client, draft['category'], draft['material_id'], 'running', 'writing', dumps(snapshot), stamp, stamp))
            self.launch(rid)
            return {'id': rid, 'reused': False}

    def record(self, rid):
        with self.store.connect() as c:
            row = c.execute('SELECT * FROM prompt_tests WHERE id=?', (rid,)).fetchone()
        if not row:
            raise ValueError('测试记录不存在')
        return dict(row)

    def launch(self, rid):
        w = self.worker
        w.current_run, w.halt_reason = rid, ''
        if getattr(w,'score_manager',None):
            w.score_manager.limit_blocked = False
        w.pause_flag.clear()
        if hasattr(w.provider, 'reset'):
            w.provider.reset()
        self.update(rid, state='running', error='', active_started_at=now())
        w.thread = threading.Thread(target=self.run, args=(rid,), daemon=True, name='prompt-test')
        w.thread.start()

    def pause(self, rid=None):
        with self.worker.lock:
            if not self.active() or rid and rid != self.worker.current_run:
                raise ValueError('该测试已结束或不在执行中，请刷新')
            self.worker.pause_flag.set()
            self.update(self.worker.current_run, state='pausing')
        return {'ok': True, 'message': '当前响应返回并保存后暂停，后续步骤不会发起新请求'}

    def resume(self, rid):
        with self.worker.lock:
            self.idle()
            row = self.record(rid)
            if row['state'] not in ('paused', 'blocked', 'failed'):
                raise ValueError('该测试无需继续')
            snapshot = json.loads(row['snapshot_json'])
            old, current = snapshot['settings'], self.store.settings()
            if current['provider'] != old['provider'] or current['provider'] == 'api' and (current.get('api_base', '').rstrip('/') != old.get('api_base', '').rstrip('/') or current.get('api_protocol', 'chat') != old.get('api_protocol', 'chat')):
                raise ValueError('执行接口已变化，请恢复原接口后继续，或重新开始测试')
            for key in (['api_key_encrypted'] if old['provider'] == 'api' else ['codex_path']):
                old[key] = current.get(key, '')
            self.update(rid, snapshot_json=dumps(snapshot))
            self.launch(rid)
        return {'id': rid}

    def update(self, rid, **fields):
        fields['updated_at'] = now()
        with self.store.connect() as c:
            c.execute('UPDATE prompt_tests SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?', [*fields.values(), rid])

    def check_pause(self):
        if self.worker.pause_flag.is_set():
            raise StepPaused()

    def call(self, rid, phase, prompt, schema, snapshot):
        self.check_pause()
        self.update(rid, phase=phase)
        settings = snapshot['settings']
        context = {'settings': settings, 'output_mode': 'article', 'usage_limits_override': {
            'request_limit': settings.get('task_request_limit', 0), 'token_limit': settings.get('task_token_limit', 0)}}
        return self.worker.call('test-' + phase, prompt, schema, rid, snapshot['source']['material_id'], context, '-' + uuid.uuid4().hex[:8])

    def write(self, rid, snapshot):
        from article_flow import article_prompt, normalize_article
        from military_profile import active, schema_for as military_schema, profile_for, prepare_answer, visible
        from funny_singlecall import MULTISTAGE_VARIANTS, schema_for as funny_schema, audit_result
        from article_quality import scored_schema
        draft, source = snapshot['draft'], snapshot['source']
        category, variant = draft['category'], draft['write_variant']
        military = active(category, variant)
        funny = category == '搞笑' and variant in MULTISTAGE_VARIANTS
        schema = military_schema(variant) if military else funny_schema(variant) if funny else scored_schema(ARTICLE, category)
        prompt = article_prompt(draft['write_rule'], source, None, category, '', draft['requirements'], variant)
        if category != '搞笑':
            schema = copy.deepcopy(schema)
            schema['properties']['assessment'] = ASSESSMENT['properties']['assessment']
            schema['required'].append('assessment')
            prompt = prompt.replace('只返回JSON的三个字段category、title、article', '返回category、title、article以及assessment')
            prompt += ('\n在同一次响应中先完成终稿，再填assessment。accuracy、fit、structure、language、title分别评价原文一致性、赛道适配、结构、语言、标题。'
                       '每项给0至100整数，reason解释分数，evidence逐字引用终稿中的1至3段短句，risks列问题。')
        answer = self.call(rid, 'writing', prompt, schema, snapshot)
        self.update(rid, response_json=dumps(answer))
        if not isinstance(answer, dict) or answer.get('category') != category or not isinstance(answer.get('title'), str) or not isinstance(answer.get('article'), str):
            raise ValueError('写文结果缺少本赛道的标题和正文，原始响应已留档')
        if not answer['title'].strip() or not visible(answer['article']).strip():
            raise ValueError('写文未返回完整文章：' + '；'.join(answer.get('material_notes') or ['标题或正文为空']))
        issues = []
        try:
            if military:
                answer = prepare_answer(answer, variant, source, {})
            if funny:
                from funny_metadata import normalize
                answer, _ = normalize(answer)
                audit_result(answer, variant, allow_missing_title_notes=True)
            if category == '军事':
                from military_ip_style import validate_article
                validate_article(answer['title'], visible(answer['article']))
            article, _, _ = normalize_article(answer, category, profile_for(variant) if military else None)
        except ValueError as exc:
            # A lab must show an imperfect draft, rather than hide the reason a prompt failed.
            issues.append(str(exc))
            article = {'category': category, 'title': answer['title'].strip(), 'article': visible(answer['article'])}
        article.update(char_count=chars(article['article']), title_chars=len(article['title']))
        self.update(rid, article_json=dumps(article), validation_json=dumps(issues))
        return article, answer, issues

    def score(self, category, article, answer):
        from article_quality import grade
        text = article['title'] + '\n' + article['article']
        if category == '搞笑':
            review = answer.get('quality_score')
            return {**grade(text, review), 'method': '生成响应内评分', 'dimensions': [
                {'name': name, 'score': review[key]} for key, name in [('completeness', '故事完整性'), ('reversal', '反转程度'), ('fun', '趣味性')]]}
        review = answer.get('assessment')
        if not isinstance(review, dict) or any(type(review.get(k)) is not int or not 0 <= review[k] <= 100 for k in DIMENSIONS):
            raise ValueError('测试评分维度必须为0至100整数，文章已保留，可重新测试')
        evidence, reason, risks = review.get('evidence'), review.get('reason'), review.get('risks')
        if not isinstance(reason, str) or not reason.strip() or not isinstance(evidence, list) or not 1 <= len(evidence) <= 3 or any(not isinstance(q, str) or not q.strip() or q not in text for q in evidence):
            raise ValueError('评分缺少具体理由，或引用并非最终文章原句；文章已保留，可重新测试')
        if not isinstance(risks, list) or any(not isinstance(r, str) for r in risks):
            raise ValueError('评分问题列表格式错误，可重新测试')
        total = (sum(review[k] for k in DIMENSIONS) + 2) // 5
        return {**review, 'final_total': total, 'final_tier': tier(total), 'method': '生成响应内评分',
                'dimensions': [{'name': name, 'score': review[key]} for key, name in DIMENSIONS.items()], 'version': 'prompt_test_general_v1'}

    def run(self, rid):
        started = time.monotonic()
        original = self.record(rid)
        snapshot = json.loads(original['snapshot_json'])
        try:
            self.check_pause()
            article, answer, _ = self.write(rid, snapshot)
            review = self.score(snapshot['draft']['category'], article, answer)
            self.update(rid, assessment_json=dumps(review), state='completed', phase='completed', error='')
        except StepPaused:
            self.update(rid, state='paused', error='已保存当前步骤，可继续未完成的步骤')
        except ProviderLimit as exc:
            if getattr(self.worker,'score_manager',None):
                self.worker.score_manager.limit_blocked = True
            self.update(rid, state='blocked', error=str(exc)[:1800])
        except Exception as exc:
            self.update(rid, state='failed', error=str(exc)[:1800])
        finally:
            self.update(rid, elapsed_ms=original['elapsed_ms'] + round((time.monotonic() - started) * 1000), active_started_at='')
            with self.worker.lock:
                if self.worker.current_run == rid:
                    self.worker.current_run = None

    def detail(self, rid):
        row = self.record(rid)
        snapshot = json.loads(row.pop('snapshot_json'))
        for key in ('extraction', 'response', 'article', 'assessment', 'validation'):
            value = row.pop(key + '_json')
            row[key] = json.loads(value) if value else None
        # Settings contain protected credentials; only expose explicit display fields.
        row.update(draft=snapshot['draft'], source=snapshot['source'], source_hash=snapshot['source_hash'],
                   provider=snapshot['settings']['provider'], model=self.model(snapshot['settings']))
        with self.store.connect() as c:
            from usage_budget import summary
            row['usage'] = summary(c, rid)
            saved = c.execute('SELECT id,name FROM prompt_test_plans WHERE test_id=?', (rid,)).fetchone()
            row['saved_plan'] = dict(saved) if saved else None
        return row

    def plans(self, category):
        self.category(category)
        with self.store.connect() as c:
            rows = [dict(r) for r in c.execute('SELECT * FROM prompt_test_plans WHERE category=? ORDER BY id DESC', (category,))]
        for row in rows:
            row['config'] = json.loads(row.pop('config_json'))
        return {'rows': rows}

    def create_plan(self, payload):
        draft = self.clean_draft(payload)
        config = {key: draft[key] for key in PLAN_FIELDS}
        name = payload.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError('方案名称需为1至120字符')
        with self.store.connect() as c:
            cursor = c.execute('INSERT INTO prompt_test_plans(category,name,config_json,created_at) VALUES(?,?,?,?)',
                               (draft['category'], name.strip(), dumps(config), now()))
            return {'ok': True, 'id': cursor.lastrowid, 'name': name.strip()}

    def update_plan(self, payload):
        draft = self.clean_draft(payload)
        config = {key: draft[key] for key in PLAN_FIELDS}
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM prompt_test_plans WHERE id=? AND category=?',
                            (payload.get('plan_id'), draft['category'])).fetchone()
            if not row:
                raise ValueError('请选择要更新的已保存方案')
            if row['revision'] != payload.get('plan_revision'):
                raise ValueError('此方案已更新，请重新进入测试页并载入后保存')
            if config != json.loads(row['config_json']):
                c.execute('UPDATE prompt_test_plans SET config_json=?,test_id=NULL,score=NULL,revision=revision+1 WHERE id=?',
                          (dumps(config), row['id']))
            return {'ok': True, 'id': row['id'], 'name': row['name']}

    def save_formal(self, payload):
        draft = self.clean_draft(payload)
        revision = payload.get('formal_revision')
        if type(revision) is not int:
            raise ValueError('请载入最新的正式版本后保存')
        prompt = next(p for p in self.store.prompts(draft['category']) if p['kind']=='write' and p['variant']==draft['write_variant'])
        return self.store.save_prompt({'id': prompt['id'], 'content': draft['write_rule'], 'expected_revision': revision})

    def save_plan(self, payload):
        row = self.record(payload.get('id'))
        if row['state'] != 'completed' or not row['assessment_json'] or json.loads(row['validation_json']):
            raise ValueError('文章生成、评分与格式校验全部完成后，才可保存为测试方案')
        snapshot = json.loads(row['snapshot_json'])
        draft, score = snapshot['draft'], json.loads(row['assessment_json'])['final_total']
        config = {key: draft[key] for key in PLAN_FIELDS}
        name = payload.get('name') or f"{row['category']} · {draft['write_variant']} · {score}分 · {row['created_at'].replace('T',' ')}"
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError('方案名称需为1至120字符')
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT OR IGNORE INTO prompt_test_plans(test_id,category,name,config_json,score,created_at) VALUES(?,?,?,?,?,?)',
                      (row['id'], row['category'], name.strip(), dumps(config), score, now()))
            saved = c.execute('SELECT id,name FROM prompt_test_plans WHERE test_id=?', (row['id'],)).fetchone()
        return {'ok': True, **dict(saved)}

    def history(self, category):
        self.category(category)
        with self.store.connect() as c:
            rows = [dict(r) for r in c.execute('SELECT id,category,material_id,state,phase,created_at,updated_at,elapsed_ms,reused_from,article_json,assessment_json FROM prompt_tests WHERE category=? ORDER BY created_at DESC,rowid DESC LIMIT 30', (category,))]
        for r in rows:
            article, assessment = r.pop('article_json'), r.pop('assessment_json')
            r['title'] = json.loads(article)['title'] if article else ''
            r['score'] = json.loads(assessment)['final_total'] if assessment else None
        return {'rows': rows}

    def handle(self, method, path, query, payload):
        action = path.rsplit('/', 1)[-1]
        if method == 'GET' and action == 'options':
            return self.options()
        if method == 'GET' and action == 'draft':
            return self.draft(query.get('category'))
        if method == 'GET' and action == 'material':
            return self.material(int(query.get('id', 0)), query.get('category'))
        if method == 'GET' and action == 'history':
            return self.history(query.get('category'))
        if method == 'GET' and action == 'plans':
            return self.plans(query.get('category'))
        if method == 'POST' and action == 'plans':
            return self.create_plan(payload)
        if method == 'PUT' and action == 'plans':
            return self.update_plan(payload)
        if method == 'PUT' and action == 'formal':
            return self.save_formal(payload)
        if method == 'GET' and action == 'detail':
            return self.detail(query.get('id'))
        if method == 'PUT' and action == 'draft':
            return self.save_draft(payload)
        if method == 'POST' and action == 'random':
            return self.random(payload)
        if method == 'POST' and action == 'start':
            return self.start(payload)
        if method == 'POST' and action == 'pause':
            return self.pause(payload.get('id'))
        if method == 'POST' and action == 'resume':
            return self.resume(payload.get('id'))
        if method == 'POST' and action == 'save-plan':
            return self.save_plan(payload)
        raise ValueError('未知提示词测试操作')
