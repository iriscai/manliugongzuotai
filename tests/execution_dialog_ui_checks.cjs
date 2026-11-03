const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('path'),fs=require('fs'),assert=require('assert');const root=path.resolve(__dirname,'..');let app;
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(path.join(root,'build/execution-dialog-ui-fixture.json'),'utf8'));
 const env={...process.env,COMIC_DATA_DIR:fixture.data,COMIC_PUSH_TARGET_PROJECT:path.join(root,'build/quality-target')};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 // Intercept task creation before the real backend; previews still exercise the real API.
 await app.evaluate(()=>{
  const real=globalThis.fetch;globalThis.dialogStarts=[];globalThis.previewLimits=[];
  globalThis.fetch=async(url,opts)=>{
   const route=new URL(url).pathname;
   if(route==='/run/start'||route==='/run/enqueue'){const body=JSON.parse(opts.body);dialogStarts.push({route,body});return new Response(JSON.stringify({run_id:'ui-mock',total:body.ids.length}),{status:200,headers:{'Content-Type':'application/json'}});}
   if(route==='/run/preview'){const body=JSON.parse(opts.body);previewLimits.push(body.limit);if(body.limit===4)await new Promise(r=>setTimeout(r,1000));}
   return real(url,opts);
  };
 });
 const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.locator('.stat-value').first().waitFor({timeout:90000});
 await page.locator('[data-nav="materials"]').first().click();await page.locator('.material-table').waitFor();
 await page.evaluate(async()=>{materialSelection.clear();for(let i=1;i<=30;i++)materialSelection.add(i);await render();});
 await page.locator('[data-ops="execute-selected"]').click();await page.waitForFunction(()=>executionPreview?.ids.length===28);
 assert.equal(await page.locator('#run-limit').inputValue(),'30');assert(await page.locator('[data-ops="confirm-execution"]').isEnabled());
 assert((await page.locator('#execution-preview').innerText()).includes('其余2条本轮跳过'));
 await page.locator('.execution-exclusions summary').click();assert((await page.locator('.execution-exclusions').innerText()).includes('尚未取得有效正文'));
 assert.equal(await app.evaluate(()=>dialogStarts.length),0);
 await page.screenshot({path:path.join(root,'build/execution-dialog-ready.png'),fullPage:true});
 await page.locator('#run-limit').fill('0');await page.waitForFunction(()=>document.querySelector('#execution-preview')?.textContent.includes('1至1000'));
 assert(await page.locator('[data-ops="confirm-execution"]').isDisabled());
 await page.locator('#run-limit').fill('4');await page.locator('[data-ops="preview-execution"]').click();
 await page.waitForTimeout(100);await page.locator('#run-limit').fill('9');await page.waitForFunction(()=>executionPreview?.ids.length===9);
 await page.waitForTimeout(1100);assert.equal(await page.evaluate(()=>executionPreview.ids.length),9,'stale response overrode new configuration');
 await page.locator('[data-ops="confirm-execution"]').click();await page.waitForFunction(()=>state.page==='queue');
 const first=await app.evaluate(()=>dialogStarts[0]);assert.equal(first.body.ids.length,9);assert(!first.body.ids.includes(1)&&!first.body.ids.includes(2));
 await page.locator('[data-nav="overview"]').first().click();await page.locator('#start-btn').click();await page.waitForFunction(()=>executionPreview?.ids.length===20);
 assert(await page.locator('[data-ops="confirm-execution"]').isEnabled());await page.locator('[data-ops="confirm-execution"]').click();await page.waitForFunction(()=>state.page==='queue');
 assert.equal(await app.evaluate(()=>dialogStarts[1].body.ids.length),20);
 await page.evaluate(()=>{materialSelection.clear();materialSelection.add(1);materialSelection.add(2);});
 await page.locator('[data-nav="materials"]').first().click();await page.locator('[data-ops="execute-selected"]').click();await page.waitForFunction(()=>executionPreview&&executionPreview.ids.length===0);
 assert(await page.locator('[data-ops="confirm-execution"]').isDisabled());assert((await page.locator('#execution-preview').innerText()).includes('当前没有符合'));
 await page.locator('#run-delivery').selectOption('queue');await page.waitForFunction(()=>executionPreview?.ids.length===1&&executionPayload.queue);
 await page.locator('[data-ops="confirm-execution"]').click();await page.waitForFunction(()=>state.page==='queue');
 const third=await app.evaluate(()=>dialogStarts[2]);assert.equal(third.route,'/run/enqueue');assert.deepEqual(third.body.ids,[2]);
 assert.deepEqual(errors,[]);await app.close();app=null;
 console.log(JSON.stringify({ok:true,auto_preview_enables_both_entries:true,selected30_limit_matches:true,eligible_subset_only:true,empty_and_invalid_reasons_visible:true,stale_responses_ignored:true,queue_confirmation_works:true,real_model_calls:0,production_changes:0}));
})().catch(async e=>{console.error(e);if(app){try{const p=await app.firstWindow();console.error((await p.locator('body').innerText()).slice(-1800));await p.screenshot({path:path.join(root,'build/execution-dialog-failure.png')});}catch{}await app.close().catch(()=>{});}process.exitCode=1;});
