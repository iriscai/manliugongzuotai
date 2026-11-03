// Additional variants and execution controls are exclusive to the funny lane.
pages.rules[1]='搞笑赛道新增独立方案J；A至I原文保留，按版本启用状态执行。';
let promptStatusFilter='all';
let lastFunnyRuleContext='';
const promptEnabled=p=>p?.enabled!==0&&p?.enabled!==false;
function unverifiedJ(p){return p?.category==='搞笑'&&p.variant==='J'&&state.settings.funny_J_validation?.status!=='approved';}
function promptStateText(p){return promptEnabled(p)?(unverifiedJ(p)?'试用已启用':'已启用'):'已停用';}
function funnyJNotice(){const j=state.settings.funny_J_validation||{},active=state.prompts.filter(p=>unverifiedJ(p)&&promptEnabled(p));return `<p class="hint"><strong>新增J版：</strong>${j.status==='approved'?'已通过当前版本试跑校验，可单独选择执行。':`${active.length?'手动试用中':'尚未通过90分验证'}${j.trial_mean!==undefined?'，最近试跑均分'+esc(j.trial_mean):''}。可以点击“试用启用J”手动测试，试用不代表质量验证通过。启用后在上方选择J并保存执行方案。`} 原A至I内容保留。</p>`;}

function funnyProfileControl(kind,label){
 const selected=state.settings['funny_'+kind+'_variant']||'follow';
 const variants=state.prompts.filter(p=>p.category==='搞笑'&&p.kind===kind);
 return `<label class="result-filter"><span>${label}</span><select id="funny-${kind}-variant" aria-label="${label}"><option value="follow" ${selected==='follow'?'selected':''}>跟随全局 A / B 设置</option>${variants.map(p=>`<option value="${esc(p.variant)}" ${selected===p.variant?'selected':''} ${promptEnabled(p)?'':'disabled'}>${p.variant} · ${esc(p.name)}${promptEnabled(p)?(unverifiedJ(p)?'（试用）':''):'（已停用）'}</option>`).join('')}</select></label>`;
}
rules=function(){
 const cats=[...new Set(state.prompts.map(p=>p.category))];
 const allVariants=state.prompts.filter(p=>p.category===state.ruleCategory&&p.kind===state.ruleKind);
 const variants=allVariants.filter(p=>promptStatusFilter==='all'||promptEnabled(p)===(promptStatusFilter==='enabled'));
 const context=state.ruleCategory+'|'+state.ruleKind;if(context!==lastFunnyRuleContext){const preferred=state.settings['funny_'+state.ruleKind+'_variant'];if(state.ruleCategory==='搞笑'&&variants.some(p=>p.variant===preferred&&promptEnabled(p)))state.ruleVariant=preferred;lastFunnyRuleContext=context;}
 if(!variants.some(p=>p.variant===state.ruleVariant))state.ruleVariant=variants[0]?.variant||'A';
 const p=variants.find(p=>p.variant===state.ruleVariant),funny=state.ruleCategory==='搞笑';
 const quality=state.settings.funny_singlecall_validation||{};
 const extra=funny?`<div class="funny-profile"><div><strong>搞笑赛道专用执行方案</strong><p>方案I把R0、R1/R2与T1/T2放在一次响应中，保存实际稿件和简短修订摘要，不另发复审请求。这里只影响搞笑赛道，新任务生效，已启动任务沿用原快照。</p><p>${quality.status==='approved'?`方案I已通过${quality.sample_count}篇试跑评分，最低${quality.min_score}分，平均${quality.mean_score}分（模型评分，含原标准数字加分）。`:'方案I尚未通过当前内容版本的90分试跑，保持停用。'}</p></div>${funnyJNotice()}<div class="funny-profile-controls">${funnyProfileControl('extract','搞笑提炼方案')}${funnyProfileControl('write','搞笑生文方案')}<button class="btn small primary" data-funny-action="save-profile">保存搞笑执行方案</button></div></div>`:'';
 return `<div class="rule-badges"><span><b>${cats.length}</b> 个分类</span><span><b>${state.prompts.filter(p=>p.kind==='extract'&&promptEnabled(p)).length}/${state.prompts.filter(p=>p.kind==='extract').length}</b> 提炼规则已启用</span><span><b>${state.prompts.filter(p=>p.kind==='write'&&promptEnabled(p)).length}/${state.prompts.filter(p=>p.kind==='write').length}</b> 改写提示词已启用</span><span>状态分别保存 · 新任务生效</span></div>
 <div class="rule-layout"><section class="panel category-list">${cats.map(c=>`<button data-rule-category="${esc(c)}" class="${c===state.ruleCategory?'active':''}">${esc(c)}<small>${state.prompts.filter(p=>p.category===c&&p.kind==='extract').length} + ${state.prompts.filter(p=>p.category===c&&p.kind==='write').length}</small></button>`).join('')}</section>
 <section class="panel rule-editor"><div class="panel-title"><h2>${esc(state.ruleCategory)} · 规则配置</h2><small>内容版本 ${p?.revision||'—'}</small></div>${extra}
 <div class="tabs"><button class="tab ${state.ruleKind==='extract'?'active':''}" data-rule-kind="extract">提炼规则</button><button class="tab ${state.ruleKind==='write'?'active':''}" data-rule-kind="write">短文改写提示词</button></div>
 ${state.ruleKind==='write'&&state.ruleCategory==='搞笑'?'<p class="hint">搞笑赛道当前规格：按完整意思自然分段，不限段数，不按段数指定图片；覆盖旧版本中的固定段数和每段一句要求。下方保留各版本原文。</p>':''}<div class="prompt-status-tools"><label class="result-filter"><span>版本状态</span><select id="prompt-status-filter" aria-label="版本状态">${[['all','全部版本'],['enabled','仅启用'],['disabled','仅停用']].map(([v,t])=>`<option value="${v}" ${promptStatusFilter===v?'selected':''}>${t}</option>`).join('')}</select></label><span>本步骤已启用 ${allVariants.filter(promptEnabled).length}/${allVariants.length} 份</span>${p?`<span class="pill ${promptEnabled(p)?'green':'amber'}" id="current-prompt-status">${promptStateText(p)}</span><button class="btn small ${promptEnabled(p)?'':'primary'}" data-prompt-status="${p.id}" data-next-enabled="${promptEnabled(p)?'false':'true'}">${promptEnabled(p)?'停用当前版本':unverifiedJ(p)?'试用启用J（未达标）':'启用当前版本'}</button>`:''}</div>
 <p class="hint">提炼与改写分别开关。停用不删除内容，不参与新任务；选定方案停用时自动使用该赛道首个启用版本。同一步骤全部停用时该赛道本步骤不可用。已启动任务沿用原状态快照。</p>
 <div class="variant-buttons">${variants.map(rule=>`<button data-rule-variant="${esc(rule.variant)}" class="${state.ruleVariant===rule.variant?'active':''} ${promptEnabled(rule)?'':'prompt-disabled'}">方案 ${esc(rule.variant)} · ${esc(rule.name)} <span class="prompt-state ${promptEnabled(rule)?'on':'off'}">${promptEnabled(rule)?'启用':'停用'}</span></button>`).join('')||'<p class="hint">当前筛选没有版本，可切换“全部版本”查看和启用。</p>'}</div>
 <textarea id="prompt-content" aria-label="当前规则全文" spellcheck="false" ${p?'':'disabled'}>${esc(p?.content||'')}</textarea><div class="editor-footer"><span>状态开关不改变内容版本，也不删除旧成果</span><div><button class="btn small" data-action="copy-rule" ${p?'':'disabled'}>复制全文</button> <button class="btn primary small" data-save-prompt="${p?.id}" ${p?'':'disabled'}>保存当前版本</button></div></div></section></div>`;
};
document.addEventListener('click',async event=>{
 const toggle=event.target.closest('[data-prompt-status]');
 if(toggle){
  toggle.disabled=true;try{const p=state.prompts.find(p=>p.id===Number(toggle.dataset.promptStatus)),enabled=toggle.dataset.nextEnabled==='true',trial=enabled&&unverifiedJ(p);await api('/prompts/status',{id:p.id,enabled,expected_enabled:promptEnabled(p),expected_revision:p.revision,trial_enable:trial});[state.prompts,state.settings]=await Promise.all([api('/prompts'),api('/settings')]);toast(trial?'J已试用启用；请在上方选择J并保存执行方案':'规则状态已保存，提炼和改写各自独立');await render();}catch(error){toast(error.message,true);}finally{if(toggle.isConnected)toggle.disabled=false;}return;
 }
 const button=event.target.closest('[data-funny-action="save-profile"]');if(!button)return;button.disabled=true;
 try{
  await api('/settings',{funny_extract_variant:document.querySelector('#funny-extract-variant').value,funny_write_variant:document.querySelector('#funny-write-variant').value});
  state.settings=await api('/settings');toast('搞笑执行方案已保存，其他赛道设置未改动');
 }catch(error){toast(error.message,true);}finally{button.disabled=false;}
});
document.addEventListener('change',async event=>{if(event.target.id==='prompt-status-filter'){promptStatusFilter=event.target.value;try{await render();}catch(error){toast(error.message,true);}}});
