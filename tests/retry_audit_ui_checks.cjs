const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('path'),assert=require('assert'),fs=require('fs');const root=path.resolve(__dirname,'..');let app;
(async()=>{
 const env={...process.env,COMIC_DATA_DIR:path.join(root,'build/singlecall-ui-data')};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].hide());
 page.on('pageerror',e=>errors.push(e.message));await page.locator('.stat-value').first().waitFor({timeout:90000});
 await page.locator('[data-nav="results"]').first().click();await page.locator('.article-title').first().click();await page.locator('.singlecall-artifacts').waitFor();
 await page.evaluate(()=>{
  const data=JSON.parse(articleDetail.data_json);
  data.validation_audit={changes:[{field:'t1_short_reasons',action:'缺失说明保留为空'}],warnings:[{message:'模型未提供短标题说明'}],publication_text_changed:false};
  data.recovered_response={run_id:'aaaaaaaaaaaa',additional_model_calls:0};articleDetail.data_json=JSON.stringify(data);drawArticle();
 });
 assert((await page.locator('.article-drawer').innerText()).includes('本篇未新增生文请求'));
 await page.locator('.singlecall-artifacts').first().locator('summary').click();
 assert((await page.locator('.article-drawer').innerText()).includes('缺失说明保留为空'));
 assert((await page.locator('.article-drawer').innerText()).includes('模型未提供短标题说明'));
 assert.deepEqual(errors,[]);await app.close();app=null;
 const report={ok:true,format_warning_visible:true,saved_response_origin_visible:true,renderer_errors:0,external_model_calls:0,production_changes:0};
 fs.writeFileSync(path.join(root,'build/retry-audit-ui-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1;});
