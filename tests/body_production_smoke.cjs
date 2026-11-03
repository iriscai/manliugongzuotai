const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path');const root=path.resolve(__dirname,'..');let app;
(async()=>{
 const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;delete env.COMIC_DATA_DIR;
 app=await _electron.launch({executablePath:'C:/Users/74319/Desktop/漫画文章工作台_V0.3.0/漫画文章工作台.exe',args:[],env,timeout:90000});
 const page=await app.firstWindow();await page.locator('.stat-value').first().waitFor({timeout:90000});
 const task=await page.evaluate(()=>window.desktop.api('/body/start',{method:'POST',body:{ids:[1,2],limit:2}}));
 console.log(JSON.stringify({started:task}));
 await page.locator('#body-btn').click();let detail,deadline=Date.now()+180000;
 while(Date.now()<deadline){
   detail=await page.evaluate(id=>window.desktop.api('/body/jobs/'+id),task.job_id);
   if(!['running','pausing'].includes(detail.job.state))break;
   await new Promise(r=>setTimeout(r,1000));
 }
 if(['running','pausing'].includes(detail.job.state)){
   await page.evaluate(()=>window.desktop.api('/body/pause',{method:'POST',body:{}}));
   const end=Date.now()+20000;
   while(Date.now()<end){detail=await page.evaluate(id=>window.desktop.api('/body/jobs/'+id),task.job_id);if(!['running','pausing'].includes(detail.job.state))break;await new Promise(r=>setTimeout(r,500));}
 }
 const materials=[];for(const id of [1,2]){const m=await page.evaluate(mid=>window.desktop.api('/materials/'+mid),id);materials.push({id:m.id,body_status:m.body_status,body_chars:m.body?.length||0,error:m.body_fetch_error||m.error||''});}
 const report={job:detail.job,items:detail.items,materials,model_calls:0};
 fs.writeFileSync(path.join(root,'build/body-production-smoke.json'),JSON.stringify(report,null,2));
 await page.waitForTimeout(1200);await page.screenshot({path:path.join(root,'build/body-production-page.png'),fullPage:true});
 console.log(JSON.stringify(report));await app.close();app=null;
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1});
