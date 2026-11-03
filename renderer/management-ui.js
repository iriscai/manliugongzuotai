// Operational controls use the existing visual system and actual database records.
const resultView={push:'',rule:'',batch:'',score_band:'',date_from:'',date_to:'',visibility:'active',sort:'newest',size:30};
const ruleLabels={current:'当前规则',outdated:'规则已更新',unknown:'历史规则未标注'};
let articleDetail=null,articleTab='read',articleVersion=null,editorDirty=false,managementBusy=false;
const pageMemory=new Map();let refreshPending=false;let resultOptions=null,resultOptionsAt=0;
const editorDrafts=new Map();
Object.assign(stateLabels,{reused:'复用已有',ready:'待生成',queued:'排队中',writing:'正在生成',failed:'生成失败',blocked:'额度受限'});
pages.overview[1]='查看合格素材、提炼、生文和推送进度。';
pages.writing[1]='按真实状态查看排队、正在生成、失败和已完成文章。';
pages.results[1]='按生成文章的赛道、批次、规则和推送状态筛选，支持编辑、重生成与恢复。';
const resultQuery=()=>({...resultView,page:state.resultPage,q:state.q,category:state.category});
function selectedScope(){return {ids:[...pushSelection]};}
function managementButton(label,action,extra='',cls='btn small'){return `<button class="${cls}" data-management="${action}" ${extra}>${label}</button>`;}
function selectField(label,key,items){return `<label class="result-filter"><span>${label}</span><select data-result-filter="${key}" aria-label="${label}">${items.map(([v,t])=>`<option value="${esc(v)}" ${String(resultView[key])===String(v)?'selected':''}>${esc(t)}</option>`).join('')}</select></label>`;}
function resultCategoryOptions(categories){
 const items=[...categories];if(state.category&&!items.some(x=>x.category===state.category))items.push({category:state.category,count:0});
 return `<option value="">全部赛道（${num(categories.reduce((n,x)=>n+x.count,0))}篇）</option>`+items.map(x=>`<option value="${esc(x.category)}" ${state.category===x.category?'selected':''}>${esc(x.category||'未分类')}（${num(x.count)}篇）</option>`).join('');
}
function resultControls(options,categories){return `<section class="panel result-filters" data-preserve-live>
 ${typeof operatorResultSourceMarkup==='function'?operatorResultSourceMarkup():''}
 <label class="result-filter result-category-filter"><span>文章赛道</span><select id="category-filter" aria-label="生成文章赛道">${resultCategoryOptions(categories)}</select></label>
 ${selectField('推送状态','push',[['','全部'],['not_pushed','未推送'],['pending','等待接收'],['pushed','已推送'],['failed','推送失败']])}
 ${selectField('作品评分','score_band',[['','全部评分'],['excellent','搞笑 ≥90分'],['good','搞笑 80—89分'],['low','搞笑 <80分'],['pending','搞笑待评分（全部）'],['rescore','搞笑待重新评分'],['score_failed','搞笑评分失败'],['default','其他赛道默认60分']])}
 ${selectField('文章位置','visibility',[['active','结果库'],['cleared','已归档（'+options.cleared+'）'],['all','全部（含已归档）'],['deleted','已删除']])}
 ${managementButton('重置筛选','reset-filters')}
 <details class="operator-result-advanced"><summary>更多筛选 · 批次、规则、日期与排序${resultView.batch||resultView.rule||resultView.date_from||resultView.date_to?'（有条件已应用）':''}</summary><div>
 ${selectField('规则版本','rule',[['','全部'],['current','当前规则'],['outdated','规则已更新'],['unknown','历史规则未标注']])}
 ${selectField('生成批次','batch',[['','全部批次'],...options.batches.map(b=>[b.batch_id,shortTime(b.created_at)+' · '+b.count+'篇 · '+b.batch_id])])}
 <label class="result-filter"><span>生成日期起</span><input type="date" data-result-filter="date_from" value="${esc(resultView.date_from)}"></label><label class="result-filter"><span>至</span><input type="date" data-result-filter="date_to" value="${esc(resultView.date_to)}"></label>
 ${selectField('排序','sort',[['newest','生成时间从新到旧'],['oldest','生成时间从旧到新'],['id','编号从大到小'],['title','标题'],['score','评分从高到低']])}
 ${selectField('每页','size',[[20,'20篇'],[30,'30篇'],[50,'50篇'],[100,'100篇']])}
 </div></details></section>`;}

results=async function(){
 if(!resultOptions||Date.now()-resultOptionsAt>15000){resultOptions=await api('/results/options');resultOptionsAt=Date.now();}
 const r=await api('/results?'+new URLSearchParams(resultQuery()));state.resultPage=r.page;pushRows=r.rows;pushClearable=r.clearable_count||0;
 const all=r.rows.length&&r.rows.every(x=>pushSelection.has(x.id));
 return `<div class="toolbar"><div class="search"><span>⌕</span><input id="list-search" aria-label="搜索结果文章" placeholder="搜索标题或正文关键词" value="${esc(state.q)}"></div></div>`+resultControls(resultOptions,r.categories||[])+`<section class="panel push-tools"><div><strong>${resultView.visibility==='cleared'?'已归档文章，可恢复到结果库':'文章批量操作'}</strong><p>勾选可跨页保留。重生成仅复用所选文章的种子；新稿成功后替换，旧稿自动留存。</p></div><div class="push-buttons"><span>已选 <b>${pushSelection.size}</b> 篇</span>
 ${managementButton('勾选当前筛选全部','select-filtered',managementBusy?'disabled':'')}
 <button class="btn small" data-push-action="clear" ${pushBusy?'disabled':''}>清空勾选</button>
 ${typeof scoreSelectionControls==='function'?scoreSelectionControls():''}
 <details class="operator-article-more"><summary class="btn soft-gray">更多文章操作</summary><div class="operator-article-more-menu">
 <button class="btn small" data-quality-action="mapping">推送匹配 / 评分分流</button>
 ${managementButton('导出勾选','export-selected',!pushSelection.size?'disabled':'')}
 ${managementButton('导出筛选结果','export-filtered')}
 ${managementButton('按最新规则重新生成','regenerate',!pushSelection.size||activeRun()||managementBusy?'disabled':'')}
 ${resultView.visibility!=='active'?managementButton('恢复勾选文章','restore-cleared',!pushSelection.size?'disabled':''):''}${typeof libraryAction==='function'?libraryAction(resultView.visibility==='deleted'?'恢复勾选文章':'删除勾选文章','results',resultView.visibility==='deleted'?'restore':'delete','',!pushSelection.size):''}</div></details>
 <button class="btn primary" data-push-action="send" ${!pushSelection.size||pushBusy||resultView.visibility==='cleared'?'disabled':''}>一键推送勾选文章</button>${typeof operatorPushButtonMarkup==='function'?operatorPushButtonMarkup():''}
 </div>${typeof operatorReceiptPanelMarkup==='function'?operatorReceiptPanelMarkup():''}</section>${typeof scoreJobPanels==='function'?scoreJobPanels():''}${typeof operatorSelectionPanelMarkup==='function'?operatorSelectionPanelMarkup():''}
 <div class="result-scope-note">共 ${num(r.total)} 篇符合条件 · 跨页勾选不会随筛选自动取消
 <button class="text-btn danger" data-push-action="cleanup" title="覆盖所有分页和筛选；仅归档已确认推送的当前版本" ${!pushClearable||pushBusy?'disabled':''}>归档全部已推送（${pushClearable}）</button></div>`+
 (r.rows.length?`<section class="panel"><div class="table-wrap"><table class="data-table article-results managed-results"><thead><tr>
 <th class="push-check"><input type="checkbox" data-push-select="page" aria-label="勾选本页文章" ${all?'checked':''} ${pushBusy?'disabled':''}></th><th>文章 / 原标题</th><th>正文摘要</th><th>作品评分 / 推送匹配</th><th>版本与规格</th><th>推送状态</th><th>操作</th></tr></thead><tbody>
 ${r.rows.map(x=>`<tr data-row-key="result-${x.id}"><td class="push-check"><input type="checkbox" data-push-select="${x.id}" aria-label="勾选文章${x.id}" ${pushSelection.has(x.id)?'checked':''} ${pushBusy?'disabled':''}></td>
 <td><span class="pill blue">${esc(x.category)}</span><small class="muted"> #${x.id} · 素材#${x.material_id}</small><button class="article-title" data-management="article" data-id="${x.id}">${esc(x.title)}</button><small class="original-title" title="${esc(x.original_title)}">原题：${esc(x.original_title||'未提供')}</small></td>
 <td><div class="article-summary">${esc(x.article||x.short_text)}</div>${managementButton('阅读全文','article',`data-id="${x.id}"`,'text-btn')}</td>
 <td class="quality-cell">${qualityCell(x)}</td>
 <td><span class="pill ${x.rule_status==='current'?'green':'amber'}">${ruleLabels[x.rule_status]}</span><small>${x.rule_revision?'规则R'+x.rule_revision+' · '+esc(x.write_variant):'版本待标注'}</small><small>标题 ${x.title_chars}/64 · ${x.paragraph_count}段</small><small>合计 ${x.char_count}/300字符</small><small>${esc(shortTime(x.created_at))}</small>${x.edited_at?'<small>已手动修改 / 恢复</small>':''}</td>
 <td class="push-status"><span class="pill ${x.push_state==='pushed'?'green':x.push_state==='failed'?'red':x.push_state==='pending'?'amber':''}" title="${esc(x.push_error||'')}">${pushLabel[x.push_state]||'未推送'}</span>${x.cleared_at?'<small>已清除</small>':''}</td>
 <td>${managementButton('编辑 / 历史','article',`data-id="${x.id}"`)}${managementButton('重新生成','regen-one',`data-id="${x.id}" ${activeRun()||managementBusy?'disabled':''}`)}</td></tr>`).join('')}
 </tbody></table></div></section>`:`<section class="panel">${empty('当前筛选没有文章','可重置条件，或切换“文章位置”查看已清除文章。')}</section>`)+pagination(r,'results');
};

async function openArticle(id){articleDetail=await api('/results/detail/'+id);articleTab='read';articleVersion=null;editorDirty=false;drawArticle();}
function paragraphCards(text){return text.split(/\r?\n/).map(x=>x.trim()).filter(Boolean).map((p,i)=>`<div class="article-paragraph"><span>${i+1}</span><p>${esc(p)}</p></div>`).join('');}
function drawArticle(){
 const x=articleDetail;if(!x)return;
 let body='';
 if(articleTab==='edit')body=`<div class="field"><label for="article-edit-title">标题</label><textarea id="article-edit-title" rows="2">${esc(x.title)}</textarea></div><div class="field"><label for="article-edit-body">正文 · ${x.category==='搞笑'?'按意思自然分段':'8—15个自然段'}</label><textarea id="article-edit-body" class="article-editor">${esc(x.article||x.short_text)}</textarea></div><div id="article-editor-meter"></div><p class="hint">保存前校验标题≤64字符、标题与正文合计≤300字符、${x.category==='搞笑'?'正文完整且非空，不限定段数':'正文8—15段'}。修改前自动留存版本。</p>${managementButton('保存修改','save-article','','btn primary')}`;
 else if(articleTab==='history'){
   const v=x.history.find(v=>v.id===articleVersion)||x.history[0];
   body=x.history.length?`<div class="field"><label>选择历史版本</label><select id="article-history-select">${x.history.map(z=>`<option value="${z.id}" ${z.id===v.id?'selected':''}>${esc(shortTime(z.archived_at))} · ${esc(z.reason)} · ${esc(z.batch_id)}</option>`).join('')}</select></div><div class="version-compare"><section><h3>当前版本</h3><strong>${esc(x.title)}</strong>${paragraphCards(x.article||x.short_text)}</section><section><h3>选中的历史版本</h3><strong>${esc(v.title)}</strong>${paragraphCards(v.article)}</section></div>${managementButton('恢复此历史版本','restore-version',`data-version="${v.id}"`,'btn')}`:empty('暂无历史版本','编辑、重生成或恢复文章前会自动保存当前版本。');
 }else body=`<div class="source-title-box"><span>原标题</span><p>${esc(x.original_title||'未提供')}</p></div><h2 class="article-read-title">${esc(x.title)}</h2><div class="result-meta"><span>${esc(x.category)}</span><span>标题 ${[...x.title].length}/64</span><span>${(x.article||x.short_text).split(/\r?\n/).filter(p=>p.trim()).length}段</span><span>合计 ${x.char_count}/300字符</span><span>${x.rule_revision?'规则R'+x.rule_revision+' · '+esc(x.write_variant):'历史规则未标注'}</span></div>${paragraphCards(x.article||x.short_text)}`;
 document.querySelector('#drawer-root').innerHTML=`<div class="drawer-mask" data-management="close-article"></div><aside class="drawer article-drawer"><header><div><div class="muted">文章#${x.id} · 素材#${x.material_id} · ${esc(x.category)}</div><h2>${esc(x.title)}</h2></div>${managementButton('×','close-article','','close-btn')}</header><div class="drawer-content"><div class="tabs">${[['read','分段阅读'],['edit','编辑文章'],['history','历史与对照 · '+x.history.length]].map(([k,t])=>managementButton(t,'article-tab',`data-tab="${k}"`,'tab '+(articleTab===k?'active':''))).join('')}</div>${body}</div><div class="drawer-actions"><span id="article-save-note" class="muted">${x.category==='搞笑'?'按意思自然分段，漫画张数后续另定':'每段对应一张后续漫画画面'}</span>${managementButton('按最新规则重生成','regen-one',`data-id="${x.id}" ${activeRun()?'disabled':''}`)}</div></aside>`;
 updateArticleMeter();
}
function updateArticleMeter(){const t=document.querySelector('#article-edit-title'),a=document.querySelector('#article-edit-body'),m=document.querySelector('#article-editor-meter');if(!m||!t||!a)return;const title=[...t.value.trim()].length,total=[...(t.value+a.value).replace(/\s/g,'')].length,paras=a.value.split(/\r?\n/).filter(p=>p.trim()).length,funny=articleDetail?.category==='搞笑';m.textContent=`标题 ${title}/64 · 正文 ${paras}${funny?'段 · 不限段数':'/8—15段'} · 合计 ${total}/300字符${editorDirty?' · 尚未保存':''}`;m.className='editor-meter'+(title>64||total>300||(funny?paras<1:paras<8||paras>15)?' invalid':'');}

async function showRegenerate(ids){
 if(editorDirty){toast("请先保存或放弃正在编辑的内容");return;}
 if(!ids.length)throw new Error('请先勾选文章');
 modal(`<header><div><h2>按最新规则重新生成 ${ids.length} 篇</h2><p>复用已有素材和提炼种子，只执行本次写文。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="callout">成功的新稿替换当前版本，旧稿自动留存；失败的文章保留当前稿。新内容需要重新推送。</div><p>本次写文任务 ${ids.length} 份；接口失败可能触发已配置的重试。写文并发 ${state.settings.write_workers} 路，总并发上限 ${state.settings.global_max_concurrency||16} 路。</p><div class="modal-actions">${managementButton('开始重新生成','confirm-regenerate',`data-ids="${ids.join(',')}"`,'btn primary')}</div>`,true);
}
async function managementAction(b){
 const action=b.dataset.management;
 if(action==='article')return openArticle(Number(b.dataset.id));
 if(action==='close-article'){if(editorDirty){toast('文章尚未保存，请先保存或点“放弃修改”');if(!document.querySelector('[data-management="discard-article"]'))document.querySelector('.drawer-actions').insertAdjacentHTML('beforeend',managementButton('放弃修改','discard-article'));return;}document.querySelector('#drawer-root').innerHTML='';articleDetail=null;return;}
 if(action==='discard-article'){editorDirty=false;document.querySelector('#drawer-root').innerHTML='';articleDetail=null;return;}
 if(action==='article-tab'){if(editorDirty){toast('请先保存修改，或关闭编辑后放弃修改');return;}articleTab=b.dataset.tab;return drawArticle();}
 if(action==='save-article'){
   const r=await api('/results/edit',{id:articleDetail.id,content_hash:articleDetail.content_hash,title:document.querySelector('#article-edit-title').value,article:document.querySelector('#article-edit-body').value});
   editorDirty=false;toast(r.changed?'修改已保存，旧稿已留存':'内容没有变化');await openArticle(articleDetail.id);return refresh();
 }
 if(action==='restore-version'){await api('/results/restore-version',{id:articleDetail.id,version_id:Number(b.dataset.version),content_hash:articleDetail.content_hash});toast('历史版本已恢复，恢复前的版本也已留存');await openArticle(articleDetail.id);return refresh();}
 if(action==='regenerate')return showRegenerate([...pushSelection]);
 if(action==='regen-one')return showRegenerate([Number(b.dataset.id)]);
 if(action==='confirm-regenerate'){
   if(managementBusy)return;managementBusy=true;b.disabled=true;
   try{const r=await api('/results/regenerate',{ids:b.dataset.ids.split(',').map(Number)});closeModal();editorDirty=false;document.querySelector('#drawer-root').innerHTML='';articleDetail=null;toast(`重生成已开始，${r.total}条素材的指定文章`);await refresh();await navigate('queue');}finally{managementBusy=false;if(b.isConnected)b.disabled=false;}return;
 }
 if(action==='select-filtered'){const r=await api('/results/select',{all_filtered:true,filters:resultQuery()});r.ids.forEach(id=>pushSelection.add(id));await render();return;}
 if(action==='reset-filters'){Object.assign(resultView,{push:'',rule:'',batch:'',date_from:'',date_to:'',visibility:'active',sort:'newest',size:30});state.q='';state.category='';state.resultPage=1;return render();}
 if(action==='restore-cleared'){const r=await api('/results/restore-cleared',selectedScope());toast(`已恢复${r.count}篇文章，原推送状态保留`);pushSelection.clear();resultOptionsAt=0;return refresh();}
 if(action==='export-selected'||action==='export-filtered'){
   const path=await window.desktop.saveFile('文章成品');if(!path)return;
   const r=await api('/export',{kind:'results',path,...(action==='export-selected'?selectedScope():{filters:resultQuery()})});return toast(`已导出${r.count}篇文章`);
 }
 if(action==='retry-seed'){b.disabled=true;try{await api('/run/retry-seeds',{ids:[Number(b.dataset.id)]});toast('已启动该篇写文重试');await refresh();}finally{if(b.isConnected)b.disabled=false;}return;}
 if(action==='save-budget'){
   const values={};for(const k of ['global_max_concurrency','daily_request_limit','daily_token_limit'])values[k]=document.getElementById(k).value;
   await api('/settings',values);state.settings=await api('/settings');toast('额度与并发设置已保存');return refresh();
 }
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-management]');if(!b)return;e.stopImmediatePropagation();managementAction(b).catch(x=>toast(x.message,true));},true);
document.addEventListener('change',async e=>{try{const k=e.target.dataset.resultFilter;if(k){resultView[k]=e.target.value;state.resultPage=1;await render();}if(e.target.id==='article-history-select'){articleVersion=Number(e.target.value);drawArticle();}}catch(x){toast(x.message,true);}});
document.addEventListener('input',e=>{if(['article-edit-title','article-edit-body'].includes(e.target.id)){editorDirty=true;updateArticleMeter();}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&articleDetail){e.stopImmediatePropagation();managementAction({dataset:{management:'close-article'}}).catch(x=>toast(x.message,true));}},true);

function usagePanel(){const u=state.stats.usage||{},s=state.settings;return `<section class="panel usage-panel"><div class="panel-title"><h2>今日任务模型用量</h2><small>北京时间 · 升级后开始记录</small></div><div class="usage-values"><div><strong>${num(u.requests)}</strong><span>请求${s.daily_request_limit?' / '+num(s.daily_request_limit):''}</span></div><div><strong>${num(u.total_tokens)}</strong><span>已报告Token${s.daily_token_limit?' / '+num(s.daily_token_limit):''}</span></div><div><strong>${num(u.unknown_usage)}</strong><span>请求用量未知</span></div><div><strong>${num(u.active)}</strong><span>当前模型请求</span></div></div><details data-preserve-live><summary>额度和总并发设置</summary><div class="form-grid">${[['global_max_concurrency','总并发上限',1,64,16],['daily_request_limit','每日请求额度',0,1000000,0],['daily_token_limit','每日已报告Token额度',0,1000000000,0]].map(([k,t,min,max,v])=>`<div class="field"><label for="${k}">${t}</label><input id="${k}" type="number" min="${min}" max="${max}" step="1" value="${s[k]??v}"></div>`).join('')}</div><p class="hint">每日额度0表示不限制。请求包含失败重试；Token仅累计服务端实际报告值，未知用量不能纳入Token额度。达到额度后停止新请求，已经进行的请求会完成并保存，Token可能因此超出额度。总并发修改用于新任务。</p>${managementButton('保存额度设置','save-budget','','btn')}</details></section>`;}

writingPage=async function(){
 const r=await api('/run/writing?'+new URLSearchParams({state:writingView.filter,page:writingView.page}));
 const retryTools=writingRetryControls(r.rows),failedRows=r.rows.filter(x=>x.state==='failed');
 const allFailed=failedRows.length>0&&failedRows.every(x=>writingRetrySelection.has(x.id));
 return pipelineMetrics()+`<section class="panel"><div class="panel-title"><h2>写文任务</h2><span class="pill blue">按单篇文章显示真实状态</span></div>${pipelineActions()}
 <div class="writing-filters">${[['','全部'],['ready','待生成'],['queued','排队中'],['writing','正在生成'],['failed','生成失败'],['paused','已暂停'],['written','已完成']].map(([k,t])=>`<button class="btn small ${writingView.filter===k?'primary':'ghost'}" data-pipeline-action="filter" data-state="${k}">${t}</button>`).join('')}</div>
 ${retryTools}
 ${r.rows.length?`<div class="table-wrap writing-table"><table class="data-table"><thead><tr><th class="writing-retry-check"><input type="checkbox" data-writing-failed-select="page" aria-label="勾选本页失败写文" ${allFailed?'checked':''} ${!failedRows.length||writingRetryBusy?'disabled':''}></th><th>素材 / 赛道主题</th><th>写文状态</th><th>结果与失败原因</th><th>操作</th></tr></thead><tbody>${r.rows.map(x=>`<tr data-row-key="seed-${x.id}"><td class="writing-retry-check"><input type="checkbox" data-writing-failed-select="${x.id}" aria-label="勾选失败写文${x.id}" ${writingRetrySelection.has(x.id)&&x.state==='failed'?'checked':''} ${x.state!=='failed'||writingRetryBusy?'disabled':''}></td><td><strong>#${x.material_id} · ${esc(x.title)}</strong><small>${esc(x.category)} · ${esc(x.topic||x.angle)}</small></td><td>${pill(x.state)}</td><td>${x.error?`<div class="workflow-write-error">${esc(x.error)}</div>`:''}${x.result_id?`<small>${x.cleared_at?'成品已推送清除，可在已清除列表恢复':x.state==='failed'?'上一版文章仍保留':'文章成品已保存'}</small>`:x.state==='writing'?'正在请求模型，完成后自动入库':x.state==='queued'?'已排队，等待并发空位':x.state==='failed'?'本篇未生成成功，可重试勾选或单独重试':'可复用已有种子生成文章'}</td><td>${x.result_id?managementButton('查看文章','article',`data-id="${x.result_id}"`):''}${['failed','ready','paused'].includes(x.state)?managementButton(x.state==='failed'?'重试本篇':'生成本篇','retry-seed',`data-id="${x.id}" ${activeRun()||writingRetryBusy?'disabled':''}`):''}<button class="btn small ghost" data-pipeline-action="material" data-id="${x.material_id}" data-tab="extract">查看元素</button></td></tr>`).join('')}</tbody></table></div>`:empty('当前筛选没有写文任务')}
 <div class="writing-pagination"><span>共${num(r.total)}份 · 第${r.page}/${Math.max(1,Math.ceil(r.total/r.size))}页</span><button class="btn small" data-pipeline-action="page" data-page="${r.page-1}" ${r.page<=1?'disabled':''}>上一页</button><button class="btn small" data-pipeline-action="page" data-page="${r.page+1}" ${r.page*r.size>=r.total?'disabled':''}>下一页</button></div></section>`;
};

function draftKey(){return state.page==='rules'?'rule:'+state.ruleCategory+':'+state.ruleKind+':'+state.ruleVariant:state.page==='settings'?'settings:'+state.settings.provider:'';}
document.addEventListener('input',e=>{
 if(!e.target.closest('#content')||!['settings','rules'].includes(state.page))return;
 const key=draftKey();if(!key)return;const values=editorDrafts.get(key)||{};
 const el=e.target;if(el.id&&el.id!=='api_key')values[el.id]={value:el.value,checked:el.checked};
 if(el.name==='allowed_category')values['category:'+el.value]={checked:el.checked};
 editorDrafts.set(key,values);
});
const originalSaveSettings=saveSettings;
saveSettings=async function(){const key=draftKey();await originalSaveSettings();editorDrafts.delete(key);};

// Keyed DOM updates retain nodes, selection and scrolling during passive polling.
function nodeKey(n){if(n.nodeType!==1)return '';return n.id||n.dataset.rowKey||n.dataset.runId||n.dataset.material||n.dataset.result||'';}
function morphNode(old,newNode,passive){
 if(old.nodeType!==newNode.nodeType||old.nodeName!==newNode.nodeName){old.replaceWith(newNode.cloneNode(true));return;}
 if(old.nodeType===3){if(old.nodeValue!==newNode.nodeValue)old.nodeValue=newNode.nodeValue;return;}
 if(old.nodeType!==1)return;
 if(passive&&(old.matches('[data-preserve-live]')||old.contains(document.activeElement)&&document.activeElement.matches('input,textarea,select')))return;
 for(const a of [...old.attributes])if(!newNode.hasAttribute(a.name))old.removeAttribute(a.name);
 for(const a of [...newNode.attributes])if(old.getAttribute(a.name)!==a.value)old.setAttribute(a.name,a.value);
 if(old.matches('input')){if(old.type!=='checkbox'&&old.value!==newNode.value)old.value=newNode.value;old.checked=newNode.checked;}
 if(old.matches('select')){const value=newNode.value;morphChildren(old,newNode,passive);old.value=value;return;}
 morphChildren(old,newNode,passive);
}
function morphChildren(old,newNode,passive){
 const keys=new Map([...old.childNodes].map(n=>[nodeKey(n),n]).filter(([k])=>k));
 let cursor=old.firstChild;
 for(const fresh of [...newNode.childNodes]){
   const key=nodeKey(fresh);let node=key?keys.get(key):cursor;
   if(!node||node.nodeType!==fresh.nodeType||node.nodeName!==fresh.nodeName||(!key&&nodeKey(node))){node=fresh.cloneNode(true);old.insertBefore(node,cursor);}
   else{if(node!==cursor)old.insertBefore(node,cursor);morphNode(node,fresh,passive);}
   cursor=node.nextSibling;
 }
 while(cursor){const next=cursor.nextSibling;cursor.remove();cursor=next;}
}
render=async function(passive=false){
 const revision=++renderRevision,page=state.page;if(!state.stats||!state.settings)return;
 let html='';switch(page){case'overview':html=overview()+usagePanel();break;case'materials':html=await materialCatalog();break;case'queue':html=pipelineQueue()+(typeof queuePanel==='function'?await queuePanel():'')+usagePanel();break;case'writing':html=await writingPage();break;case'bodies':html=await bodyPage();break;case'results':html=await results();break;case'rules':html=rules();break;case'settings':html=settings()+usagePanel();break;}
 html=await distributionHeader(page)+html;
 if(page!==state.page||revision!==renderRevision)return;
 const content=document.querySelector('#content'),selection=window.getSelection();
 if(passive&&selection&&!selection.isCollapsed&&content.contains(selection.anchorNode))return;
 const scroll=document.querySelector('.main-scroll'),top=scroll.scrollTop;
 const fragment=document.createElement('div');fragment.innerHTML=html;
 morphChildren(content,fragment,passive);scroll.scrollTop=top;
 syncDistributionTooltip();
 const drafts=editorDrafts.get(draftKey());if(drafts){for(const [key,value] of Object.entries(drafts)){const el=key.startsWith('category:')?[...content.querySelectorAll('[name="allowed_category"]')].find(e=>e.value===key.slice(9)):document.getElementById(key);if(!el)continue;if('checked'in value&&el.type==='checkbox')el.checked=value.checked;else if('value'in value)el.value=value.value;}}
};
refresh=async function(){
 if(refreshPending)return;refreshPending=true;
 try{state.stats=await api('/stats');document.querySelector('#last-update').textContent='更新于 '+new Date().toLocaleTimeString('zh-CN',{hour12:false});
   if(typeof updatePauseControls==='function')updatePauseControls();
   if(state.page==='materials'&&(catalogState.dirty||document.activeElement?.closest('#catalog-controls')))return;
   if(['overview','queue','writing','bodies','materials','results','history'].includes(state.page))await render(true);
 }finally{refreshPending=false;}
};
navigate=async function(page){
 if(editorDirty){toast('编辑中的文章尚未保存，请先保存或放弃修改');return;}
 pageMemory.set(state.page,{q:state.q,category:state.category,filterState:state.filterState,filterQualification:state.filterQualification,materialPage:state.materialPage,resultPage:state.resultPage,scroll:document.querySelector('.main-scroll').scrollTop});
 if(state.page==='settings'){state.settings=await api('/settings');updateProvider();}
 state.page=page;Object.assign(state,pageMemory.get(page)||{q:'',category:'',filterState:'',filterQualification:'',materialPage:1,resultPage:1});
 nav();document.querySelector('#page-title').textContent=pages[page][0];document.querySelector('#page-description').textContent=pages[page][1];document.querySelector('#breadcrumb').innerHTML='工作空间 <span>/</span> '+pages[page][0];
 await render();document.querySelector('.main-scroll').scrollTop=pageMemory.get(page)?.scroll||0;
};
