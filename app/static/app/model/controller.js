(function (root, factory) { const api = factory(root); if (typeof module === "object" && module.exports) module.exports = api; root.FabModelController = api; })(globalThis, (root) => {
  function createModelController(deps = {}) {
    const { state, $, escapeHtml, api, showToast, updateSystemStatus, thinkingControl, windowImpl = root, alertImpl = root.alert } = deps;
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
  const toggle = $('#thinkingToggle');
  const next = thinkingControl.reconcile(state.modelConfig, toggle.getAttribute('aria-pressed') === 'true');
  toggle.setAttribute('aria-pressed', String(next.enabled));
  toggle.setAttribute('aria-disabled', String(!next.supported));
  toggle.title = next.supported ? (next.enabled ? '已开启 Thinking' : '开启 Thinking') : '当前模型不支持 Thinking';
}

function thinkingEnabled() {
  return thinkingControl.reconcile(state.modelConfig, $('#thinkingToggle').getAttribute('aria-pressed') === 'true').enabled;
}

function toggleThinking() {
  const toggle = $('#thinkingToggle');
  if (!thinkingControl.supportsThinking(state.modelConfig)) {
    showToast('当前模型不支持 Thinking，已保持关闭');
    return;
  }
  toggle.setAttribute('aria-pressed', String(!thinkingEnabled()));
  syncThinkingToggle();
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

    return { renderModelConfig, syncThinkingToggle, thinkingEnabled, toggleThinking, loadModelConfig, openModelSettings, saveModelSettings };
  }
  return { createModelController };
});
