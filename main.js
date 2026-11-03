const { app, BrowserWindow, ipcMain, dialog, shell, Tray, Menu, nativeImage } = require('electron');
const { spawn, spawnSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const readline = require('readline');
let win, backend, port, tray, exitPending=false;
const token = crypto.randomBytes(32).toString('hex');
const dataDir = process.env.COMIC_DATA_DIR || path.join(app.isPackaged ? path.dirname(app.getPath('exe')) : __dirname, 'data');
const resources = path.join(__dirname, 'resources');
const devPython = process.env.COMIC_PYTHON || 'C:\\Users\\74319\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe';
if(process.env.COMIC_DATA_DIR){const isolatedSession=path.join(dataDir,'.app-session');fs.mkdirSync(isolatedSession,{recursive:true});app.setPath('userData',isolatedSession);}
const ownsInstance = app.requestSingleInstanceLock();
if (!ownsInstance) app.quit();
function showMainWindow(){
  if(!win || win.isDestroyed())return;
  if(win.isMinimized())win.restore();
  if(!win.isVisible())win.show();
  win.focus();
}
async function backendApi(route,body){
 const response=await fetch(`http://127.0.0.1:${port}${route}`,{method:body===undefined?'GET':'POST',headers:{'X-Workbench-Token':token,'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
 const result=await response.json();if(!response.ok)throw new Error(result.error||'请求失败');return result;
}
function quitNow(){app.allowQuit=true;app.quit();}
async function safeQuit(){
 if(exitPending)return {waiting:true};exitPending=true;
 try{
   await backendApi('/run/drain',{});
   const activity=await backendApi('/run/activity');
   if(activity.model_active||activity.body_active){
     const timer=setInterval(async()=>{try{const a=await backendApi('/run/activity');if(!a.model_active&&!a.body_active){clearInterval(timer);quitNow();}}catch(e){if(backend?.exitCode!==null){clearInterval(timer);quitNow();}}},1000);
     win?.webContents.send('lifecycle-status','正在保存当前步骤，完成后退出');return {waiting:true};
   }
   quitNow();return {waiting:false};
 }catch(error){exitPending=false;if(!backend||backend.exitCode!==null)quitNow();else{showMainWindow();win?.webContents.send('lifecycle-status','退出未完成：'+error.message);}return {error:error.message};}
}
function setupTray(){
 try{
   tray=new Tray(nativeImage.createFromPath(path.join(__dirname,'assets','icon.png')).resize({width:20,height:20}));tray.setToolTip('漫流工作台 · 关闭窗口后可继续运行');
   tray.setContextMenu(Menu.buildFromTemplate([{label:'打开漫流工作台',click:showMainWindow},{label:'保存当前步骤后退出',click:()=>safeQuit()},{type:'separator'},{label:'立即退出…',click:async()=>{const r=await dialog.showMessageBox(win,{type:'warning',message:'立即退出会中断在途请求，已保存成果保留。',buttons:['取消','立即退出'],defaultId:0,cancelId:0});if(r.response===1)quitNow();}}]));
   tray.on('double-click',showMainWindow);
 }catch(error){tray=null;}
}
app.on('second-instance', showMainWindow);
app.on('activate', showMainWindow);
async function startBackend(){
  fs.mkdirSync(dataDir,{recursive:true});
  const exe = path.join(__dirname,'backend','comic-backend.exe');
  const useExe=fs.existsSync(exe);
  const args=useExe ? [] : ['-X','utf8','-B',path.join(__dirname,'backend','server.py')];
  args.push('--data',dataDir,'--resources',resources);
  backend=spawn(useExe?exe:devPython,args,{windowsHide:true,env:{...process.env,COMIC_WORKBENCH_TOKEN:token},stdio:['ignore','pipe','pipe']});
  backend.stderr.on('data',chunk=>fs.appendFileSync(path.join(dataDir,'backend.log'),chunk));
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('数据库服务启动超时')),60000);
    const lines=readline.createInterface({input:backend.stdout});
    lines.on('line',line=>{try{const r=JSON.parse(line);if(r.ready){port=r.port;clearTimeout(timer);resolve();}}catch{}});
    backend.on('error',err=>{clearTimeout(timer);reject(err)});
    backend.on('exit',code=>{clearTimeout(timer);if(!port)reject(new Error('数据库服务退出：'+code));else if(win&&!app.isQuitting)win.webContents.send('backend-offline');});
  });
}
function validateURL(url){const u=new URL(url);if(!['https:','http:'].includes(u.protocol))throw new Error('仅支持网页链接');return u.href;}
ipcMain.handle('api',async(_event,route,options={})=>{
  if(!/^\/(health|stats|materials|results|prompts|settings|provider|import|run|export|body)(\/|\?|$)/.test(route))throw new Error('非法请求路径');
  const response=await fetch(`http://127.0.0.1:${port}${route}`,{method:options.method||'GET',headers:{'X-Workbench-Token':token,'Content-Type':'application/json'},body:options.body===undefined?undefined:JSON.stringify(options.body)});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'请求失败');return data;
});
ipcMain.handle('choose-file',async()=>{const r=await dialog.showOpenDialog(win,{title:'导入素材表',properties:['openFile'],filters:[{name:'素材表格',extensions:['xlsx','csv','tsv','jsonl']}]});return r.canceled?null:r.filePaths[0];});
ipcMain.handle('save-file',async(_e,kind)=>{const r=await dialog.showSaveDialog(win,{title:'导出'+kind,defaultPath:kind+'.json',filters:[{name:'JSON完整记录',extensions:['json']},{name:'CSV表格',extensions:['csv']}]});return r.canceled?null:r.filePath;});
ipcMain.handle('open-external',(_e,url)=>shell.openExternal(validateURL(url)));
ipcMain.handle('open-data',()=>shell.openPath(dataDir));
ipcMain.handle('choose-body-tool',async()=>{const r=await dialog.showOpenDialog(win,{title:'选择正文抓取工具.exe',properties:['openFile'],filters:[{name:'正文抓取程序',extensions:['exe']}]});return r.canceled?null:r.filePaths[0];});
ipcMain.handle('open-body-records',(_e,id)=>{if(!/^body_[a-f0-9]{12}$/.test(id))throw new Error('无效任务编号');const folder=path.join(dataDir,'body_fetch',id);if(!fs.existsSync(folder))throw new Error('该任务尚无文件记录');return shell.openPath(folder);});
ipcMain.handle('window',(_e,action)=>{if(action==='minimize')win.minimize();if(action==='maximize')win.isMaximized()?win.unmaximize():win.maximize();if(action==='close')win.close();});
ipcMain.handle('lifecycle',async(_e,action)=>{if(action==='show'){showMainWindow();return {ok:true};}if(action==='background'){tray?win.hide():win.minimize();return {ok:true};}if(action==='safe-exit')return safeQuit();return {hidden:!win.isVisible(),draining:exitPending};});
if(ownsInstance)app.whenReady().then(async()=>{
  try{
    await startBackend();
    win=new BrowserWindow({width:1480,height:980,minWidth:1080,minHeight:720,show:false,backgroundColor:'#f4f6fb',frame:false,icon:path.join(__dirname,'assets','icon.png'),title:'漫画文章工作台',webPreferences:{preload:path.join(__dirname,'preload.js'),contextIsolation:true,nodeIntegration:false,sandbox:true}});
    setupTray();win.on('close',event=>{if(!app.allowQuit){event.preventDefault();tray?win.hide():win.minimize();}});
    win.webContents.setWindowOpenHandler(({url})=>{shell.openExternal(validateURL(url)).catch(()=>{});return{action:'deny'};});
    win.webContents.on('will-navigate',(event,url)=>{if(!url.startsWith('file://'))event.preventDefault();});
    await win.loadFile(path.join(__dirname,'renderer','index.html'));
    showMainWindow();
  }catch(err){dialog.showErrorBox('工作台启动失败',err.message+'\n日志：'+path.join(dataDir,'backend.log'));app.quit();}
});
app.on('window-all-closed',()=>{if(app.allowQuit)app.quit();});
app.on('before-quit',event=>{if(!app.allowQuit&&port){event.preventDefault();safeQuit();return;}app.isQuitting=true;tray?.destroy();if(backend&&backend.exitCode===null){if(process.platform==='win32')spawnSync('taskkill',['/PID',String(backend.pid),'/T','/F'],{windowsHide:true,stdio:'ignore'});else backend.kill();}});
