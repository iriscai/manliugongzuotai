from pathlib import Path
import hashlib
import json
import shutil
import sqlite3

ROOT=Path(__file__).resolve().parent
TARGET=Path('C:/Users/74319/Desktop/漫画文章工作台_V0.3.0')
RUNTIME=Path('E:/日程提醒/node_modules/electron/dist')
assert TARGET.parent==Path('C:/Users/74319/Desktop')
if TARGET.exists() and not (TARGET/'portable-manifest.json').exists():raise RuntimeError('目标目录已存在且不属于本构建，停止覆盖')
exe=ROOT/'build/backend/comic-backend.exe'
assert exe.is_file() and exe.stat().st_size>1000000
shutil.copytree(RUNTIME,TARGET,dirs_exist_ok=True)
original=TARGET/'electron.exe';named=TARGET/'漫画文章工作台.exe'
if original.exists():
    if named.exists():named.unlink()
    original.rename(named)
app=TARGET/'resources/app';app.mkdir(parents=True,exist_ok=True)
for name in ['main.js','preload.js','package.json']:shutil.copy2(ROOT/name,app/name)
for name in ['renderer','assets','resources']:shutil.copytree(ROOT/name,app/name,dirs_exist_ok=True)
(app/'backend').mkdir(exist_ok=True);shutil.copy2(exe,app/'backend/comic-backend.exe')
(TARGET/'规则库').mkdir(exist_ok=True)
for name in ['prompt-library.json','37类_双版本提炼规则与短文提示词.md']:shutil.copy2(ROOT/'resources'/name,TARGET/'规则库'/name)
for name in ['使用说明.md','API接入说明.md','单次多赛道提炼说明.md']:
    if (ROOT/name).is_file():shutil.copy2(ROOT/name,TARGET/name)
skill=Path('C:/Users/74319/.codex/skills/material-comic-article')
shutil.copytree(skill,TARGET/'独立SKILL/material-comic-article',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
data=TARGET/'data';data.mkdir(exist_ok=True)
if not (data/'workbench.sqlite3').exists():
    previous=Path('C:/Users/74319/Desktop/漫画文章工作台_V0.2.0/data/workbench.sqlite3')
    source=sqlite3.connect(previous if previous.exists() else ROOT/'data/workbench.sqlite3');dest=sqlite3.connect(data/'workbench.sqlite3')
    source.backup(dest);dest.close();source.close()
with sqlite3.connect(data/'workbench.sqlite3') as c:
    count=c.execute('SELECT count(*) FROM materials').fetchone()[0]
    prompt_count=c.execute('SELECT count(*) FROM prompts').fetchone()[0]
assert prompt_count==148
manifest={'app':'漫画文章工作台','version':'0.10.3','exe':str(named),'data':str(data),'material_count':count,'prompt_count':prompt_count,'backend_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'actual_generated_images':0,'body_engine':'ArticleBodyScraper (external file-mode executable)','source_database_migrated_without_overwriting_existing':True,'intake_workflow':'auto_fetch_then_title_and_body_dedup_then_qualify','image_only':'delete','browser_worker_options':[1,2,4,8]}
manifest.update(extraction_scheme='adaptive_topics_v1',target_topic_groups=0,single_call_multi_category_extraction=True,output_mode='article',verification_policy='direct_seed',writing_policy='comic_title64_v4')
(TARGET/'portable-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(manifest,ensure_ascii=False,indent=2))
