const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert'),fs=require('fs'),path=require('path');let app;
(async()=>{
 const root=path.resolve(__dirname,'..'),env={...process.env,COMIC_DATA_DIR:path.join(root,'build/military-versions-ui-data'),COMIC_SOURCE_ONLY:'1'};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[root],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].hide());
 await page.locator('.stat-value').first().waitFor({timeout:90000});await page.locator('[data-nav="rules"]').click();await page.locator('[data-rule-category="军事"]').click();
 await page.locator('[data-military="save"]').waitFor();assert.equal(await page.locator('[data-rule-variant]').count(),7);
 for(const v of ['D','E','F','G']){await page.locator('#military-extract-variant').selectOption(v);await page.locator('#military-write-variant').selectOption(v);await page.locator('[data-military="save"]').click();await page.waitForFunction(v=>state.settings.military_write_variant===v,v);}
 await page.locator('[data-nav="results"]').click();await page.locator('.article-title').first().click();await page.locator('.military-html-preview').waitFor();
 assert((await page.locator('.article-drawer').innerText()).includes('700–800'));assert(!(await page.locator('.military-html-preview').innerText()).includes('资料来源')); 
 await page.locator('[data-management="article-tab"][data-tab="edit"]').click();assert((await page.locator('#article-editor-meter').innerText()).includes('700–800'));assert(!(await page.locator('#article-editor-meter').getAttribute('class')).includes('invalid'));
 await page.locator('.article-drawer [data-management="close-article"]').click();const frow=page.locator('tr').filter({hasText:'规则R1 · F'}).first();await frow.locator('.article-title').click();await page.locator('.military-html-preview h3').waitFor();
 assert((await page.locator('.article-drawer').innerText()).includes('1200–1500'));
 await page.locator('.article-drawer [data-management="close-article"]').click();await page.locator('[data-nav="rules"]').click();await page.locator('[data-rule-category="生活"]').click();await page.locator('[data-military="save"]').waitFor({state:'detached'});assert.equal(await page.locator('[data-military="save"]').count(),0);
 assert.deepEqual(errors,[]);const report={ok:true,seven_military_versions:true,new_versions_can_be_selected_and_saved:true,G_body_count_private_sources:true,F_long_text_and_headings:true,other_lane_controls_unchanged:true,external_model_calls:0};fs.writeFileSync(path.join(root,'build/military-versions-ui-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));await app.close();app=null;
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1;});
