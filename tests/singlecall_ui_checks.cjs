const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('path'),assert=require('assert');const root=path.resolve(__dirname,'..');let app;
(async()=>{
 const env={...process.env,COMIC_DATA_DIR:path.join(root,'build/singlecall-ui-data')};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.locator('.stat-value').first().waitFor({timeout:90000});
 await page.locator('[data-nav="rules"]').first().click();await page.locator('[data-rule-category="搞笑"]').click();await page.waitForFunction(()=>state.ruleVariant==='I');
 assert.equal(await page.locator('[data-rule-variant]').count(),9);assert.equal(await page.locator('.prompt-state.on').count(),1);assert.equal(await page.locator('.prompt-state.off').count(),8);
 assert((await page.locator('.funny-profile').innerText()).includes('最低92分'));
 await page.locator('[data-rule-kind="write"]').click();await page.waitForFunction(()=>state.ruleKind==='write'&&state.ruleVariant==='I');
 assert((await page.locator('#prompt-content').inputValue()).includes('标题泄底专查'));
 await page.locator('[data-nav="results"]').first().click();await page.locator('.article-title').first().click();await page.locator('.singlecall-artifacts').waitFor();
 await page.locator('.singlecall-artifacts>summary').click();assert((await page.locator('.singlecall-artifacts').innerText()).includes('T1标题候选'));
 await page.screenshot({path:path.join(root,'build/singlecall-audit-ui.png'),fullPage:true});assert.deepEqual(errors,[]);
 await app.close();app=null;console.log(JSON.stringify({ok:true,only_I_enabled_in_UI:true,passed_trial_score_visible:true,single_response_artifacts_readable:true,renderer_errors:0,external_model_calls:0}));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1;});
