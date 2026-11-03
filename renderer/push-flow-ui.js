let pushFlowTarget=null,pushFlowTargetAt=0,pushFlowBusy=false,pushFlowBatch=null;
const pushPhaseLabels={queued:'已保存待投递',waiting:'等待接收回执',retry_wait:'等待自动重试',failed:'重试已停止',verified:'已核对入库',missing:'目标缺失/不一致',blocked:'规则未通过'};
async function pushFlowStatus(force=false){
 if(force||!pushFlowTarget||Date.now()-pushFlowTargetAt>20000){pushFlowTarget=await api('/results/push-target');pushFlowTargetAt=Date.now();}
 return pushFlowTarget;
}
const resultsBeforePushFlow=results;
results=async function(){
 const html=await resultsBeforePushFlow(),target=await pushFlowStatus();
 const receiver=target.receiver&&Date.now()/1000-target.receiver.heartbeat<30;
 const note=target.error||((target.matching_processes||[]).length?(receiver?'接收组件在线 · 成功后会核对实际标题库':'软件在线，尚未报告接收组件就绪；等待实际入库回执'):'生图工具未运行，推送将直接写入标题库并核对');
 const tools=`<details class="panel push-flow-panel" data-preserve-live><summary><strong>推送连接与记录</strong><span class="pill ${target.error?'red':receiver?'green':''}">${esc(note)}</span></summary><div class="operator-connection-details"><p class="push-target-path" title="${esc(target.db)}">${esc(target.db)}</p></div><div class="pipeline-actions"><button class="btn small" data-push-flow="target">目标设置</button><button class="btn small" data-push-flow="history">推送记录</button><button class="btn small" data-push-flow="sync">检查回执</button><button class="btn small" data-push-flow="retry">重试失败 / 超时</button></div></details>`;
 return tools+html;
};
async function pushFlowTargetDialog(){
 const t=await pushFlowStatus(true);
 modal(`<header><div><h2>生图工具推送目标</h2><p>目标按软件实际读取的数据库确认，版本切换后可在这里重新绑定。</p></div><button class="close-btn" data-action="close-modal">×</button></header>${t.error?`<div class="callout">${esc(t.error)}</div>`:''}<div class="field"><label for="push-target-project">生图工具的数据目录（内含 picfactory_matrix.db）</label><input id="push-target-project" value="${esc(t.project)}"><small>当前：${esc(t.db)}</small></div><h3>检测到的生图软件</h3>${t.running.length?t.running.map((r,i)=>`<div class="push-runtime-row"><div><strong>进程 ${r.pid}</strong><p>${esc(r.executable)}</p><small>实际标题库：${esc(r.db)}</small></div><button class="btn small" data-push-flow="bind-running" data-index="${i}">绑定此工具</button></div>`).join(''):'<p class="hint">当前未检测到运行中的生图工具，可填写数据目录后保存。</p>'}<p class="hint">绑定用于之后的推送；历史批次保留原目标和原始文案。需要补发时，在推送记录中选择“补发到当前目标”。</p><div class="modal-actions"><button class="btn primary" data-push-flow="save-target">保存目录</button></div>`,false);
}
async function pushFlowHistory(page=1){
 const r=await api('/results/push-history?page='+page);
 modal(`<header><div><h2>推送记录</h2><p>记录目标、接收状态和重试过程；只有核对目标标题、正文和分类后才算成功。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="table-wrap"><table class="data-table push-history-table"><thead><tr><th>时间 / 批次</th><th>目标数据库</th><th>接收情况</th><th>操作</th></tr></thead><tbody>${r.rows.map(x=>`<tr><td>${esc(x.created_at.replace('T',' '))}<small>${esc(x.id)}</small><small>${esc(x.origin)}</small></td><td class="push-target-path">${esc(x.target_path)}</td><td><span class="pill green">成功 ${x.counts.pushed||0}</span><small>等待 ${x.counts.pending||0} · 失败 ${x.counts.failed||0} · 拦截 ${x.counts.blocked||0}</small></td><td><button class="btn small" data-push-flow="detail" data-id="${esc(x.id)}">查看 / 重试</button></td></tr>`).join('')}</tbody></table></div><div class="modal-actions"><span class="hint">共${r.total}个批次 · 第${r.page}/${Math.max(1,Math.ceil(r.total/r.size))}页</span><button class="btn small" data-push-flow="history" data-page="${r.page-1}" ${r.page<=1?'disabled':''}>上一页</button><button class="btn small" data-push-flow="history" data-page="${r.page+1}" ${r.page*r.size>=r.total?'disabled':''}>下一页</button></div>`,false);
}
async function pushFlowDetail(id){
 const d=await api('/results/push-detail?id='+encodeURIComponent(id));pushFlowBatch=d;
 modal(`<header><div><h2>推送批次明细</h2><p>${esc(d.batch.created_at)} · ${esc(id)}</p></div><button class="close-btn" data-action="close-modal">×</button></header><p class="push-target-path">目标：${esc(d.batch.target_path)}</p><div class="table-wrap push-delivery-rows"><table class="data-table"><thead><tr><th>文章 / 目标分类</th><th>状态</th><th>次数 / 原因</th></tr></thead><tbody>${d.rows.map(x=>`<tr><td>#${x.result_id} ${esc(x.title||'规则拦截')}<small>${esc(x.target_category)}</small></td><td><span class="pill ${x.state==='pushed'?'green':x.state==='failed'?'red':'amber'}">${esc(pushPhaseLabels[x.phase]||pushLabel[x.state]||x.state)}</span></td><td>${x.attempts||0} 次<small>${esc(x.error||'')}</small></td></tr>`).join('')}</tbody></table></div><details><summary>执行与重试记录（最近100条）</summary>${d.events.map(x=>`<p class="hint">${esc(x.created_at)} · ${esc(x.action)} · ${esc(x.message)}</p>`).join('')}</details><div class="modal-actions"><button class="btn" data-push-flow="history">返回记录</button><button class="btn" data-push-flow="retry-batch" data-id="${esc(id)}">重试本批失败 / 等待项</button><button class="btn primary" data-push-flow="replay-dialog" data-id="${esc(id)}">补发到当前目标</button></div>`,false);
}
async function pushFlowAction(button){
 const action=button.dataset.pushFlow;if(pushFlowBusy)return;
 if(action==='target')return pushFlowTargetDialog();
 if(action==='history')return pushFlowHistory(Number(button.dataset.page)||1);
 if(action==='detail')return pushFlowDetail(button.dataset.id);
 if(action==='replay-dialog'){
  const d=await api('/results/push-detail?id='+button.dataset.id),t=await pushFlowStatus(true);pushFlowBatch=d;
  const count=d.rows.filter(x=>x.state!=='blocked').length;
  return modal(`<header><div><h2>补发 ${count} 篇到当前目标</h2><p>使用此批次保存的标题、正文和目标分类，不重新生文。</p></div><button class="close-btn" data-action="close-modal">×</button></header><p class="push-target-path">原目标：${esc(d.batch.target_path)}</p><p class="push-target-path">当前目标：${esc(t.db)}</p><div class="callout">同内容同分类会复用已有标题，不重复新增，不重置已使用或停用状态。原批次和回执会继续保留，新建补发批次便于核对。</div><div class="modal-actions"><button class="btn primary" data-push-flow="confirm-replay" data-id="${esc(button.dataset.id)}">确认补发 ${count} 篇</button></div>`,true);
 }
 pushFlowBusy=true;button.disabled=true;
 try{
  if(action==='save-target'||action==='bind-running'){
   const project=action==='bind-running'?pushFlowTarget.running[Number(button.dataset.index)].project:document.querySelector('#push-target-project').value;
   await api('/results/push-target',{project});pushFlowTargetAt=0;closeModal();toast('目标已绑定，历史批次可在推送记录中补发');await refresh();return;
  }
  if(action==='sync'){await api('/results/push-sync',{});pushFlowTargetAt=0;toast('已核对接收回执与实际标题库');await refresh();return;}
  if(action==='retry'||action==='retry-batch'){
   const r=await api('/results/push-retry',action==='retry-batch'?{id:button.dataset.id}:{});
   toast(r.batch_id?`本批已入库 ${r.pushed}，等待 ${r.pending}，失败 ${r.failed}`:`已重试 ${r.retried} 条失败/等待项`);
   if(action==='retry-batch')await pushFlowDetail(button.dataset.id);else await refresh();return;
  }
  if(action==='confirm-replay'){
   const r=await api('/results/push-replay',{id:button.dataset.id});toast(`补发批次已保存：成功 ${r.pushed}，等待 ${r.pending}，失败 ${r.failed}`);await pushFlowDetail(r.batch_id);await refresh();
  }
 }finally{pushFlowBusy=false;if(button.isConnected)button.disabled=false;}
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-push-flow]');if(!b)return;e.stopImmediatePropagation();pushFlowAction(b).catch(error=>toast(error.message,true));},true);
