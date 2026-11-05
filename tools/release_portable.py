"""Stage a local portable release without overwriting a live installation or its data."""
import argparse,hashlib,json,os,shutil,sqlite3
from contextlib import closing
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    package=json.loads((ROOT/'package.json').read_text(encoding='utf8'))
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',type=Path,default=ROOT/'build'/('portable-'+package['version']))
    parser.add_argument('--data-from',type=Path)
    args=parser.parse_args();target=args.target.resolve()
    if target.exists() and any(target.iterdir()):raise RuntimeError('请使用新的发布目录，防止覆盖运行中的程序')
    runtime=Path(os.environ.get('COMIC_ELECTRON_RUNTIME','E:/日程提醒/node_modules/electron/dist'))
    backend=ROOT/'build/backend/comic-backend.exe'
    assert backend.is_file() and backend.stat().st_size>1000000,'请先构建后端'
    shutil.copytree(runtime,target,dirs_exist_ok=True)
    named=target/'漫画文章工作台.exe';(target/'electron.exe').rename(named)
    app=target/'resources/app';app.mkdir(parents=True,exist_ok=True)
    for name in ['main.js','preload.js','package.json']:shutil.copy2(ROOT/name,app/name)
    for name in ['renderer','assets','resources']:shutil.copytree(ROOT/name,app/name)
    (app/'backend').mkdir();shutil.copy2(backend,app/'backend/comic-backend.exe')
    (target/'规则库').mkdir()
    for name in ['prompt-library.json','37类_双版本提炼规则与短文提示词.md']+[p.name for p in (ROOT/'resources').glob('military-*-*.txt')]:
        if (ROOT/'resources'/name).is_file():shutil.copy2(ROOT/'resources'/name,target/'规则库'/name)
    for name in ['使用说明.md','API接入说明.md','单次多赛道提炼说明.md']:
        shutil.copy2(ROOT/name,target/name)
    shutil.copytree(ROOT/'docs',target/'docs')
    skill=Path.home()/'.codex/skills/material-comic-article'
    if skill.is_dir():shutil.copytree(skill,target/'独立SKILL/material-comic-article',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    counts={};data=target/'data';data.mkdir()
    if args.data_from:
        source=args.data_from.resolve();assert source.is_file()
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(data/'workbench.sqlite3')) as dst:
            src.backup(dst)
            counts={t:dst.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['materials','prompts','results']}
            assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    manifest={'app':package['productName'],'version':package['version'],'exe':str(named),'data':str(data),
        'backend_sha256':hashlib.sha256(backend.read_bytes()).hexdigest(),'counts':counts,'profile':'military_ip_C_v2',
        'actual_generated_images':0,'local_release':True,'git_uploaded':False,'session_follows_data':True}
    (target/'portable-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(manifest,ensure_ascii=False))

if __name__=='__main__':main()
