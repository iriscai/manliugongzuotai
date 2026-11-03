let historyCleanupPreview=null,historyCleanupRevision=0,historyCleanupBusy=false;
const cleanupNames={runs:'提炼 / 写文任务',body_jobs:'正文抓取任务',model_queue:'独立处理队列',events:'执行日志',model_requests:'接口调用记录',run_items:'素材执行明细',run_writes:'主题写文明细',run_article_slots:'生成额度记录',body_items:'正文抓取明细',model_queue_items:'独立队列明细',model_queue_runs:'队列关联记录'};
function cleanupSize(bytes){return bytes>=1048576?(bytes/1048576).toFixed(2)+' MB':bytes>=1024?(bytes/1024).toFixed(1)+' KB':bytes+' B';}
async function showHistoryCleanup(){
 historyCleanupPreview=null;
 modal(`<header><div><h2>清理执行记录与日志</h2><p>按北京时间清理过期执行记录和日志。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div id="history-cleanup-form"><div class="history-cleanup-options"><label>时间范围<select id="history-cleanup-period"><option value="month">一个月前</option><option value="7d">7天前</option></select></label><label><input type="checkbox" data-history-cleanup-option="records" checked> 清理执行记录及关联明细</label><label><input type="checkbox" data-history-cleanup-option="logs" checked> 清理日志和旧日志文件</label><label><input type="checkbox" data-history-cleanup-option="files" checked> 同时清理对应的运行缓存文件</label></div><p class="hint">“一个月前”按上月同日计算。只清理最后更新早于截止时间的已结束记录；可续跑、待重试和未完成队列保留。</p><div class="callout">素材、文章成品、提炼种子、评分、文章历史版本和推送回执均保留。执行前自动压缩备份本次选中的记录和文件。</div><div id="history-cleanup-preview" aria-live="polite">正在统计清理范围…</div><div class="modal-actions"><button class="btn" data-action="close-modal">取消</button><button class="btn danger" id="confirm-history-cleanup" disabled>确认清理所选历史</button></div></div>`,false);
 await refreshHistoryCleanupPreview();
}
async function refreshHistoryCleanupPreview(){
 const revision=++historyCleanupRevision,form=document.querySelector('#history-cleanup-form');if(!form)return;
 const button=form.querySelector('#confirm-history-cleanup');button.disabled=true;historyCleanupPreview=null;
 const payload={period:form.querySelector('#history-cleanup-period').value};for(const x of form.querySelectorAll('[data-history-cleanup-option]'))payload[x.dataset.historyCleanupOption]=x.checked;
 form.querySelector('[data-history-cleanup-option="files"]').disabled=!payload.records;
 const target=form.querySelector('#history-cleanup-preview');target.innerHTML='<p class="muted">正在统计清理范围…</p>';
 try{
  const result=await api('/run/cleanup-preview',payload);if(revision!==historyCleanupRevision||!form.isConnected)return;
  historyCleanupPreview=result;
  target.innerHTML=`<div class="history-cleanup-cutoff"><strong>清理截止时间</strong><span>${esc(result.cutoff.slice(0,19).replace('T',' '))} · 北京时间以前</span></div><div class="history-cleanup-counts">${Object.entries(result.counts).map(([k,n])=>`<div><span>${cleanupNames[k]||esc(k)}</span><b>${num(n)}</b></div>`).join('')}<div><span>历史文件</span><b>${num(result.files)}个 · ${cleanupSize(result.file_bytes)}</b></div></div><p class="hint">合计 ${num(result.total_records)} 条记录。${result.protected_tasks?'保留 '+num(result.protected_tasks)+' 个未完成或可续跑 / 重试任务。':''}</p>${result.busy?'<p class="cleanup-notice">当前有任务执行或排队中，请先暂停并等待当前步骤保存，再重新预览。</p>':!result.total_records&&!result.files?'<p class="cleanup-notice">当前范围没有可清理的历史。</p>':''}`;
  button.disabled=result.busy||(!result.total_records&&!result.files);
 }catch(error){if(revision===historyCleanupRevision&&form.isConnected)target.innerHTML=`<p class="cleanup-notice">${esc(error.message)}</p>`;}
}
async function confirmHistoryCleanup(){
 if(historyCleanupBusy||!historyCleanupPreview)return;
 historyCleanupBusy=true;const selected=historyCleanupPreview,form=document.querySelector('#history-cleanup-form');form?.querySelectorAll('button,input,select').forEach(x=>x.disabled=true);
 const button=document.querySelector('#confirm-history-cleanup');if(button)button.textContent='正在备份并清理…';
 try{
  const result=await api('/run/cleanup-history',{preview_id:selected.preview_id,digest:selected.digest});historyCleanupPreview=null;historyView.page=1;
  await refresh();await render();
  modal(`<header><div><h2>历史清理完成</h2><p>素材和文章成品保留。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="callout">已清理 ${num(result.total_records)} 条历史记录、${num(result.files_removed)} 个历史文件（${cleanupSize(result.file_bytes_removed)}）。</div><label class="field">压缩备份位置<input readonly value="${esc(result.backup_path)}"></label>${result.warnings.length?`<p class="cleanup-notice">以下文件已有更新或暂时无法删除，已保留：</p><ul>${result.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>`:''}<div class="modal-actions"><button class="btn" data-history-cleanup="open-data">打开数据目录</button><button class="btn primary" data-action="close-modal">完成</button></div>`,false);
 }catch(error){toast(error.message,true);if(document.querySelector('#history-cleanup-form')){form.querySelectorAll('button,input,select').forEach(x=>x.disabled=false);if(button)button.textContent='确认清理所选历史';await refreshHistoryCleanupPreview();}}
 finally{historyCleanupBusy=false;}
}
document.addEventListener('click',e=>{
 const button=e.target.closest('[data-history-cleanup],#confirm-history-cleanup');if(!button)return;e.stopImmediatePropagation();
 const promise=button.id==='confirm-history-cleanup'?confirmHistoryCleanup():button.dataset.historyCleanup==='open-data'?window.desktop.openData():showHistoryCleanup();
 Promise.resolve(promise).catch(error=>toast(error.message,true));
},true);
document.addEventListener('change',e=>{if(e.target.closest('#history-cleanup-form'))refreshHistoryCleanupPreview();});
