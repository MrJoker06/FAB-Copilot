const adminState = { token: sessionStorage.getItem('fabInsightAdminToken') || '', activeView: 'runtime', refreshTimer: null };
const $ = selector => document.querySelector(selector);
const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]));
const formatNumber = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString('zh-CN') : '—';
const formatDate = value => value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '—';
const statusLabels = {running:'运行中', idle:'空闲', error:'异常', offline:'离线', published:'已发布', retired:'已停用', success:'成功'};

class AdminApiError extends Error {
  constructor(message, status = 0) { super(message); this.status = status; }
}

async function adminApi(url, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set('Authorization', `Bearer ${adminState.token}`);
  headers.set('X-Tenant-ID', 'platform');
  headers.set('X-User-ID', 'administrator');
  headers.set('X-Roles', 'admin');
  let response;
  try { response = await fetch(url, {...options, headers}); }
  catch { throw new AdminApiError('无法连接管理服务'); }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail;
    const message = typeof detail === 'string' ? detail : detail?.message || '管理请求失败';
    throw new AdminApiError(message, response.status);
  }
  return payload;
}

function setConnection(connected) {
  $('#adminConnection').classList.toggle('connected', connected);
  $('#adminConnection').lastChild.textContent = connected ? '已连接' : '未连接';
}

function showToast(message) {
  const toast = $('#adminToast');
  toast.textContent = message; toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { toast.hidden = true; }, 3800);
}

function showNotice(selector, message, error = false) {
  const notice = $(selector); notice.textContent = message; notice.classList.toggle('error', error); notice.hidden = !message;
}

function showAuth(message = '') {
  setConnection(false);
  $('#adminAuthMessage').textContent = message;
  $('#adminAuthMessage').hidden = !message;
  if (!$('#adminAuthDialog').open) $('#adminAuthDialog').showModal();
}

function statusChip(status) {
  const normalized = statusLabels[status] ? status : 'offline';
  return `<span class="status-chip status-${normalized}">${statusLabels[normalized]}</span>`;
}

function successRate(user) {
  const runs = Number(user.run_count) || 0;
  return runs ? `${((Number(user.success_runs) || 0) * 100 / runs).toFixed(1)}%` : '—';
}

function renderOverview(data) {
  const summary = data.summary || {};
  const agent = data.agent || {};
  const kpis = [
    ['用户', summary.users, `${summary.online_users || 0} 在线`],
    ['运行中', summary.running_users, '实时任务'],
    ['Agent Runs', summary.runs, `失败 ${summary.failed_runs || 0}`],
    ['成功率', agent.success_rate_pct, '%'],
    ['输入 Token', summary.input_tokens, '窗口累计'],
    ['输出 Token', summary.output_tokens, '窗口累计'],
  ];
  $('#runtimeKpis').innerHTML = kpis.map(([label, value, meta]) => `<div class="admin-kpi"><span>${escapeHtml(label)}</span><strong>${formatNumber(value)}</strong><small>${escapeHtml(meta)}</small></div>`).join('');
  $('#userStatusBody').innerHTML = (data.users || []).map(user => `<tr><td><div class="identity-cell"><strong>${escapeHtml(user.tenant_id)} / ${escapeHtml(user.user_id)}</strong><span>${escapeHtml(user.question_preview || user.session_id || '')}</span></div></td><td>${statusChip(user.status)}</td><td>${escapeHtml(user.model || '—')}</td><td>${formatNumber(user.session_count)}</td><td>${formatNumber(user.run_count)}</td><td>${successRate(user)}</td><td>${formatNumber((Number(user.input_tokens)||0) + (Number(user.output_tokens)||0))}</td><td>${formatDate(user.last_seen_at)}</td></tr>`).join('') || '<tr><td class="empty-row" colspan="8">当前窗口没有用户活动</td></tr>';
  $('#recentAdminRuns').innerHTML = (data.recent_runs || []).map(run => `<tr><td>${formatDate(run.completed_at)}</td><td><div class="identity-cell"><strong>${escapeHtml(run.tenant_id)} / ${escapeHtml(run.user_id)}</strong><span>${escapeHtml(run.run_id)}</span></div></td><td>${escapeHtml(run.session_title || run.session_id)}</td><td>${escapeHtml(run.model || '—')}</td><td>${statusChip(run.status)}</td><td>${run.duration_ms == null ? '—' : `${formatNumber(Math.round(run.duration_ms))} ms`}</td><td>${formatNumber((Number(run.input_tokens)||0) + (Number(run.output_tokens)||0))}</td></tr>`).join('') || '<tr><td class="empty-row" colspan="7">当前窗口没有运行记录</td></tr>';
  $('#runtimeWindow').textContent = `最近 ${data.window_hours} 小时 · 10 秒刷新`;
  $('#runtimeUpdated').textContent = `更新于 ${new Date(data.generated_at).toLocaleTimeString('zh-CN',{hour12:false})}`;
  $('#adminBuild').textContent = `${data.build?.version || 'unknown'} · ${data.build?.git_commit || ''}`;
}

async function loadOverview() {
  try {
    const data = await adminApi(`/api/admin/overview?hours=${$('#runtimeHours').value}&recent_limit=40`);
    renderOverview(data); setConnection(true); showNotice('#adminNotice', '');
  } catch (error) {
    if (error.status === 401 || error.status === 503) showAuth(error.message);
    else showNotice('#adminNotice', error.message, true);
    throw error;
  }
}

function renderModels(models) {
  const published = models.filter(model => model.status === 'published').length;
  $('#modelCatalogCount').textContent = `${models.length} 个版本 · ${published} 个可供用户选择`;
  $('#modelCatalogBody').innerHTML = models.map(model => `<tr><td><div class="identity-cell"><strong>${escapeHtml(model.display_name)}</strong><span>${escapeHtml(model.base_url)}</span></div></td><td>${escapeHtml(model.model_id)}</td><td>${escapeHtml(model.provider)}</td><td>${escapeHtml(model.provider_model)}</td><td>${formatNumber(model.selected_user_count)}</td><td>${statusChip(model.status)}</td><td>${formatDate(model.published_at)}</td><td><div class="catalog-actions"><button class="quiet-button" type="button" data-model-id="${escapeHtml(model.model_id)}" data-model-status="${model.status === 'published' ? 'retired' : 'published'}">${model.status === 'published' ? '停用' : '重新发布'}</button></div></td></tr>`).join('') || '<tr><td class="empty-row" colspan="8">模型目录为空</td></tr>';
}

async function loadModels() {
  try { renderModels(await adminApi('/api/admin/models')); setConnection(true); showNotice('#modelNotice', ''); }
  catch (error) { if (error.status === 401 || error.status === 503) showAuth(error.message); else showNotice('#modelNotice', error.message, true); throw error; }
}

async function publishModel(event) {
  event.preventDefault();
  const button = $('#confirmPublishModel'); button.disabled = true;
  $('#publishModelMessage').hidden = true;
  const payload = {
    model_id: $('#publishModelId').value.trim(), display_name: $('#publishDisplayName').value.trim(),
    provider: $('#publishProvider').value, provider_model: $('#publishProviderModel').value.trim(),
    base_url: $('#publishBaseUrl').value.trim(),
    capabilities: {streaming: $('#publishStreaming').checked, tool_calls: $('#publishToolCalls').checked},
  };
  try {
    await adminApi('/api/admin/models', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    $('#publishModelDialog').close(); $('#publishModelForm').reset(); $('#publishBaseUrl').value = 'https://api.deepseek.com'; $('#publishStreaming').checked = true; $('#publishToolCalls').checked = true;
    await loadModels(); showToast(`模型 ${payload.display_name} 已发布`);
  } catch (error) { $('#publishModelMessage').textContent = error.message; $('#publishModelMessage').hidden = false; }
  finally { button.disabled = false; }
}

async function updateModelStatus(modelId, status, button) {
  button.disabled = true;
  try {
    await adminApi(`/api/admin/models/${encodeURIComponent(modelId)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status})});
    await loadModels(); showToast(status === 'published' ? '模型已重新发布' : '模型已停用');
  } catch (error) { showNotice('#modelNotice', error.message, true); button.disabled = false; }
}

function showView(name) {
  adminState.activeView = name;
  document.querySelectorAll('.admin-view').forEach(view => view.classList.toggle('active', view.id === `${name}View`));
  document.querySelectorAll('.admin-nav').forEach(button => button.classList.toggle('active', button.dataset.adminView === name));
  if (name === 'models') loadModels().catch(() => {}); else loadOverview().catch(() => {});
}

async function authenticate(event) {
  event.preventDefault();
  adminState.token = $('#adminToken').value.trim();
  try {
    await loadOverview();
    sessionStorage.setItem('fabInsightAdminToken', adminState.token);
    $('#adminToken').value = ''; $('#adminAuthDialog').close(); setConnection(true);
  } catch { adminState.token = ''; sessionStorage.removeItem('fabInsightAdminToken'); }
}

function init() {
  document.querySelectorAll('[data-admin-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.adminView)));
  $('#adminAuthForm').addEventListener('submit', authenticate);
  $('#adminLogout').addEventListener('click', () => { adminState.token = ''; sessionStorage.removeItem('fabInsightAdminToken'); showAuth(); });
  $('#refreshRuntime').addEventListener('click', () => loadOverview().catch(() => {}));
  $('#runtimeHours').addEventListener('change', () => loadOverview().catch(() => {}));
  $('#refreshModels').addEventListener('click', () => loadModels().catch(() => {}));
  $('#openPublishModel').addEventListener('click', () => { $('#publishModelMessage').hidden = true; $('#publishModelDialog').showModal(); });
  $('#closePublishModel').addEventListener('click', () => $('#publishModelDialog').close());
  $('#cancelPublishModel').addEventListener('click', () => $('#publishModelDialog').close());
  $('#publishModelForm').addEventListener('submit', publishModel);
  $('#modelCatalogBody').addEventListener('click', event => { const button = event.target.closest('[data-model-id]'); if (button) updateModelStatus(button.dataset.modelId, button.dataset.modelStatus, button); });
  if (adminState.token) loadOverview().then(() => setConnection(true)).catch(() => {}); else showAuth();
  adminState.refreshTimer = window.setInterval(() => adminState.token && adminState.activeView === 'runtime' && loadOverview().catch(() => {}), 10000);
}

document.addEventListener('DOMContentLoaded', init);
