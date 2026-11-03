const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');let app;
const root=path.resolve(__dirname,'..'),fixture=JSON.parse(fs.readFileSync(path.join(root,'build/writing-bulk-fixture.json'),'utf8'));
(async()=>{
 const env={...process.env,COMIC_DATA_DIR:fixture.data};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[fixture.app],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(15000);
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].hide());
 await page.locator('.stat-value').first().waitFor({timeout:60000});
 await page.evaluate(async()=>navigate('writing'));
 await page.locator('[data-writing-retry="select-all"]').click();await page.waitForFunction(()=>writingRetrySelection.size===128);
 const selected=await page.evaluate(()=>[...writingRetrySelection]);
 assert.equal(await page.locator('[data-writing-failed-select]:disabled').count(),2,'ready rows must not be selectable');
 await page.locator('[data-pipeline-action="page"][data-page="2"]').click();await page.waitForFunction(()=>writingView.page===2);
 await page.locator('[data-pipeline-action="page"][data-page="3"]').click();await page.waitForFunction(()=>writingView.page===3);
 await page.waitForFunction(()=>document.querySelectorAll('.writing-table tbody tr').length===32);
 assert.equal(await page.locator('[data-writing-failed-select]:disabled').count(),2,'written rows must not be selectable');
 await page.locator('[data-pipeline-action="filter"][data-state="failed"]').click();
 await page.waitForFunction(()=>document.querySelector('.writing-pagination').textContent.includes('第1/3页'));
 await page.locator('[data-pipeline-action="page"][data-page="2"]').click();
 await page.waitForFunction(()=>document.querySelector('.writing-pagination').textContent.includes('第2/3页'));
 assert.equal(await page.locator('tbody [data-writing-failed-select]:checked').count(),50,'selection must survive paging');
 await page.locator('[data-writing-retry="selected"]').click();await page.locator('[data-writing-retry="confirm"]').waitFor();
 assert((await page.locator('.modal h2').innerText()).includes('128'));
 await app.evaluate((_,id)=>globalThis.bulkSkip.push(id),selected[0]);
 await page.locator('[data-writing-retry="confirm"]').click();await page.waitForFunction(()=>state.page==='queue');
 const posted=await app.evaluate(()=>globalThis.bulkPosts[0].ids);assert.equal(posted.length,127);assert(!posted.includes(selected[0]));
 await page.waitForFunction(()=>state.page==='queue');assert.equal(await page.locator('[data-writing-retry="all"]').count(),1);
 await app.evaluate(()=>{globalThis.bulkSkip=[];globalThis.bulkNoFailures=false;});
 await page.locator('[data-writing-retry="all"]').click();await page.locator('[data-writing-retry="confirm"]').waitFor();
 await app.evaluate(()=>globalThis.bulkNoFailures=true);
 await page.locator('[data-writing-retry="confirm"]').click();await page.waitForFunction(()=>!document.querySelector('[data-writing-retry="confirm"]'));
 await page.waitForFunction(()=>!writingRetryBusy);
 assert.equal(await app.evaluate(()=>globalThis.bulkPosts.length),1,'no post when all selected failures have disappeared');
 const limitError=await page.evaluate(async()=>{
  const original=currentWritingFailures;
  try{currentWritingFailures=async()=>Array.from({length:501},(_,i)=>({id:10000+i,material_id:10000+i,category:'生活'}));await prepareWritingRetry(true);return '';}
  catch(e){return e.message;}finally{currentWritingFailures=original;writingRetrySelection.clear();}
 });
 assert(limitError.includes('每轮最多 500'));
 assert.equal(await app.evaluate(()=>globalThis.bulkPosts.length),1,'over-limit selection must not start a task');
 await app.evaluate(()=>globalThis.bulkNoFailures=false);
 await page.evaluate(async()=>{await navigate('writing');writingView.filter='failed';await render();});
 await page.locator('[data-writing-retry="select-all"]').click();await page.waitForFunction(()=>writingRetrySelection.size===128);
 await page.screenshot({path:path.join(root,'build/writing-bulk-retry.png'),fullPage:true});
 assert.deepEqual(errors,[]);await app.close();app=null;
 console.log(JSON.stringify({ok:true,cross_page_selected:128,stale_success_excluded:true,ready_and_written_not_selectable:true,queue_entry:true,no_post_when_no_failures:true,external_model_calls:0,production_changes:0}));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1;});
