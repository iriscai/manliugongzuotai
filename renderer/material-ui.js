const materialSelection=new Set();let materialPageRows=[];
const catalogDefaults=()=>({visibility:'active',q:'',search_scope:'all',match_mode:'contains',exclude:'',category:'',qualification:'',state:'',workflow_node:'',import_id:'',body_filter:'',read_min:'',read_max:'',published_from:'',published_to:'',date_unknown:'',length_min:'',length_max:''});
const catalogState={draft:catalogDefaults(),applied:catalogDefaults(),dirty:false,advanced:false,sortBy:'id',sortDir:'desc',size:30,options:null,optionsAt:0};
const catalogSorts={id:'入库顺序',read_count:'阅读量',published_at:'发布日期',article_count:'文章数',body_length:'正文字数',title:'标题',category:'分类',updated_at:'更新时间'};
function catalogOptions(values,selected){return values.map(([value,label])=>`<option value="${esc(value)}" ${String(selected)===String(value)?'selected':''}>${esc(label)}</option>`).join('')}
function catalogSelect(id,key,label,values){return `<label class="catalog-select"><span>${label}</span><select id="${id}" data-catalog-filter="${key}" data-catalog-immediate>${catalogOptions(values,catalogState.draft[key])}</select></label>`}
function catalogRange(label,min,max,type='text',hint=''){
  const d=catalogState.draft;return `<div class="catalog-range"><span>${label}</span><div><input aria-label="${label}最小值" id="catalog-${min}" data-catalog-filter="${min}" type="${type}" ${type==='number'?'min="0" step="1"':''} placeholder="最小值" value="${esc(d[min])}"><b>至</b><input aria-label="${label}最大值" id="catalog-${max}" data-catalog-filter="${max}" type="${type}" ${type==='number'?'min="0" step="1"':''} placeholder="不限" value="${esc(d[max])}"></div>${hint?`<small>${hint}</small>`:''}</div>`;
}
function catalogWorkflowFilter(){
 const o=catalogState.options,d=catalogState.draft;
 const groups=[...new Set((o.workflow_nodes||[]).map(x=>x.group))];
 return `<label class="catalog-select catalog-workflow-select"><span>处理节点</span><select id="catalog-workflow-node" aria-label="处理节点" data-catalog-filter="workflow_node" data-catalog-immediate><option value="">全部处理节点</option>${typeof workflowGroupOptions==='function'?workflowGroupOptions(d.workflow_node):''}${groups.map(group=>`<optgroup label="${esc(group)}">${o.workflow_nodes.filter(x=>x.group===group).map(x=>`<option value="${esc(x.code)}" ${d.workflow_node===x.code?'selected':''}>${esc(x.label)} · ${num(x.count)}</option>`).join('')}</optgroup>`).join('')}<optgroup label="完成记录（含后续节点）">${catalogOptions((o.workflow_milestones||[]).map(x=>[x.code,x.label]),d.workflow_node)}</optgroup></select></label>`;
}
function materialWorkflowBadge(x){
 const code=x.workflow_node,color=['pushed','push_pending'].includes(code)?'green':code.includes('failed')?'red':code.includes('paused')||code==='push_blocked'?'amber':'blue';
 const seeds=x.workflow_seed_count||0,generated=x.workflow_generated_count||0,pushed=x.workflow_pushed_count||0,archived=x.workflow_archived_count||0;
 return `<span class="pill ${color}" title="${esc(x.workflow_description||'')}">${esc(x.workflow_label||stateLabels[x.state]||x.state)}</span>${seeds?`<small>已生文 ${generated}/${seeds}篇</small>`:''}${generated?`<small>已推送 ${pushed}/${x.workflow_deliverable_count||0}篇${archived?' · 已清除/删除'+archived+'篇':''}</small>`:''}${x.workflow_write_failed_count?`<small class="workflow-failed">写文失败 ${x.workflow_write_failed_count}篇</small>`:''}`;
}
async function showWorkflowGuide(){
 const o=catalogState.options||await api('/materials/options');
 modal(`<header><div><h2>素材处理节点说明</h2><p>按正文、原赛道文章和推送回执计算。</p></div><button class="close-btn" data-action="close-modal">×</button></header><div class="workflow-path">导入标题/链接 → 正文抓取与验收去重 → 按原赛道写文 → 推送与回执确认</div><p class="hint">等待、排队、执行中、暂停和失败分别显示。</p><p class="hint">“当前节点”表示现在卡在哪一步；“完成记录”可筛出已通过某一步的所有素材，包含已进入后续节点的记录。纯图片和精确重复素材沿用原规则自动删除或合并，不虚设待处理节点。</p><div class="workflow-guide">${(o.workflow_nodes||[]).map(x=>`<div><strong>${esc(x.label)}</strong><span>${esc(x.description)}</span></div>`).join('')}</div><p class="hint">成品清除/删除保留已生文事实，不自动补生。推送成功仅认当前目标、当前内容的回执；本文案工具不代表已经生图或发文。</p>`,false);
}
function catalogControls(){
  const d=catalogState.draft,o=catalogState.options;
  const categories=[['','全部分类'],...o.categories.map(x=>[x.name,`${x.name} · ${num(x.count)}`])];
  const states=[['','全部处理状态'],...[...new Set([...o.states.map(x=>x.state),'pending','needs_source','fetching','routing','extracting','extracted','writing','written','failed','needs_review','skipped'])].map(x=>[x,stateLabels[x]||x])];
  return `<div id="catalog-controls">${typeof operatorQuickMarkup==='function'?operatorQuickMarkup():''}
    <div class="catalog-search-row"><select id="catalog-search-scope" aria-label="检索字段" data-catalog-filter="search_scope">${catalogOptions([['all','标题＋正文'],['title','仅标题'],['body','仅正文'],['url','原文链接'],['id','素材编号']],d.search_scope)}</select><select id="catalog-match-mode" aria-label="关键词匹配方式" data-catalog-filter="match_mode">${catalogOptions([['contains','包含整句'],['all','全部关键词'],['any','任一关键词'],['exact','完全相同']],d.match_mode)}</select><div class="catalog-search-input"><span>⌕</span><input id="list-search" aria-label="检索关键词" data-catalog-filter="q" placeholder="输入关键词；选择全部 / 任一关键词时用空格分隔" value="${esc(d.q)}"></div><button class="btn primary" data-catalog-action="search">检索</button><button class="btn" data-catalog-action="reset">重置</button></div>
    <div class="catalog-filter-row">${catalogWorkflowFilter()}${catalogSelect('category-filter','category','分类',categories)}${catalogSelect('qualification-filter','qualification','验收',[['','全部验收状态'],['qualified','合格素材'],['pending','待验收素材']])}${catalogSelect('catalog-body-filter','body_filter','正文',[['','全部正文状态'],['present','有正文'],['missing','缺正文'],['failed','抓取失败 / 截断'],['no_text','无文字 / 失效']])}<button class="btn small ${catalogState.advanced?'catalog-active':''}" data-catalog-action="advanced" aria-expanded="${catalogState.advanced}">${catalogState.advanced?'收起':'高级筛选'} <span>${catalogState.advanced?'⌃':'⌄'}</span></button></div>
    ${catalogState.advanced?`<div class="catalog-advanced">${catalogSelect('state-filter','state','执行状态（高级）',states)}${catalogRange('阅读量','read_min','read_max','text','支持数字、万、亿，例如10万')}
      <div class="catalog-range"><span>发布日期</span><div><input aria-label="发布日期开始" id="catalog-published_from" type="date" data-catalog-filter="published_from" value="${esc(d.published_from)}"><b>至</b><input aria-label="发布日期结束" id="catalog-published_to" type="date" data-catalog-filter="published_to" value="${esc(d.published_to)}"></div><label class="catalog-check"><input type="checkbox" data-catalog-filter="date_unknown" ${d.date_unknown?'checked':''}>仅日期缺失 / 未识别</label></div>
      ${catalogRange('正文字数','length_min','length_max','number')}
      <label class="catalog-exclude"><span>排除关键词</span><input id="catalog-exclude" data-catalog-filter="exclude" value="${esc(d.exclude)}" placeholder="多个词用空格分隔，命中任一个即排除"></label>
      <div class="catalog-date-presets"><span>日期快捷选择</span><div>${[3,7,30].map(n=>`<button class="btn small" data-catalog-action="days" data-days="${n}">近${n}天</button>`).join('')}</div></div></div>`:''}
    <div class="catalog-quick-row"><span>快捷筛选</span>${[["body_pending","待抓取"],["write_pending","待生文"]].map(([code,label])=>`<button class="catalog-chip ${d.workflow_node===code?'selected':''}" data-catalog-action="workflow-quick" data-node="${code}">${label}</button>`).join('')}<button class="catalog-chip ${d.qualification==='qualified'?'selected':''}" data-catalog-action="quick" data-key="qualified">合格素材</button><button class="catalog-chip ${d.body_filter==='missing'?'selected':''}" data-catalog-action="quick" data-key="missing">缺正文</button><button class="catalog-chip ${d.read_min==='100000'?'selected':''}" data-catalog-action="quick" data-key="popular">阅读 ≥10万</button><button class="catalog-chip" data-catalog-action="days" data-days="7">近7天</button><span id="catalog-draft-note" class="catalog-draft-note">${catalogState.dirty?'条件待应用':''}</span></div>
  </div>`;
}
function catalogSortHead(key,label,hint=''){
  const active=catalogState.sortBy===key;return `<th aria-sort="${active?(catalogState.sortDir==='asc'?'ascending':'descending'):'none'}"><button class="catalog-head-sort ${active?'selected':''}" data-catalog-sort="${key}" title="${esc(hint||'按'+label+'排序')}">${label}<span>${active?(catalogState.sortDir==='asc'?'↑':'↓'):'↕'}</span></button></th>`;
}
function catalogDate(row){
  const raw=row.published_sort||row.published_at||'';
  if(!raw)return '<span class="muted">未提供</span>';
  const parts=raw.replace('T',' ').split(' ');return `<span class="catalog-date" title="${esc(row.published_at)}">${esc(parts[0])}<small>${esc(parts.slice(1).join(' '))}</small></span>`;
}
async function materialCatalog(){
  if(catalogState.optionsVisibility!==catalogState.applied.visibility){catalogState.optionsAt=0;catalogState.optionsVisibility=catalogState.applied.visibility;}
  if(!catalogState.options||Date.now()-catalogState.optionsAt>30000){catalogState.options=await api('/materials/options?visibility='+encodeURIComponent(catalogState.applied.visibility||'active'));catalogState.optionsAt=Date.now()}
  const query={...catalogState.applied,page:state.materialPage,size:catalogState.size,sort_by:catalogState.sortBy,sort_dir:catalogState.sortDir};
  const r=await api('/materials?'+new URLSearchParams(query));state.materialPage=r.page;materialPageRows=r.rows;
  return `<section class="panel catalog-panel ${catalogState.advanced?'advanced-open':''}">${typeof operatorImportScopeMarkup==='function'?operatorImportScopeMarkup():''}${catalogControls()}<div class="ops-material-actions"><span>已勾选 ${materialSelection.size} 条素材</span><button class="btn small" data-ops="clear-material-selection">清空勾选</button><button class="btn small" data-ops="execute-filtered">执行当前筛选</button><button class="btn small primary" data-ops="execute-selected" ${materialSelection.size?'':'disabled'}>执行勾选素材</button>${typeof operatorMaterialScopeButtons==='function'?operatorMaterialScopeButtons():''}</div>
  <div class="catalog-result-bar"><div><strong>${num(r.total)}</strong> 条筛选结果 <span>/ 素材库 ${num(r.all_total)} 条</span></div><div class="catalog-sort-tools">${typeof operatorDensityButton==='function'?operatorDensityButton():''}<button class="btn small ghost" data-catalog-action="workflow-guide">节点说明</button><label>排序 <select id="catalog-sort-by" aria-label="排序字段">${catalogOptions(Object.entries(catalogSorts),catalogState.sortBy)}</select></label><button class="btn small" data-catalog-action="direction" aria-label="切换排序方向">${catalogState.sortDir==='desc'?'↓ 降序':'↑ 升序'}</button><label>每页 <select id="catalog-page-size" aria-label="每页条数">${catalogOptions([20,30,50,100].map(n=>[n,n+'条']),catalogState.size)}</select></label><button class="btn small ghost" data-catalog-action="refresh">刷新</button></div></div>
  ${r.rows.length?`<div class="table-wrap catalog-table-scroll"><table class="data-table full material-table"><colgroup><col style="width:38px"><col style="width:56px"><col style="width:204px"><col style="width:190px"><col style="width:240px"><col style="width:84px"><col style="width:96px"><col style="width:122px"><col style="width:80px"><col style="width:135px"></colgroup><thead><tr><th><input type="checkbox" data-material-select="page" aria-label="勾选本页素材" ${r.rows.length&&r.rows.every(x=>materialSelection.has(x.id))?'checked':''}></th>${catalogSortHead('id','编号')}${catalogSortHead('title','标题')}<th>当前处理节点 / 进度</th><th>正文 <span class="muted">/ 预览</span></th>${catalogSortHead('category','分类')}${catalogSortHead('read_count','阅读量')}${catalogSortHead('published_at','发布日期')}${catalogSortHead('article_count','文章数')}<th>操作</th></tr></thead><tbody>${r.rows.map(x=>`<tr data-material="${x.id}"><td><input type="checkbox" data-material-select="${x.id}" aria-label="勾选素材${x.id}" ${materialSelection.has(x.id)?'checked':''}></td><td class="id-cell">#${x.id}</td><td class="catalog-title-cell"><span class="catalog-title" title="${esc(x.title)}">${esc(x.title||'缺少标题')}</span></td><td class="catalog-state">${materialWorkflowBadge(x)}<small>${x.qualification==='qualified'?'正文已验收':'待正文验收'}</small></td><td class="catalog-body-cell">${x.body_length?`<span class="catalog-body-preview" title="点击查看完整正文">${esc(x.body_preview.replace(/\s+/g,' '))}</span><small>${num(x.body_length)} 字符 · 查看全文 ↗</small>`:`<span class="catalog-body-empty" title="${esc(x.body_fetch_error||x.error||'')}">${x.body_status==='failed'||x.body_status==='truncated'?'抓取未成功':'待获取正文'}</span>`}</td><td><span class="catalog-category" title="${esc(x.category)}">${esc(x.category)}</span></td><td class="catalog-number">${num(x.read_count)}</td><td>${catalogDate(x)}</td><td>${num(x.article_count)}篇</td><td><button class="catalog-view" aria-label="查看素材${x.id}">查看 ↗</button>${typeof materialNextButton==='function'?materialNextButton(x):''}</td></tr>`).join('')}</tbody></table></div>`:empty('没有符合条件的素材','调整组合筛选条件，或点击“重置”查看全部素材。')}
  ${pagination(r,'materials')}<p class="catalog-footnote">节点按实际当前进度计算，支持与分类、阅读量等条件组合筛选。原赛道文章生成后标记生文完成；已推送不代表已生图。列表展示正文摘要，点击素材查看全文。</p></section>`;
}
function catalogMarkDirty(){catalogState.dirty=JSON.stringify(catalogState.draft)!==JSON.stringify(catalogState.applied);const note=document.getElementById('catalog-draft-note');if(note)note.textContent=catalogState.dirty?'条件待应用':''}
async function catalogApply(){
  const previous=catalogState.applied;catalogState.applied={...catalogState.draft};catalogState.dirty=false;state.materialPage=1;
  try{await render()}catch(error){catalogState.applied=previous;catalogMarkDirty();throw error}
}
function catalogReadControl(el){catalogState.draft[el.dataset.catalogFilter]=el.type==='checkbox'?(el.checked?'1':''):el.value;catalogMarkDirty()}
function catalogSetDays(days){
  const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  const [year,month,day]=today.split('-').map(Number);const from=new Date(Date.UTC(year,month-1,day-days+1)).toISOString().slice(0,10);
  Object.assign(catalogState.draft,{published_from:from,published_to:today,date_unknown:''});
}
async function catalogAction(action,button){
  switch(action){
    case'workflow-guide':return showWorkflowGuide();
    case'workflow-quick':catalogState.draft.workflow_node=catalogState.draft.workflow_node===button.dataset.node?'':button.dataset.node;return catalogApply();
    case'search':return catalogApply();
    case'reset':catalogState.draft=catalogDefaults();catalogState.applied=catalogDefaults();catalogState.dirty=false;catalogState.advanced=false;catalogState.sortBy='id';catalogState.sortDir='desc';state.materialPage=1;return render();
    case'advanced':catalogState.advanced=!catalogState.advanced;return render();
    case'refresh':catalogState.optionsAt=0;state.stats=await api('/stats');return render();
    case'direction':catalogState.sortDir=catalogState.sortDir==='desc'?'asc':'desc';state.materialPage=1;return render();
    case'days':catalogSetDays(Number(button.dataset.days));return catalogApply();
    case'quick':{
      const d=catalogState.draft;
      switch(button.dataset.key){
        case'qualified':d.qualification=d.qualification==='qualified'?'':'qualified';break;
        case'missing':d.body_filter=d.body_filter==='missing'?'':'missing';break;
        case'popular':d.read_min=d.read_min==='100000'?'':'100000';break;
      }return catalogApply();
    }
  }
}
document.addEventListener('input',event=>{const el=event.target.closest('[data-catalog-filter]');if(el)catalogReadControl(el)});
document.addEventListener('change',async event=>{try{
  const el=event.target;if(el.matches('[data-catalog-filter]')){
    catalogReadControl(el);
    if(el.dataset.catalogFilter==='date_unknown'&&el.checked)Object.assign(catalogState.draft,{published_from:'',published_to:''});
    if(['published_from','published_to'].includes(el.dataset.catalogFilter)&&el.value)catalogState.draft.date_unknown='';
    if(el.hasAttribute('data-catalog-immediate'))await catalogApply();
  }else if(el.id==='catalog-sort-by'){catalogState.sortBy=el.value;state.materialPage=1;await render()}
  else if(el.id==='catalog-page-size'){catalogState.size=Number(el.value);state.materialPage=1;await render()}
}catch(error){toast(error.message,true)}});
document.addEventListener('click',async event=>{try{
  const sort=event.target.closest('[data-catalog-sort]');if(sort){const key=sort.dataset.catalogSort;catalogState.sortDir=catalogState.sortBy===key?(catalogState.sortDir==='desc'?'asc':'desc'):(['title','category'].includes(key)?'asc':'desc');catalogState.sortBy=key;state.materialPage=1;return await render()}
  const button=event.target.closest('[data-catalog-action]');if(button)await catalogAction(button.dataset.catalogAction,button);
}catch(error){toast(error.message,true)}});
document.addEventListener('keydown',async event=>{if(event.key==='Enter'&&!event.isComposing&&event.target.closest('#catalog-controls')){event.preventDefault();try{await catalogApply()}catch(error){toast(error.message,true)}}});
