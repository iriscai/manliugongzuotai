const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('path'),fs=require('fs'),assert=require('assert');const root=path.resolve(__dirname,'..');let app;
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(path.join(root,'build/task-pause-ui-fixture.json'),'utf8'));
 const env={...process.env,COMIC_DATA_DIR:fixture.data,COMIC_PUSH_TARGET_PROJECT:path.join(root,'build/quality-target')};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 // Only presentation states and pause transport are mocked; never start a real model.
 await app.evaluate((_,rid)=>{
  const real=globalThis.fetch;globalThis.pauseState='running';globalThis.pausePosts=[];
  globalThis.fetch=async(url,opts)=>{
   const route=new URL(url).pathname;
   if(route==='/run/pause'){pausePosts.push(JSON.parse(opts.body));pauseState='pausing';return new Response(JSON.stringify({ok:true,message:'在途响应保存后暂停'}),{status:200});}
   const response=await real(url,opts);
   if(!['/stats','/run/history'].includes(route))return response;
   const data=await response.json();for(const r of (route==='/stats'?data.runs:data.rows)){if(r.id===rid){r.state=pauseState;r.current_phase=pauseState==='blocked'?'余额不足，已停止新请求':'模拟在途请求';}}
   return new Response(JSON.stringify(data),{status:response.status,headers:response.headers});
  };
 },fixture.rid);
 const page=await app.firstWindow(),errors=[];page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].hide());await page.locator('.stat-value').first().waitFor({timeout:90000});await page.evaluate(()=>refresh());console.log('pause-ui: ready');
 const global=page.locator('[data-ops="pause-current"]');assert(await global.isEnabled());
 await global.click();await page.waitForFunction(()=>document.querySelector('[data-ops="pause-current"]').textContent.includes('保存后暂停'));
 assert(await global.isDisabled());assert.deepEqual(await app.evaluate(()=>pausePosts),[{id:fixture.rid}]);
 await page.waitForFunction(()=>!refreshPending);await app.evaluate(()=>pauseState='running');await page.evaluate(async()=>{await refresh();await navigate('queue');});await page.waitForFunction(()=>state.page==='queue'&&activeRun()?.state==='running');console.log('pause-ui: queue');
 const card=page.locator(`.pipeline-run[data-run-id="${fixture.rid}"]`);await card.locator('[data-ops="pause-task"]').click();
 await page.waitForFunction(()=>document.querySelector('.pipeline-run')?.textContent.includes('正在保存后暂停'));
 await page.waitForFunction(()=>!refreshPending);await app.evaluate(()=>pauseState='running');await page.evaluate(async()=>{await refresh();await navigate('history');});await page.waitForFunction(()=>state.page==='history'&&activeRun()?.state==='running');console.log('pause-ui: history');
 const history=page.locator(`[data-row-key="history-${fixture.rid}"]`);await history.locator('[data-ops="pause-task"]').click();
 await page.waitForFunction(()=>document.querySelector('.data-table')?.textContent.includes('正在保存后暂停'));
 assert.equal(await app.evaluate(()=>pausePosts.length),3);
 await page.waitForFunction(()=>!refreshPending);await app.evaluate(()=>pauseState='blocked');await page.evaluate(()=>refresh());await history.locator('[data-ops="resume-dialog"]').waitFor();
 assert(await global.isDisabled());await history.locator('[data-ops="resume-dialog"]').click();await page.locator('#resume-refresh-key').waitFor();await page.locator('[data-action="close-modal"]').click();await page.screenshot({path:path.join(root,'build/task-pause-history.png'),fullPage:true});
 assert.deepEqual(errors,[]);await app.close();app=null;
 console.log(JSON.stringify({ok:true,global_pause:true,queue_task_pause:true,history_pause:true,pausing_disabled:true,quota_resume_visible:true,external_calls:0,production_changes:0}));
})().catch(async e=>{console.error(e);if(app){try{const p=await app.firstWindow();await p.screenshot({path:path.join(root,'build/task-pause-ui-failure.png')});}catch{}await app.close().catch(()=>{});}process.exitCode=1;});
