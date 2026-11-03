function relaySettingsPanel(s){
  const field=(label,key,hint='',min='',max='',step='1')=>`<div class="field"><label for="${key}">${label}</label><input id="${key}" type="number" value="${esc(s[key])}" min="${min}" max="${max}" step="${step}"><small>${hint}</small></div>`;
  return `<div class="relay-note"><strong>沿用 FunnyComicTitleGenerator 的API调用方式</strong><p>流式接收文案、多个Key轮询。分类、提炼和生文仍使用本工作台的规则。</p><button class="btn small" data-relay-action="import-reference">导入原项目API配置</button></div>
  <div class="field"><label for="api_base">GPT URL / API基础地址</label><input id="api_base" value="${esc(s.api_base)}" placeholder="https://服务地址/v1"><small>支持基础地址或完整的 /chat/completions 地址。</small></div>
  <div class="form-grid"><div class="field"><label for="api_model">模型</label><div class="relay-model-row"><input id="api_model" list="api-model-options" value="${esc(s.api_model)}"><button class="btn small" data-relay-action="models">拉取模型列表</button></div><datalist id="api-model-options">${(s.api_model_options||[]).map(model=>`<option value="${esc(model)}"></option>`).join('')}</datalist><small>可直接输入模型名称，也可从已拉取列表选择。</small></div><div class="field"><label for="api_protocol">接口模式</label><select id="api_protocol"><option value="chat" ${s.api_protocol==='chat'?'selected':''}>Chat Completions · 原项目流式方式</option><option value="responses" ${s.api_protocol==='responses'?'selected':''}>Responses · 保留兼容模式</option></select></div></div>
  <div class="field"><label for="api_key">API Keys · 每行一个</label><textarea id="api_key" class="relay-key-input" autocomplete="off" spellcheck="false" style="-webkit-text-security:disc" placeholder="${s.api_key_saved?'已加密保存'+s.api_key_count+'个Key，留空保留；输入新内容会替换':'每行输入一个API Key'}"></textarea><div class="relay-key-actions"><label><input id="relay-show-key" type="checkbox"> 显示本次输入</label><small>已保存 ${num(s.api_key_count)} 个Key，保存后按请求轮询使用</small>${s.api_key_saved?'<button class="text-btn" data-relay-action="clear-keys">清除已保存Key</button>':''}</div></div>
  <div class="form-grid">${field('Temperature','api_temperature','与原项目一致，默认0.7','0','2','.1')}${field('响应等待上限（秒）','api_timeout','默认300秒','30','3600')}${field('本步骤失败重试次数','api_retry_count','默认1次，可设0—3；临时错误退避重试，余额不足立即暂停','0','3')}</div>
  <details class="relay-compat"><summary>连接兼容设置</summary><label><input id="api_skip_tls_verify" type="checkbox" ${s.api_skip_tls_verify?'checked':''}> 忽略HTTPS证书校验（兼容原项目）</label><p>常规连接保留证书校验；已有接口环境确需兼容时启用。</p></details>
  <div class="relay-test-row"><button class="btn small" data-relay-action="test">测试连接</button><span>测试会向每个Key发送一条简短请求；保存配置不调用模型。</span></div>`;
}
async function relayAction(action,button){
  button.disabled=true;
  try{
    if(action==='import-reference'){
      const r=await api('/provider/import-reference',{});state.settings=await api('/settings');updateProvider();await render();toast(r.message);return;
    }
    if(action==='clear-keys'){
      await api('/settings',{clear_api_key:true});state.settings=await api('/settings');await render();toast('已清除本工作台保存的API Keys');return;
    }
    await saveSettings();
    if(action==='test'){
      const r=await api('/provider/check',{});toast(r.message,!r.ok);return;
    }
    if(action==='models'){
      const r=await api('/provider/models',{});state.settings=await api('/settings');await render();toast(`已获取${r.models.length}个模型${r.errors.length?'，部分Key未返回列表':''}`);
    }
  }finally{if(button.isConnected)button.disabled=false}
}
document.addEventListener('click',async event=>{const button=event.target.closest('[data-relay-action]');if(button)try{await relayAction(button.dataset.relayAction,button)}catch(error){toast(error.message,true)}});
document.addEventListener('change',event=>{if(event.target.id==='relay-show-key'){const input=document.getElementById('api_key');if(input)input.style.webkitTextSecurity=event.target.checked?'none':'disc'}});
