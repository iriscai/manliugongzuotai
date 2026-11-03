const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');let app;
const root=path.resolve(__dirname,'..'),fixture=JSON.parse(fs.readFileSync(path.join(root,'build/usability-ui-fixture.json'),'utf8'));
(async()=>{
 const env={...process.env,COMIC_DATA_DIR:fixture.data,COMIC_PUSH_TARGET_PROJECT:fixture.target};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(20000);
 await app.evaluate(({BrowserWindow})=>{
  BrowserWindow.getAllWindows()[0].hide();const original=globalThis.fetch;globalThis.operatorPosts=[];
  globalThis.fetch=async(url,options)=>{
   const route=new URL(url).pathname;
   if(['/body/scoped-start','/run/start','/run/retry-seeds','/run/enqueue'].includes(route)){
    const body=JSON.parse(options.body);operatorPosts.push({route,body});return new Response(JSON.stringify({run_id:'operator-mock',job_id:'body_mock',total:route==='/run/retry-seeds'?body.ids.length:body.ids?.length||1}),{status:200,headers:{'Content-Type':'application/json'}});
   }
   return original(url,options);
  };
 });
 await page.locator('#operator-progress').waitFor({timeout:90000});assert.equal(await page.locator('.operator-step').count(),5);
 await page.locator('.operator-step[data-node="todo_body"]').click();
 await page.waitForFunction(()=>state.page==='materials'&&catalogState.applied.workflow_node==='todo_body'&&document.querySelectorAll('tr[data-material]').length===3);
 await page.locator('#category-filter').selectOption('教育');await page.waitForFunction(()=>materialPageRows.length===1&&document.querySelectorAll('tr[data-material]').length===1);
 await page.locator('[data-operator="body-filtered"]').click();await page.locator('[data-operator="body-confirm"]:enabled').waitFor();
 assert.deepEqual(await page.evaluate(()=>scopedBodyPreview.rows.map(x=>x.id)),[5]);
 await page.locator('[data-operator="body-confirm"]').click();await page.waitForFunction(()=>state.page==='bodies');
 const first=await app.evaluate(()=>operatorPosts[0]);assert.equal(first.route,'/body/scoped-start');
 await page.evaluate(async()=>navigate('materials'));await page.locator('[data-catalog-action="reset"]').click();
 await page.waitForFunction(()=>materialPageRows.length>=10&&document.querySelectorAll('tr[data-material]').length>=10);
 await page.locator('tr[data-material="3"] [data-operator="next-write"]').click();
 await page.waitForFunction(()=>executionPreview?.ids.length===1);assert.equal(await page.locator('#run-mode').inputValue(),'write');
 assert.equal(await page.locator('#execution-advanced').getAttribute('open'),null);
 await page.locator('#execution-advanced summary').click();assert(await page.locator('#run-delivery').isVisible());
 await page.locator('[data-action="close-modal"]').first().click();
 await page.locator('tr[data-material="7"] [data-operator="next-write"]').click();await page.locator('[data-operator="next-retry-write"]').waitFor();
 await page.locator('[data-operator="next-retry-write"]').click();await page.waitForFunction(()=>state.page==='queue');
 assert.equal((await app.evaluate(()=>operatorPosts)).filter(x=>x.route==='/run/retry-seeds').length,1);
 // Normal import is exercised against the isolated database with an already complete body.
 await page.evaluate(async file=>{state.importPreview=await api('/import/preview',{path:file});showImport();},fixture.import_file);
 await page.locator('[data-action="confirm-import"]').click();await page.locator('[data-operator="import-view"]').waitFor();
 const imported=await page.evaluate(()=>importReceipt.id);assert(imported>1);
 await page.locator('[data-operator="import-view"]').click();await page.waitForFunction(id=>catalogState.applied.import_id===String(id)&&document.querySelectorAll('tr[data-material]').length===1,imported);
 await page.locator('[data-operator="clear-import"]').click();await page.waitForFunction(()=>!catalogState.applied.import_id);
 await page.evaluate(async()=>navigate('results'));
 await page.locator('#operator-receipts .operator-receipt-totals').waitFor();
 const ids=fixture.results.map(x=>x.id),inside=fixture.results[0].id;
 await page.evaluate(async({ids,inside})=>{pushSelection.clear();ids.forEach(x=>pushSelection.add(x));state.q=String(inside)===String(ids[0])?'图书角第1版':'';resultView.material_id=1;await render();},{ids,inside});
 await page.waitForFunction(()=>document.querySelector('#operator-selection-scope').textContent.includes('筛选外 2'));
 await page.locator('[data-push-action="send"]').click();await page.locator('[data-operator="push-confirm"]').waitFor();
 assert((await page.locator('.modal .operator-selection-scope').innerText()).includes('筛选外'));
 await page.locator('[data-action="close-modal"]').first().click();
 await page.evaluate(async()=>{state.q='';delete resultView.material_id;pushSelection.clear();await render();});
 await page.locator('[data-operator="push-filtered"]').click();await page.locator('[data-operator="push-confirm"]:enabled').waitFor();
 assert.equal(await page.evaluate(()=>scopedPushPreview.total),4);
 // Isolated SQLite receiver only. No production target or model is contacted.
 await page.locator('[data-operator="push-confirm"]').click();await page.waitForFunction(()=>!operatorPushRunning);
 await page.waitForFunction(()=>document.querySelector('#operator-push-progress')?.textContent.includes('已送达'));
 await page.locator('[data-action="close-modal"]').first().click();await page.evaluate(async()=>render());
 await page.locator('[data-push-action="cleanup"]:enabled').waitFor();
 await page.locator('[data-push-action="cleanup"]').click();assert((await page.locator('.modal h2').innerText()).includes('归档'));
 await page.locator('[data-action="close-modal"]').first().click();
 await page.locator('.operator-more summary').click();await page.locator('[data-history-cleanup="open"]').click();
 await page.locator('#history-cleanup-form').waitFor();assert((await page.locator('.modal h2').innerText()).includes('记录与日志'));
 await page.locator('[data-action="close-modal"]').first().click();
 await page.evaluate(async()=>navigate('materials'));await page.locator('[data-operator="density"]').click();assert.equal(await page.evaluate(()=>document.body.classList.contains('operator-compact')),false);
 await page.locator('[data-operator="density"]').click();await page.locator('[data-operator="chart"]').click();assert(await page.locator('.lane-distribution').evaluate(x=>x.classList.contains('operator-chart-collapsed')));
 await page.evaluate(()=>document.querySelector('#toast-root').replaceChildren());
 await page.screenshot({path:path.join(root,'build/usability-materials.png'),fullPage:true});
 await page.evaluate(async()=>navigate('results'));await page.evaluate(()=>document.querySelector('#toast-root').replaceChildren());await page.screenshot({path:path.join(root,'build/usability-results.png'),fullPage:true});
 assert.deepEqual(errors,[]);await app.close();app=null;
 const report={ok:true,progress_navigation:true,body_filter_scope:true,next_actions:true,advanced_options_preserved:true,import_receipt_scope:true,cross_filter_selection_visible:true,filtered_push_and_receipts:true,archive_and_history_distinct:true,compact_and_chart_toggle:true,external_model_calls:0,production_changes:0};
 fs.writeFileSync(path.join(root,'build/usability-ui-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(async e=>{console.error(e);if(app){try{const page=await app.firstWindow();console.error((await page.locator('body').innerText()).slice(-1600));await page.screenshot({path:path.join(root,'build/usability-ui-failure.png'),fullPage:true});}catch{}await app.close().catch(()=>{});}process.exitCode=1;});
