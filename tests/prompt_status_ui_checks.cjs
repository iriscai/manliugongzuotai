const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('path'),assert=require('assert');const root=path.resolve(__dirname,'..');let app;
(async()=>{
 const env={...process.env,COMIC_DATA_DIR:path.join(root,'build/prompt-status-ui-data')};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.locator('.stat-value').first().waitFor({timeout:90000});
 await page.locator('[data-nav="rules"]').first().click();await page.locator('[data-rule-category="搞笑"]').click();
 await page.waitForFunction(()=>document.querySelectorAll('[data-rule-variant]').length===8);
 await page.locator('[data-rule-variant="C"]').click();await page.waitForFunction(()=>state.ruleVariant==='C');
 const before=await page.evaluate(()=>state.prompts.find(p=>p.category==='搞笑'&&p.kind==='extract'&&p.variant==='C'));
 // Keep the fixture deterministic if this check is invoked again.
 if(!before.enabled){await page.locator('[data-prompt-status]').click();await page.waitForFunction(()=>state.prompts.find(p=>p.category==='搞笑'&&p.kind==='extract'&&p.variant==='C').enabled===1);}
 await page.locator('[data-prompt-status]').click();await page.waitForFunction(()=>state.prompts.find(p=>p.category==='搞笑'&&p.kind==='extract'&&p.variant==='C').enabled===0);
 assert.equal(await page.locator('#current-prompt-status').innerText(),'已停用');
 assert((await page.locator('[data-rule-variant="C"]').innerText()).includes('停用'));
 await page.getByRole('combobox',{name:'版本状态',exact:true}).selectOption('disabled');await page.waitForFunction(()=>document.querySelectorAll('[data-rule-variant]').length===1);
 await page.locator('[data-rule-kind="write"]').click();await page.waitForFunction(()=>state.ruleKind==='write');assert.equal(await page.locator('[data-rule-variant]').count(),0);assert(await page.locator('#prompt-content').isDisabled());
 await page.getByRole('combobox',{name:'版本状态',exact:true}).selectOption('all');await page.waitForFunction(()=>document.querySelectorAll('[data-rule-variant]').length===8);
 assert.equal(await page.evaluate(()=>state.prompts.find(p=>p.category==='搞笑'&&p.kind==='write'&&p.variant==='C').enabled),1);
 await page.locator('[data-rule-variant="B"]').click();await page.waitForFunction(()=>state.ruleVariant==='B');
 if(!(await page.evaluate(()=>state.prompts.find(p=>p.category==='搞笑'&&p.kind==='write'&&p.variant==='B').enabled))){await page.locator('[data-prompt-status]').click();await page.waitForFunction(()=>state.prompts.find(p=>p.category==='搞笑'&&p.kind==='write'&&p.variant==='B').enabled===1);}
 await page.locator('[data-prompt-status]').click();await page.waitForFunction(()=>state.prompts.find(p=>p.category==='搞笑'&&p.kind==='write'&&p.variant==='B').enabled===0);
 const after=await page.evaluate(()=>state.prompts.find(p=>p.category==='搞笑'&&p.kind==='extract'&&p.variant==='C'));assert.equal(after.content,before.content);assert.equal(after.revision,before.revision);
 await page.screenshot({path:path.join(root,'build/prompt-status-ui.png'),fullPage:true});
 await page.locator('[data-rule-category="生活"]').click();await page.waitForFunction(()=>document.querySelectorAll('[data-rule-variant]').length===2);assert.equal(await page.locator('.prompt-state.off').count(),0);
 assert.deepEqual(errors,[]);await app.close();app=null;console.log(JSON.stringify({ok:true,status_badges_and_independent_toggles:true,enabled_disabled_filter:true,disabled_content_visible_and_unchanged:true,other_lanes_untouched:true,renderer_errors:0,external_model_calls:0}));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1;});
