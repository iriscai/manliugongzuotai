// Military C-G have independent writing policies; all other lanes keep their controls.
const militaryPolicies={C:{name:'IP军经重构',min:400,max:600,scope:'body',question:false,titleMax:null},D:{name:'军经代价短评',min:400,max:600,scope:'body',question:false,titleMax:null},E:{name:'结构变奏短评',min:400,max:600,scope:'body',question:false,titleMax:null},F:{name:'冲突解读长文',min:1200,max:1500,scope:'total',question:false,titleMax:30},G:{name:'冷静重构中篇',min:700,max:800,scope:'body',question:false,titleMax:null}};
let militaryContext='';
function militaryData(x){try{return JSON.parse(x?.data_json||'{}');}catch{return {};}}
function militaryVariant(x){if(x?.category!=='军事')return null;return militaryPolicies[x.write_variant]?x.write_variant:(militaryData(x).writing_profile||'').match(/^military_ip_([C-G])_v[12]$/)?.[1]||null;}
function militaryRow(x){return !!militaryVariant(x);}
function militaryPolicy(x){const v=militaryVariant(x),p=militaryPolicies[v],profile=militaryData(x).writing_profile;if(['C','D','E'].includes(v)&&profile===`military_ip_${v}_v1`)return {...p,min:v==='C'?201:241,max:v==='C'?300:290,scope:'total',question:['C','D'].includes(v)};return p;}
function militaryMeasure(x,title=x.title||'',body=x.article||x.short_text||''){const p=militaryPolicy(x);return [...((p.scope==='body'?body.split('\n\n资料来源\n\n')[0]:title+body).replace(/\s/g,''))].length;}
function militaryTitleInfo(x){const p=militaryPolicy(x);return `标题 ${[...(x.title||'')].length}${p.titleMax?'/'+p.titleMax:''}字`;}
function militaryCountInfo(x){const p=militaryPolicy(x);return `${p.scope==='body'?'正文':'合计'} ${militaryMeasure(x)}/${p.min}–${p.max}可见字`;}
function militaryEditorHint(x){const p=militaryPolicy(x);return `军事${militaryVariant(x)} · ${p.scope==='body'?'正文（不含标题）':'标题与正文合计'}${p.min}–${p.max}可见字，自然分段${p.question?'，结尾具体反问':''}；`;}
function militaryReadHTML(x){const p=militaryPolicy(x),data=militaryData(x),headings=militaryVariant(x)==='F'&&Array.isArray(data.military_headings)?data.military_headings:[];return `<div class="military-html-preview" style="font-size:12px;font-weight:bold;line-height:1.8">${(x.article||x.short_text).split(/\r?\n/).map(t=>t.trim()).filter(Boolean).map(t=>headings.includes(t)?`<h3 style="font-size:14px;font-weight:bold;margin:18px 0 10px">${esc(t)}</h3>`:`<p style="font-size:12px;font-weight:bold;margin:0 0 12px">${esc(t)}</p>`).join('')}</div><p class="hint">${militaryEditorHint(x)}HTML正文12px加粗。初稿与自改稿分别留档。</p><button class="btn small soft-blue" data-military="export" data-id="${x.id}">导出公众号HTML</button>`;}
function militaryProfileControl(kind,label){const value=state.settings['military_'+kind+'_variant']||'C';return `<label class="result-filter"><span>${label}</span><select id="military-${kind}-variant"><option value="follow" ${value==='follow'?'selected':''}>跟随全局A/B</option>${state.prompts.filter(p=>p.category==='军事'&&p.kind===kind).map(p=>`<option value="${p.variant}" ${value===p.variant?'selected':''} ${promptEnabled(p)?'':'disabled'}>${p.variant} · ${esc(p.name)}${promptEnabled(p)?'':'（停用）'}</option>`).join('')}</select></label>`;}
const beforeMilitaryRules=rules;
rules=function(){
 if(state.ruleCategory!=='军事'){militaryContext='';return beforeMilitaryRules();}
 const context='军事|'+state.ruleKind;if(context!==militaryContext){state.ruleVariant=state.settings['military_'+state.ruleKind+'_variant']||'C';militaryContext=context;}
 const lengths=Object.entries(militaryPolicies).map(([v,p])=>`${v} ${p.name}：${p.scope==='body'?'正文':'合计'}${p.min}–${p.max}字`).join('；');
 const card=`<section class="funny-profile"><strong>军事C–G · 独立版本</strong><p>按素材原文直接生成军事稿件，初稿和自改在同一次响应中完成。</p><p>${lengths}。HTML正文12px加粗，标点自然。成品直接报道事件、交代时间并给出个人判断；来源与核验留在内部。</p><div class="funny-profile-controls">${militaryProfileControl('write','军事写文方案')}<button class="btn small primary" data-military="save">保存军事执行方案</button></div></section>`;
 return beforeMilitaryRules().replace('<div class="prompt-status-tools">',card+'<div class="prompt-status-tools">');
};
const beforeMilitaryMeter=updateArticleMeter;
updateArticleMeter=function(){
 if(!militaryRow(articleDetail))return beforeMilitaryMeter();
 const t=document.querySelector('#article-edit-title'),a=document.querySelector('#article-edit-body'),m=document.querySelector('#article-editor-meter');if(!t||!a||!m)return;
 const p=militaryPolicy(articleDetail),count=militaryMeasure(articleDetail,t.value,a.value),paragraphs=a.value.split(/\r?\n/).filter(t=>t.trim()).length;
 m.textContent=`军事${militaryVariant(articleDetail)} · ${p.scope==='body'?'正文':'合计'} ${count}/${p.min}–${p.max}可见字 · ${paragraphs}个自然段 · HTML标签不计字数${p.titleMax?' · 标题≤'+p.titleMax+'字':''}${editorDirty?' · 尚未保存':''}`;
 m.className='editor-meter'+(count<p.min||count>p.max||(p.titleMax&&[...t.value.trim()].length>p.titleMax)||(p.question&&!/[？?]\s*$/.test(a.value))?' invalid':'');
};
const beforeMilitaryDraw=drawArticle;
drawArticle=function(){beforeMilitaryDraw();if(!militaryRow(articleDetail))return;let data={};try{data=JSON.parse(articleDetail.data_json);}catch{}
 const body=document.querySelector('.article-drawer .drawer-content');if(!body)return;
 const audit=data.military_audit;if(audit&&articleTab==='read')body.insertAdjacentHTML('beforeend',`<details><summary>查看军事初稿与自改记录</summary><h3>${esc(audit.draft_title||'初稿')}</h3><div style="white-space:pre-wrap">${esc(audit.draft_article||'')}</div><h3>实际改动</h3><ul>${(audit.edit_notes||[]).map(n=>`<li>${esc(n)}</li>`).join('')}</ul><h3>材料缺口</h3><ul>${(audit.material_notes||[]).map(n=>`<li>${esc(n)}</li>`).join('')||'<li>未记录新增缺口</li>'}</ul></details>`);
};
document.addEventListener('click',async event=>{const b=event.target.closest('[data-military]');if(!b)return;event.stopImmediatePropagation();b.disabled=true;
 try{if(b.dataset.military==='save'){await api('/settings',{military_write_variant:document.querySelector('#military-write-variant').value});state.settings=await api('/settings');toast('军事执行方案已保存');}
 else if(b.dataset.military==='export'){const path=await window.desktop.saveFile('军事HTML');if(path){await api('/export',{path,kind:'military_html',ids:[Number(b.dataset.id)]});toast('军事HTML已导出，原稿未改动');}}}
 catch(error){toast(error.message,true);}finally{if(b.isConnected)b.disabled=false;}
});
const militaryDevLabel=new URLSearchParams(location.search).get('devLabel');if(militaryDevLabel){document.title=militaryDevLabel;document.querySelector('.version').textContent=militaryDevLabel;}
