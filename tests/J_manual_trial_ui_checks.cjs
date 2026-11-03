const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');const root=path.resolve(__dirname,'..');let app;
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(path.join(root,'build/J-manual-ui-fixture.json'),'utf8'));const env={...process.env,COMIC_DATA_DIR:fixture.data,COMIC_PUSH_TARGET_PROJECT:path.join(root,'build/quality-target')};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].hide());
 await page.locator('.stat-value').first().waitFor({timeout:60000});await page.evaluate(async()=>{await navigate('rules');state.ruleCategory='搞笑';state.ruleKind='write';await render();});
 await page.locator('[data-rule-variant="J"]').click();const toggle=page.locator('[data-prompt-status]');assert((await toggle.innerText()).includes('试用启用J'));
 const before=await page.evaluate(()=>window.desktop.api('/prompts'));
 await toggle.click();await page.waitForFunction(()=>document.querySelector('#current-prompt-status')?.textContent.includes('试用已启用'));
 assert((await page.locator('.funny-profile').innerText()).includes('试用不代表质量验证通过'));
 await page.locator('#funny-write-variant').selectOption('J');await page.locator('[data-funny-action="save-profile"]').click();
 await page.waitForFunction(()=>state.settings.funny_write_variant==='J');
 const settings=await page.evaluate(()=>window.desktop.api('/settings'));assert.equal(settings.funny_J_validation.status,'pending');assert.equal(settings.funny_write_variant,'J');assert.equal(settings.funny_extract_variant,'I');
 const after=await page.evaluate(()=>window.desktop.api('/prompts'));assert.deepEqual(after.filter(p=>p.variant!=='J'),before.filter(p=>p.variant!=='J'));
 await page.screenshot({path:path.join(root,'build/J-manual-trial-enabled.png'),fullPage:true});assert.deepEqual(errors,[]);await app.close();app=null;
 console.log(JSON.stringify({ok:true,manual_button_enables_J:true,execution_profile_can_choose_J:true,pending_score_not_approved:true,old_prompt_rows_unchanged:true,model_calls:0}));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1;});
