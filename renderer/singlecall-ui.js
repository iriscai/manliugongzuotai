// Only funny-I results have these actual artifacts from the single response.
const beforeSinglecallDraw=drawArticle;
drawArticle=function(){
 beforeSinglecallDraw();const x=articleDetail;if(!x)return;
 let data;try{data=JSON.parse(x.data_json||'{}');}catch{return;}
 const a=data.generation_audit;if(!a||!['funny_singlecall_I_v1','funny_singlecall_J_v1'].includes(data.generation_mode))return;
 const body=document.querySelector('.article-drawer .drawer-content');if(!body)return;
 if(data.validation_audit){const v=data.validation_audit;body.insertAdjacentHTML('beforeend',`<details class="singlecall-artifacts"><summary>辅助字段格式校验记录 · ${(v.changes||[]).length}处归一 / ${(v.warnings||[]).length}项警告</summary><p class="hint">程序只归一明确的格式，未改写标题、正文、评分，也未编造短标题原因。</p><ul>${(v.changes||[]).map(x=>`<li>${esc(x.field)}：${esc(x.action)}</li>`).join('')}${(v.warnings||[]).map(x=>`<li>${esc(x.message)}</li>`).join('')}</ul></details>`);}
 if(data.recovered_response)body.insertAdjacentHTML('beforeend',`<p class="hint">已复用同来源、同规则和同模型的原失败响应；本篇未新增生文请求。原任务 #${esc(data.recovered_response.run_id)}</p>`);
 body.insertAdjacentHTML('beforeend',`${data.generation_mode==='funny_singlecall_J_v1'?`<p class="hint">J版取材：${esc(a.material_mode)} · ${esc(a.retained_core)}</p>`:''}<details class="singlecall-artifacts"><summary>单次响应内的R1/R2与T1/T2创作记录</summary><p class="hint">以下为同一次模型响应返回的稿件和简短修订摘要，不代表独立模型评审，也不表示每篇都有新增实质修改。</p>${[['初稿',a.draft,[]],['R1修订稿',a.r1_text,a.r1_notes],['R2冻结终稿',a.r2_text,a.r2_notes],['T1优化正文',a.t1_article,[]]].map(([name,text,notes])=>`<details><summary>${name}</summary>${paragraphCards(text)}<ul>${notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul></details>`).join('')}<h3>T1标题候选</h3>${a.t1_titles.map((t,i)=>`<p>${i+1} · ${[...t].length}字符${i+1===a.t1_choice?' · 选中':''}<br>${esc(t)}</p>`).join('')}<h3>T2核对摘要</h3><ul>${a.t2_notes.map(n=>`<li>${esc(n)}</li>`).join('')}</ul></details>`);
};
