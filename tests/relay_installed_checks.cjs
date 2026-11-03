const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert'),fs=require('fs'),path=require('path');const root=path.resolve(__dirname,'..');let app;
(async()=>{
 const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;delete env.COMIC_DATA_DIR;
 app=await _electron.launch({executablePath:'C:/Users/74319/Desktop/漫画文章工作台_V0.3.0/漫画文章工作台.exe',args:[],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.locator('.stat-value').first().waitFor({timeout:90000});
 assert.equal((await page.evaluate(()=>window.desktop.api('/health'))).version,'0.5.0');
 const s=await page.evaluate(()=>window.desktop.api('/settings'));assert.equal(s.provider,'api');assert.equal(s.api_protocol,'chat');assert.equal(s.api_key_count,7);assert.equal(s.api_model,'gpt-6.1-sol');assert.equal(s.api_temperature,.7);assert(!('api_key_encrypted' in s));
 assert.equal((await page.evaluate(()=>window.desktop.api('/stats'))).counts.total,3217);
 await page.locator('[data-nav="settings"]').click();await page.locator('#api_key').waitFor();
 assert.equal(await page.locator('#api_key').inputValue(),'');assert((await page.locator('#api_key').getAttribute('placeholder')).includes('7个Key'));
 assert.equal(await page.locator('[data-relay-action="test"]').isVisible(),true);assert.equal(await page.locator('[data-relay-action="models"]').isVisible(),true);
 assert.equal(await page.locator('#api_skip_tls_verify').isChecked(),false);
 await page.screenshot({path:path.join(root,'build/relay-installed.png'),fullPage:true});
 await page.locator('[data-provider="codex"]').click();await page.locator('#codex_path').waitFor();await page.locator('[data-provider="api"]').click();await page.locator('#api_key').waitFor();
 assert.deepEqual(errors,[]);await app.close();app=null;
 const report={ok:true,installed_exe:true,provider:s.provider,api_base:s.api_base,model:s.api_model,encrypted_keys:s.api_key_count,api_protocol:s.api_protocol,tls_verified:!s.api_skip_tls_verify,materials:3217,real_inference_calls_in_this_check:0};fs.writeFileSync(path.join(root,'build/relay-installed-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1});
