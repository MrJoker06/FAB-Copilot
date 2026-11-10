(function (root, factory) { const api = factory(root); if (typeof module === "object" && module.exports) module.exports = api; root.FabModelController = api; })(globalThis, (root) => {
  function createModelController(deps = {}) {
    const { state, $, escapeHtml, api, updateSystemStatus, thinkingControl, windowImpl = root, alertImpl = root.alert } = deps;
    const window = windowImpl, alert = alertImpl;
function renderModelConfig(config) {
  state.modelConfig = config;
  const activeLabel = config.display_name || config.model;
  $('#activeModelLabel').textContent = activeLabel;
  $('#agentMode').textContent = `${activeLabel} · 工具分析`;
  const select = $('#modelSelect');
  const options = config.model_options?.length ? config.model_options : config.allowed_models.map(model => ({model_id:model, display_name:model, provider_model:model}));
  select.innerHTML = options.map(model => `<option value="${escapeHtml(model.model_id)}" ${model.model_id === config.model ? 'selected' : ''}>${escapeHtml(model.display_name)} · ${escapeHtml(model.provider_model)}</option>`).join('');
  syncThinkingToggle();
}

function syncThinkingToggle() {
  const select = $('#thinkingEffort');
  const options = thinkingControl.options(state.modelConfig);
  select.innerHTML = options.map(item => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join('');
  const next = thinkingControl.reconcile(state.modelConfig, select.value || 'off');
  select.value = next.effort;
  select.disabled = !next.supported;
  select.title = next.supported ? '选择思考强度' : '当前模型不支持 Thinking';
}

function thinkingEffort() {
  return thinkingControl.reconcile(state.modelConfig, $('#thinkingEffort').value).effort;
}

function thinkingEnabled() {
  return thinkingEffort() !== 'off';
}

async function loadModelConfig() {
  const config = await api('/api/settings/model');
  renderModelConfig(config);
  return config;
}

async function openModelSettings() {
  const message = $('#modelSettingsMessage'); message.hidden = true; message.classList.remove('error');
  try { await loadModelConfig(); $('#modelDialog').showModal(); $('#modelSelect').focus(); }
  catch (error) { alert(`无法加载模型配置：${error.message}`); }
}

async function saveModelSettings(event) {
  event.preventDefault();
  const button = $('#saveModelSettings'), message = $('#modelSettingsMessage');
  const body = {model: $('#modelSelect').value};
  button.disabled = true; message.hidden = true;
  try {
    const config = await api('/api/settings/model', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    renderModelConfig(config);
    message.textContent = `已切换到 ${config.display_name || config.model}`; message.classList.remove('error'); message.hidden = false;
    updateSystemStatus(config.display_name || config.model);
    window.setTimeout(() => $('#modelDialog').open && $('#modelDialog').close(), 700);
  } catch (error) {
    message.textContent = error.message; message.classList.add('error'); message.hidden = false;
  } finally { button.disabled = false; }
}

    return { renderModelConfig, syncThinkingToggle, thinkingEnabled, thinkingEffort, loadModelConfig, openModelSettings, saveModelSettings };
  }
  return { createModelController };
});
