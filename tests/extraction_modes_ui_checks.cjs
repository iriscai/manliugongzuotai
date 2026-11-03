const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');let app;
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(path.join(root,'build/extraction-modes-ui-fixture.json'),'utf8'));
 const env={...process.env,COMIC_DATA_DIR:fixture.data,COMIC_PUSH_TARGET_PROJECT:path.join(fixture.data,'unused-target')};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 const page=await app.firstWindow();
 await app.evaluate(({BrowserWindow})=>{
  BrowserWindow.getAllWindows()[0].hide();
  const real=globalThis.fetch;globalThis.modePosts=[];
  globalThis.fetch=async(url,opts)=>{
   const route=new URL(url).pathname;
   if(['/run/start','/run/enqueue'].includes(route)){
    const body=JSON.parse(opts.body);modePosts.push({route,body});
    return new Response(JSON.stringify({run_id:'mode-ui-mock',total:body.ids.length}),{status:200,headers:{'Content-Type':'application/json'}});
   }
   return real(url,opts);
  };
 });
 const errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(20000);
 await page.locator('.stat-value').first().waitFor({timeout:90000});
 await page.evaluate(async()=>navigate('settings'));
 assert.equal(await page.locator('#extraction_mode').inputValue(),'multi');
 await page.locator('#extraction_mode').selectOption('single');
 await page.locator('[data-action="save-settings"]').click();
 await page.waitForFunction(()=>state.settings.extraction_mode==='single');
 const bad=await page.evaluate(async()=>{try{await api('/settings',{extraction_mode:'invalid'});return '';}catch(e){return e.message;}});
 assert(bad.includes('提炼模式'));
 await page.reload();await page.locator('.stat-value').first().waitFor();
 await page.evaluate(async()=>showStart('both','all'));
 await page.waitForFunction(()=>executionPreview?.ids.length===2);
 assert.equal(await page.locator('#run-extraction-mode').inputValue(),'single');
 await page.locator('#run-extraction-mode').selectOption('multi');
 await page.waitForFunction(()=>executionPreview?.ids.length===3&&executionPreview.extraction_mode==='multi');
 await page.locator('[data-ops="confirm-execution"]').click();await page.waitForFunction(()=>state.page==='queue'&&!executionBusy&&!document.querySelector('#execution-config'));
 const first=await app.evaluate(()=>modePosts[0]);assert.equal(first.body.extraction_mode,'multi');assert.equal(first.body.ids.length,3);
 assert.equal(await page.evaluate(async()=>(await api('/settings')).extraction_mode),'single');
 await page.evaluate(async()=>showStart('both','all'));
 await page.waitForFunction(()=>executionPreview?.ids.length===2);
 await page.locator('#execution-advanced summary').click();
 await page.locator('#run-delivery').selectOption('queue');
 await page.waitForFunction(()=>executionPayload?.queue&&executionPreview?.ids.length===2);
 await page.locator('[data-ops="confirm-execution"]').click();await page.waitForFunction(()=>state.page==='queue'&&!executionBusy&&!document.querySelector('#execution-config'));
 const second=await app.evaluate(()=>modePosts[1]);assert.equal(second.route,'/run/enqueue');assert.equal(second.body.extraction_mode,'single');
 await page.evaluate(async()=>{materialSelection.add(3);await showDetail(1);await handleAction('process-source');});
 await page.waitForFunction(()=>executionPreview?.ids.length===1);
 assert.deepEqual(await page.evaluate(()=>executionPreview.ids),[1]);
 assert.deepEqual(await page.evaluate(()=>[...materialSelection]),[3]);
 await page.screenshot({path:path.join(root,'build/extraction-modes-ui.png'),fullPage:true});
 assert.deepEqual(errors,[]);await app.close();app=null;
 const report={ok:true,global_setting_persisted:true,execution_override:true,preview_recalculates:true,queue_payload_mode:true,single_material_selector:true,external_model_calls:0,production_changes:0};
 fs.writeFileSync(path.join(root,'build/extraction-modes-ui-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1;});
