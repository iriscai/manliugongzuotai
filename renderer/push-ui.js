// Selection survives polling and pagination; push status follows the saved content version.
const pushSelection=new Set();let pushBusy=false;let pushRows=[];let pushClearable=0;let pushOperation='';
const pushLabel={not_pushed:'未推送',pending:'等待接收',pushed:'已推送',failed:'推送失败'};
function updatePushControls(){
 const send=document.querySelector('[data-push-action="send"]');
 if(send){send.disabled=pushBusy||!pushSelection.size;send.textContent=pushBusy&&pushOperation==='send'?'正在推送…':'一键推送勾选文章';}
 const cleanup=document.querySelector('[data-push-action="cleanup"]');if(cleanup){cleanup.disabled=pushBusy||!pushClearable;cleanup.textContent=pushBusy&&pushOperation==='cleanup'?'正在清除…':`归档全部已推送（${pushClearable}）`;}
 const clear=document.querySelector('[data-push-action="clear"]');if(clear)clear.disabled=pushBusy;
 const count=document.querySelector('.push-buttons>span b');if(count)count.textContent=pushSelection.size;
 document.querySelectorAll('[data-push-select]').forEach(x=>{x.disabled=pushBusy||(x.dataset.pushSelect==='page'&&!pushRows.length);});
}
results=async function(){
 const r=await api('/results?'+new URLSearchParams({page:state.resultPage,q:state.q,category:state.category}));pushRows=r.rows;pushClearable=r.clearable_count||0;
 const selectable=r.rows;
 const all=selectable.length>0&&selectable.every(x=>pushSelection.has(x.id));
 const panel=`<section class="panel push-tools"><div><strong>推送到参考图工厂标题库</strong><p>标题 → 标题，文章 → 正文，赛道 → 分类；推送后保留勾选，可继续推送，已有相同内容不会重复入库。</p></div><div class="push-buttons"><span>已选 <b>${pushSelection.size}</b> 篇</span><button class="btn danger small" data-push-action="cleanup" title="清除所有已确认推送的成品，不受分页和筛选限制；自动备份，保留素材、种子和目标标题库" ${!r.cleanup_supported||!pushClearable||pushBusy?'disabled':''}>${pushBusy&&pushOperation==='cleanup'?'正在清除…':`归档全部已推送（${pushClearable}）`}</button><button class="btn small" data-push-action="clear" ${pushBusy?'disabled':''}>清空勾选</button><button class="btn primary" data-push-action="send" ${!pushSelection.size||pushBusy?'disabled':''}>${pushBusy&&pushOperation==='send'?'正在推送…':'一键推送勾选文章'}</button></div></section>`;
 return toolbar()+panel+(r.rows.length?`<section class="panel"><div class="panel-title"><h2>文章成品</h2><small>共${num(r.total)}篇 · 可跨页勾选</small></div><div class="table-wrap"><table class="data-table article-results"><thead><tr><th class="push-check"><input type="checkbox" data-push-select="page" aria-label="勾选本页文章" ${all?'checked':''} ${!selectable.length||pushBusy?'disabled':''}></th><th style="width:85px">赛道</th><th style="width:200px">标题</th><th>文章</th><th style="width:112px">推送状态</th></tr></thead><tbody>${r.rows.map(x=>`<tr data-result="${x.material_id}"><td class="push-check"><input type="checkbox" data-push-select="${x.id}" aria-label="勾选文章${x.id}" ${pushSelection.has(x.id)?'checked':''} ${pushBusy?'disabled':''}></td><td><span class="pill blue">${esc(x.category)}</span></td><td><strong>${esc(x.title)}</strong></td><td class="article-copy">${esc(x.article||x.short_text)}</td><td class="push-status" title="${esc(x.push_error||'')}"><span class="pill ${x.push_state==='pushed'?'green':x.push_state==='failed'?'red':x.push_state==='pending'?'amber':''}">${pushLabel[x.push_state]||'未推送'}</span>${x.pushed_at?`<small>${esc(shortTime(x.pushed_at))}</small>`:''}</td></tr>`).join('')}</tbody></table></div></section>`:`<section class="panel">${empty('结果库还没有文章成品')}</section>`)+pagination(r,'results');
};
document.addEventListener('click',async e=>{
 const checkbox=e.target.closest('[data-push-select]'),button=e.target.closest('[data-push-action]');
 if(!checkbox&&!button)return;e.stopImmediatePropagation();
 try{
  if(checkbox){
   if(pushBusy)return;
   if(checkbox.dataset.pushSelect==='page')pushRows.forEach(x=>checkbox.checked?pushSelection.add(x.id):pushSelection.delete(x.id));
   else{const id=Number(checkbox.dataset.pushSelect);checkbox.checked?pushSelection.add(id):pushSelection.delete(id);}
   updatePushControls();await render();return;
  }
  if(button.dataset.pushAction==='clear'){pushSelection.clear();updatePushControls();await render();return;}
  const cleaning=button.dataset.pushAction==='cleanup';
  if(pushBusy||(cleaning?!pushClearable:!pushSelection.size))return;
  const ids=[...pushSelection];pushBusy=true;pushOperation=cleaning?'cleanup':'send';updatePushControls();
  try{
   await render();
   if(cleaning){
    const r=await api('/results/clear-pushed',{});r.ids.forEach(id=>pushSelection.delete(id));state.resultPage=1;
    toast(r.count?`已清除 ${r.count} 篇已推送文章，已自动备份；素材和目标标题库保留。`:'暂无可清除的已推送文章');
   }else{
    const r=await api('/results/push',{ids});
    toast(`已推送 ${r.pushed} 篇${r.pending?'，等待目标接收 '+r.pending+' 篇':''}${r.failed?'，失败 '+r.failed+' 篇':''}${r.blocked?'，暂不推送 '+r.blocked+' 篇（未匹配评分规则或评分无效）':''}`,!!r.failed||!!r.blocked);
   }
  }finally{
   pushBusy=false;pushOperation='';updatePushControls();
   try{await refresh();}catch(error){toast('界面刷新失败，推送按钮已恢复：'+error.message,true);}
  }
 }catch(error){toast(error.message,true);}
},true);
