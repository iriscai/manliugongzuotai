// Scores describe the exact current published text; ordinary lanes use a labeled default.
function qualityCell(x){
 const pending=x.score===null||x.score===undefined;
 return `<span class="pill ${pending?'amber':x.score>=90?'green':x.score>=80?'blue':''}">${pending?'待评分':x.score+'分'}</span><small>${x.category==='搞笑'?'模型语义评分 / 可复核':'默认分 · 未做质量评价'}</small><small class="quality-target">${esc(x.push_category?'→ '+x.push_category:x.push_block_reason||'暂不推送')}</small>${x.category==='搞笑'?`<button class="text-btn" data-quality-action="detail" data-id="${x.id}">评分明细 / 复核</button>`:''}`;
}
const beforeQualityDraw=drawArticle;
drawArticle=function(){
 beforeQualityDraw();const x=articleDetail,body=document.querySelector('.article-drawer .drawer-content');if(!x||!body)return;
 let q={};try{q=JSON.parse(x.score_json||'{}');}catch{}
 body.insertAdjacentHTML('beforeend',`<details class="quality-details"><summary>作品评分与推送分类 · ${x.score===null?'待评分':x.score+'分'}</summary>${qualityCell(x)}${x.category==='搞笑'?`<p class="hint">完整性、反转、趣味性等权平均四舍五入；发布文本含数字字符时加5分，封顶100。评分只适用于当前标题与正文，不是读者实测。</p>${q.reason?`<p>${esc(q.reason)}</p><p class="muted">基础 ${q.base_total} + 数字 ${q.number_bonus} = ${q.final_total} · ${esc(q.final_tier)} · ${esc(q.evaluator||'')}</p>`:''}${q.error?`<p class="danger">${esc(q.error)}</p>`:''}<div class="quality-inputs">${[['completeness','故事完整性'],['reversal','反转程度'],['fun','趣味性']].map(([k,t])=>`<label>${t}<input type="number" min="0" max="100" data-grade="${k}" value="${q[k]??''}"></label>`).join('')}</div><label class="field">具体评分理由<textarea data-grade="reason">${esc(q.reason||'')}</textarea></label><label class="field">原句证据 · 每行一条，1—3条<textarea data-grade="evidence">${esc((q.evidence||[]).join('\n'))}</textarea></label><label class="field">风险或扣分问题 · 每行一条<textarea data-grade="risks">${esc((q.risks||[]).join('\n'))}</textarea></label><button class="btn small" data-quality-action="save-grade">保存复核评分</button>`:'<p class="hint">此赛道无评分规则，默认60分，按对应分类推送。</p>'}</details>`);
};
let pushMappingConfig=null;
function scoreRoutingRow(r){return `<tr data-score-rule><td><input type="checkbox" data-score-enabled aria-label="启用评分区间" ${r.enabled?'checked':''}></td><td><input type="number" data-score-min aria-label="最低分" min="0" max="100" step="1" value="${r.min_score}"></td><td><input type="number" data-score-max aria-label="最高分" min="0" max="100" step="1" value="${r.max_score}"></td><td><input data-score-target aria-label="评分目标分类" list="push-category-choices" maxlength="80" placeholder="选择或填写目标分类" value="${esc(r.target)}"></td><td><button class="text-btn danger" data-quality-action="remove-score-rule">删除</button></td></tr>`;}
function updateScoreRoutingEmpty(){const hint=document.querySelector('#score-routing-empty');if(hint)hint.hidden=!!document.querySelector('[data-score-rule]');}
async function openPushMapping(){
 const data=await api('/results/push-mapping');pushMappingConfig=data;
 modal(`<header><div><h2>推送匹配与评分分流</h2><p>在这里自定义评分区间和目标分类，保存后用于后续推送。</p></div><button class="close-btn" data-action="close-modal">×</button></header><datalist id="push-category-choices">${data.target_categories.map(c=>`<option value="${esc(c)}">`).join('')}</datalist><section class="score-route-editor"><div class="score-route-heading"><h3>搞笑赛道 · 按评分分流</h3><span>区间包含最低分、最高分</span></div><p class="hint">可配置96—100分到精品、90—95分到优秀等任意区间。启用区间不能重叠；未匹配区间、未评分或评分失效的稿件暂不推送。</p><div class="table-wrap"><table class="score-route-table"><thead><tr><th>启用</th><th>最低分</th><th>最高分</th><th>推送到目标分类</th><th></th></tr></thead><tbody id="score-routing-rows">${data.score_rules.map(scoreRoutingRow).join('')}</tbody></table></div><p id="score-routing-empty" class="hint" ${data.score_rules.length?'hidden':''}>暂无评分区间，搞笑作品将暂不推送。</p><div class="score-route-actions"><button class="btn small" data-quality-action="add-score-rule">＋ 添加评分区间</button><button class="text-btn" data-quality-action="reset-score-rules">恢复默认评分分流</button></div></section><details class="ordinary-push-mapping" open><summary>其他赛道 · 分类匹配</summary><p class="hint">其他赛道仍默认60分，不套用搞笑评分区间。</p><div class="mapping-grid">${data.rows.map(r=>`<label><span>${esc(r.source)}</span><span>→</span><input data-category-source="${esc(r.source)}" list="push-category-choices" value="${esc(r.target)}" maxlength="80" aria-label="${esc(r.source)}目标分类"></label>`).join('')}</div></details><p class="hint">目标分类可选已有名称或手动填写。保存配置不会自动推送、移动历史标题或修改文章原赛道。</p><p id="push-mapping-error" class="danger" role="alert"></p><div class="modal-actions push-mapping-save"><button class="btn primary" data-quality-action="save-mapping">保存推送配置</button></div>`,false);
}
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-quality-action]');if(!b)return;e.stopImmediatePropagation();
 try{
  if(b.dataset.qualityAction==='mapping')return await openPushMapping();
  if(b.dataset.qualityAction==='add-score-rule'){document.querySelector('#score-routing-rows').insertAdjacentHTML('beforeend',scoreRoutingRow({min_score:0,max_score:79,target:'',enabled:true}));updateScoreRoutingEmpty();return;}
  if(b.dataset.qualityAction==='remove-score-rule'){b.closest('[data-score-rule]').remove();updateScoreRoutingEmpty();return;}
  if(b.dataset.qualityAction==='reset-score-rules'){document.querySelector('#score-routing-rows').innerHTML=pushMappingConfig.default_score_rules.map(scoreRoutingRow).join('');updateScoreRoutingEmpty();return;}
  if(b.dataset.qualityAction==='detail'){await openArticle(Number(b.dataset.id));const d=document.querySelector('.quality-details');if(d){d.open=true;d.scrollIntoView({block:'nearest'});}return;}
  b.disabled=true;
  if(b.dataset.qualityAction==='save-mapping'){
   const mapping=Object.fromEntries([...document.querySelectorAll('[data-category-source]')].map(x=>[x.dataset.categorySource,x.value.trim()]));
   const score_rules=[...document.querySelectorAll('[data-score-rule]')].map(row=>({min_score:row.querySelector('[data-score-min]').value.trim()===''?null:Number(row.querySelector('[data-score-min]').value),max_score:row.querySelector('[data-score-max]').value.trim()===''?null:Number(row.querySelector('[data-score-max]').value),target:row.querySelector('[data-score-target]').value.trim(),enabled:row.querySelector('[data-score-enabled]').checked}));
   await api('/results/push-mapping',{mapping,score_rules,expected_revision:pushMappingConfig.revision});document.querySelector('#modal-root').innerHTML='';await refresh();toast('评分分流与分类匹配已保存');
  }else if(b.dataset.qualityAction==='save-grade'){
   const review={};for(const x of document.querySelectorAll('[data-grade]')){const k=x.dataset.grade;review[k]=['completeness','reversal','fun'].includes(k)?(x.value.trim()===''?null:Number(x.value)):['evidence','risks'].includes(k)?x.value.split('\n').map(s=>s.trim()).filter(Boolean):x.value.trim();}
   await api('/results/score',{id:articleDetail.id,content_hash:articleDetail.content_hash,review});await openArticle(articleDetail.id);document.querySelector('.quality-details').open=true;await refresh();toast('复核评分已保存，推送分类已刷新');
  }
 }catch(error){const field=document.querySelector('#push-mapping-error');if(field)field.textContent=error.message;toast(error.message,true);}finally{b.disabled=false;}
},true);
