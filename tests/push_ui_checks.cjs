const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');let app;
const root=path.resolve(__dirname,'..'),fixture=JSON.parse(fs.readFileSync(path.join(root,'build/push-ui-fixture.json'),'utf8'));
const installed=process.argv.includes('--installed');
(async()=>{
 const env={...process.env,COMIC_DATA_DIR:fixture.data,COMIC_PUSH_TARGET_PROJECT:fixture.target_project};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:installed?'C:/Users/74319/Desktop/漫画文章工作台_V0.3.0/漫画文章工作台.exe':'E:/日程提醒/node_modules/electron/dist/electron.exe',args:installed?[]:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 const page=await app.firstWindow();await page.locator('.stat-value').first().waitFor({timeout:90000});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.locator('[data-nav="results"]').first().click();await page.locator('.article-results').waitFor();
 assert.equal(await page.locator('[data-push-select]:not([data-push-select="page"])').count(),30);
 await page.locator('[data-push-select="31"]').check();assert.equal(await page.locator('.drawer').count(),0);
 await page.waitForTimeout(4300);assert.equal(await page.locator('[data-push-select="31"]').isChecked(),true);
 await page.locator('[data-paginate="results"][data-page="2"]').click();await page.locator('[data-push-select="1"]').check();
 assert((await page.locator('.push-buttons').innerText()).includes('2'));
 await page.locator('[data-push-action="send"]').click();
 await page.locator('.push-status .pill.green').waitFor({timeout:20000});
 const received=await page.evaluate(()=>window.desktop.api('/results?page=2'));assert.equal(received.rows[0].push_state,'pushed');
 await page.waitForFunction(()=>!document.querySelector('[data-push-action="send"]').disabled);
 assert.equal(await page.locator('[data-push-select="1"]').isDisabled(),false);
 assert.equal(await page.locator('[data-push-select="1"]').isChecked(),true);
 // A second user click is allowed and remains idempotent.
 await page.locator('[data-push-action="send"]').click();
 await page.waitForFunction(()=>!document.querySelector('[data-push-action="send"]').disabled);
 await page.locator('[data-push-action="clear"]').click();
 assert.equal(await page.locator('[data-push-action="send"]').isDisabled(),true);
 await page.locator('[data-push-select="1"]').check();
 // A render failure before the request must never leave the busy flag latched.
 await page.evaluate(()=>{globalThis.pushTestRender=render;render=async function(...args){if(pushBusy)throw new Error('模拟推送界面渲染失败');return pushTestRender(...args);};});
 await page.locator('[data-push-action="send"]').click();
 await page.waitForFunction(()=>!pushBusy&&!document.querySelector('[data-push-action="send"]').disabled);
 await page.locator('.toast').filter({hasText:'模拟推送界面渲染失败'}).first().waitFor();
 await page.evaluate(()=>{render=pushTestRender;});
 // A failure refreshing the page after success must also restore the button.
 await page.evaluate(()=>{globalThis.pushTestRefresh=refresh;refresh=async function(){throw new Error('模拟刷新失败');};});
 await page.locator('[data-push-action="send"]').click();
 await page.waitForFunction(()=>!pushBusy&&!document.querySelector('[data-push-action="send"]').disabled);
 await page.locator('.toast').filter({hasText:'推送按钮已恢复'}).first().waitFor();
 await page.evaluate(()=>{refresh=pushTestRefresh;});
 const again=await page.evaluate(()=>window.desktop.api('/results/push',{method:'POST',body:{ids:[1,31]}}));assert.equal(again.pushed,2);
 await page.locator('[data-paginate="results"][data-page="1"]').click();await page.locator('.article-results').waitFor();
 assert.equal(await page.locator('[data-push-select="31"]').isDisabled(),false);
 assert.equal(await page.locator('.push-status .pill.green').count(),1);assert.deepEqual(errors,[]);
 await page.locator('[data-push-action="clear"]').click();await page.locator('[data-push-select="30"]').check();
 await page.locator('[data-push-action="send"]').click();await page.waitForFunction(()=>!pushBusy&&!document.querySelector('[data-push-action="send"]').disabled);
 const extra=await page.evaluate(()=>window.desktop.api('/results'));assert.equal(extra.rows.find(r=>r.id===30).push_state,'pushed');
 // Cleanup covers all delivered articles, even when a search hides some of them.
 assert.equal(extra.clearable_count,3);
 await page.locator('#list-search').fill('生成标题1');
 await page.waitForFunction(()=>state.q==='生成标题1');
 await page.locator('[data-push-action="cleanup"]').click();
 await page.waitForFunction(()=>!pushBusy&&pushClearable===0);
 const cleaned=await page.evaluate(()=>window.desktop.api('/results'));assert.equal(cleaned.total,28);
 assert(!cleaned.rows.some(r=>[1,30,31].includes(r.id)));
 assert.equal(await page.locator('[data-push-action="cleanup"]').isDisabled(),true);
 const stats=await page.evaluate(()=>window.desktop.api('/stats'));assert.equal(stats.writing.ready,0);
 await page.screenshot({path:path.join(root,'build/push-ui.png'),fullPage:true});await app.close();app=null;
 console.log(JSON.stringify({ok:true,polling_preserves_selection:true,cross_page_selection:true,push_status_persistent:true,repeat_button_click:true,success_preserves_selection:true,render_failure_unlocks:true,refresh_failure_unlocks:true,another_article_can_be_pushed:true,duplicate_request_safe:true,model_calls:0,real_target_writes:0}));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1});
