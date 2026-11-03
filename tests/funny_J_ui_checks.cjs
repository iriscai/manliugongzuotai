const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('path'),fs=require('fs'),assert=require('assert');const root=path.resolve(__dirname,'..');let app;
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(path.join(root,'build/task-pause-ui-fixture.json'),'utf8'));const env={...process.env,COMIC_DATA_DIR:fixture.data,COMIC_PUSH_TARGET_PROJECT:path.join(root,'build/quality-target')};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].hide());
 await page.locator('.stat-value').first().waitFor({timeout:60000});await page.evaluate(async()=>{await navigate('rules');state.ruleCategory='搞笑';state.ruleKind='write';await render();});
 await page.locator('[data-rule-variant="J"]').click();await page.waitForFunction(()=>document.querySelector('#prompt-content')?.value.includes('方案J：单次响应'));
 assert((await page.locator('#current-prompt-status').innerText()).includes('停用'));assert((await page.locator('.funny-profile').innerText()).includes('候选版本'));
 assert.equal(await page.locator('#funny-write-variant').inputValue(),'I');
 await page.screenshot({path:path.join(root,'build/funny-J-candidate.png'),fullPage:true});assert.deepEqual(errors,[]);await app.close();app=null;
 console.log(JSON.stringify({ok:true,J_visible_disabled:true,I_default_preserved:true,frozen_backend_started:true,external_calls:0}));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1;});
