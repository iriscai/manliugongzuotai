const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert'),fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..'),installed=process.argv.includes('--installed');
const data=fs.mkdtempSync(path.join(root,'build/body-workers-ui-'));let app;
async function launch(){const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;if(installed)delete env.COMIC_DATA_DIR;else env.COMIC_DATA_DIR=data;app=await _electron.launch({executablePath:installed?'C:/Users/74319/Desktop/漫画文章工作台_V0.3.0/漫画文章工作台.exe':'E:/日程提醒/node_modules/electron/dist/electron.exe',args:installed?[]:[root],env,timeout:90000});const page=await app.firstWindow();await page.locator('.stat-value').first().waitFor({timeout:90000});return page;}
async function openSettings(page){await page.locator('#body-btn').click();await page.locator('[data-body-action="settings"]').click();await page.locator('#body-setting-body_workers').waitFor();}
(async()=>{
 let page=await launch();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 assert.equal((await page.evaluate(()=>window.desktop.api('/health'))).version,'0.5.1');
 const original=(await page.evaluate(()=>window.desktop.api('/settings'))).body_workers;
 await openSettings(page);
 assert.deepEqual(await page.locator('#body-setting-body_workers option').evaluateAll(options=>options.map(x=>Number(x.value))),[1,2,4,8]);
 assert.equal(await page.locator('#body-setting-body_workers').inputValue(),String(original));
 if(!installed){
   for(const workers of [1,2,4,8]){
     await page.locator('#body-setting-body_workers').selectOption(String(workers));
     await page.locator('[data-body-action="save-settings"]').click();await page.locator('#body-setting-body_workers').waitFor({state:'detached'});
     assert.equal((await page.evaluate(()=>window.desktop.api('/settings'))).body_workers,workers);
     assert.equal((await page.evaluate(()=>window.desktop.api('/body/stats'))).engine.workers,workers);
     assert((await page.locator('.body-engine').innerText()).includes('浏览器并发 '+workers+' 个'));
     await openSettings(page);
   }
   for(const value of [0,3,5,7,9,16,true,1.5,'4.0']){
     const rejected=await page.evaluate(async v=>{try{await window.desktop.api('/settings',{method:'POST',body:{body_workers:v}});return false}catch(e){return e.message.includes('1、2、4、8')}},value);
     assert.equal(rejected,true);
   }
   await app.close();app=null;page=await launch();page.on('pageerror',e=>errors.push(e.message));await openSettings(page);
   assert.equal(await page.locator('#body-setting-body_workers').inputValue(),'8');
 }
 await page.screenshot({path:path.join(root,installed?'build/body-workers-installed.png':'build/body-workers-settings.png'),fullPage:true});
 assert.deepEqual(errors,[]);await app.close();app=null;
 const report={ok:true,installed_exe:installed,options:[1,2,4,8],selected:installed?original:8,api_validation_and_persistence:!installed,real_browser_fetches:0,model_calls:0};
 fs.writeFileSync(path.join(root,installed?'build/body-workers-installed-checks.json':'build/body-workers-ui-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1});
