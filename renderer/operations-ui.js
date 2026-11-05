pages.history=['任务历史','检索全部处理轮次，查看实际配置、用量与关联成果。'];
Object.assign(stateLabels,{waiting:'等待正文',done:'已完成'});
const historyView={q:'',state:'',mode:'',from:'',to:'',page:1};let executionPreview=null,executionPayload=null,executionBusy=false,executionRevision=0,executionPreviewTimer=null,executionMaterialIds=null,executionFixedFilters=null;
function opsButton(text,action,attrs='',cls='btn small'){return `<button class="${cls}" data-ops="${action}" ${attrs}>${text}</button>`;}
function taskPauseControl(task){return task.state==='running'?opsButton('暂停任务','pause-task',`data-id="${esc(task.id)}"`,'btn small danger'):task.state==='pausing'?'<button class="btn small" disabled>正在保存后暂停…</button>':'';}
function updatePauseControls(){const button=document.querySelector('[data-ops="pause-current"]');if(!button)return;const task=activeRun()||state.stats?.scoring?.rows.find(j=>j.id===state.stats.scoring.active_id);button.disabled=!task||task.state==='pausing';button.dataset.id=task?.id||'';button.textContent=task?.state==='pausing'?'正在保存后暂停…':'暂停任务';button.title=task?'停止领取新的模型请求，在途响应保存后暂停':'当前没有运行中的模型任务';}
function extractionModeLabel(value){return value==='direct'?'原赛道直接写文':value==='single'?'历史 1→1':'历史 1→N';}
function taskBudgetFields(values={},prefix='task'){return `<div class="form-grid">${[['request_limit','本轮请求上限'],['article_limit','本轮最多生成篇数'],['token_limit','本轮已报告Token上限']].map(([k,t])=>`<div class="field"><label for="${prefix}-${k}">${t}</label><input id="${prefix}-${k}" type="number" min="0" step="1" value="${values[k]??0}"></div>`).join('')}</div><p class="hint">0表示不限。请求包含失败重试；未知Token不估算，进行中的请求可能使Token超过上限。每条素材按原赛道写一篇。</p>`;}
const catalogFilters=()=>({...catalogState.applied,sort_by:catalogState.sortBy,sort_dir:catalogState.sortDir});
showStart=async function(mode='both',scope=null,ids=null,options={}){
 executionMaterialIds=ids;executionFixedFilters=options.filters||null;
 clearTimeout(executionPreviewTimer);executionRevision++;
 state.settings=await api('/settings');updateProvider();executionPreview=null;executionPayload=null;
 const chosen=scope||(state.page==='materials'?(materialSelection.size?'selected':'filtered'):'all');
 const selectedCount=executionMaterialIds?executionMaterialIds.length:materialSelection.size;
 const limit=chosen==='selected'&&selectedCount?Math.min(1000,selectedCount):state.settings.run_size;
 modal(`<header><div><h2>配置执行范围</h2><p>自动核对实际领取范围，确认后启动任务。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div id="execution-config">
 <div class="form-grid">
 <div class="field"><label for="run-scope">素材范围</label><select id="run-scope"><option value="filtered">${executionFixedFilters?'指定批次素材':'当前素材库筛选'}</option><option value="selected">勾选素材（${selectedCount}条）</option><option value="all">全库待处理素材</option></select></div>
 <div class="field"><label for="run-limit">本次最多领取素材数</label><input id="run-limit" type="number" min="1" max="1000" step="1" value="${limit}"></div>
 </div><p class="run-scope-hint">${options.label?esc(options.label)+' · ':''}按素材原赛道直接写文，一条素材生成一篇文章。推送在结果库单独执行。</p>
 <details id="execution-advanced" class="execution-advanced"><summary>高级选项 · 并发、预算与等待正文</summary><p class="hint">写文并发 ${state.settings.write_workers||8} 路。</p>
 <div class="field"><label for="run-delivery">执行方式</label><select id="run-delivery"><option value="direct">直接执行（只领取合格素材）</option><option value="queue">加入队列（可等待正文抓取）</option></select></div>
 ${taskBudgetFields({request_limit:state.settings.task_request_limit,article_limit:state.settings.task_article_limit,token_limit:state.settings.task_token_limit})}</details>
 <p class="hint">正文通过验收后可写文。缺少正文的素材可以加入队列等待抓取。</p></div>
 <div class="modal-actions">${opsButton('重新核对清单','preview-execution','','btn')}${opsButton('正在核对素材…','confirm-execution','disabled','btn primary')}</div><div id="execution-preview" aria-live="polite"></div>`,false);
 document.querySelector('#run-scope').value=chosen;
 await previewExecution();
};
function executionDraft(){
 const scope=document.querySelector('#run-scope').value,queue=document.querySelector('#run-delivery').value==='queue';
 const task_budget={};for(const k of ['request_limit','article_limit','token_limit'])task_budget[k]=Number(document.querySelector('#task-'+k).value);
 const limit=Number(document.querySelector('#run-limit').value);
 if(!Number.isInteger(limit)||limit<1||limit>1000)throw new Error('本次领取数量需为1至1000的整数');
 for(const [key,high] of [['request_limit',1000000],['article_limit',1000000],['token_limit',1000000000]])if(!Number.isInteger(task_budget[key])||task_budget[key]<0||task_budget[key]>high)throw new Error('本轮预算需填写有效非负整数，0表示不限');
 return {mode:'write',scope,limit,filters:scope==='filtered'?(executionFixedFilters||catalogFilters()):{},...(scope==='selected'?{ids:executionMaterialIds||[...materialSelection]}:{}),task_budget,queue};
}
async function previewExecution(){
 clearTimeout(executionPreviewTimer);
 const root=document.querySelector('#execution-config');if(!root||executionBusy)return;
 const revision=++executionRevision,button=document.querySelector('[data-ops="confirm-execution"]'),refreshButton=document.querySelector('[data-ops="preview-execution"]'),target=document.querySelector('#execution-preview');
 executionPreview=null;executionPayload=null;button.disabled=true;button.textContent='正在核对素材…';refreshButton.disabled=true;target.innerHTML='<p class="hint">正在核对正文、处理状态和本轮领取范围…</p>';
 try{
  const draft=executionDraft();if(draft.scope==='filtered'&&!executionFixedFilters&&catalogState.dirty)throw new Error('素材库筛选条件尚未应用，请先点击检索，再核对执行范围');
  const out=await api(draft.queue?'/run/queue-preview':'/run/preview',draft);
  if(revision!==executionRevision||!root.isConnected||JSON.stringify(draft)!==JSON.stringify(executionDraft()))return;
  executionPayload=draft;executionPreview=out;const excluded=out.excluded_ids||[];
  target.innerHTML=`<div class="callout"><strong>本次实际领取 ${out.ids.length} 条素材</strong> · ${extractionModeLabel(out.extraction_mode)}${draft.queue?` · ${out.rows.filter(r=>r.waiting_body).length}条等待正文`:out.eligible_count>out.ids.length?' · 范围内另有'+num(out.eligible_count-out.ids.length)+'条留待下一轮':''}${excluded.length?' · 其余'+excluded.length+'条本轮跳过，保持原状态':''}</div>${!out.ids.length?'<p class="execution-readiness">当前没有符合所选步骤的素材。请查看下方原因，或调整执行范围；缺正文可选择“加入队列”。</p>':''}<div class="execution-list">${out.rows.map(r=>`<div><b>#${r.id}</b><span>${esc(r.title)}</span><small>${esc(r.category)}${r.waiting_body?' · 等待正文':''}</small></div>`).join('')}</div>${excluded.length?`<details class="execution-exclusions"><summary>本轮跳过 ${excluded.length} 条 · 查看原因</summary><div class="execution-list">${(out.excluded_rows||excluded.map(id=>({id,title:'',reason:'当前不符合执行条件或超出本轮数量'}))).map(r=>`<div><b>#${r.id}</b><span>${esc(r.title)}<small>${esc(r.reason)}</small></span></div>`).join('')}</div></details>`:''}`;
  button.disabled=!out.ids.length;button.textContent=out.ids.length?`确认执行 ${out.ids.length} 条`:'暂无可执行素材';
  if(out.disabled_categories?.length)target.insertAdjacentHTML('afterbegin',`<p class="hint">以下赛道缺少启用的步骤规则，本轮不参与：${out.disabled_categories.map(esc).join('、')}</p>`);
 }catch(error){if(revision===executionRevision&&root.isConnected){target.innerHTML=`<p class="execution-readiness">${esc(error.message)}</p>`;button.textContent='暂不可执行';}}
 finally{if(revision===executionRevision&&root.isConnected)refreshButton.disabled=false;}
}
async function confirmExecution(button){
 if(executionBusy||!executionPreview?.ids.length)return;executionBusy=true;button.disabled=true;
 try{
   if(JSON.stringify(executionDraft())!==JSON.stringify(executionPayload))throw new Error('执行配置已变化，请等待重新核对后确认');
   const p={...executionPayload,ids:executionPreview.ids,expected_hashes:executionPreview.expected_hashes,expected_urls:executionPreview.expected_urls,config_hash:executionPreview.config_hash};
   if(p.queue)p.scope='selected';
   const r=await api(p.queue?'/run/enqueue':'/run/start',p);closeModal();toast(p.queue?`已将${r.total}条素材加入独立处理队列${r.body_error?'；正文抓取未启动：'+r.body_error:r.body_job?'；本次正文抓取'+r.body_job.total+'条':''}`:`任务已启动，实际领取${r.total}条素材`,!!r.body_error);await refresh();await navigate('queue');
 }finally{executionBusy=false;if(button.isConnected)await previewExecution();}
}
async function selectedList(){
 if(!pushSelection.size){closeModal();toast('勾选已清空');return;}
 const s=await api('/results/selection',{ids:[...pushSelection],filters:resultQuery()});
 modal(`<header><div><h2>已选文章 ${pushSelection.size} 篇</h2><p>当前筛选内 ${s.inside.length} 篇，筛选外 ${s.outside.length} 篇，失效 ${s.missing.length} 篇。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="modal-actions">${opsButton('只保留当前筛选内勾选','selection-inside',`data-ids="${s.inside.join(',')}"`)}${opsButton('移除失效项','selection-remove-missing',`data-ids="${s.missing.join(',')}"`)}</div><div class="execution-list">${s.rows.map(r=>`<div><b>#${r.id}</b><span>${esc(r.title)}<small>${esc(r.category)} · ${pushLabel[r.push_state]} · ${r.in_filter?'当前筛选内':'筛选外'}${r.cleared_at?' · 已清除':''}</small></span>${opsButton('移除','selection-remove',`data-id="${r.id}"`)}</div>`).join('')}</div>`,false);
}
async function taskDialog(id,resume=false){
 const r=await api('/run/info?id='+encodeURIComponent(id));
 modal(`<header><div><h2>${resume?'续跑任务':'任务配置与实际用量'}</h2><p>#${esc(r.id)} · ${stateLabels[r.state]||r.state}</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="task-config-grid"><div>写文流程<strong>${r.targeted_seeds?"重写选中文章":extractionModeLabel(r.extraction_mode)}</strong></div><div>执行方式<strong>${r.provider==='api'?'中转API':'本机Codex'}</strong></div><div>实际模型<strong>${esc(r.model)}</strong></div><div>写文并发<strong>${r.write_workers}</strong></div><div>总并发上限<strong>${r.global_max_concurrency}</strong></div><div>请求数<strong>${r.usage_available?r.usage.requests:'历史未记录'}</strong></div><div>已报告Token<strong>${num(r.usage.total_tokens)} · ${r.usage.unknown_usage}次用量未知</strong></div></div>
 ${taskPauseControl(r)}<p class="hint">规则政策：${esc(r.writing_policy)}。${r.funny_paragraph_policy==='funny_natural_paragraphs_v1'?'搞笑正文自然分段，不限段数。':''}本轮新生成${r.progress.write_completed}篇，复用${r.progress.reused}篇，失败${r.progress.write_failed}篇。</p>
 ${resume?`<label class="ops-checkbox"><input id="resume-refresh-key" type="checkbox">使用当前保存的连接密钥（仅同一接口地址）</label><p class="hint">保留原任务的模型、规则、并发及已完成步骤；只刷新连接密钥。同接口地址不一致时会拒绝刷新。</p>${taskBudgetFields(r.task_budget,'resume-budget')}<p class="hint">额度是本轮累计上限，已完成的请求和文章不会清零。提高额度可继续未完成部分。</p>${opsButton('按以上配置续跑','confirm-resume',`data-id="${r.id}"`,'btn primary')}`:''}
 <details class="task-rules"><summary>本轮规则版本快照（${r.rule_versions.length}份）</summary><div>${r.rule_versions.map(p=>`<span>${esc(p.category)} · ${p.kind==='write'?'写文':'提炼'} ${p.variant} R${p.revision}</span>`).join('')}</div></details>`,false);
}
async function historyPage(){
 const r=await api('/run/history?'+new URLSearchParams(historyView));historyView.page=r.page;
 return `<section class="panel"><div class="panel-title"><h2>全部处理任务</h2><small>共${num(r.total)}轮</small></div><div class="toolbar" data-preserve-live><input id="history-search" placeholder="搜索任务编号或模型" value="${esc(historyView.q)}"><select data-history-filter="state"><option value="">全部状态</option>${['running','paused','blocked','completed','interrupted'].map(k=>`<option value="${k}" ${historyView.state===k?'selected':''}>${stateLabels[k]}</option>`).join('')}</select><select data-history-filter="mode"><option value="">全部模式</option>${[['both','提炼与写文'],['extract','仅提炼'],['write','仅写文']].map(([k,t])=>`<option value="${k}" ${historyView.mode===k?'selected':''}>${t}</option>`).join('')}</select><input type="date" data-history-filter="from" value="${historyView.from}" aria-label="开始日期"><input type="date" data-history-filter="to" value="${historyView.to}" aria-label="结束日期">${opsButton('检索','history-search')}</div>
 <div class="table-wrap"><table class="data-table"><thead><tr><th>任务 / 时间</th><th>实际模型 / 规则</th><th>本轮产出</th><th>请求与Token</th><th>状态 / 操作</th></tr></thead><tbody>${r.rows.map(x=>`<tr data-row-key="history-${x.id}"><td>#${x.id}<small>${esc(x.created_at.replace('T',' '))}</small></td><td>${esc(x.model)}<small>${esc(x.writing_policy)} · ${extractionModeLabel(x.extraction_mode)}</small></td><td>新生成 ${x.progress.write_completed} · 复用 ${x.progress.reused}<small>失败 ${x.progress.write_failed} · 剩余 ${x.progress.remaining}</small></td><td>${x.usage_available?x.usage.requests+'次请求':'历史用量未记录'}<small>${num(x.usage.total_tokens)} Token · ${x.usage.unknown_usage}次未知</small></td><td class="task-history-actions">${pill(x.state)}${taskPauseControl(x)}${opsButton('查看实际配置','task-info',`data-id="${x.id}"`)}${['paused','blocked','interrupted'].includes(x.state)?opsButton('配置续跑','resume-dialog',`data-id="${x.id}"`):''}${opsButton('关联成果','task-results',`data-id="${x.id}"`)}</td></tr>`).join('')}</tbody></table></div><div class="pagination"><span>第${r.page}/${Math.max(1,Math.ceil(r.total/r.size))}页</span>${opsButton('上一页','history-page',`data-page="${r.page-1}" ${r.page<=1?'disabled':''}`)}${opsButton('下一页','history-page',`data-page="${r.page+1}" ${r.page*r.size>=r.total?'disabled':''}`)}</div></section>`;
}
async function queuePanel(){
 const r=await api('/run/model-queue');return `<section class="panel section-spacer" id="independent-model-queue"><div class="panel-title"><h2>独立处理队列</h2><small>正文验收后自动领取本范围素材</small></div>${r.rows.length?r.rows.map(j=>`<div class="run-card" data-row-key="model-job-${j.id}"><strong>#${j.id}</strong> ${pill(j.state)} <span class="pill blue">${extractionModeLabel(j.extraction_mode)}</span><p>完成 ${j.counts.done||0} · 跳过 ${j.counts.skipped||0} · 等待 ${j.counts.pending||0}</p><p class="hint">${esc(j.error||'按本次固定范围处理')}</p>${opsButton('查看范围与原因','queue-detail',`data-id="${j.id}"`)}${j.run_id?opsButton('关联任务','task-info',`data-id="${j.run_id}"`):''}${j.state==='paused'?opsButton('继续队列','queue-resume',`data-id="${j.id}"`):['queued','waiting','running'].includes(j.state)?opsButton('暂停队列','queue-pause',`data-id="${j.id}"`):''}</div>`).join(''):empty('还没有独立队列任务','开始处理时可选择“加入队列”，等待正文的素材会显示具体原因。')}</section>`;
}
const operationsRender=render;
render=async function(passive=false){
 updatePauseControls();
 if(state.page==='history'){
   const revision=++renderRevision;let html=await historyPage();html=await distributionHeader('history')+html;if(state.page!=='history'||revision!==renderRevision)return;
   const div=document.createElement('div');div.innerHTML=html;morphChildren(document.querySelector('#content'),div,passive);syncDistributionTooltip();return;
 }
 await operationsRender(passive);
 if(state.page==='results'&&!document.querySelector('[data-ops="selection-list"]'))document.querySelector('.push-buttons')?.insertAdjacentHTML('beforeend',opsButton('查看已选清单','selection-list',pushSelection.size?'':'disabled'));
 if(state.page==='settings'&&!document.querySelector('#task-default-settings'))document.querySelector('#content').insertAdjacentHTML('beforeend',`<section class="panel section-spacer" id="task-default-settings"><div class="panel-title"><h2>单轮默认预算</h2></div>${taskBudgetFields({request_limit:state.settings.task_request_limit,article_limit:state.settings.task_article_limit,token_limit:state.settings.task_token_limit},'default-budget')}${opsButton('保存单轮默认预算','save-task-defaults','','btn primary')}</section>`);
};
async function opsAction(b){
 const a=b.dataset.ops;
 if(a==='pause-task'||a==='pause-current'){
   const id=b.dataset.id||activeRun()?.id;if(!id)return toast('当前没有运行中的写文任务');
   b.disabled=true;try{const r=await api('/run/pause',{id});toast(r.message);await refresh();await render();}finally{updatePauseControls();}return;
 }
 if(a==='execute-filtered'||a==='execute-selected')return showStart('both',a==='execute-selected'?'selected':'filtered');
 if(a==='clear-material-selection'){materialSelection.clear();return render();}
 if(a==='preview-execution')return previewExecution();
 if(a==='confirm-execution')return confirmExecution(b);
 if(a==='selection-list')return selectedList();
 if(a==='selection-remove'){pushSelection.delete(Number(b.dataset.id));await selectedList();return render();}
 if(a==='selection-inside'){pushSelection.clear();b.dataset.ids.split(',').filter(Boolean).map(Number).forEach(i=>pushSelection.add(i));closeModal();return render();}
 if(a==='selection-remove-missing'){b.dataset.ids.split(',').filter(Boolean).map(Number).forEach(i=>pushSelection.delete(i));return selectedList();}
 if(a==='task-info'||a==='resume-dialog')return taskDialog(b.dataset.id,a==='resume-dialog');
 if(a==='confirm-resume'){
   const task_budget={};for(const k of ['request_limit','article_limit','token_limit'])task_budget[k]=Number(document.querySelector('#resume-budget-'+k).value);
   b.disabled=true;try{await api('/run/resume',{id:b.dataset.id,refresh_credentials:document.querySelector('#resume-refresh-key').checked,task_budget});closeModal();toast('任务已按原规则续跑');await refresh();}finally{if(b.isConnected)b.disabled=false;}return;
 }
 if(a==='history-search'){historyView.q=document.querySelector('#history-search').value;historyView.page=1;return render();}
 if(a==='history-page'){historyView.page=Number(b.dataset.page);return render();}
 if(a==='task-results'){await navigate('results');state.q='';state.category='';state.resultPage=1;Object.assign(resultView,{batch:b.dataset.id,rule:'',push:'',date_from:'',date_to:'',visibility:'active'});return render();}
 if(a==='queue-detail'){const r=await api('/run/model-queue/detail?id='+b.dataset.id);modal(`<header><div><h2>队列范围与处理原因</h2><p>#${esc(r.job.id)}</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="execution-list">${r.items.map(i=>`<div><b>#${i.material_id}</b><span>${esc(i.title)}<small>${esc(i.error||(i.state==='pending'?(i.qualification==='qualified'?'已验收，等待模型空位':'等待有效正文与验收'):stateLabels[i.state]||i.state))}</small></span></div>`).join('')}</div>`,false);return;}
 if(a==='queue-pause'||a==='queue-resume'){await api(a==='queue-pause'?'/run/queue-pause':'/run/queue-resume',{id:b.dataset.id});return render();}
 if(a==='background')return window.desktop.lifecycle('background');
 if(a==='safe-exit'){toast('正在保存当前步骤，完成后退出');return window.desktop.lifecycle('safe-exit');}
 if(a==='save-task-defaults'){
   const values={};for(const k of ['request_limit','article_limit','token_limit'])values['task_'+k]=Number(document.querySelector('#default-budget-'+k).value);
   await api('/settings',values);state.settings=await api('/settings');return toast('单轮默认预算已保存');
 }
}
document.addEventListener('click',e=>{
 const checkbox=e.target.closest('[data-material-select]');if(checkbox){e.stopImmediatePropagation();const key=checkbox.dataset.materialSelect;if(key==='page')materialPageRows.forEach(r=>checkbox.checked?materialSelection.add(r.id):materialSelection.delete(r.id));else checkbox.checked?materialSelection.add(Number(key)):materialSelection.delete(Number(key));render().catch(x=>toast(x.message,true));return;}
 const resume=e.target.closest('[data-resume]');if(resume){e.stopImmediatePropagation();taskDialog(resume.dataset.resume,true).catch(x=>toast(x.message,true));return;}
 const b=e.target.closest('[data-ops]');if(!b)return;e.stopImmediatePropagation();opsAction(b).catch(x=>toast(x.message,true));
},true);
function invalidatePreview(e){if(e.target.closest('#execution-config')){try{if(executionPreview&&executionPayload&&JSON.stringify(executionDraft())===JSON.stringify(executionPayload))return;}catch{}clearTimeout(executionPreviewTimer);executionRevision++;executionPreview=null;executionPayload=null;const button=document.querySelector('[data-ops="confirm-execution"]');if(button){button.disabled=true;button.textContent='正在重新核对…';}const p=document.querySelector('#execution-preview');if(p)p.innerHTML='<p class="hint">配置已变化，正在重新核对素材范围…</p>';executionPreviewTimer=setTimeout(()=>previewExecution(),300);}}
document.addEventListener('input',invalidatePreview);
document.addEventListener('change',e=>{invalidatePreview(e);const key=e.target.dataset.historyFilter;if(key){historyView[key]=e.target.value;historyView.page=1;render().catch(x=>toast(x.message,true));}});
window.desktop.onLifecycle?.(message=>toast(message));
document.querySelector('.header-actions').insertAdjacentHTML('afterbegin',opsButton('后台运行','background')+opsButton('保存后退出','safe-exit')+opsButton('暂停任务','pause-current','disabled','btn danger'));
