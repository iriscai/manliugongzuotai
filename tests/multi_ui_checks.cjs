const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert'),fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..'),installed=process.argv.includes('--installed');let app;
const fixture=JSON.parse(fs.readFileSync(path.join(root,'build/multi-ui-data.json'),'utf8'));
(async()=>{
 const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;if(installed)delete env.COMIC_DATA_DIR;else env.COMIC_DATA_DIR=fixture.data;
 app=await _electron.launch({executablePath:installed?'C:/Users/74319/Desktop/漫画文章工作台_V0.3.0/漫画文章工作台.exe':'E:/日程提醒/node_modules/electron/dist/electron.exe',args:installed?[]:[root],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.locator('.stat-value').first().waitFor({timeout:90000});
 const health=await page.evaluate(()=>window.desktop.api('/health'));assert.equal(health.version,'0.7.1');assert.equal(health.extraction_scheme,'three_topics_v1');
 await page.locator('[data-nav="queue"]').first().click();await page.locator('.pipeline-overview').waitFor();
 assert((await page.locator('.pipeline-overview').innerText()).includes('正文只发送一次'));
 await page.locator('[data-pipeline-action="both"]').click();await page.locator('#run-mode').waitFor();assert((await page.locator('#run-mode option[value="both"]').innerText()).includes('一次提炼3组选题'));
 await page.locator('[data-action="close-modal"]').first().click();
 if(!installed){
   assert((await page.locator('.pipeline-run').first().innerText()).includes('已保存合并提炼 1 次'));
   await page.locator('[data-nav="writing"]').first().click();await page.locator('.writing-table').waitFor();
   assert((await page.locator('.writing-table tbody tr').first().innerText()).includes('1项元素'));
   await page.locator('[data-pipeline-action="material"][data-tab="extract"]').first().click();await page.locator('.extracted-element').first().waitFor();
   assert((await page.locator('.drawer').innerText()).includes('单次多赛道提炼'));
   assert.equal(await page.locator('.extracted-element').count(),2);
   assert((await page.locator('.extracted-element').first().innerText()).includes('正文原句 · E1'));
   const item=await page.evaluate(id=>window.desktop.api('/materials/'+id),fixture.material_id);assert.equal(item.title,'单次多赛道提炼功能测试');assert.equal(item.extraction_batches.length,1);assert.equal(item.extractions.length,2);
 }
 await page.screenshot({path:path.join(root,installed?'build/multi-installed.png':'build/multi-elements.png'),fullPage:true});
 assert.deepEqual(errors,[]);await app.close();app=null;
 const report={ok:true,installed_exe:installed,one_request_multiple_categories_label:true,element_contents_and_evidence:!installed,model_calls:0};
 fs.writeFileSync(path.join(root,installed?'build/multi-installed-checks.json':'build/multi-ui-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1});
