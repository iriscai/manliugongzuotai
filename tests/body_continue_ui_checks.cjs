const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');const root=path.resolve(__dirname,'..');let app;
(async()=>{
 const fixture=JSON.parse(fs.readFileSync(path.join(root,'build/body-continue-ui-fixture.json'),'utf8'));const env={...process.env,COMIC_DATA_DIR:fixture.data,COMIC_PUSH_TARGET_PROJECT:path.join(root,'build/quality-target')};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 await app.evaluate(()=>{const real=globalThis.fetch;globalThis.resumePosts=[];globalThis.fetch=async(url,opts)=>{if(new URL(url).pathname==='/body/resume'){const body=JSON.parse(opts.body);resumePosts.push(body);return new Response(JSON.stringify({ok:true,total:body.limit,job_id:'mock-only'}),{status:200});}return real(url,opts);};});
 const page=await app.firstWindow(),errors=[];page.setDefaultTimeout(15000);page.on('pageerror',e=>errors.push(e.message));await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].hide());
 await page.locator('.stat-value').first().waitFor({timeout:60000});await page.evaluate(()=>navigate('bodies'));
 const top=page.locator('[data-body-action="continue"]');await top.waitFor();assert((await top.innerText()).includes('继续抓取'));
 assert(await page.locator(`[data-body-action="resume"][data-id="${fixture.queued}"]`).isVisible());
 await top.click();await page.locator('#body-resume-job').waitFor();assert.equal(await page.locator('#body-resume-job').inputValue(),fixture.queued);
 await page.locator('#body-resume-job').selectOption(fixture.paused);await page.waitForFunction(id=>document.querySelector('[data-body-action="confirm-start"]')?.dataset.jobId===id,fixture.paused);
 await page.locator('#body-limit').fill('1');const confirm=page.locator('[data-body-action="confirm-start"]');assert((await confirm.innerText()).includes('继续'));
 await page.screenshot({path:path.join(root,'build/body-continue-dialog.png'),fullPage:true});await confirm.click();await page.waitForFunction(()=>!document.querySelector('#body-limit'));
 const posted=await app.evaluate(()=>resumePosts);assert.equal(posted.length,1);assert.equal(posted[0].id,fixture.paused);assert.equal(posted[0].limit,1);
 assert.deepEqual(errors,[]);await app.close();app=null;console.log(JSON.stringify({ok:true,top_continue_visible:true,queued_card_resume:true,old_paused_job_selectable:true,exact_job_and_limit_sent:true,real_scrapes:0,model_calls:0}));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1;});
