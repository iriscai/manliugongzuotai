const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert'),{spawn,spawnSync}=require('child_process');
const root=path.resolve(__dirname,'..'),PY='C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';let app,mock;
(async()=>{
 const original=JSON.parse(fs.readFileSync(path.join(root,'build/operations-ui-fixture.json'),'utf8')).data;
 const data=path.join(root,'build/lifecycle-'+Date.now());
 mock=spawn(PY,['-X','utf8','-B',path.join(__dirname,'lifecycle_mock.py'),original,data],{windowsHide:true,stdio:['ignore','pipe','pipe']});
 const info=await new Promise((resolve,reject)=>{let text='';mock.stdout.on('data',chunk=>{text+=chunk;const i=text.indexOf('\n');if(i>=0)try{resolve(JSON.parse(text.slice(0,i)));}catch(e){reject(e);}});mock.once('exit',code=>reject(new Error('mock exited '+code)));});
 const base='http://127.0.0.1:'+info.port;
 const env={...process.env,COMIC_DATA_DIR:data};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 const page=await app.firstWindow();await page.locator('.stat-value').first().waitFor({timeout:90000});
 await page.evaluate(async base=>{await window.desktop.api('/settings',{method:'POST',body:{provider:'api',api_base:base+'/v1',api_model:'loopback-only',api_key:'fixture-safe-exit',api_retry_count:0}});},base);
 const run=await page.evaluate(async()=>{const rows=await window.desktop.api('/results');return window.desktop.api('/results/regenerate',{method:'POST',body:{ids:[rows.rows.find(r=>r.category==='生活').id]}});});
 for(let i=0;i<100;i++){if((await(await fetch(base+'/state')).json()).started)break;await new Promise(r=>setTimeout(r,50));}
 assert((await(await fetch(base+'/state')).json()).started);
 const exited=new Promise(resolve=>app.process().once('exit',resolve));
 const status=await page.evaluate(()=>window.desktop.lifecycle('safe-exit'));assert.equal(status.waiting,true);
 assert.equal((await page.evaluate(()=>window.desktop.api('/run/activity'))).model_active,true);
 await fetch(base+'/release');
 await Promise.race([exited,new Promise((_,reject)=>setTimeout(()=>reject(new Error('graceful exit did not finish')),15000))]);app=null;
 const check=spawnSync(PY,['-X','utf8','-B','-c',"import sqlite3,json,sys;c=sqlite3.connect(sys.argv[1]);print(json.dumps({'saved':c.execute(\"SELECT count(*) FROM results WHERE title='安全退出验证稿'\").fetchone()[0],'run':c.execute('SELECT state FROM runs WHERE id=?',(sys.argv[2],)).fetchone()[0]}))",path.join(data,'workbench.sqlite3'),run.run_id],{encoding:'utf8',windowsHide:true});
 assert.equal(check.status,0,check.stderr);const r=JSON.parse(check.stdout);assert.equal(r.saved,1);assert.equal(r.run,'completed');
 mock.kill();mock=null;console.log(JSON.stringify({ok:true,close_does_not_discard_inflight_response:true,safe_exit_waits_for_save:true,loopback_http_requests:1,external_model_calls:0,production_changes:0}));
})().catch(async e=>{console.error(e);if(mock)mock.kill();if(app)await app.close().catch(()=>{});process.exitCode=1;});
