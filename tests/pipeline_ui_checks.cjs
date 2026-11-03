const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert'),fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..'),installed=process.argv.includes('--installed');let app;
const data=JSON.parse(fs.readFileSync(path.join(root,'build/pipeline-ui-data.json'),'utf8')).data;
async function launch(){const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;if(installed)delete env.COMIC_DATA_DIR;else env.COMIC_DATA_DIR=data;app=await _electron.launch({executablePath:installed?'C:/Users/74319/Desktop/漫画文章工作台_V0.3.0/漫画文章工作台.exe':'E:/日程提醒/node_modules/electron/dist/electron.exe',args:installed?[]:[root],env,timeout:90000});const page=await app.firstWindow();await page.locator('.stat-value').first().waitFor({timeout:90000});return page;}
(async()=>{
 let page=await launch();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 assert.equal((await page.evaluate(()=>window.desktop.api('/health'))).version,'0.6.0');
 const stats=await page.evaluate(()=>window.desktop.api('/stats'));assert.equal(stats.writing.ready,0);assert.equal(stats.writing.needs_review,33);assert.equal(stats.writing.written,0);
 await page.locator('[data-nav="queue"]').first().click();await page.locator('.pipeline-run').first().waitFor();
 assert((await page.locator('.pipeline-run').first().innerText()).includes('文案 0 份'));
 assert.equal(await page.locator('[data-pipeline-action="write"]').isDisabled(),true);
 await page.screenshot({path:path.join(root,installed?'build/pipeline-installed-queue.png':'build/pipeline-queue.png'),fullPage:true});
 await page.locator('[data-pipeline-action="both"]').click();assert.equal(await page.locator('#run-mode').inputValue(),'both');await page.locator('[data-action="close-modal"]').first().click();
 await page.locator('[data-pipeline-action="extract"]').click();assert.equal(await page.locator('#run-mode').inputValue(),'extract');await page.locator('[data-action="close-modal"]').first().click();
 await page.locator('[data-pipeline-action="blocked"]').click();await page.locator('.writing-table').waitFor();
 assert.equal(await page.locator('#page-title').innerText(),'写文任务');
 await page.locator('.writing-table summary').first().click();assert((await page.locator('.writing-table details').first().innerText()).includes('核实'));
 await page.screenshot({path:path.join(root,installed?'build/pipeline-installed-writing.png':'build/pipeline-writing.png'),fullPage:true});
 await page.locator('[data-nav="queue"]').first().click();await page.locator('[data-pipeline-action="detail"][data-blocked="1"]').first().click();
 await page.locator('.verification-item').first().waitFor();assert((await page.locator('.modal').innerText()).includes('33 份'));await page.locator('[data-action="close-modal"]').first().click();
 await page.locator('[data-nav="settings"]').first().click();await page.locator('#process_workers').waitFor();
 for(const key of ['process_workers','write_workers'])assert.deepEqual(await page.locator('#'+key+' option').evaluateAll(xs=>xs.map(x=>Number(x.value))),[1,2,4,8,16,32]);
 if(!installed){
   await page.locator('#process_workers').selectOption('32');await page.locator('#write_workers').selectOption('16');await page.locator('[data-action="save-settings"]').click();
   await page.waitForFunction(()=>document.querySelector('#process_workers')?.value==='32');
   let s=await page.evaluate(()=>window.desktop.api('/settings'));assert.equal(s.process_workers,32);assert.equal(s.write_workers,16);
   for(const value of [0,3,33,true,1.5])assert.equal(await page.evaluate(async value=>{try{await window.desktop.api('/settings',{method:'POST',body:{write_workers:value}});return false}catch{return true}},value),true);
   await app.close();app=null;page=await launch();page.on('pageerror',e=>errors.push(e.message));await page.locator('[data-nav="settings"]').first().click();await page.locator('#process_workers').waitFor();assert.equal(await page.locator('#process_workers').inputValue(),'32');assert.equal(await page.locator('#write_workers').inputValue(),'16');
 }else{assert.equal(await page.locator('#process_workers').inputValue(),'8');assert.equal(await page.locator('#write_workers').inputValue(),'8')}
 assert.deepEqual(errors,[]);await app.close();app=null;
 const report={ok:true,installed_exe:installed,verification_rows:33,actual_results:0,writing_entry:true,independent_concurrency_options:[1,2,4,8,16,32],settings_persisted:!installed,model_calls:0};
 fs.writeFileSync(path.join(root,installed?'build/pipeline-installed-checks.json':'build/pipeline-ui-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1});
