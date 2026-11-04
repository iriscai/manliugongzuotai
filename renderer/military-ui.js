// Military C alone has IP/HTML rules; other categories retain their original controls.
let militaryContext='';
function militaryRow(x){if(x?.category!=='军事')return false;try{return x.write_variant==='C'||JSON.parse(x.data_json||'{}').writing_profile==='military_ip_C_v1';}catch{return false;}}
function militaryReadHTML(x){return `<div class="military-html-preview" style="font-size:12px;font-weight:bold;line-height:1.8">${(x.article||x.short_text).split(/\r?\n/).map(p=>p.trim()).filter(Boolean).map(p=>`<p style="font-size:12px;font-weight:bold;margin:0 0 12px">${esc(p)}</p>`).join('')}</div><p class="hint">军事C · HTML正文12px加粗，自然分段，标题与正文可见文字合计201–300字。初稿与自改稿分开保存，尚待你确认。</p><button class="btn small soft-blue" data-military="export" data-id="${x.id}">导出公众号HTML</button>`;}
function militaryProfileControl(kind,label){const value=state.settings['military_'+kind+'_variant']||'C';return `<label class="result-filter"><span>${label}</span><select id="military-${kind}-variant"><option value="follow" ${value==='follow'?'selected':''}>跟随全局A/B</option>${state.prompts.filter(p=>p.category==='军事'&&p.kind===kind).map(p=>`<option value="${p.variant}" ${value===p.variant?'selected':''} ${promptEnabled(p)?'':'disabled'}>${p.variant} · ${esc(p.name)}${promptEnabled(p)?'':'（停用）'}</option>`).join('')}</select></label>`;}
const beforeMilitaryRules=rules;
rules=function(){
 if(state.ruleCategory!=='军事'){militaryContext='';return beforeMilitaryRules();}
 const context='军事|'+state.ruleKind;if(context!==militaryContext){state.ruleVariant=state.settings['military_'+state.ruleKind+'_variant']||'C';militaryContext=context;}
 const card=`<section class="funny-profile"><strong>军事C · 两份材料学习后的IP军经重构</strong><p>事实底稿 → 独立视角 → 实际初稿 → 局部自改。侧重军事与经济、产业、能源及国际局势；可见文字201–300字，HTML正文12px加粗，自然分段，标点正常。A/B原文保留；此配置只作用于军事。</p><div class="funny-profile-controls">${militaryProfileControl('extract','军事提炼方案')}${militaryProfileControl('write','军事写文方案')}<button class="btn small primary" data-military="save">保存军事执行方案</button></div></section>`;
 return beforeMilitaryRules().replace('<div class="tabs">',card+'<div class="tabs">');
};
const beforeMilitaryMeter=updateArticleMeter;
updateArticleMeter=function(){
 if(!militaryRow(articleDetail))return beforeMilitaryMeter();
 const t=document.querySelector('#article-edit-title'),a=document.querySelector('#article-edit-body'),m=document.querySelector('#article-editor-meter');if(!t||!a||!m)return;
 const count=[...(t.value+a.value).replace(/\s/g,'')].length,paragraphs=a.value.split(/\r?\n/).filter(p=>p.trim()).length;
 m.textContent=`军事C · 可见文字 ${count}/201–300字 · ${paragraphs}个自然段 · 标题不单限64字 · HTML标签不计字数${editorDirty?' · 尚未保存':''}`;
 m.className='editor-meter'+(count<201||count>300||!/[？?]\s*$/.test(a.value)?' invalid':'');
};
const beforeMilitaryDraw=drawArticle;
drawArticle=function(){beforeMilitaryDraw();if(!militaryRow(articleDetail))return;let data={};try{data=JSON.parse(articleDetail.data_json);}catch{}
 const body=document.querySelector('.article-drawer .drawer-content');if(!body)return;
 const audit=data.military_audit;if(audit&&articleTab==='read')body.insertAdjacentHTML('beforeend',`<details><summary>查看军事初稿与自改记录</summary><h3>${esc(audit.draft_title||'初稿')}</h3><div style="white-space:pre-wrap">${esc(audit.draft_article||'')}</div><h3>实际改动</h3><ul>${(audit.edit_notes||[]).map(n=>`<li>${esc(n)}</li>`).join('')}</ul><h3>材料缺口</h3><ul>${(audit.material_notes||[]).map(n=>`<li>${esc(n)}</li>`).join('')||'<li>未记录新增缺口</li>'}</ul></details>`);
};
document.addEventListener('click',async event=>{const b=event.target.closest('[data-military]');if(!b)return;event.stopImmediatePropagation();b.disabled=true;
 try{if(b.dataset.military==='save'){await api('/settings',{military_extract_variant:document.querySelector('#military-extract-variant').value,military_write_variant:document.querySelector('#military-write-variant').value});state.settings=await api('/settings');toast('军事执行方案已保存');}
 else if(b.dataset.military==='export'){const path=await window.desktop.saveFile('军事HTML');if(path){await api('/export',{path,kind:'military_html',ids:[Number(b.dataset.id)]});toast('军事HTML已导出，原稿未改动');}}}
 catch(error){toast(error.message,true);}finally{if(b.isConnected)b.disabled=false;}
});
const militaryDevLabel=new URLSearchParams(location.search).get('devLabel');if(militaryDevLabel){document.title=militaryDevLabel;document.querySelector('.version').textContent=militaryDevLabel;}
