const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('desktop',{
  api:(route,options)=>ipcRenderer.invoke('api',route,options),
  chooseFile:()=>ipcRenderer.invoke('choose-file'),
  saveFile:kind=>ipcRenderer.invoke('save-file',kind),
  openExternal:url=>ipcRenderer.invoke('open-external',url),
  openData:()=>ipcRenderer.invoke('open-data'),
  chooseBodyTool:()=>ipcRenderer.invoke('choose-body-tool'),
  openBodyRecords:id=>ipcRenderer.invoke('open-body-records',id),
  window:action=>ipcRenderer.invoke('window',action),
  lifecycle:action=>ipcRenderer.invoke('lifecycle',action),
  onLifecycle:fn=>ipcRenderer.on('lifecycle-status',(_e,message)=>fn(message)),
  onOffline:fn=>ipcRenderer.on('backend-offline',fn)
});
