// Retry selections contain extraction IDs, never material IDs or result IDs.
const writingRetrySelection=new Set();
let writingRetryRows=[],writingRetryBusy=false,writingRetryPreview=null;
const WRITING_RETRY_LIMIT=500;
const actionsBeforeWritingRetry=pipelineActions;
pipelineActions=function(){return actionsBeforeWritingRetry().replace(/<\/div>$/,writingRetryEntry()+'</div>');};
function writingRetryEntry(){return `<button class="btn" data-writing-retry="all" ${activeRun()||writingRetryBusy?'disabled':''}>一键重试全部失败写文</button>`;}
function writingRetryControls(rows){
 writingRetryRows=rows;
 rows.filter(x=>x.state!=='failed').forEach(x=>writingRetrySelection.delete(x.id));
 return `<div class="writing-retry-tools"><div><strong>失败写文批量重试</strong><small>勾选跨页保留 · 全选覆盖全部分页 · 每轮最多 ${WRITING_RETRY_LIMIT} 篇</small></div><div class="pipeline-actions"><span>已选 <b>${writingRetrySelection.size}</b> 篇</span><button class="btn small" data-writing-retry="select-all" ${writingRetryBusy?'disabled':''}>全选失败（跨页）</button><button class="btn primary small" data-writing-retry="selected" ${!writingRetrySelection.size||activeRun()||writingRetryBusy?'disabled':''}>重试勾选</button><button class="btn small ghost" data-writing-retry="clear" ${writingRetryBusy?'disabled':''}>清空勾选</button></div></div>`;
}
async function currentWritingFailures(){
 const found=new Map();let page=1,pages=1;
 do{
  const r=await api('/run/writing?'+new URLSearchParams({state:'failed',page}));
  pages=Math.max(pages,Math.ceil(r.total/r.size));
  for(const x of r.rows)if(x.state==='failed')found.set(x.id,{id:x.id,material_id:x.material_id,category:x.category});
  page++;
 }while(page<=pages);
 return [...found.values()];
}
async function assertWritingRetryIdle(){
 const activity=await api('/run/activity');
 if(activity.model_active||activity.draining)throw Error('请先等待当前提炼/写文任务结束或暂停，再批量重试；正文抓取可以同时运行。');
}
function retryWritingDialog(rows,skipped){
 const counts=new Map();rows.forEach(x=>counts.set(x.category,(counts.get(x.category)||0)+1));
 modal(`<header><div><h2>重试 ${rows.length} 篇失败写文</h2><p>仅复用这些篇目的提炼种子，使用当前启用的生文提示词。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="callout">${skipped?`已排除 ${skipped} 篇后来已成功、状态变化或已失效的任务。`:'执行前会再次核对失败状态，已成功的篇目自动排除。'}只重试失败的赛道主题，不重新提炼，也不重跑同素材已成功的其他文章。</div><p class="hint">${[...counts].map(([k,n])=>esc(k)+' '+n+'篇').join(' · ')}<br>写文并发 ${state.settings.write_workers||8} 路，总并发上限 ${state.settings.global_max_concurrency||16} 路。沿用已配置的单轮预算和余额不足暂停规则。</p><div class="modal-actions"><button class="btn" data-action="close-modal">取消</button><button class="btn primary" data-writing-retry="confirm">确认重试 ${rows.length} 篇</button></div>`,true);
}
async function prepareWritingRetry(all){
 if(writingRetryBusy)return;writingRetryBusy=true;
 try{
  await assertWritingRetryIdle();
  const failures=await currentWritingFailures(),wanted=all?new Set(failures.map(x=>x.id)):new Set(writingRetrySelection);
  const rows=failures.filter(x=>wanted.has(x.id)),skipped=wanted.size-rows.length;
  writingRetrySelection.clear();rows.forEach(x=>writingRetrySelection.add(x.id));
  writingRetryPreview=null;
  if(!rows.length){toast('没有仍处于失败状态的写文任务，无需重试');await render();return;}
  if(rows.length>WRITING_RETRY_LIMIT){await render();throw Error(`共有 ${rows.length} 篇失败任务，已全部勾选。现有接口每轮最多 ${WRITING_RETRY_LIMIT} 篇，请在写文任务页调整勾选后重试。`);}
  writingRetryPreview={ids:rows.map(x=>x.id)};
  retryWritingDialog(rows,skipped);
 }finally{writingRetryBusy=false;}
}
async function confirmWritingRetry(button){
 if(writingRetryBusy||!writingRetryPreview)return;
 writingRetryBusy=true;button.disabled=true;
 try{
  await assertWritingRetryIdle();
  const wanted=new Set(writingRetryPreview.ids),latest=await currentWritingFailures();
  const ids=latest.filter(x=>wanted.has(x.id)).map(x=>x.id);
  if(!ids.length){closeModal();writingRetryPreview=null;writingRetrySelection.clear();toast('所选任务已成功或状态已变化，没有发出重试请求');await refresh();return;}
  if(ids.length>WRITING_RETRY_LIMIT)throw Error('超出单轮写文重试上限，请重新选择');
  const r=await api('/run/retry-seeds',{ids});
  wanted.forEach(id=>writingRetrySelection.delete(id));writingRetryPreview=null;closeModal();
  toast(`已启动 ${ids.length} 篇失败写文重试（${r.total} 条素材）${wanted.size>ids.length?'，自动跳过 '+(wanted.size-ids.length)+' 篇状态已变化的任务':''}`);
  await refresh();await navigate('queue');
 }finally{writingRetryBusy=false;if(button.isConnected)button.disabled=false;}
}
document.addEventListener('click',e=>{
 const box=e.target.closest('[data-writing-failed-select]'),button=e.target.closest('[data-writing-retry]');
 if(!box&&!button)return;e.stopImmediatePropagation();
 (async()=>{
  if(box){
   if(writingRetryBusy)return;
   if(box.dataset.writingFailedSelect==='page')writingRetryRows.filter(x=>x.state==='failed').forEach(x=>box.checked?writingRetrySelection.add(x.id):writingRetrySelection.delete(x.id));
   else{const id=Number(box.dataset.writingFailedSelect);if(writingRetryRows.some(x=>x.id===id&&x.state==='failed'))box.checked?writingRetrySelection.add(id):writingRetrySelection.delete(id);}
   await render();return;
  }
  if(writingRetryBusy)return;
  switch(button.dataset.writingRetry){
   case'clear':writingRetrySelection.clear();writingRetryPreview=null;return render();
   case'select-all':writingRetryBusy=true;try{const rows=await currentWritingFailures();writingRetrySelection.clear();rows.forEach(x=>writingRetrySelection.add(x.id));toast(`已勾选全部 ${rows.length} 篇失败写文，覆盖所有分页`);}finally{writingRetryBusy=false;}return render();
   case'all':return prepareWritingRetry(true);
   case'selected':return prepareWritingRetry(false);
   case'confirm':return confirmWritingRetry(button);
  }
 })().catch(error=>toast(error.message,true));
},true);
