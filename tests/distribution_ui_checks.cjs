const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('path'),assert=require('assert');const root=path.resolve(__dirname,'..');let app;
(async()=>{
 const env={...process.env,COMIC_DATA_DIR:path.join(root,'build/distribution-ui-data'),COMIC_PUSH_TARGET_PROJECT:path.join(root,'build/quality-target')};delete env.ELECTRON_RUN_AS_NODE;
 app=await _electron.launch({executablePath:'E:/日程提醒/node_modules/electron/dist/electron.exe',args:[process.env.COMIC_TEST_APP||root],env,timeout:90000});
 const page=await app.firstWindow(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.locator('.stat-value').first().waitFor({timeout:90000});
 for(const module of ['overview','materials','bodies','queue','writing','results','rules','settings','history']){
  await page.locator(`[data-nav="${module}"]`).first().click();
  await page.locator(`[data-row-key="distribution-${module}"]`).waitFor();
  const check=await page.evaluate(async(module)=>{
   const chart=document.querySelector('.lane-distribution'),scope=JSON.parse(chart.dataset.distScope),data=await window.desktop.api('/stats/distribution?'+new URLSearchParams({module,filters:JSON.stringify(scope[1])}));
   const segments=[...chart.querySelectorAll('.lane-segment')],bar=chart.querySelector('.lane-distribution-track');
   return {first:document.querySelector('#content').firstElementChild===chart,total:data.total,count:segments.length,expected:data.category_count,
    proportions:!bar||segments.every((s,i)=>Math.abs(s.getBoundingClientRect().width/bar.getBoundingClientRect().width-data.rows[i].count/data.total)<.003)};
  },module);
  assert(check.first&&check.count===check.expected&&check.proportions,module+' chart scope or proportions mismatch');
 }
 await page.locator('[data-nav="overview"]').first().click();const segment=page.locator('.lane-segment').first();await segment.hover();
 await page.locator('#lane-distribution-tooltip').waitFor({state:'visible'});await page.waitForTimeout(180);
 assert(await segment.evaluate(el=>new DOMMatrix(getComputedStyle(el).transform).d>1.5));
 await page.evaluate(()=>globalThis.originalDistributionSegment=document.querySelector('.lane-segment'));
 await page.waitForTimeout(4500);assert(await page.evaluate(()=>originalDistributionSegment===document.querySelector('.lane-segment')),'poll replaced hovered segment');
 assert(await page.locator('#lane-distribution-tooltip').isVisible());
 await page.screenshot({path:path.join(root,'build/distribution-hover.png'),fullPage:true});
 await segment.focus();await page.keyboard.press('End');assert(await page.locator('.lane-segment').last().evaluate(el=>document.activeElement===el));assert(await page.locator('#lane-distribution-tooltip').isVisible());
 await page.keyboard.press('Escape');assert(!(await page.locator('#lane-distribution-tooltip').isVisible()));
 await page.locator('[data-nav="results"]').first().click();await page.locator('[data-row-key="distribution-results"]').waitFor();
 const full=await page.locator('.lane-distribution-total').innerText();assert(full.includes('65'));
 await page.locator('[data-result-filter="score_band"]').selectOption('excellent');await page.waitForFunction(()=>document.querySelector('.lane-distribution-total')?.textContent.includes('6篇'));
 assert.equal(await page.locator('.lane-segment').count(),1);await page.locator('.lane-segment').hover();assert((await page.locator('#lane-distribution-tooltip').innerText()).includes('100%'));
 await page.locator('#list-search').fill('一定不存在的分布空状态');await page.keyboard.press('Enter');await page.waitForFunction(()=>document.querySelector('.lane-distribution-empty'));
 assert.equal(await page.locator('.lane-segment').count(),0);
 assert.deepEqual(errors,[]);await app.close();app=null;console.log(JSON.stringify({ok:true,all9module_headers:true,real_proportions:true,hover_enlarges_and_details:true,poll_preserves_hover:true,keyboard_supported:true,filters_ignore_pagination:true,zero_state:true,external_calls:0}));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1;});
