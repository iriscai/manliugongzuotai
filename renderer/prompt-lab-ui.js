// Editors stay mounted while progress and results refresh independently.
pages.promptlab=['提示词测试','按原赛道随机选素材，用一条写文请求测试提示词和评分。'];
icons.promptlab='<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3M8 15h8"/>';
const labUI={options:null,category:'',draft:null,source:null,sourceHash:'',history:[],plans:[],planId:null,detail:null,activeId:'',busy:false,polling:false,dirty:false,sequence:0,saveError:'',clientId:'',loaded:false};
const labRevisions=new Map(),labStates={running:'测试中',pausing:'等待响应保存',paused:'已暂停',blocked:'额度受限',failed:'测试未完成',completed:'测试完成'},labPhases={extracting:'提炼主题与元素',writing:'生成文章',scoring:'评价最终文章',completed:'已完成'};
let labSaveTimer,labSaveChain=Promise.resolve();
const labRoute=(action,q={})=>'/prompts/test/'+action+(Object.keys(q).length?'?'+new URLSearchParams(q):'');
const labPayload=()=>({...labUI.draft,material_id:labUI.source?.material_id||null,source_hash:labUI.sourceHash});
function labSaveStatus(text,error=false){const el=document.querySelector('#lab-save-status');if(el){el.textContent=text;el.classList.toggle('lab-save-error',error);}}
function labQueueSave(){
 const payload=labPayload(),sequence=labUI.sequence;labUI.dirty=false;
 labSaveChain=labSaveChain.catch(()=>{}).then(async()=>{
  const r=await api(labRoute('draft'),{...payload,revision:labRevisions.get(payload.category)??payload.revision},'PUT');labRevisions.set(payload.category,r.revision);
  if(labUI.category===payload.category){labUI.draft.revision=r.revision;labUI.saveError='';if(sequence===labUI.sequence)labSaveStatus('测试草稿已保存');}
 }).catch(error=>{if(labUI.category===payload.category){labUI.saveError=error.message;labSaveStatus('保存失败：'+error.message,true);}throw error;});
 labSaveChain.catch(()=>{});return labSaveChain;
}
function labDirty(){labUI.dirty=true;labUI.sequence++;labUI.clientId='';labSaveStatus('正在保存测试草稿…');clearTimeout(labSaveTimer);labSaveTimer=setTimeout(()=>labQueueSave().catch(()=>{}),650);labUpdateButtons();}
async function labFlush(){clearTimeout(labSaveTimer);if(labUI.dirty)await labQueueSave();else await labSaveChain;if(labUI.saveError)throw new Error(labUI.saveError);}
async function labLoad(category){
 if(labUI.draft)await labFlush();
 const [draft,history,plans]=await Promise.all([api(labRoute('draft',{category})),api(labRoute('history',{category})),api(labRoute('plans',{category}))]);
 Object.assign(labUI,{category,draft,history:history.rows,plans:plans.rows,planId:null,saveError:'',clientId:'',source:null,sourceHash:'',detail:null});labRevisions.set(category,draft.revision);localStorage.setItem('prompt-lab-category',category);
 if(draft.material_id){try{const r=await api(labRoute('material',{id:draft.material_id,category}));labUI.source=r.source;labUI.sourceHash=r.source_hash;}catch{draft.material_id=null;draft.source_hash='';}}
 if(!labUI.source&&labUI.options.categories.find(c=>c.name===category)?.count){const r=await api(labRoute('random'),{category});labUI.source=r.source;labUI.sourceHash=r.source_hash;labDirty();}
 const active=labUI.options.active,id=active?.category===category?active.id:history.rows[0]?.id;
 if(id)labUI.detail=await api(labRoute('detail',{id}));labUI.loaded=true;
}
async function labEnsure(){
 if(labUI.loaded)return;labUI.options=await api(labRoute('options'));labUI.activeId=labUI.options.active?.id||'';
 const cs=labUI.options.categories,saved=localStorage.getItem('prompt-lab-category');
 await labLoad(cs.some(c=>c.name===saved)?saved:labUI.options.active?.category||cs.find(c=>c.name==='军事'&&c.count)?.name||cs.find(c=>c.count)?.name||cs[0].name);
}
function labVersionOptions(kind){return labUI.options.prompts.filter(p=>p.category===labUI.category&&p.kind===kind).map(p=>`<option value="${esc(p.variant)}" ${p.variant===labUI.draft[kind+'_variant']?'selected':''}>${esc(p.variant)} · ${esc(p.name)}${p.enabled?'':'（正式停用，可测试）'}</option>`).join('');}
function labSource(){const s=labUI.source;return s?`<div class="lab-source-title"><span class="pill blue">素材 #${s.material_id}</span><strong>${esc(s.title)}</strong></div><div class="lab-source-meta">${esc(s.published_at||'未记录发布日期')}<span>阅读量 ${num(s.read_count)}</span><span>正文 ${num([...s.body.replace(/\s/g,'')].length)} 字</span></div><details class="lab-source-detail"><summary>展开原始正文</summary><div class="lab-source-body">${esc(s.body)}</div>${s.url?'<button class="text-btn" data-lab="open-source">打开原文 ↗</button>':''}</details>`:'<p class="lab-no-source">本赛道暂无合格正文素材。请先导入并抓取正文，再来测试。</p>';}
function labEditor(kind,title,note){const value=labUI.draft[kind+'_rule'];return `<section class="panel lab-editor"><div class="lab-editor-head"><div><h2>${title}</h2><p>${note}</p></div><span class="lab-step-number">${kind==='extract'?'01':'02'}</span></div><label class="lab-version-label"><span>参考版本</span><select id="lab-${kind}-variant" aria-label="${title}参考版本">${labVersionOptions(kind)}</select><button class="btn small soft-gray" data-lab="reset-${kind}">还原参考版</button></label><label class="lab-sr-only" for="lab-${kind}-rule">${title}编辑器</label><textarea id="lab-${kind}-rule" class="lab-rule-input" spellcheck="false" maxlength="120000">${esc(value)}</textarea><div class="lab-editor-foot"><span>直接编辑，自动保存测试草稿</span><span id="lab-${kind}-count">${num([...value].length)} 字符</span></div></section>`;}
function labCanSave(d){return d?.state==='completed'&&d.assessment&&!(d.validation||[]).length;}
function labFormalPrompt(kind){
 return labUI.options.prompts.find(p=>p.category===labUI.category&&p.kind===kind&&p.variant===labUI.draft[kind+'_variant']);
}
function labSaveTarget(){
 const plan=labUI.plans.find(p=>p.id===labUI.planId);
 if(plan)return '测试方案 · '+plan.name;
 return `正式规则 · ${labUI.category} · 写文 ${labUI.draft.write_variant}`;
}
function labUpdateButtons(){
 for(const id of ['lab-category','lab-write-variant','lab-saved-plan']){const select=document.getElementById(id);if(select)select.disabled=labUI.busy;}
 const target=document.getElementById('lab-save-target');
 if(target)target.textContent=labSaveTarget();
 for(const action of ['new-plan','save-changes']){
  const button=document.querySelector(`[data-lab="${action}"]`);
  if(button)button.disabled=labUI.busy;
 }
 const start=document.querySelector('[data-lab="start"]');
 if(start)start.disabled=labUI.busy||!!labUI.activeId||!labUI.source;
 const b=document.querySelector('[data-lab="save-plan"]');if(b)b.disabled=labUI.busy||!labCanSave(labUI.detail)||!!labUI.detail.saved_plan;
}
function labProgress(d){return `<div class="lab-progress-steps"><span class="${d.state==='completed'?'done':'current'}"><i>${d.state==='completed'?'✓':'1'}</i>写文与评分 · 同一次响应</span></div>`;}
function labResult(){
 const d=labUI.detail;if(!d)return `<section class="panel lab-first-run">${empty('准备好，试写一篇','选择赛道和素材，编辑上方规则，点击“完整测试”。')}</section>`;
 const u=d.usage||{},score=d.assessment,a=d.article,warnings=d.validation||[],elapsed=Math.max(0,d.elapsed_ms+(d.active_started_at&&['running','pausing'].includes(d.state)?Date.now()-new Date(d.active_started_at).getTime():0));
 return `<section class="panel lab-run-panel" aria-label="测试运行状态"><div class="lab-run-heading"><div><span class="pill ${d.state==='completed'?'green':['failed','blocked'].includes(d.state)?'red':'blue'}">${labStates[d.state]||d.state}</span><span class="lab-run-id">${esc(d.id)} · 素材 #${d.material_id} · ${esc(d.provider==='api'?'中转API':'本机Codex')} / ${esc(d.model)}</span></div><div class="lab-run-buttons">${['running','pausing'].includes(d.state)?`<button class="btn small soft-orange" data-lab="pause" ${d.state==='pausing'?'disabled':''}>保存后暂停</button>`:''}${['failed','blocked','paused'].includes(d.state)?'<button class="btn small soft-blue" data-lab="resume">继续未完成步骤</button>':''}<button class="btn small" data-lab="load-record">载入本次规则</button></div></div>${labProgress(d)}<div class="lab-usage"><span>实际请求 <b>${num(u.requests)}</b> 次</span><span>已报告 <b>${num(u.total_tokens)}</b> Tokens${u.unknown_usage?' · '+u.unknown_usage+' 次未报告':''}</span><span>有效执行 <b>${(elapsed/1000).toFixed(1)}</b> 秒</span></div><p class="lab-run-note">按点击执行时的规则快照运行；继续步骤沿用这次快照。上方可继续编辑，为下一次测试准备。</p>${d.error?`<div class="lab-error" role="alert">${esc(d.error)}</div>`:''}${warnings.length?`<div class="lab-warning"><strong>格式校验待调整，草稿已保留</strong>${warnings.map(w=>`<p>${esc(w)}</p>`).join('')}</div>`:''}</section>
 <div class="lab-output-grid"><section class="panel lab-article-panel"><div class="lab-result-heading"><h2>生成文章</h2>${a?'<button class="btn small" data-lab="copy-article">复制文案</button>':''}</div>${a?`<h3 class="lab-article-title">${esc(a.title)}</h3><div class="lab-article ${d.category==='军事'&&['C','D','E','F','G'].includes(d.draft.write_variant)?'lab-military-article':''}">${esc(a.article)}</div><p class="lab-article-metrics">标题 ${a.title_chars} 字符 · 正文 ${a.char_count} 字符</p>`:'<p class="lab-output-placeholder">生成后在这里预览完整标题与正文。</p>'}${d.response?`<details class="lab-response"><summary>查看实际响应与修订记录</summary><pre>${esc(JSON.stringify(d.response,null,2))}</pre></details>`:''}</section>
 <section class="panel lab-score-panel"><div class="lab-result-heading"><h2>测试评分</h2><span class="lab-score-note">模型评价</span></div>${score?`<div class="lab-score-total"><strong>${score.final_total}</strong><div><span>/ 100</span><b>${esc(score.final_tier)}</b></div></div><div class="lab-dimensions">${(score.dimensions||[]).map(v=>`<div class="lab-dimension"><div><span>${esc(v.name)}</span><b>${v.score}</b></div><div class="lab-dimension-track"><i style="width:${Number(v.score)}%"></i></div></div>`).join('')}</div>${score.number_bonus?`<p class="lab-score-note">搞笑基础分 ${score.base_total} + 数字加分 ${score.number_bonus}，封顶100。</p>`:''}<p class="lab-score-reason">${esc(score.reason)}</p>${(score.evidence||[]).map(q=>`<blockquote class="lab-score-evidence">${esc(q)}</blockquote>`).join('')}${score.risks?.length?`<ul class="lab-score-risks">${score.risks.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>`:''}<p class="lab-score-note">${esc(score.method)} · 仅评价本次终稿${d.category!=='搞笑'?'；事实一致性依据输入资料':''}</p>`:'<p class="lab-output-placeholder">文章生成后展示维度分、理由与问题。</p>'}<div class="lab-plan-save"><button class="btn primary" data-lab="save-plan" ${!labCanSave(d)||d.saved_plan?'disabled':''}>${d.saved_plan?'方案已保存':'一键保存为新方案'}</button><p>${d.saved_plan?esc(d.saved_plan.name):'保存本次通过测试的写文提示词，之后从“编辑对象”再次载入。'}</p></div></section></div>`;
}
function labHistory(){return `<section class="panel lab-history-panel"><div class="lab-result-heading"><h2>最近测试 <small>${esc(labUI.category)} · 最近30次</small></h2><button class="btn small" data-lab="refresh">刷新记录</button></div>${labUI.history.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>时间 / 素材</th><th>生成标题</th><th>状态</th><th>评分</th><th></th></tr></thead><tbody>${labUI.history.map(r=>`<tr class="${labUI.detail?.id===r.id?'lab-selected-row':''}"><td>${esc(shortTime(r.created_at))}<small>#${r.material_id}</small></td><td class="lab-history-title">${esc(r.title||labPhases[r.phase])}</td><td>${esc(labStates[r.state]||r.state)}</td><td><b>${r.score??'—'}</b></td><td><button class="btn small" data-lab="record" data-id="${esc(r.id)}">查看</button></td></tr>`).join('')}</tbody></table></div>`:'<p class="lab-output-placeholder">本赛道暂无测试记录。</p>'}</section>`;}
function labPlanOptions(){
 const plans=labUI.plans.map(p=>`<option value="${p.id}" ${p.id===labUI.planId?'selected':''}>${esc(p.name)}</option>`).join('');
 return '<option value="">编辑正式版本</option>'+(plans?`<optgroup label="已保存方案">${plans}</optgroup>`:'');
}
function labPlanToolbar(){
 return `<div class="lab-plan-toolbar"><span>保存目标 <strong id="lab-save-target">${esc(labSaveTarget())}</strong></span><div><button class="btn" data-lab="new-plan">新增方案</button><button class="btn primary" data-lab="save-changes">保存修改</button></div></div>`;
}
async function labReloadPlans(){
 labUI.plans=(await api(labRoute('plans',{category:labUI.category}))).rows;
 const select=document.querySelector('#lab-saved-plan');
 if(select)select.innerHTML=labPlanOptions();
}
function labShowSaveDialog(action){
 const create=action==='new-plan';
 const name=create?`<div class="field"><label for="lab-plan-name">方案名称</label><input id="lab-plan-name" maxlength="120" value="${esc(labUI.category+' '+labUI.draft.write_variant+' 新方案')}"></div>`:'';
 const description=create?'使用编辑框中的写文提示词和补充要求创建测试方案。':`将编辑框中的写文提示词保存到 ${labSaveTarget()}，后续正式任务可使用这份修改。`;
 modal(`<header><div><h2>${create?'新增方案':'保存正式规则修改'}</h2><p>${esc(description)}</p></div></header>${name}<div class="modal-actions"><button class="btn" data-action="close-modal">取消</button><button class="btn primary" data-lab="${create?'confirm-new-plan':'confirm-save-formal'}">${create?'新增方案':'保存修改'}</button></div>`,true);
 if(create)document.querySelector('#lab-plan-name').select();
}
function labMarkup(){const l=labUI;return `<div class="prompt-lab"><section class="panel lab-control-panel"><div class="lab-controls"><label><span>测试赛道</span><select id="lab-category" aria-label="测试赛道">${l.options.categories.map(c=>`<option value="${esc(c.name)}" ${c.name===l.category?'selected':''}>${esc(c.name)} · ${num(c.count)}条合格素材</option>`).join('')}</select></label><label class="lab-plan-selector"><span>编辑对象</span><select id="lab-saved-plan" aria-label="编辑对象">${labPlanOptions()}</select></label><button class="btn soft-blue" data-lab="random">随机换一条</button><span class="lab-scope-badge">单条 · 同赛道</span></div>${labPlanToolbar()}<div id="lab-source">${labSource()}</div></section><div class="lab-editors lab-write-only">${labEditor('write','写文提示词','直接阅读原文，按素材原赛道生成一篇文章')}</div><section class="panel lab-execute-panel"><label class="lab-requirements"><span>本次补充要求 <small>可选</small></span><textarea id="lab-requirements" rows="2" maxlength="12000" placeholder="例如：结尾更自然，保留原标题的核心信息…">${esc(l.draft.requirements)}</textarea></label><div class="lab-execute-bottom"><div><span id="lab-save-status">${l.dirty?'正在保存测试草稿…':'测试草稿已保存'}</span><p>使用执行设置中的 ${esc(l.options.provider==='api'?'中转API':'本机Codex')} · ${esc(l.options.model)}。写文与评分在同一次响应中完成。请求失败后的重试单独计数。</p></div><div class="lab-execute-buttons"><button class="btn primary" data-lab="start" ${!l.source||l.activeId?'disabled':''}>完整测试</button></div></div></section><div id="lab-live-result">${labResult()}</div><div id="lab-history">${labHistory()}</div></div>`;}
function labDrawResult(){if(state.page!=='promptlab')return;const el=document.querySelector('#lab-live-result');if(el)el.innerHTML=labResult();labUpdateButtons();}
async function labRefreshHistory(){const category=labUI.category,r=await api(labRoute('history',{category}));if(category!==labUI.category)return;labUI.history=r.rows;const el=document.querySelector('#lab-history');if(el)el.innerHTML=labHistory();}
async function labPoll(){
 if(!labUI.loaded||labUI.polling||state.page!=='promptlab')return;labUI.polling=true;
 try{const selected=labUI.detail?.id,id=labUI.activeId||selected;if(!id)return;const d=await api(labRoute('detail',{id}));
  if(labUI.activeId===id&&!['running','pausing'].includes(d.state)){labUI.activeId='';await labRefreshHistory();}
  if((!selected||selected===id)&&d.category===labUI.category){labUI.detail=d;labDrawResult();}labUpdateButtons();
 }finally{labUI.polling=false;}
}
function labReloadEditors(){for(const kind of ['write']){document.querySelector('#lab-'+kind+'-rule').value=labUI.draft[kind+'_rule'];document.querySelector('#lab-'+kind+'-variant').value=labUI.draft[kind+'_variant'];document.querySelector('#lab-'+kind+'-count').textContent=num([...labUI.draft[kind+'_rule']].length)+' 字符';}document.querySelector('#lab-requirements').value=labUI.draft.requirements;labDirty();}
async function labAction(button){
 if(button.disabled||labUI.busy)return;const action=button.dataset.lab,l=labUI;l.busy=true;button.disabled=true;labUpdateButtons();
 try{
  if(action==='random'){const r=await api(labRoute('random'),{category:l.category,exclude_id:l.source?.material_id});l.source=r.source;l.sourceHash=r.source_hash;document.querySelector('#lab-source').innerHTML=labSource();labDirty();}
  else if(action==='start'){const payload={...labPayload(),client_id:l.clientId||crypto.randomUUID()};l.clientId=payload.client_id;await labFlush();const r=await api(labRoute('start'),payload);l.activeId=r.id;l.detail=await api(labRoute('detail',{id:r.id}));l.clientId='';labDrawResult();await labRefreshHistory();}
  else if(action==='pause'){const r=await api(labRoute('pause'),{id:l.detail.id});toast(r.message);await labPoll();}
  else if(action==='resume'){const r=await api(labRoute('resume'),{id:l.detail.id});l.activeId=r.id;await labPoll();}
  else if(action==='record'){l.detail=await api(labRoute('detail',{id:button.dataset.id}));labDrawResult();await labRefreshHistory();document.querySelector('#lab-live-result').scrollIntoView({block:'start'});}
  else if(action==='refresh'){await labPoll();await labRefreshHistory();}
  else if(action==='load-record'){const d=l.detail;l.draft={...d.draft,revision:labRevisions.get(l.category)};l.source=d.source;l.sourceHash=d.source_hash;l.planId=null;document.querySelector('#lab-saved-plan').value='';document.querySelector('#lab-source').innerHTML=labSource();labReloadEditors();toast('已载入本次测试实际使用的规则和素材');}
  else if(action==='new-plan'||action==='save-changes'&&!l.planId)labShowSaveDialog(action);
  else if(action==='confirm-new-plan'){
   const name=document.querySelector('#lab-plan-name').value.trim();
   const result=await api(labRoute('plans'),{...labPayload(),name});
   l.planId=result.id;closeModal();await labReloadPlans();toast('已新增方案「'+result.name+'」');
  }
  else if(action==='save-changes'){
   const plan=l.plans.find(p=>p.id===l.planId);
   if(!plan)throw new Error('请重新选择要编辑的测试方案');
   const result=await api(labRoute('plans'),{...labPayload(),plan_id:plan.id,plan_revision:plan.revision},'PUT');
   await labReloadPlans();
   if(l.detail?.saved_plan?.id===plan.id)await labPoll();
   toast('已保存「'+result.name+'」的修改');
  }
  else if(action==='confirm-save-formal'){
   const formal_revision=labFormalPrompt('write').revision;
   await api(labRoute('formal'),{...labPayload(),formal_revision},'PUT');
   closeModal();state.prompts=await api('/prompts');l.options.prompts=state.prompts;
   toast('已保存到'+labSaveTarget());
  }
  else if(action==='save-plan'){const r=await api(labRoute('save-plan'),{id:l.detail.id});l.detail.saved_plan={id:r.id,name:r.name};await labReloadPlans();labDrawResult();toast('方案已保存，可从“已保存方案”载入');}
  else if(action==='copy-article'){await navigator.clipboard.writeText(l.detail.article.title+'\n\n'+l.detail.article.article);toast('测试文章已复制');}
  else if(action==='open-source')await window.desktop.openExternal(l.source.url);
  else if(action.startsWith('reset-')){const kind=action.slice(6),p=l.options.prompts.find(p=>p.category===l.category&&p.kind===kind&&p.variant===l.draft[kind+'_variant']);l.draft[kind+'_rule']=p.content;labReloadEditors();}
 }finally{l.busy=false;if(button.isConnected)button.disabled=false;labUpdateButtons();}
}
const beforeLabRender=render;
render=async function(...args){if(state.page!=='promptlab')return beforeLabRender(...args);const rev=++renderRevision;await labEnsure();if(state.page==='promptlab'&&rev===renderRevision){document.querySelector('#content').innerHTML=labMarkup();labUpdateButtons();}};
const beforeLabNavigate=navigate;
navigate=async function(page){if(state.page==='promptlab'&&labUI.loaded)await labFlush();if(page==='promptlab'){labUI.options=await api(labRoute('options'));labUI.activeId=labUI.options.active?.id||'';}return beforeLabNavigate(page);};
const beforeLabRefresh=refresh;
refresh=async function(...args){await beforeLabRefresh(...args);if(state.page==='promptlab')await labPoll();};
document.addEventListener('input',event=>{const id=event.target.id;if(!['lab-write-rule','lab-requirements'].includes(id))return;const key=id==='lab-requirements'?'requirements':id.slice(4).replaceAll('-','_');labUI.draft[key]=event.target.value;const count=document.querySelector('#'+id.replace('-rule','-count'));if(count&&count!==event.target)count.textContent=num([...event.target.value].length)+' 字符';labDirty();});
document.addEventListener('change',async event=>{
 const id=event.target.id;if(!['lab-category','lab-write-variant','lab-saved-plan'].includes(id)||labUI.busy)return;labUI.busy=true;labUpdateButtons();
 try{if(id==='lab-category'){await labLoad(event.target.value);await render();}
  else if(id==='lab-saved-plan'){
   const plan=labUI.plans.find(p=>p.id===Number(event.target.value));
   labUI.planId=plan?.id||null;
   if(plan)Object.assign(labUI.draft,plan.config);
   else for(const kind of ['write'])labUI.draft[kind+'_rule']=labFormalPrompt(kind).content;
   labReloadEditors();
  }
  else{const kind='write';labUI.draft[kind+'_variant']=event.target.value;const p=labUI.options.prompts.find(p=>p.category===labUI.category&&p.kind===kind&&p.variant===event.target.value);labUI.draft[kind+'_rule']=p.content;labReloadEditors();}
 }catch(error){toast(error.message,true);}finally{labUI.busy=false;labUpdateButtons();}
});
document.addEventListener('click',event=>{const b=event.target.closest('[data-lab]');if(b){event.preventDefault();labAction(b).catch(e=>toast(e.message,true));}});
