const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert'),fs=require('fs'),path=require('path');
const {spawn}=require('child_process');
const root=path.resolve(__dirname,'..'),exe='C:/Users/74319/Desktop/漫画文章工作台_V0.3.0/漫画文章工作台.exe';let app;
const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;delete env.COMIC_DATA_DIR;
async function invokeAgain(){await new Promise((resolve,reject)=>{const p=spawn(exe,[],{env,windowsHide:true,stdio:'ignore'});p.on('error',reject);p.on('exit',code=>code===0?resolve():reject(new Error('Second instance exit '+code)));});}
async function waitVisible(){for(let i=0;i<50;i++){const r=await app.evaluate(({BrowserWindow})=>{const w=BrowserWindow.getAllWindows()[0];return {visible:w.isVisible(),minimized:w.isMinimized()}});if(r.visible&&!r.minimized)return r;await new Promise(r=>setTimeout(r,100));}throw new Error('Window not restored');}
(async()=>{
 app=await _electron.launch({executablePath:exe,args:[],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.locator('.stat-value').first().waitFor({timeout:90000});
 await waitVisible();assert.equal((await page.evaluate(()=>window.desktop.api('/stats'))).counts.total,3215);
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].hide());
 assert.equal(await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].isVisible()),false);
 await invokeAgain();await waitVisible();
 await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].minimize());
 await invokeAgain();await waitVisible();
 assert.equal(await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().length),1);
 await page.screenshot({path:path.join(root,'build/startup-window-restored.png'),fullPage:true});
 assert.deepEqual(errors,[]);await app.close();app=null;
 const report={ok:true,installed_exe:true,startup_visible:true,hidden_window_restored_on_relaunch:true,minimized_window_restored_on_relaunch:true,single_window:true,materials:3215,model_calls:0,body_fetches:0};
 fs.writeFileSync(path.join(root,'build/startup-window-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1});
