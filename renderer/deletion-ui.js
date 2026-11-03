let deletionPreview=null,deletionBusy=false;
function libraryAction(text,kind,action,ids,disabled=false){return `<button class="btn small ${action==='delete'?'danger':''}" data-library-kind="${kind}" data-library-action="${action}" ${ids?`data-library-ids="${ids}"`:''} ${disabled?'disabled':''}>${text}</button>`;}
const beforeDeletionRender=render;
render=async function(passive=false){
 await beforeDeletionRender(passive);
 if(state.page==='materials'){
  const trashed=catalogState.applied.visibility==='deleted',bar=document.querySelector('.ops-material-actions');
  if(bar&&!bar.querySelector('[data-library-action]')){
   bar.insertAdjacentHTML('afterbegin',`<label class="catalog-select"><span>素材位置</span><select id="material-visibility" aria-label="素材位置"><option value="active" ${trashed?'':'selected'}>素材库</option><option value="deleted" ${trashed?'selected':''}>已删除</option></select></label>`);
   bar.insertAdjacentHTML('beforeend',libraryAction(trashed?'恢复勾选素材':'删除勾选素材','materials',trashed?'restore':'delete','',!materialSelection.size));
   if(trashed)bar.querySelectorAll('[data-ops^="execute-"]').forEach(b=>b.disabled=true);
  }
  for(const row of document.querySelectorAll('.material-table tbody tr[data-material]'))if(!row.querySelector('[data-library-action]'))row.lastElementChild.insertAdjacentHTML('beforeend',libraryAction(trashed?'恢复':'删除','materials',trashed?'restore':'delete',row.dataset.material));
 }
 if(state.page==='results'){
  const trashed=resultView.visibility==='deleted',bar=document.querySelector('.push-buttons');
  if(bar&&!bar.querySelector('[data-library-action]'))(bar.querySelector('.operator-article-more-menu')||bar).insertAdjacentHTML('beforeend',libraryAction(trashed?'恢复勾选文章':'删除勾选文章','results',trashed?'restore':'delete','',!pushSelection.size));
  if(trashed){document.querySelectorAll('[data-management="regenerate"],[data-management="regen-one"],[data-management="restore-cleared"],[data-push-action="send"]').forEach(b=>b.remove());document.querySelector('.push-tools>div>strong').textContent='已删除文章，可恢复';document.querySelector('.push-tools>div>p').textContent='原素材、种子与推送记录保留；恢复不会调用模型。';document.querySelectorAll('[data-management="article"]').forEach(b=>{b.dataset.deletedView=b.dataset.id;b.removeAttribute('data-management');if(!b.classList.contains('article-title'))b.textContent='查看';});}
  for(const row of document.querySelectorAll('[data-row-key^="result-"]'))if(!row.querySelector('[data-library-action]'))row.lastElementChild.insertAdjacentHTML('beforeend',libraryAction(trashed?'恢复':'删除','results',trashed?'restore':'delete',row.dataset.rowKey.slice(7)));
 }
};
async function showDeletion(kind,action,ids){
 const out=await api('/'+kind+'/delete-preview',{ids,action});deletionPreview=out;
 const verb=action==='restore'?'恢复':'删除',noun=kind==='materials'?'素材':'文章';
 modal(`<header><div><h2>${verb}${out.count}条${noun}</h2><p>以下是本次完整清单，包含跨页和筛选外的勾选。</p></div><button class="close-btn" data-action="close-modal">×</button></header>
 <div class="callout">${kind==='materials'?`已有${out.preserved_articles}篇关联成品与提炼种子保留。删除的素材不再抓取或生文，恢复后可继续使用。`:'原素材和提炼种子保留，已删除文章不会被普通任务自动补生。'}已推送到外部标题库的内容不受影响。${action==='delete'?'本次移入“已删除”，可以恢复。':''}</div>
 ${out.blocked.length?`<p class="delete-blocked">当前不可操作：${out.blocked.map(x=>'#'+x.id+' '+esc(x.reason)).join('；')}</p>`:''}
 <div class="execution-list">${out.rows.map(r=>`<div><b>#${r.id}</b><span>${esc(r.title)}<small>${esc(r.category)}</small></span></div>`).join('')}</div>
 <div class="modal-actions"><button class="btn" data-action="close-modal">取消</button><button class="btn ${action==='delete'?'danger':'primary'}" data-confirm-library ${out.blocked.length?'disabled':''}>确认${verb}${out.count}条${noun}</button></div>`,false);
}
async function confirmDeletion(button){
 if(deletionBusy||!deletionPreview)return;deletionBusy=true;button.disabled=true;
 try{
  const p=deletionPreview,r=await api('/'+p.kind+'/'+(p.action==='restore'?'restore':'delete'),{ids:p.ids,version:p.version});
  r.ids.forEach(id=>(p.kind==='materials'?materialSelection:pushSelection).delete(id));state.materialPage=state.resultPage=1;resultOptionsAt=0;catalogState.optionsAt=0;deletionPreview=null;closeModal();toast(`${p.action==='restore'?'已恢复':'已删除'}${r.count}条记录`);await refresh();if(state.page==='materials'&&catalogState.dirty)await render();
 }finally{deletionBusy=false;if(button.isConnected)button.disabled=false;}
}
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-library-action],[data-confirm-library]');
 if(button){event.preventDefault();event.stopImmediatePropagation();try{if(button.hasAttribute('data-confirm-library'))await confirmDeletion(button);else{const kind=button.dataset.libraryKind,ids=button.dataset.libraryIds?button.dataset.libraryIds.split(',').map(Number):[...(kind==='materials'?materialSelection:pushSelection)];await showDeletion(kind,button.dataset.libraryAction,ids);}}catch(error){toast(error.message,true);}return;}
 const article=event.target.closest('[data-deleted-view]');if(article&&state.page==='results'&&resultView.visibility==='deleted'){
  event.preventDefault();event.stopImmediatePropagation();try{const r=await api('/results/detail/'+article.dataset.deletedView);modal(`<header><div><h2>${esc(r.title)}</h2><p>已删除 · ${esc(r.category)}</p></div><button class="close-btn" data-action="close-modal">×</button></header>${paragraphCards(r.article||r.short_text)}<div class="modal-actions">${libraryAction('恢复文章','results','restore',String(r.id))}</div>`,false);}catch(error){toast(error.message,true);}
 }
},true);
document.addEventListener('change',async event=>{if(event.target.id==='material-visibility'){catalogState.draft.visibility=catalogState.applied.visibility=event.target.value;catalogState.optionsAt=0;catalogMarkDirty();state.materialPage=1;try{await render();}catch(error){toast(error.message,true);}}});
