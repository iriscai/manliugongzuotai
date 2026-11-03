const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert'),fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..'),installed=process.argv.includes('--installed');
const data=fs.mkdtempSync(path.join(root,'build/body-length-ui-'));let app;
async function launch(){const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;if(installed)delete env.COMIC_DATA_DIR;else env.COMIC_DATA_DIR=data;app=await _electron.launch({executablePath:installed?'C:/Users/74319/Desktop/漫画文章工作台_V0.3.0/漫画文章工作台.exe':'E:/日程提醒/node_modules/electron/dist/electron.exe',args:installed?[]:[root],env,timeout:90000});const page=await app.firstWindow();await page.locator('.stat-value').first().waitFor({timeout:90000});return page;}
async function settings(page){await page.locator('#body-btn').click();await page.locator('[data-body-action="settings"]').click();await page.locator('#body-setting-body_max_chars').waitFor();}
async function save(page,value){await page.locator('#body-setting-body_max_chars').fill(String(value));await page.locator('[data-body-action="save-settings"]').click();await page.locator('#body-setting-body_max_chars').waitFor({state:'detached'});}
(async()=>{
 let page=await launch(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 assert.equal((await page.evaluate(()=>window.desktop.api('/health'))).version,'0.3.2');
 await settings(page);assert.equal(await page.locator('#body-setting-body_max_chars').inputValue(),'800');
 assert.equal(await page.locator('#body-setting-body_max_chars').getAttribute('min'),'0');
 assert.equal(await page.locator('#body-setting-body_max_chars').getAttribute('max'),'32766');
 await page.screenshot({path:path.join(root,installed?'build/body-length-installed.png':'build/body-length-setting.png'),fullPage:true});
 if(!installed){
   await save(page,1200);assert.equal((await page.evaluate(()=>window.desktop.api('/settings'))).body_max_chars,1200);
   await settings(page);assert.equal(await page.locator('#body-setting-body_max_chars').inputValue(),'1200');await save(page,0);
   assert.equal((await page.evaluate(()=>window.desktop.api('/body/stats'))).engine.max_chars,0);
   assert((await page.locator('.body-engine').innerText()).includes('正文上限 不限'));
   await app.close();app=null;page=await launch();page.on('pageerror',e=>errors.push(e.message));
   await settings(page);assert.equal(await page.locator('#body-setting-body_max_chars').inputValue(),'0');await save(page,800);
 }
 assert.deepEqual(errors,[]);await app.close();app=null;
 const report={ok:true,installed_exe:installed,default:800,range:[0,32766],saved_1200_and_0:!installed,restart_preserved_zero:!installed,model_calls:0,production_fetches:0};
 fs.writeFileSync(path.join(root,installed?'build/body-length-installed-checks.json':'build/body-length-ui-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1});
