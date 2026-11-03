const {_electron}=require('C:/Users/74319/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert');const fs=require('fs');const path=require('path');
const exe='C:/Users/74319/Desktop/漫画文章工作台_V0.2.0/漫画文章工作台.exe';
const root=path.resolve(__dirname,'..');let app;
async function launch(){const env={...process.env};delete env.ELECTRON_RUN_AS_NODE;delete env.COMIC_DATA_DIR;app=await _electron.launch({executablePath:exe,args:[],env,timeout:90000});const page=await app.firstWindow();await page.locator('.stat-value').first().waitFor({timeout:90000});return page;}
(async()=>{
  let page=await launch();assert.equal(await page.locator('.stat-value').first().innerText(),'3,217');
  const settings=await page.evaluate(()=>window.desktop.api('/settings'));
  assert(settings.codex_path.endsWith('codex.exe'));
  assert.equal(settings.configured_model,'gpt-6.1-sol');
  assert.equal((await page.evaluate(()=>window.desktop.api('/prompts'))).length,148);
  const preview=await page.evaluate(()=>window.desktop.api('/import/preview',{method:'POST',body:{path:'C:/Users/74319/Downloads/article-1029150107179325726744084.xlsx'}}));
  assert.equal(preview.count,2000);assert.equal(preview.suggested.body,'');
  const auth=await page.evaluate(()=>window.desktop.api('/provider/check',{method:'POST',body:{}}));assert.equal(auth.ok,true);
  await page.evaluate(()=>window.desktop.api('/settings',{method:'POST',body:{batch_size:7}}));
  await app.close();app=null;
  page=await launch();
  const persisted=await page.evaluate(()=>window.desktop.api('/settings'));assert.equal(persisted.batch_size,7);
  await page.evaluate(()=>window.desktop.api('/settings',{method:'POST',body:{batch_size:5}}));
  await page.screenshot({path:path.join(root,'build/packaged-overview.png'),fullPage:true});
  await app.close();app=null;
  const report={ok:true,checks:['独立EXE正常启动','冻结后端可读取XLSX与SQLite','真实3217条素材和148份规则保留','本机登录状态检测成功','重启后数据库配置持久化','测试参数恢复默认'],production_inference_calls:0};
  fs.writeFileSync(path.join(root,'build/packaged-checks.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
})().catch(async e=>{console.error(e);if(app)await app.close().catch(()=>{});process.exitCode=1});
