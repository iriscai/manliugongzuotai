import json,shutil
from pathlib import Path
root=Path(__file__).resolve().parents[1];fixture=json.loads((root/'build/writing-bulk-fixture.json').read_text(encoding='utf8'))
target=Path(fixture['data']).parent/'app';target.mkdir(exist_ok=True)
for name in ['renderer','resources','assets']:shutil.copytree(root/name,target/name,dirs_exist_ok=True)
for name in ['main.js','preload.js','package.json']:shutil.copy2(root/name,target/name)
(target/'backend').mkdir(exist_ok=True)
shutil.copy2('C:/Users/74319/Desktop/漫画文章工作台_V0.3.0/resources/app/backend/comic-backend.exe',target/'backend/comic-backend.exe')
main=(target/'main.js').read_text(encoding='utf8')
needle="ipcMain.handle('api',async(_event,route,options={})=>{"
assert main.count(needle)==1
main=main.replace(needle,"globalThis.bulkPosts=[];globalThis.bulkSkip=[];globalThis.bulkNoFailures=false;\n"+needle+"\n if(route==='/run/retry-seeds'){globalThis.bulkPosts.push(options.body);return {run_id:'ui-test-only',total:options.body.ids.length};}\n")
needle="const data=await response.json();if(!response.ok)throw new Error(data.error||'请求失败');return data;"
assert main.count(needle)==1
main=main.replace(needle,"const data=await response.json();if(!response.ok)throw new Error(data.error||'请求失败');if(route.startsWith('/run/writing?')&&new URLSearchParams(route.split('?')[1]).get('state')==='failed'){data.rows=globalThis.bulkNoFailures?[]:data.rows.filter(x=>!globalThis.bulkSkip.includes(x.id));if(globalThis.bulkNoFailures)data.total=0;}return data;")
(target/'main.js').write_text(main,encoding='utf8');fixture['app']=str(target)
(root/'build/writing-bulk-fixture.json').write_text(json.dumps(fixture,ensure_ascii=False),encoding='utf8')
print(json.dumps({'app':str(target),'retry_model_endpoint_mocked':True},ensure_ascii=False))
