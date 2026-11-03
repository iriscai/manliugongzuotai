// A single proportional strip. Detailed values stay in the hover/focus card.
const distributionData=new Map();let distributionHovered=null,distributionPoint=null;
const distributionPalette=['#526cf0','#249b90','#e3a443','#d5727f','#7397ca','#8b7abd','#53a3b5','#90aa50','#b88760','#c478b4','#4d8dce','#80a997','#b8a544','#e19267','#707db0','#a2879b'];
function distributionColor(category){let hash=2166136261;for(const c of category){hash^=c.codePointAt(0);hash=Math.imul(hash,16777619);}return distributionPalette[(hash>>>0)%distributionPalette.length];}
function distributionPercent(n){return n>0&&n<.01?'<0.01%':n.toLocaleString('zh-CN',{maximumFractionDigits:2})+'%';}
function distributionLegend(data){return `<div class="lane-distribution-legend" role="group" aria-label="赛道名称图例">${data.rows.map(row=>`<span class="lane-legend-item" title="${esc(row.category)}：${num(row.count)}${esc(data.unit)}，${esc(distributionPercent(row.percentage))}"><i style="background:${distributionColor(row.category)}" aria-hidden="true"></i><span>${esc(row.category)}</span></span>`).join('')}</div>`;}
function distributionFilters(page){
 if(page==='materials')return {...catalogState.applied};
 if(page==='results'){const {page,size,sort,...filters}=resultQuery();return filters;}
 if(page==='writing')return {state:writingView.filter};
 if(page==='history'){const {page,...filters}=historyView;return filters;}
 return {};
}
async function distributionHeader(page){
 try{
  const filters=distributionFilters(page),key=JSON.stringify([page,filters]);
  const data=await api('/stats/distribution?'+new URLSearchParams({module:page,filters:JSON.stringify(filters)}));
  // Cache by immutable scope, so an older navigation cannot overwrite another chart's data.
  distributionData.set(key,data);if(distributionData.size>30)distributionData.delete(distributionData.keys().next().value);
  return `<section class="panel lane-distribution ${typeof operatorChartClass==='function'?operatorChartClass(page):''}" data-row-key="distribution-${esc(page)}" data-dist-scope="${esc(key)}" aria-label="赛道数量分布"><div class="lane-distribution-head"><div><h2>赛道分布</h2><span>${esc(data.scope)}</span></div><div class="lane-distribution-total"><strong>${num(data.total)}</strong><span>${esc(data.unit)} · ${data.category_count}个赛道</span></div>${typeof operatorChartButton==='function'?operatorChartButton(page):''}</div>${data.total?`<div class="lane-distribution-track" role="group" aria-label="按数量占比的赛道分布，可用左右方向键查看各赛道">${data.rows.map((row,i)=>`<button type="button" class="lane-segment" data-row-key="lane-${esc(row.category)}" data-dist-category="${esc(row.category)}" tabindex="${i===0?'0':'-1'}" aria-label="${esc(row.category)}，${num(row.count)}${esc(data.unit)}，占比${esc(distributionPercent(row.percentage))}" style="flex:${row.count} 1 0%;--lane-color:${distributionColor(row.category)}"></button>`).join('')}</div>${distributionLegend(data)}<div class="lane-distribution-foot">悬停放大分段，查看数量与占比<span>按整个数据范围统计 · 不受分页影响</span></div>`:`<div class="lane-distribution-empty">当前范围暂无可统计数据</div>`}</section>`;
 }catch(error){return `<section class="panel lane-distribution distribution-error" data-row-key="distribution-${esc(page)}"><strong>赛道分布</strong><span>暂时无法读取统计，刷新后重试。</span></section>`;}
}
function distributionTip(){let tip=document.getElementById('lane-distribution-tooltip');if(!tip){tip=document.createElement('div');tip.id='lane-distribution-tooltip';tip.className='lane-distribution-tooltip';tip.role='tooltip';tip.hidden=true;document.body.append(tip);}return tip;}
function hideDistributionTip(){distributionHovered?.removeAttribute('aria-describedby');distributionHovered=null;const tip=document.getElementById('lane-distribution-tooltip');if(tip)tip.hidden=true;}
function showDistributionTip(segment,clientX,clientY){
 const root=segment.closest('[data-dist-scope]'),data=distributionData.get(root?.dataset.distScope);if(!data)return;
 const rank=data.rows.findIndex(r=>r.category===segment.dataset.distCategory),row=data.rows[rank];if(!row)return;
 const tip=distributionTip();if(distributionHovered!==segment)distributionHovered?.removeAttribute('aria-describedby');distributionHovered=segment;segment.setAttribute('aria-describedby',tip.id);
 distributionPoint=clientX===undefined?null:{x:clientX,y:clientY};
 const details=[['qualified','合格素材'],['with_body','已有正文'],['ready','待写文'],['written','已生成'],['enabled','启用'],['disabled','停用']].filter(([k])=>row[k]!==undefined);
 tip.innerHTML=`<div class="lane-tip-title"><i style="background:${distributionColor(row.category)}"></i><strong>${esc(row.category)}</strong><span>#${rank+1}</span></div><div class="lane-tip-numbers"><strong>${num(row.count)}<small>${esc(data.unit)}</small></strong><b>${esc(distributionPercent(row.percentage))}</b></div><p>占本范围 ${num(data.total)} ${esc(data.unit)}中的比例</p>${details.length?`<div class="lane-tip-details">${details.map(([k,t])=>`<span>${t}<b>${num(row[k])}</b></span>`).join('')}</div>`:''}<small class="lane-tip-scope">${esc(data.scope)}</small>`;
 tip.hidden=false;
 const bounds=segment.getBoundingClientRect(),x=clientX??(bounds.left+bounds.width/2),y=clientY??bounds.bottom;
 const left=Math.max(12,Math.min(innerWidth-tip.offsetWidth-12,x+12));let top=y+18;
 if(top+tip.offsetHeight>innerHeight-12)top=Math.max(12,y-tip.offsetHeight-16);
 tip.style.left=left+'px';tip.style.top=top+'px';
}
function syncDistributionTooltip(){
 if(!distributionHovered)return;
 if(!distributionHovered.isConnected){hideDistributionTip();return;}
 showDistributionTip(distributionHovered,distributionPoint?.x,distributionPoint?.y);
}
document.addEventListener('pointermove',e=>{const segment=e.target.closest?.('.lane-segment');if(segment)showDistributionTip(segment,e.clientX,e.clientY);else if(distributionHovered)hideDistributionTip();},{passive:true});
document.addEventListener('pointerout',e=>{if(e.target.closest?.('.lane-segment')&&!e.relatedTarget?.closest?.('.lane-segment'))hideDistributionTip();});
document.addEventListener('focusin',e=>{const segment=e.target.closest?.('.lane-segment');if(segment)showDistributionTip(segment);else hideDistributionTip();});
document.addEventListener('keydown',e=>{
 const segment=e.target.closest?.('.lane-segment');if(!segment)return;
 if(e.key==='Escape'){hideDistributionTip();return;}
 if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){
  e.preventDefault();const list=[...segment.parentElement.children],i=list.indexOf(segment),next=e.key==='Home'?0:e.key==='End'?list.length-1:(i+(e.key==='ArrowRight'?1:-1)+list.length)%list.length;
  list.forEach((b,n)=>b.tabIndex=n===next?0:-1);list[next].focus();
 }
});
document.addEventListener('scroll',hideDistributionTip,true);window.addEventListener('resize',hideDistributionTip);
document.addEventListener('click',e=>{if(e.target.closest('[data-nav]'))hideDistributionTip();});
