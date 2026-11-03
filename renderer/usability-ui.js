// Optional operator shortcuts. Core task execution remains in the existing services.
const operatorGroups=[['todo_body','待抓正文'],['todo_extract','待提炼'],['todo_write','待生文'],['todo_push','待推送'],['done_push','已推送'],['workflow_failed','失败待处理'],['workflow_paused','已暂停'],['workflow_active','排队／执行中']];
const operatorCache=new Map();let operatorSummary=null,operatorSelectionRevision=0,scopedBodyContext=null,scopedBodyPreview=null,scopedBodyDraft=null,scopedBodyRevision=0,scopedBodyBusy=false;
let scopedPushPreview=null,scopedPushContext=null,operatorLastPush='',operatorPushRunning=false,importReceipt=null,operatorArchiveTarget='',operatorReceiptMarkup='',operatorSelectionMarkup='';
const operatorRead=(key,factory,ttl=3500)=>{const old=operatorCache.get(key);if(old&&Date.now()-old.at<ttl)return old.promise;const value={at:Date.now(),promise:factory()};operatorCache.set(key,value);value.promise.catch(()=>operatorCache.delete(key));return value.promise;};
function operatorButton(label,action,attrs='',classes='btn soft-blue'){return `<button class="${classes}" data-operator="${action}" ${attrs}>${label}</button>`;}
function workflowGroupOptions(selected){return `<optgroup label="常用节点集合">${operatorGroups.map(([key,label])=>`<option value="${key}" ${selected===key?'selected':''}>${label}</option>`).join('')}</optgroup>`;}
function materialNextButton(x){
 const node=x.workflow_node;let label='',action='';
 if(['body_pending','body_failed','body_truncated'].includes(node)){label='获取正文';action='next-body';}
 else if(['extract_pending','extract_failed','no_topics'].includes(node)){label='提炼并生文';action='next-generate';}
 else if(['write_pending','write_partial','write_failed'].includes(node)){label=node==='write_failed'?'查看失败写文':'继续生文';action='next-write';}
 else if(['push_pending','push_partial','push_failed'].includes(node)){label='推送文章';action='next-push';}
 else if(['push_blocked','pushed','outputs_archived'].includes(node)){label='查看成品';action='next-results';}
 else if(node==='body_paused'){label='继续原抓取';action='body-jobs';}
 else if(['extract_paused','write_paused'].includes(node)){label='查看原任务';action='model-jobs';}
 return action?operatorButton(label,action,`data-id="${x.id}"`,'btn small soft-blue next-step-button'):'';
}
function operatorProgress(summary){return `<section class="operator-progress panel" id="operator-progress"><div class="operator-section-title"><strong>素材处理进度</strong><small>全库 · 按素材计数 · 点击查看</small></div><div class="operator-steps">${summary.groups.slice(0,5).map((g,i)=>`<button data-operator="node" data-node="${g.code}" class="operator-step"><span>${i+1} · ${esc(g.label)}</span><strong>${num(g.count)}<small>条</small></strong></button>`).join('')}</div><div class="operator-exceptions">${localStorage.getItem('manliu-last-import')?operatorButton('最近导入批次 #'+localStorage.getItem('manliu-last-import'),'import-view',`data-id="${esc(localStorage.getItem('manliu-last-import'))}"`,'btn small soft-blue'):''}${summary.groups.slice(5).map(g=>operatorButton(`${g.label} ${num(g.count)}`,'node',`data-node="${g.code}"`,'btn small '+(g.code==='workflow_failed'?'soft-orange':'soft-gray'))).join('')}</div></section>`;}
async function operatorNode(code){
 if(state.page!=='materials'){await navigate('materials');catalogState.draft=catalogDefaults();}
 catalogState.draft.workflow_node=code;return catalogApply();
}
function operatorQuick(summary){return `<div class="operator-node-shortcuts" id="operator-node-shortcuts"><span>节点直达</span>${summary.groups.slice(0,6).map(g=>operatorButton(`${g.label} ${num(g.count)}`,'node',`data-node="${g.code}" aria-pressed="${catalogState.applied.workflow_node===g.code}"`,'btn small '+(catalogState.applied.workflow_node===g.code?'soft-blue is-active':'soft-blue'))).join('')}<small>数量为全库素材数；分类等条件可继续组合。</small></div>`;}
function operatorHeader(){
 const header=document.querySelector('.header-actions');if(!header||header.querySelector('.operator-more'))return;
 const more=document.createElement('details');more.className='operator-more';more.innerHTML='<summary class="btn soft-gray">更多操作</summary><div class="operator-more-menu"></div>';
 const menu=more.querySelector('div');for(const selector of ['[data-ops="background"]','[data-ops="safe-exit"]','#export-btn','[data-history-cleanup="open"]']){const b=header.querySelector(selector);if(b)menu.append(b);}
 header.append(more);
}
function operatorDensity(){document.body.classList.toggle('operator-compact',localStorage.getItem('manliu-compact')!=='false');}
function operatorDensityButton(){return operatorButton(localStorage.getItem('manliu-compact')!=='false'?'舒展显示':'紧凑显示','density','','btn small soft-gray');}
function operatorChartClass(page){return localStorage.getItem('manliu-distribution-'+page)==='true'?'operator-chart-collapsed':'';}
function operatorChartButton(page){return operatorButton(operatorChartClass(page)?'展开分布':'收起分布','chart','','text-btn');}
function operatorQuickMarkup(){return operatorSummary?operatorQuick(operatorSummary):'';}
function operatorMaterialScopeButtons(){return operatorButton('获取当前筛选正文','body-filtered','','btn small soft-teal')+operatorButton('获取勾选正文','body-selected',materialSelection.size?'':'disabled','btn small soft-teal');}
function operatorImportScopeMarkup(){return catalogState.applied.import_id?`<div id="operator-import-scope" class="operator-scope-note">正在查看导入批次 #${esc(catalogState.applied.import_id)} ${operatorButton('清除此批次限制','clear-import','','text-btn')}</div>`:'';}
function operatorPushButtonMarkup(){return operatorButton('推送筛选内未推送','push-filtered',resultView.visibility==='active'&&!pushBusy?'':'disabled','btn soft-teal');}
function operatorReceiptPanelMarkup(){return `<section id="operator-receipts" class="operator-receipts" aria-live="polite">${operatorReceiptMarkup||'<p class="hint">正在读取推送接收结果…</p>'}</section>`;}
function operatorSelectionPanelMarkup(){return `<div id="operator-selection-scope" class="operator-selection-scope" aria-live="polite">${operatorSelectionMarkup||'正在核对勾选范围…'}</div>`;}
function operatorResultSourceMarkup(){return resultView.material_id?`<div id="operator-result-source" class="operator-scope-note">来源素材 #${esc(resultView.material_id)} ${operatorButton('清除素材限制','clear-result-material','','text-btn')}</div>`:'';}
const beforeOperatorOverview=overview;
overview=function(){return (operatorSummary?operatorProgress(operatorSummary):'')+beforeOperatorOverview();};

function materialScopeLabel(context){return context.label||(context.scope==='selected'?`勾选的 ${context.ids.length} 条素材`:context.scope==='all'?'全库待抓正文素材':'当前素材库筛选');}
async function showScopedBody(context){
 scopedBodyContext=JSON.parse(JSON.stringify(context));scopedBodyPreview=null;scopedBodyDraft=null;scopedBodyBusy=false;scopedBodyRevision++;
 const settings=await api('/settings');
 modal(`<header><div><h2>获取指定范围正文</h2><p>${esc(materialScopeLabel(context))}；本入口只抓正文及验收去重。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="field"><label for="scoped-body-limit">本次最多抓取条数</label><input id="scoped-body-limit" type="number" min="1" max="10000" value="${context.scope==='selected'?Math.min(context.ids.length,settings.body_run_size||100):settings.body_run_size||100}"></div><p class="hint">已有正文、失效链接、纯视频、正在抓取的素材按现有规则跳过。不会从范围外补足数量。</p><div id="scoped-body-preview" aria-live="polite"></div><div class="modal-actions">${operatorButton('重新核对范围','body-preview','','btn soft-blue')}${operatorButton('正在核对…','body-confirm','disabled','btn primary')}</div>`,false);
 await refreshScopedBody();
}
async function refreshScopedBody(){
 if(scopedBodyBusy||!document.querySelector('#scoped-body-limit'))return;
 const revision=++scopedBodyRevision,button=document.querySelector('[data-operator="body-confirm"]'),target=document.querySelector('#scoped-body-preview');button.disabled=true;scopedBodyPreview=null;
 const draft={...scopedBodyContext,limit:Number(document.querySelector('#scoped-body-limit').value)};target.innerHTML='<p class="hint">正在按当前范围核对可抓取素材…</p>';
 try{
  const value=await api('/body/scoped-preview',draft);if(revision!==scopedBodyRevision||!target.isConnected)return;
  scopedBodyPreview=value;scopedBodyDraft=draft;
  target.innerHTML=`<div class="callout">本次实际抓取 <strong>${value.total} 条</strong> · 浏览器 ${value.engine.workers} 路 · 字数上限 ${value.engine.max_chars||'不限'}</div>${value.active?'<p class="operator-warning">已有正文任务正在运行，请完成或暂停原任务后再开始。</p>':!value.engine.available?`<p class="operator-warning">${esc(value.engine.message)}</p>`:!value.total?'<p class="hint">此范围暂无可抓取素材。正在执行的素材不会重复领取。</p>':''}<div class="execution-list">${value.rows.map(x=>`<div><b>#${x.id}</b><span>${esc(x.title)}</span><small>${esc(x.category)}</small></div>`).join('')}</div>`;
  button.disabled=!value.total||value.active||!value.engine.available;button.textContent=value.total?`确认抓取 ${value.total} 条`:'没有可抓取素材';
 }catch(e){if(revision===scopedBodyRevision&&target.isConnected){target.innerHTML=`<p class="operator-warning">${esc(e.message)}</p>`;button.textContent='暂不可执行';}}
}
async function confirmScopedBody(button){
 if(scopedBodyBusy||!scopedBodyPreview)return;
 if(Number(document.querySelector('#scoped-body-limit').value)!==scopedBodyDraft.limit)return refreshScopedBody();
 scopedBodyBusy=true;button.disabled=true;button.textContent='正在提交…';
 try{const result=await api('/body/scoped-start',{id:scopedBodyPreview.id});closeModal();operatorCache.clear();toast(`已开始抓取 ${result.total} 条，范围外素材保留`);await refresh();await navigate('bodies');}
 finally{scopedBodyBusy=false;if(button.isConnected){button.disabled=false;button.textContent='重新核对后执行';}}
}
async function showImportReceipt(result){
 try{
  const value=await api('/materials/import-summary?id='+result.import_id);importReceipt=value;localStorage.setItem('manliu-last-import',String(value.id));operatorCache.clear();
  modal(`<header><div><h2>本次素材已入库</h2><p>${esc(value.file)} · 导入批次 #${value.id}</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="operator-receipt-grid"><div><strong>${num(value.added)}</strong><span>初始接收素材</span></div><div><strong>${num(value.total)}</strong><span>当前关联素材</span></div><div><strong>${num(value.duplicates_at_import)}</strong><span>导入时重复合并</span></div><div><strong>${num(value.counts.body_pending||0)}</strong><span>当前待抓正文</span></div></div><p class="hint">${result.auto_body?`系统已按原设置排队抓取 ${result.auto_body.total} 条。`:'原有自动抓取设置继续生效。'}${result.auto_body_error?'自动抓取未启动：'+esc(result.auto_body_error):''}后续仅处理本导入批次关联素材。</p><div class="modal-actions">${operatorButton('查看本批素材','import-view',`data-id="${value.id}"`)}${operatorButton('获取本批正文','import-body',`data-id="${value.id}"`,'btn soft-teal')}${operatorButton('提炼／生文本批','import-generate',`data-id="${value.id}"`,'btn primary')}</div>`,false);
 }catch(e){toast('素材已导入；批次面板暂不可用：'+e.message,true);}
}
async function openImport(iid){
 closeModal();await navigate('materials');catalogState.draft={...catalogDefaults(),import_id:String(iid)};catalogState.applied={...catalogState.draft};state.materialPage=1;catalogState.dirty=false;await render();
}
async function showScopedPush(filters,ids=null){
 if(pushBusy||operatorPushRunning)return;
 const context=ids?await api('/results/selection',{ids,filters:resultQuery()}):null;
 modal('<div class="loading">正在核对未推送文章、评分分流和目标范围…</div>');
 try{
  const value=await api('/results/scoped-push-preview',ids?{ids}:{filters});scopedPushPreview=value;scopedPushContext=context;
  modal(`<header><div><h2>${ids?'推送勾选文章':'推送当前筛选未推送文章'}</h2><p>按已配置的赛道与评分分流，沿用现有推送服务。</p></div><button class="close-btn" data-action="close-modal">×</button></header>${context?`<div class="operator-selection-scope">勾选 ${context.rows.length} 篇 · 当前筛选内 ${context.inside.length} · 筛选外 <strong>${context.outside.length}</strong> · 失效 ${context.missing.length}</div>`:''}<div class="callout">本次可推送 <strong>${value.total} 篇</strong> · 分 ${value.parts} 批，每批不超过500篇${value.skipped.length?' · 跳过'+value.skipped.length+'篇':''}</div><p class="push-target-path">接收目标：${esc(value.target)}</p><div class="operator-destinations">${Object.entries(value.categories).map(([category,n])=>`<span class="pill blue">${esc(category)} ${num(n)}篇</span>`).join('')}</div>${value.skipped.length?`<details><summary>查看跳过原因</summary><div class="execution-list">${value.skipped.slice(0,100).map(x=>`<div><b>#${x.id}</b><span>${esc(x.reason)}</span></div>`).join('')}</div></details>`:''}<p class="hint">本次范围已固定；执行时再次核对文案版本与目标。已提交的文章沿用原有回执核对和失败重试，不调用模型。</p><div class="modal-actions">${context?.outside.length?operatorButton(`只推送当前筛选内 ${context.inside.length} 篇`,'push-inside',context.inside.length?'':'disabled','btn soft-blue'):''}${operatorButton(`确认推送 ${value.total} 篇`,'push-confirm',value.total?'':'disabled','btn primary')}</div>`,false);
 }catch(e){closeModal();throw e;}
}
function scopedPushProgressHtml(value){return `<div class="operator-push-progress" id="operator-push-progress"><strong>本次已核对提交 ${value.submitted}/${value.total} 篇</strong><div class="operator-receipt-grid"><div><strong>${value.pushed}</strong><span>已送达</span></div><div><strong>${value.pending}</strong><span>等待接收</span></div><div><strong>${value.failed}</strong><span>投递失败</span></div><div><strong>${value.remaining}</strong><span>尚未提交</span></div></div>${value.skipped.length?`<p class="hint">另有 ${value.skipped.length} 篇在提交时发生变化，已跳过。</p>`:''}<p class="hint">${value.remaining?'正在按固定范围逐批提交。':'全部提交结束；仍在等待的回执由原推送服务继续核对。'}</p></div>`;}
async function runScopedPush(id){
 if(pushBusy||operatorPushRunning)return;operatorPushRunning=true;pushBusy=true;pushOperation='send';operatorLastPush=id;localStorage.setItem('manliu-last-scoped-push',id);updatePushControls();
 modal(`<header><div><h2>推送提交与接收情况</h2><p>提交进度与实际送达分别显示。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div id="operator-push-progress"><p>正在提交…</p></div>`,false);
 try{
  let progress=await api('/results/scoped-push-progress?id='+id);
  while(progress.remaining){
   progress=await api('/results/scoped-push-submit',{id,cursor:progress.submitted});
   const target=document.querySelector('#operator-push-progress');if(target)target.outerHTML=scopedPushProgressHtml(progress);
  }
  operatorCache.clear();toast(`提交结束：已送达 ${progress.pushed}，等待 ${progress.pending}，失败 ${progress.failed}，跳过 ${progress.skipped.length}`);await refresh();
 }catch(e){const target=document.querySelector('#operator-push-progress');if(target)target.insertAdjacentHTML('beforeend',`<p class="operator-warning">${esc(e.message)}</p>${operatorButton('继续未提交的推送','push-resume',`data-id="${esc(id)}"`,'btn soft-orange')}`);throw e;}
 finally{operatorPushRunning=false;pushBusy=false;pushOperation='';updatePushControls();}
}
async function refreshReceiptPanel(){
 const root=document.querySelector('#operator-receipts');if(!root)return;
 try{
  const data=await operatorRead('push-summary',()=>api('/results/push-summary'));
  const saved=operatorLastPush||localStorage.getItem('manliu-last-scoped-push');let value=null;
  if(saved){try{value=await operatorRead('push-'+saved,()=>api('/results/scoped-push-progress?id='+saved));}catch{localStorage.removeItem('manliu-last-scoped-push');}}
  if(!root.isConnected||state.page!=='results')return;
  const latest=data.latest,counts=latest?.counts||{};if(value&&!value.remaining&&(value.target!==data.target||(latest&&!value.batches.includes(latest.id))))value=null;
  root.innerHTML=operatorReceiptMarkup=`<div><strong>推送接收结果</strong><small>${value?'最近一次范围推送':'最近投递批次'}</small></div><div class="operator-receipt-totals"><span>已送达 <b>${value?.pushed??counts.pushed??0}</b></span><span>等待接收 <b>${value?.pending??counts.pending??0}</b></span><span>失败 <b>${value?.failed??counts.failed??0}</b></span>${value?.remaining?`<span>未提交 <b>${value.remaining}</b></span>`:''}</div><p class="push-target-path">目标：${esc(value?.target||data.target)}</p><div class="pipeline-actions">${operatorButton('核对最新回执','receipt-refresh','','btn small soft-blue')}${latest?`<button class="btn small soft-gray" data-push-flow="detail" data-id="${esc(latest.id)}">查看投递明细</button>`:''}${value?.remaining||data.unfinished?.remaining?operatorButton('继续未提交的推送','push-resume',`data-id="${esc(value?.remaining?value.id:data.unfinished.id)}"`,'btn small soft-orange'):''}<button class="btn small soft-orange" data-push-flow="retry">重试失败／超时</button></div>`;
 }catch(e){if(root.isConnected)root.innerHTML=`<p class="hint">接收统计暂不可用：${esc(e.message)}</p>${operatorButton('刷新接收统计','receipt-refresh')}`;}
}
async function showSelectionScope(){
 if(state.page!=='results')return;const target=document.querySelector('#operator-selection-scope');if(!target)return;
 const ids=[...pushSelection],revision=++operatorSelectionRevision;
 if(!ids.length){target.textContent=operatorSelectionMarkup='未勾选文章。勾选本页、勾选筛选全部和推送筛选未推送文章分别独立。';return;}
 if(ids.length>500){target.textContent=`已选 ${ids.length} 篇；勾选推送单次最多500篇，可使用“推送筛选内未推送”分批提交。`;return;}
 try{const key=JSON.stringify(['selection',ids,resultQuery()]),r=await operatorRead(key,()=>api('/results/selection',{ids,filters:resultQuery()}),2000);if(revision!==operatorSelectionRevision||!target.isConnected)return;target.innerHTML=operatorSelectionMarkup=`已选 <b>${ids.length}</b> 篇 · 当前筛选内 ${r.inside.length} · <span class="${r.outside.length?'operator-warning':''}">筛选外 ${r.outside.length}</span> · 失效 ${r.missing.length} <button class="text-btn" data-ops="selection-list">查看勾选范围</button>`;}catch(e){if(target.isConnected)target.textContent='勾选范围暂不可用：'+e.message;}
}
const beforeOperatorRender=render;
render=async function(passive=false){
 const page=state.page;
 if(page==='overview'||page==='materials'){
  try{operatorSummary=await operatorRead('workflow',()=>api('/materials/workflow-summary',{}));}catch{}
  if(state.page!==page)return;
 }
 await beforeOperatorRender(passive);if(state.page!==page)return;operatorHeader();operatorDensity();
 if(page==='results')await Promise.allSettled([refreshReceiptPanel(),showSelectionScope()]);
};

async function operatorAction(button){
 const action=button.dataset.operator,id=Number(button.dataset.id);
 if(action==='node')return operatorNode(button.dataset.node);
 if(action==='density'){const compact=!document.body.classList.contains('operator-compact');localStorage.setItem('manliu-compact',String(compact));document.body.classList.toggle('operator-compact',compact);button.textContent=compact?'舒展显示':'紧凑显示';return render();}
 if(action==='chart'){const section=button.closest('.lane-distribution'),collapsed=!section.classList.contains('operator-chart-collapsed');localStorage.setItem('manliu-distribution-'+state.page,String(collapsed));section.classList.toggle('operator-chart-collapsed',collapsed);button.textContent=collapsed?'展开分布':'收起分布';return render();}
 if(action==='body-filtered')return showScopedBody({scope:'filtered',filters:catalogFilters()});
 if(action==='body-selected')return showScopedBody({scope:'selected',ids:[...materialSelection]});
 if(action==='next-body')return showScopedBody({scope:'selected',ids:[id],label:'素材 #'+id});
 if(action==='body-preview')return refreshScopedBody();
 if(action==='body-confirm')return confirmScopedBody(button);
 if(action==='body-jobs')return navigate('bodies');
 if(action==='model-jobs')return navigate('queue');
 if(action==='next-generate')return showStart('both','selected',[id]);
 if(action==='next-write'){
  const info=await api('/materials/pending-modes?id='+id),preferred=info.modes[state.settings.extraction_mode]?state.settings.extraction_mode:Object.keys(info.modes)[0];
  if(info.failed.length){
   modal(`<header><div><h2>重试素材 #${id} 的失败写文</h2><p>复用对应种子和现有重试功能，已成功篇目保留。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="execution-list">${info.failed.map(x=>`<div><b>#${x.id}</b><span>${esc(x.category)}</span></div>`).join('')}</div><div class="modal-actions">${operatorButton('确认重试 '+info.failed.length+' 篇','next-retry-write',`data-id="${id}"`,'btn primary')}</div>`,false);return;
  }
  if(!preferred){await navigate('writing');return toast('请在写文任务中查看失败篇目并使用现有重试入口');}
  return showStart('write','selected',[id],{extraction_mode:preferred,label:'仅生成本素材尚未完成的主题'});
 }
 if(action==='next-retry-write'){button.disabled=true;try{const current=await api('/materials/pending-modes?id='+id),ids=current.failed.map(x=>x.id);if(!ids.length){closeModal();return toast('失败篇目已更新，无需重复生成');}const r=await api('/run/retry-seeds',{ids});closeModal();toast('已提交本素材 '+ids.length+' 篇失败写文');await refresh();return navigate('queue');}finally{if(button.isConnected)button.disabled=false;}}
 if(action==='archive-confirm'){button.disabled=true;try{const r=await api('/results/clear-pushed',{expected_target:operatorArchiveTarget});r.ids.forEach(x=>pushSelection.delete(x));closeModal();operatorCache.clear();toast('已归档 '+r.count+' 篇；素材、种子和目标标题库保留');return refresh();}finally{if(button.isConnected)button.disabled=false;}}
 if(action==='next-push')return showScopedPush({material_id:id,visibility:'active'});
 if(action==='next-results'){await navigate('results');resultView.material_id=id;return render();}
 if(action==='import-view')return openImport(id);
 if(action==='import-body')return showScopedBody({scope:'filtered',filters:{import_id:id},label:'导入批次 #'+id});
 if(action==='import-generate')return showStart('both','filtered',null,{filters:{import_id:id},label:'仅处理导入批次 #'+id});
 if(action==='clear-import'){catalogState.draft.import_id='';catalogState.applied.import_id='';return render();}
 if(action==='clear-result-material'){delete resultView.material_id;return render();}
 if(action==='push-filtered')return showScopedPush(resultQuery());
 if(action==='push-inside')return showScopedPush({},scopedPushContext.inside);
 if(action==='push-confirm')return runScopedPush(scopedPushPreview.id);
 if(action==='push-resume')return runScopedPush(button.dataset.id);
 if(action==='receipt-refresh'){await api('/results/push-sync',{});operatorCache.clear();await refreshReceiptPanel();return refresh();}
}
async function showArchiveConfirm(){
 const value=await api('/results/push-summary');operatorArchiveTarget=value.target;
 modal(`<header><div><h2>归档全部已推送成品</h2><p>覆盖所有分页和筛选，仅处理已确认送达的当前版本。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="callout">当前可归档 ${pushClearable} 篇。确认时按最新回执核对；归档前沿用原逻辑自动备份，素材、种子、评分和外部标题库保留。可在“文章位置 → 已归档”恢复。</div><p class="push-target-path">只归档已送达此目标的成品：${esc(value.target)}</p><div class="modal-actions">${operatorButton('确认归档已推送成品','archive-confirm','','btn soft-orange')}</div>`,false);
}
window.addEventListener('click',event=>{
 for(const menu of document.querySelectorAll('.operator-more[open],.operator-article-more[open]'))if(!menu.contains(event.target))menu.open=false;
 const button=event.target.closest('[data-operator]');if(button){event.preventDefault();event.stopImmediatePropagation();if(button.disabled)return;operatorAction(button).catch(e=>toast(e.message,true));return;}
 const archive=event.target.closest('[data-push-action="cleanup"]');if(archive&&!archive.disabled&&!pushBusy){event.preventDefault();event.stopImmediatePropagation();showArchiveConfirm().catch(e=>toast(e.message,true));return;}
 const push=event.target.closest('[data-push-action="send"]');if(push&&!pushBusy){event.preventDefault();event.stopImmediatePropagation();showScopedPush({},[...pushSelection]).catch(e=>toast(e.message,true));return;}
 if(event.target.closest('#body-btn')&&state.page==='materials'){event.preventDefault();event.stopImmediatePropagation();const context=materialSelection.size?{scope:'selected',ids:[...materialSelection]}:{scope:'filtered',filters:catalogFilters()};showScopedBody(context).catch(e=>toast(e.message,true));}
},true);
document.addEventListener('input',event=>{if(event.target.id==='scoped-body-limit')refreshScopedBody().catch(e=>toast(e.message,true));});
