// Reuse result checkboxes; score-only jobs never invoke extraction or article generation.
let scorePreview=null,scoreBusy=false;
function scoreSelectionControls(){
 const active=!!state.stats?.scoring?.active_id||!!activeRun();
 return `<button class="btn small soft-blue" data-rescore="select" ${scoreBusy?'disabled':''}>勾选待评分/失败</button><button class="btn small soft-teal" data-rescore="selected" ${!pushSelection.size||scoreBusy||active?'disabled':''}>重新评分勾选（${pushSelection.size}）</button>`;
}
const scoreItemLabels={queued:'待评分',scoring:'评分中',completed:'已评分',failed:'评分失败',skipped:'已跳过'};
function scoreJobPanels(){
 const jobs=state.stats?.scoring?.rows||[];if(!jobs.length)return '';
 return `<section class="panel score-job-panel"><div class="panel-title"><h2>独立评分任务</h2><small>只评价现有标题与正文，不重写文章</small></div>${jobs.slice(0,5).map(j=>{
  const c=j.counts,n=(c.completed||0)+(c.failed||0)+(c.skipped||0),pct=j.total?Math.round(n/j.total*100):0;
  return `<article class="score-job" data-score-job="${esc(j.id)}"><div class="score-job-heading"><strong>${esc(j.id)}</strong>${pill(j.state)}<small>${esc(j.model||j.provider)} · ${j.concurrency}路</small></div><div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div><div class="score-job-counts"><span>已评分 <b>${c.completed||0}</b></span><span>失败 <b>${c.failed||0}</b></span><span>评分中 <b>${c.scoring||0}</b></span><span>待评 <b>${c.queued||0}</b></span><span>跳过 <b>${c.skipped||0}</b></span><span>${n}/${j.total} 篇</span></div><p class="hint">实际调用 ${j.usage.requests} 次 · 已报告 ${num(j.usage.total_tokens)} Token${j.usage.unknown_usage?' · '+j.usage.unknown_usage+'次用量未返回':''}</p>${j.error?`<p class="danger">${esc(j.error)}</p>`:''}<div class="pipeline-actions"><button class="btn small" data-rescore="detail" data-id="${esc(j.id)}">评分明细</button>${j.state==='running'?`<button class="btn small soft-orange" data-rescore="pause" data-id="${esc(j.id)}">暂停评分</button>`:''}${j.state==='pausing'?'<span class="hint">等待在途评分保存…</span>':''}${['paused','blocked'].includes(j.state)?`<button class="btn small soft-blue" data-rescore="resume" data-id="${esc(j.id)}" ${state.stats.scoring.active_id||activeRun()?'disabled':''}>继续评分（当前密钥）</button>`:''}${c.failed&& !['running','pausing'].includes(j.state)?`<button class="btn small soft-blue" data-rescore="retry" data-id="${esc(j.id)}" ${state.stats.scoring.active_id||activeRun()?'disabled':''}>重试本批失败评分（${c.failed}）</button>`:''}</div></article>`;
 }).join('')}</section>`;
}
async function previewRescore(ids){
 if(!ids.length)throw Error('请先勾选需要重新评分的文章');
 scorePreview=await api('/results/score-preview',{ids,filters:resultQuery()});const p=scorePreview;
 modal(`<header><div><h2>仅重新评分 ${p.total} 篇文章</h2><p>保留现有标题、正文、生成版本和原评分历史。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="callout">模型：${esc(p.model)} · ${p.concurrency} 路并发。每篇执行一次独立评分，会消耗模型额度${p.provider==='api'?'；临时故障按设置最多重试'+p.retry_count+'次':''}。不重新提炼、生成标题或改写文章。</div>${p.outside_filter?`<p class="danger">当前勾选有 ${p.outside_filter} 篇位于当前筛选之外，以下按跨页勾选清单确认。</p>`:''}<p class="hint">可评分 ${p.total} 篇，跳过 ${p.skipped.length} 篇（已有有效评分、其他赛道或失效文章）。执行前和保存时再次核对文案，已修改、已删除或人工重新评分的文章自动跳过。</p><details><summary>查看评分清单</summary><ul>${p.rows.map(x=>`<li>#${x.id} · ${esc(x.title)}</li>`).join('')}</ul>${p.skipped.map(x=>`<p class="hint">#${x.id} · ${esc(x.reason)}</p>`).join('')}</details><div class="modal-actions"><button class="btn" data-action="close-modal">取消</button><button class="btn primary" data-rescore="confirm" disabled>确认仅评分 ${p.total} 篇</button></div>`,true);
}
document.addEventListener('click',e=>{
 const b=e.target.closest('[data-rescore]');if(!b)return;e.stopImmediatePropagation();
 (async()=>{
  if(scoreBusy)return;scoreBusy=true;document.querySelectorAll('[data-rescore]').forEach(button=>button.disabled=true);
  try{
   const action=b.dataset.rescore;
   if(action==='select'){
    const r=await api('/results/score-select',{filters:resultQuery()});pushSelection.clear();r.ids.forEach(id=>pushSelection.add(id));
    toast(`已勾选当前筛选内 ${r.ids.length} 篇待评分文章${r.total>r.limit?'（共'+r.total+'篇，每轮最多'+r.limit+'篇）':''}`);await render();
   }else if(action==='selected'||action==='one')await previewRescore(action==='one'?[Number(b.dataset.id)]:[...pushSelection]);
   else if(action==='confirm'){
    if(!scorePreview)return;const r=await api('/results/score-start',{id:scorePreview.id});closeModal();scorePreview=null;
    toast(`已创建独立评分任务 ${r.id}，可在结果库查看进度`);await refresh();
   }else if(action==='detail'){
    const d=await api('/results/score-job?id='+encodeURIComponent(b.dataset.id));
    modal(`<header><div><h2>独立评分明细</h2><p>${esc(d.id)} · ${d.rows.length}篇</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="table-wrap"><table class="data-table"><thead><tr><th>文章</th><th>状态</th><th>原因</th></tr></thead><tbody>${d.rows.map(x=>`<tr><td>#${x.result_id} · ${esc(x.title)}</td><td>${esc(scoreItemLabels[x.state]||x.state)}</td><td>${esc(x.error||'')}</td></tr>`).join('')}</tbody></table></div>`,true);
   }else if(['pause','resume','retry'].includes(action)){
    await api('/results/score-'+action,{id:b.dataset.id});toast(action==='pause'?'正在保存后暂停评分':action==='retry'?'已重试本批失败评分':'已继续评分');await refresh();
   }
  }catch(error){toast(error.message,true);}
  finally{scoreBusy=false;if(b.isConnected)b.disabled=false;const confirm=document.querySelector('[data-rescore="confirm"]');if(confirm)confirm.disabled=!scorePreview?.total;if(state.page==='results')await render();}
 })();
},true);
