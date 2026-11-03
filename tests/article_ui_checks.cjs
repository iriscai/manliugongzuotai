const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert'),fs=require('fs'),path=require('path');const root=path.resolve(__dirname,'..'),installed=process.argv.includes('--installed');let app;
const fixture=JSON.parse(fs.readFileSync(path.join(root,'build/article-ui-data.json'),'utf8'));
(async()=>{
 const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;if(installed)delete env.COMIC_DATA_DIR;else env.COMIC_DATA_DIR=fixture.data;
 app=await _electron.launch({executablePath:installed?'C:/Users/74319/Desktop/漫画文章工作台_V0.3.0/漫画文章工作台.exe':'E:/日程提醒/node_modules/electron/dist/electron.exe',args:installed?[]:[root],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.locator('.stat-value').first().waitFor({timeout:90000});
 const health=await page.evaluate(()=>window.desktop.api('/health'));assert.equal(health.version,'0.9.2');assert.equal(health.output_mode,'article');assert.equal(health.writing_policy,'headline_comic_v2');
 const prompts=await page.evaluate(()=>window.desktop.api('/prompts'));assert.equal(prompts.filter(p=>p.kind==='write').length,74);assert(prompts.filter(p=>p.kind==='write').every(p=>p.content.startsWith('你正在以素材正文、提炼元素和所属赛道创作中文短文成品。')));
 const stats=await page.evaluate(()=>window.desktop.api('/stats'));assert(stats.writing.ready>=0);assert.equal(stats.writing.needs_review,0);
 await page.locator('[data-nav="writing"]').first().click();await page.locator('.writing-table').waitFor();
 assert.equal(await page.locator('[data-pipeline-action="write"]').isEnabled(),stats.writing.ready>0);assert(!(await page.locator('.writing-metrics').innerText()).includes('待核实'));
 assert(!(await page.locator('.writing-table').innerText()).includes('项待核实'));
 await page.locator('[data-nav="results"]').first().click();
 if(installed&&stats.counts.result_count>0){
   await page.locator('.article-results tbody tr').first().click();await page.locator('.drawer').waitFor();
   assert.equal(await page.locator('.detail-block p').first().evaluate(e=>getComputedStyle(e).whiteSpace),'pre-wrap');
   await page.locator('[data-action="close-drawer"]').first().click();
 }
 if(!installed){
   await page.locator('.article-results').waitFor();assert.deepEqual(await page.locator('.article-results th').allTextContents(),['赛道','标题','文章']);
   await page.locator('.article-results tbody tr').first().click();await page.locator('.drawer').waitFor();assert((await page.locator('.drawer').innerText()).includes('图书角开放时'));
   assert.equal(await page.locator('[data-detail-tab="frames"]').count(),0);await page.locator('[data-action="close-drawer"]').first().click();
   const out=path.join(fixture.data,'成品导出.json');await page.evaluate(out=>window.desktop.api('/export',{method:'POST',body:{path:out,kind:'results'}}),out);
   const rows=JSON.parse(fs.readFileSync(out,'utf8'));assert.deepEqual(Object.keys(rows[0]),['赛道','标题','文章']);
 }
 await page.screenshot({path:path.join(root,installed?'build/article-installed.png':'build/article-results.png'),fullPage:true});assert.deepEqual(errors,[]);await app.close();app=null;
 const report={ok:true,installed_exe:installed,old_notes_no_longer_block:true,finished_output_fields:['赛道','标题','文章'],article_display_and_export:!installed,model_calls:0};fs.writeFileSync(path.join(root,installed?'build/article-installed-checks.json':'build/article-ui-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1});
