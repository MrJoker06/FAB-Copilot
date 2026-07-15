const state = { dashboard: null, history: [], sessionId: null, sessionLibrary: [], sessionLibraryFilter: 'active', selectedLibrarySessionId: null, sessionLibraryRequestId: 0, sessionLibraryPreviewRequestId: 0, pendingRenameSessionId: null, pendingDeleteSessionId: null, toastTimer: null, activeView: 'dashboard', previousView: 'dashboard', streaming: false, chartPoints: [], activeStep: 'CVD', monitorTimer: null, modelConfig: null, knowledgeDocuments: [], knowledgeIndexPromise: null, cases: [], casesPromise: null, capabilityCache: new Map(), capabilityController: null, capabilityRequestId: 0 };
const $ = (selector) => document.querySelector(selector);
const AGENT_WIDTH_KEY = 'fabInsightAgentWidth';
const AGENT_MIN_WIDTH = 300;
const AGENT_MAX_WIDTH = 620;
const processLabels = { LITHO: '光刻', ETCH: '刻蚀', CVD: '化学气相沉积', PVD: '物理气相沉积', DIFFUSION: '扩散/炉管', IMPLANT: '离子注入', CMP: '化学机械研磨', CLEAN: '湿法清洗', METROLOGY: '量测' };
const toolLabels = { get_fab_overview: '查询工厂总览', get_yield_trend: '查询良率趋势', get_equipment_health: '查询设备健康', get_equipment_productivity: '查询设备生产状态', get_process_capability: '查询制程能力', get_defect_pareto: '查询缺陷 Pareto', get_recent_excursions: '查询近期异常', get_sensor_summary: '查询传感器摘要', search_knowledge: '检索知识与案例', query_manufacturing_data: '执行制造数据查询' };

function isoDate(date) { return date.toISOString().slice(0, 10); }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function formatNumber(value) { const number = Number(value); return Number.isFinite(number) ? number.toLocaleString('zh-CN') : String(value ?? '—'); }

function setInitialDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - 89);
  $('#startDate').value = isoDate(start);
  $('#endDate').value = isoDate(end);
}

async function api(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `请求失败 (${response.status})`);
  return payload;
}

function dismissToast() {
  window.clearTimeout(state.toastTimer);
  state.toastTimer = null;
  $('#toastRegion').innerHTML = '';
}

function showToast(message, {actionLabel = '', onAction = null, tone = 'default', duration = 5200} = {}) {
  dismissToast();
  const toast = document.createElement('div');
  toast.className = `toast${tone === 'error' ? ' error' : ''}`;
  toast.innerHTML = `<span class="toast-message">${escapeHtml(message)}</span>${actionLabel ? `<button type="button" class="toast-action">${escapeHtml(actionLabel)}</button>` : ''}<button type="button" class="toast-close" aria-label="关闭提示">×</button>`;
  $('#toastRegion').appendChild(toast);
  toast.querySelector('.toast-close').addEventListener('click', dismissToast);
  toast.querySelector('.toast-action')?.addEventListener('click', async () => {
    dismissToast();
    try { await onAction?.(); }
    catch (error) { showToast(`操作失败：${error.message}`, {tone:'error'}); }
  });
  state.toastTimer = window.setTimeout(dismissToast, duration);
}

function sourceLink(source, label) {
  if (source.source_type === 'case' || source.case_id) return `<button class="citation-link" data-case-id="${escapeHtml(source.case_id)}">${escapeHtml(label)}</button>`;
  return `<button class="citation-link" data-knowledge-chunk="${Number(source.chunk_id)}">${escapeHtml(label)}</button>`;
}

function inlineMarkdown(value, sourceReferences = new Map()) {
  let text = escapeHtml(value);
  text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  text = text.replace(/\[来源(?:\s+chunk_id\s*:)?\s*([A-Za-z0-9,，、\-\s]+)\]/gi, (match, ids) => {
    const references = ids.split(/[,，、\s]+/).filter(Boolean).map(id => sourceReferences.get(id) || sourceReferences.get(`KB-${id}`)).filter(Boolean);
    return references.length ? references.map(source => sourceLink(source, `[来源 ${source.reference_id || `KB-${source.chunk_id}`}]`)).join(' ') : match;
  });
  return text;
}

function markdownCells(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
}

function renderMarkdown(markdown, sourceReferences = new Map()) {
  const lines = String(markdown || '').replace(/\r/g, '').split('\n');
  const output = [];
  let index = 0;
  const isBlockStart = line => /^(#{1,4})\s+/.test(line) || /^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line) || /^>\s?/.test(line) || /^```/.test(line) || /^\s*---+\s*$/.test(line);
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }
    if (/^```/.test(line)) {
      const code = []; index += 1;
      while (index < lines.length && !/^```/.test(lines[index])) { code.push(lines[index]); index += 1; }
      index += index < lines.length ? 1 : 0;
      output.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`); continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) { const level = Math.min(4, heading[1].length + 1); output.push(`<h${level}>${inlineMarkdown(heading[2], sourceReferences)}</h${level}>`); index += 1; continue; }
    if (/^\s*---+\s*$/.test(line)) { output.push('<hr>'); index += 1; continue; }
    if (line.includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) {
      const headers = markdownCells(line); index += 2; const rows = [];
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) { rows.push(markdownCells(lines[index])); index += 1; }
      output.push(`<div class="markdown-table-wrap"><table><thead><tr>${headers.map(cell => `<th>${inlineMarkdown(cell, sourceReferences)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${headers.map((_, i) => `<td>${inlineMarkdown(row[i] || '', sourceReferences)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`); continue;
    }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line), tag = ordered ? 'ol' : 'ul', items = [];
      const pattern = ordered ? /^\s*\d+\.\s+(.+)$/ : /^\s*[-*]\s+(.+)$/;
      while (index < lines.length) { const match = lines[index].match(pattern); if (!match) break; items.push(match[1]); index += 1; }
      output.push(`<${tag}>${items.map(item => `<li>${inlineMarkdown(item, sourceReferences)}</li>`).join('')}</${tag}>`); continue;
    }
    if (/^>\s?/.test(line)) {
      const quote = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) { quote.push(lines[index].replace(/^>\s?/, '')); index += 1; }
      output.push(`<blockquote>${quote.map(item => inlineMarkdown(item, sourceReferences)).join('<br>')}</blockquote>`); continue;
    }
    const paragraph = [line.trim()]; index += 1;
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index]) && !(lines[index].includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1]))) { paragraph.push(lines[index].trim()); index += 1; }
    output.push(`<p>${inlineMarkdown(paragraph.join(' '), sourceReferences)}</p>`);
  }
  return output.join('');
}

function renderKnowledgeDocuments(filter = '') {
  const query = filter.trim().toLowerCase();
  const documents = state.knowledgeDocuments.filter(doc => `${doc.title} ${doc.source} ${doc.sections}`.toLowerCase().includes(query));
  $('#knowledgeCount').textContent = `${documents.length} 份文档`;
  $('#knowledgeDocuments').innerHTML = documents.map(doc => `<button class="knowledge-document" data-knowledge-chunk="${doc.first_chunk_id}" title="${escapeHtml(doc.sections)}"><strong>${escapeHtml(doc.title)}</strong><span>${escapeHtml(doc.doc_type)} · v${escapeHtml(doc.version)} · ${doc.section_count} 章</span></button>`).join('') || '<p class="empty">没有匹配的文档</p>';
}

async function loadKnowledgeIndex() {
  if (!state.knowledgeDocuments.length) {
    state.knowledgeIndexPromise ||= api('/api/knowledge/documents');
    state.knowledgeDocuments = await state.knowledgeIndexPromise;
  }
  renderKnowledgeDocuments($('#knowledgeFilter').value);
  return state.knowledgeDocuments;
}

async function openKnowledgeChunk(chunkId) {
  showView('knowledge');
  await loadKnowledgeIndex();
  const payload = await api(`/api/knowledge/chunks/${chunkId}`);
  $('#knowledgeTitle').textContent = payload.document.title;
  $('#knowledgeSource').textContent = `${payload.document.source} · v${payload.document.version} · ${payload.document.status}`;
  $('#knowledgeContent').innerHTML = payload.chunks.map(chunk => `<section id="knowledge-chunk-${chunk.chunk_id}" class="knowledge-chunk ${chunk.chunk_id === Number(chunkId) ? 'target-chunk' : ''}"><h3>${escapeHtml(chunk.section)}</h3><div class="markdown-content">${renderMarkdown(chunk.content)}</div></section>`).join('');
  document.querySelectorAll('.knowledge-document').forEach(button => button.classList.toggle('active', Number(button.dataset.knowledgeChunk) === payload.chunks[0].chunk_id));
  window.setTimeout(() => document.querySelector(`#knowledge-chunk-${chunkId}`)?.scrollIntoView({behavior:'smooth', block:'start'}), 80);
}

function renderCaseList() {
  const query = $('#caseFilter').value.trim().toLowerCase();
  const step = $('#caseStepFilter').value;
  const cases = state.cases.filter(item => {
    const searchable = `${item.case_id} ${item.title} ${item.process_step} ${item.equipment_id || ''} ${item.problem} ${item.summary} ${item.tags}`.toLowerCase();
    return (!step || item.process_step === step) && (!query || searchable.includes(query));
  });
  $('#caseCount').textContent = `${cases.length} 个案例`;
  $('#caseList').innerHTML = cases.map(item => `<button class="case-list-item" data-case-id="${escapeHtml(item.case_id)}"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.case_id)} · ${escapeHtml(item.process_step)} · ${escapeHtml(item.occurred_date)}</span></button>`).join('') || '<p class="empty">没有匹配的历史案例</p>';
}

async function loadCaseIndex() {
  if (!state.cases.length) {
    state.casesPromise ||= api('/api/cases');
    state.cases = await state.casesPromise;
    const steps = [...new Set(state.cases.map(item => item.process_step))].sort();
    $('#caseStepFilter').insertAdjacentHTML('beforeend', steps.map(step => `<option value="${escapeHtml(step)}">${escapeHtml(step)}</option>`).join(''));
  }
  renderCaseList();
  return state.cases;
}

async function openHistoricalCase(caseId) {
  showView('cases');
  await loadCaseIndex();
  const item = await api(`/api/cases/${encodeURIComponent(caseId)}`);
  $('#caseReference').textContent = item.case_id;
  $('#caseTitle').textContent = item.title;
  $('#caseMeta').innerHTML = `<span>${escapeHtml(item.process_step)}</span>${item.equipment_id ? `<span>${escapeHtml(item.equipment_id)}</span>` : ''}<span>${escapeHtml(item.defect_type)}</span><span>${escapeHtml(item.occurred_date)}</span><span class="severity-${item.severity.toLowerCase()}">${escapeHtml(item.severity)}</span><span>${escapeHtml(item.case_status)}</span><span>RCA ${(Number(item.root_cause_confidence) * 100).toFixed(0)}%</span>`;
  const sections = [['问题', item.problem], ['解决方案', item.solution], ['解决结果', item.result], ['案例总结', item.summary]];
  $('#caseContent').innerHTML = `<div class="case-governance"><strong>已验证根因</strong><span>${escapeHtml(item.root_cause)}</span><small>${escapeHtml(item.validation_method)} · ${escapeHtml(item.recurrence_status)} · ${escapeHtml(item.approved_by)}</small></div>${sections.map(([title, content]) => `<section class="case-section"><h3>${title}</h3><p>${escapeHtml(content)}</p></section>`).join('')}`;
  document.querySelectorAll('.case-list-item').forEach(button => button.classList.toggle('active', button.dataset.caseId === caseId));
  document.querySelector('.case-reader')?.scrollIntoView({behavior:'smooth', block:'start'});
}

function renderModelConfig(config) {
  state.modelConfig = config;
  $('#activeModelLabel').textContent = config.model;
  $('#agentMode').textContent = `${config.model} · 工具分析`;
  $('#apiKeyState').textContent = config.api_key_configured ? `已配置 ${config.api_key_masked}` : '尚未配置 API Key';
  const select = $('#modelSelect');
  select.innerHTML = config.allowed_models.map(model => `<option value="${escapeHtml(model)}" ${model === config.model ? 'selected' : ''}>${escapeHtml(model)}</option>`).join('');
}

async function loadModelConfig() {
  const config = await api('/api/settings/model');
  renderModelConfig(config);
  return config;
}

async function openModelSettings() {
  const message = $('#modelSettingsMessage'); message.hidden = true; message.classList.remove('error');
  $('#apiKeyInput').value = ''; $('#apiKeyInput').type = 'password';
  try { await loadModelConfig(); $('#modelDialog').showModal(); }
  catch (error) { alert(`无法加载模型配置：${error.message}`); }
}

async function saveModelSettings(event) {
  event.preventDefault();
  const button = $('#saveModelSettings'), message = $('#modelSettingsMessage');
  const apiKey = $('#apiKeyInput').value.trim();
  const body = {model: $('#modelSelect').value};
  if (apiKey) body.api_key = apiKey;
  button.disabled = true; message.hidden = true;
  try {
    const config = await api('/api/settings/model', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    renderModelConfig(config); $('#apiKeyInput').value = '';
    message.textContent = `已切换到 ${config.model}`; message.classList.remove('error'); message.hidden = false;
    $('#systemStatus').textContent = `${formatNumber(state.dashboard?.overview?.lots ?? 0)} 批次 · ${config.model}`;
    window.setTimeout(() => $('#modelDialog').open && $('#modelDialog').close(), 700);
  } catch (error) {
    message.textContent = error.message; message.classList.add('error'); message.hidden = false;
  } finally { button.disabled = false; }
}

function renderKpis(data) {
  const items = [
    ['综合良率', data.yield_pct, '%', `${formatNumber(data.good_wafers)} 片良品`],
    ['完成批次', data.lots, '', `${formatNumber(data.wafers)} 片投产`],
    ['平均周期', data.avg_cycle_hours, 'h', `平均 Hold ${data.avg_hold_hours}h`],
    ['制程异常', data.excursions, '次', '控制计划规则触发'],
    ['Hold 批次', data.held_lots, '批', '当前查询窗口'],
  ];
  $('#kpiGrid').innerHTML = items.map(([label, value, unit, meta]) => `<div class="kpi"><span class="kpi-label">${label}</span><span class="kpi-value">${formatNumber(value)}<span class="kpi-unit">${unit}</span></span><span class="kpi-meta">${meta}</span></div>`).join('');
}

function renderEquipment(rows) {
  $('#equipmentCount').textContent = `${rows.length} 台设备`;
  $('#equipmentBody').innerHTML = rows.map(row => `<tr><td><strong>${escapeHtml(row.equipment_id)}</strong></td><td><span class="status-pill status-${row.health.toLowerCase()}">${row.health}</span></td><td>${formatNumber(row.runs)}</td><td class="${row.excursions >= 3 ? 'metric-alert' : ''}">${row.excursions}</td><td>${row.pass_pct}%</td><td>${formatNumber(row.downtime_minutes)}</td></tr>`).join('');
}

function renderDefects(rows) {
  const max = Math.max(...rows.map(row => row.defect_count), 1);
  $('#defectBars').innerHTML = rows.length ? rows.map(row => `<div class="bar-row"><span class="bar-label" title="${escapeHtml(row.defect_type)} · ${escapeHtml(row.process_steps)}">${escapeHtml(row.defect_type)}</span><span class="bar-track"><span class="bar-fill" style="width:${Math.max(3, row.defect_count / max * 100)}%"></span></span><span class="bar-value">${row.defect_count}</span></div>`).join('') : '<p class="empty">范围内没有缺陷记录</p>';
}

function renderExcursions(rows) {
  $('#excursionBody').innerHTML = rows.map(row => {
    const metric = row.measurement_value == null
      ? `缺陷密度 ${row.defect_density}`
      : `${row.measurement_name} ${row.measurement_value} ${row.measurement_unit}`;
    return `<tr><td>${escapeHtml(row.run_time.slice(0, 10))}</td><td>${escapeHtml(row.lot_id)}</td><td><strong>${escapeHtml(row.equipment_id)}</strong></td><td><span class="status-pill status-critical">${escapeHtml(row.excursion_code)}</span></td><td>${metric}</td></tr>`;
  }).join('') || '<tr><td colspan="5">范围内没有制程异常</td></tr>';
}

function drawYieldChart(rows) {
  const canvas = $('#yieldChart');
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, rect.width * dpr); canvas.height = Math.max(1, rect.height * dpr);
  const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
  const w = rect.width, h = rect.height, pad = {l: 42, r: 16, t: 12, b: 28};
  ctx.clearRect(0, 0, w, h); ctx.font = '9px Segoe UI'; ctx.lineWidth = 1;
  if (!rows.length) return;
  const values = rows.map(r => Number(r.yield_pct));
  const minY = Math.min(88, Math.floor(Math.min(...values) - 1));
  const maxY = Math.max(98, Math.ceil(Math.max(...values) + 1));
  const x = i => pad.l + (rows.length === 1 ? 0 : i * (w-pad.l-pad.r)/(rows.length-1));
  const y = v => pad.t + (maxY-v)*(h-pad.t-pad.b)/(maxY-minY);
  ctx.strokeStyle = '#e5eae8'; ctx.fillStyle = '#7b8784';
  for (let tick=minY; tick<=maxY; tick+=2) { ctx.beginPath(); ctx.moveTo(pad.l,y(tick)); ctx.lineTo(w-pad.r,y(tick)); ctx.stroke(); ctx.fillText(`${tick}%`,4,y(tick)+3); }
  ctx.setLineDash([4,4]); ctx.strokeStyle='#c4944d'; ctx.beginPath(); ctx.moveTo(pad.l,y(90)); ctx.lineTo(w-pad.r,y(90)); ctx.stroke(); ctx.setLineDash([]);
  ctx.beginPath(); rows.forEach((r,i) => i ? ctx.lineTo(x(i),y(Number(r.yield_pct))) : ctx.moveTo(x(i),y(Number(r.yield_pct)))); ctx.strokeStyle='#087f70'; ctx.lineWidth=2; ctx.stroke();
  ctx.fillStyle='#087f70'; rows.forEach((r,i) => { ctx.beginPath(); ctx.arc(x(i),y(Number(r.yield_pct)),2.5,0,Math.PI*2); ctx.fill(); });
  const labelEvery = Math.max(1, Math.ceil(rows.length / 7)); ctx.fillStyle='#7b8784';
  rows.forEach((r,i) => { if (i % labelEvery === 0 || i === rows.length-1) ctx.fillText(r.week_start.slice(5), x(i)-12, h-7); });
  state.chartPoints = rows.map((r,i) => ({x:x(i), y:y(Number(r.yield_pct)), row:r}));
}

async function loadDashboard() {
  const start = $('#startDate').value, end = $('#endDate').value;
  $('#errorBanner').hidden = true;
  try {
    const data = await api(`/api/reports/dashboard?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
    state.dashboard = data;
    renderKpis(data.overview); renderEquipment(data.equipment); renderDefects(data.defects); renderExcursions(data.excursions); drawYieldChart(data.yield_trend);
    $('#rangeSummary').textContent = `${start} 至 ${end} · ${formatNumber(data.overview.lots)} 个批次`;
  } catch (error) { $('#errorBanner').textContent = error.message; $('#errorBanner').hidden = false; }
}

function capabilityRating(cpk) {
  if (cpk == null) return ['无数据', ''];
  if (cpk < 1.33) return ['能力不足', 'metric-alert'];
  if (cpk < 1.67) return ['观察', ''];
  return ['稳定', 'metric-good'];
}

async function loadCapability(step = state.activeStep) {
  state.activeStep = step;
  const start = $('#startDate').value, end = $('#endDate').value;
  const cacheKey = `${step}:${start}:${end}`;
  const table = $('#capabilityBody').closest('table');
  state.capabilityController?.abort();
  state.capabilityController = null;
  const requestId = ++state.capabilityRequestId;
  table.removeAttribute('aria-busy');
  table.classList.remove('table-loading');
  const cachedRows = state.capabilityCache.get(cacheKey);
  if (cachedRows) { renderCapability(step, cachedRows); return; }

  const controller = new AbortController();
  state.capabilityController = controller;
  table.setAttribute('aria-busy', 'true');
  table.classList.add('table-loading');
  $('#capabilityMetric').textContent = '正在计算制程能力…';
  try {
    const rows = await api(`/api/reports/capability?process_step=${encodeURIComponent(step)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`, {signal: controller.signal});
    if (requestId !== state.capabilityRequestId) return;
    state.capabilityCache.set(cacheKey, rows);
    renderCapability(step, rows);
  } catch (error) {
    if (error.name === 'AbortError') return;
    if (requestId === state.capabilityRequestId) $('#capabilityMetric').textContent = `读取失败：${error.message}`;
  } finally {
    if (requestId === state.capabilityRequestId) {
      table.removeAttribute('aria-busy');
      table.classList.remove('table-loading');
      state.capabilityController = null;
    }
  }
}

function renderCapability(step, rows) {
  const metric = rows[0];
  $('#capabilityTitle').textContent = `${processLabels[step] || step} · ${metric?.metric_name || '关键量测'}能力`;
  const lower = metric?.spec_lsl == null ? null : `LSL ${metric.spec_lsl}`;
  const upper = metric?.spec_usl == null ? null : `USL ${metric.spec_usl}`;
  const specification = [lower, upper].filter(Boolean).join(' / ');
  $('#capabilityMetric').textContent = metric ? `${specification} ${metric.metric_unit}；Cpk < 1.33 需关注` : '当前范围没有可用量测';
  $('#capabilityBody').innerHTML = rows.map(row => { const [rating, cls] = capabilityRating(row.cpk); return `<tr><td><strong>${row.equipment_id}</strong></td><td>${row.samples}</td><td>${row.mean_value}</td><td>${row.sigma}</td><td>${row.min_value}</td><td>${row.max_value}</td><td class="${cls}">${row.cpk ?? '—'}</td><td class="${cls}">${rating}</td></tr>`; }).join('') || '<tr><td colspan="8" class="empty">当前范围没有可用量测</td></tr>';
}

function formatDuration(milliseconds) {
  if (milliseconds == null) return '—';
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  return `${(milliseconds / 1000).toFixed(2)} s`;
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall through when Clipboard API exists but the browser denies permission.
    }
  }
  const textarea = document.createElement('textarea');
  textarea.value = text; textarea.setAttribute('readonly', ''); textarea.style.position = 'fixed'; textarea.style.opacity = '0';
  document.body.appendChild(textarea); textarea.select();
  const copied = document.execCommand('copy'); textarea.remove();
  if (!copied) throw new Error('浏览器未允许复制');
}

function renderToolTrace(trace, runId) {
  if (!trace?.length) return '';
  const items = trace.map((item, index) => {
    const status = item.status === 'error' ? '失败' : (item.status === 'local' ? '本地' : (item.status === 'running' ? '进行中' : '成功'));
    const result = item.rows == null ? status : `${status} · ${item.rows} 条结果`;
    const argumentsText = item.arguments && Object.keys(item.arguments).length
      ? Object.entries(item.arguments).map(([key, value]) => `${key}=${typeof value === 'string' ? value : JSON.stringify(value)}`).join(' · ')
      : '使用默认参数';
    const error = item.error ? `<p class="trace-error">${escapeHtml(item.error)}</p>` : '';
    const statusClass = item.status === 'error' ? 'error' : (item.status === 'running' ? 'running' : 'ok');
    return `<li><div class="trace-step-heading"><span>${index + 1}. ${escapeHtml(item.label || toolLabels[item.tool] || item.tool || '未知工具')}</span><small class="trace-status-${statusClass}">${result}</small></div><code>${escapeHtml(argumentsText)}</code>${error}</li>`;
  }).join('');
  const failed = trace.some(item => item.status === 'error');
  const duration = trace.reduce((sum, item) => sum + Number(item.duration_ms || 0), 0);
  const summary = failed ? `执行路径异常 · ${trace.length} 个工具` : `执行路径已完成 · ${trace.length} 个工具${duration ? ` · ${formatDuration(duration)}` : ''}`;
  const runLabel = runId ? `<span title="${escapeHtml(runId)}">运行 ${escapeHtml(runId.slice(0, 8))}</span>` : '';
  return `<details class="analysis-trace" ${failed ? 'open' : ''}><summary><span>${summary}</span><small>可展开</small></summary><ol>${items}</ol><div class="trace-footer"><span>可审计工具路径，不包含模型内部草稿</span>${runLabel}</div></details>`;
}

function welcomeMarkup(message = '我可以查询制造报表、定位设备异常，并结合厂内 SOP 给出分析建议。') {
  return `<div class="message assistant"><div class="message-meta"><div class="message-label">FAB COPILOT</div></div><div class="message-content">${escapeHtml(message)}</div></div><div class="suggestions"><button>最近三个月哪些设备风险最高？</button><button>CVD-02 的膜厚是否发生漂移？</button><button>分析刻蚀设备 CD 偏移的潜在原因</button></div>`;
}

function renderConversation(messages = []) {
  const container = $('#chatMessages'); container.innerHTML = ''; state.history = [];
  if (!messages.length) { container.innerHTML = welcomeMarkup(); return; }
  for (const item of messages) {
    addMessage(item.role, item.content, item.metadata || {});
    state.history.push({role:item.role, content:item.content});
  }
}

async function createConversation(message) {
  const session = await api('/api/sessions', {method:'POST'});
  state.sessionId = session.session_id; state.history = [];
  localStorage.setItem('fabInsightSessionId', state.sessionId);
  renderConversation([]);
  if (message) $('#chatMessages').innerHTML = welcomeMarkup(message);
  return session;
}

async function restoreConversation() {
  const savedSessionId = localStorage.getItem('fabInsightSessionId');
  if (savedSessionId) {
    try {
      const session = await api(`/api/sessions/${encodeURIComponent(savedSessionId)}`);
      state.sessionId = session.session_id; renderConversation(session.messages);
      $('#agentMode').textContent = session.messages.length ? `已恢复 · ${session.messages.length} 条消息` : '数据分析助手';
      return;
    } catch { localStorage.removeItem('fabInsightSessionId'); }
  }
  await createConversation();
}

function sessionGroup(timestamp) {
  const value = new Date(timestamp);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const day = new Date(value); day.setHours(0, 0, 0, 0);
  const distance = Math.round((today - day) / 86400000);
  if (distance === 0) return '今天';
  if (distance === 1) return '昨天';
  if (distance < 7) return '最近 7 天';
  return '更早';
}

async function openSession(sessionId) {
  const session = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
  state.sessionId = session.session_id;
  localStorage.setItem('fabInsightSessionId', state.sessionId);
  renderConversation(session.messages);
  $('#agentMode').textContent = session.messages.length ? `已恢复 · ${session.messages.length} 条消息` : '数据分析助手';
}

function filteredSessionLibrary() {
  if (state.sessionLibraryFilter === 'archived') return state.sessionLibrary.filter(item => item.archived_at);
  if (state.sessionLibraryFilter === 'active') return state.sessionLibrary.filter(item => !item.archived_at);
  return state.sessionLibrary;
}

function renderSessionLibrary() {
  const sessions = filteredSessionLibrary();
  const groups = new Map();
  for (const session of sessions) {
    const group = sessionGroup(session.updated_at);
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(session);
  }
  const archivedCount = state.sessionLibrary.filter(item => item.archived_at).length;
  $('#sessionLibraryCount').textContent = `${sessions.length} 个结果 · ${archivedCount} 个已归档`;
  $('#sessionLibraryNotice').textContent = state.sessionLibraryFilter === 'archived'
    ? '已归档会话仍保存在 AI 运营库中；恢复后会重新出现在活跃会话中。'
    : state.sessionLibraryFilter === 'all'
      ? '这里同时显示活跃与归档会话；归档可以恢复，永久删除无法撤销。'
      : '归档只会将会话移出活跃列表；永久删除会移除全部消息和分析记录。';
  $('#sessionLibraryList').innerHTML = [...groups.entries()].map(([group, items]) => `
    <section class="session-library-group"><h3>${group}</h3>${items.map(session => {
      const active = session.session_id === state.selectedLibrarySessionId ? ' active' : '';
      const timestamp = new Date(session.updated_at).toLocaleString('zh-CN', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false});
      const archived = Boolean(session.archived_at);
      const actions = archived
        ? '<button type="button" data-library-action="restore">恢复会话</button><button type="button" class="danger-action" data-library-action="delete">永久删除</button>'
        : '<button type="button" data-library-action="rename">重命名</button><button type="button" data-library-action="archive">归档</button><button type="button" class="danger-action" data-library-action="delete">永久删除</button>';
      return `<article class="session-library-item${active}" data-library-session-id="${escapeHtml(session.session_id)}"><button class="session-library-open" type="button"><strong>${escapeHtml(session.title)}</strong><span>${timestamp} · ${session.message_count} 条消息${session.model ? ` · ${escapeHtml(session.model)}` : ''}</span><small>${escapeHtml(session.last_message_preview || '空会话')}</small></button><span class="session-state${archived ? ' archived' : ''}">${archived ? '已归档' : '活跃'}</span><details class="session-item-menu"><summary title="会话操作" aria-label="会话操作">⋯</summary><div>${actions}</div></details></article>`;
    }).join('')}</section>`).join('') || '<p class="empty session-empty">没有匹配的历史会话</p>';
}

function renderSessionLibraryPreview(session) {
  state.selectedLibrarySessionId = session.session_id;
  renderSessionLibrary();
  $('#sessionLibraryReference').textContent = `CONVERSATION · ${session.session_id.slice(0, 8)}`;
  $('#sessionLibraryTitle').textContent = session.title;
  const created = new Date(session.created_at).toLocaleString('zh-CN', {hour12:false});
  const updated = new Date(session.updated_at).toLocaleString('zh-CN', {hour12:false});
  $('#sessionLibraryMeta').innerHTML = `<span>${session.archived_at ? '已归档' : '活跃会话'}</span><span>${session.messages.length} 条消息</span>${session.model ? `<span>${escapeHtml(session.model)}</span>` : ''}<span>创建 ${created}</span><span>更新 ${updated}</span>`;
  $('#sessionLibraryActions').hidden = false;
  $('#archiveLibrarySession').textContent = session.archived_at ? '恢复会话' : '归档';
  $('#deleteLibrarySession').hidden = false;
  $('#continueLibrarySession').textContent = session.archived_at ? '恢复并继续' : '在助手中继续';
  $('#sessionLibraryMessages').innerHTML = session.messages.map(item => {
    const assistant = item.role === 'assistant';
    const sourceReferences = new Map();
    for (const source of (item.metadata?.sources || [])) {
      if (source.reference_id) sourceReferences.set(source.reference_id, source);
      if (source.chunk_id) sourceReferences.set(String(source.chunk_id), source);
    }
    const content = assistant ? renderMarkdown(item.content, sourceReferences) : escapeHtml(item.content).replace(/\n/g, '<br>');
    const timestamp = new Date(item.created_at).toLocaleString('zh-CN', {hour12:false});
    const sources = assistant && item.metadata?.sources?.length
      ? `<div class="source-list"><strong>知识来源</strong>${item.metadata.sources.map(source => sourceLink(source, `[来源 ${source.reference_id || `KB-${source.chunk_id}`}] ${source.source || ''} · ${source.section || ''}`)).join('')}</div>`
      : '';
    return `<section class="session-transcript-item ${assistant ? 'assistant' : 'user'}"><div class="session-transcript-heading"><strong>${assistant ? 'FAB COPILOT' : '使用者'}</strong><time>${timestamp}</time></div><div class="session-transcript-content markdown-content">${content}${sources}</div></section>`;
  }).join('') || '<p class="empty">该会话尚无消息。</p>';
}

async function openSessionLibraryPreview(sessionId) {
  const requestId = ++state.sessionLibraryPreviewRequestId;
  const session = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
  if (requestId !== state.sessionLibraryPreviewRequestId) return;
  renderSessionLibraryPreview(session);
}

async function loadSessionLibrary(query = $('#sessionLibrarySearch').value) {
  const requestId = ++state.sessionLibraryRequestId;
  const sessions = await api(`/api/sessions?q=${encodeURIComponent(query)}&limit=200&include_archived=true`);
  if (requestId !== state.sessionLibraryRequestId) return;
  state.sessionLibrary = sessions;
  const visible = filteredSessionLibrary();
  const selected = visible.find(item => item.session_id === state.selectedLibrarySessionId) || visible[0];
  if (selected) await openSessionLibraryPreview(selected.session_id);
  else {
    state.selectedLibrarySessionId = null;
    renderSessionLibrary();
    $('#sessionLibraryReference').textContent = 'CONVERSATION';
    $('#sessionLibraryTitle').textContent = '选择一个历史会话';
    $('#sessionLibraryMeta').innerHTML = '';
    $('#sessionLibraryActions').hidden = true;
    $('#deleteLibrarySession').hidden = true;
    $('#sessionLibraryMessages').innerHTML = '<p class="empty">当前筛选条件下没有会话。</p>';
  }
}

function updateSessionRenameCount() {
  $('#sessionRenameCount').textContent = `${$('#sessionRenameInput').value.length} / 80`;
}

function openSessionRenameDialog(sessionId = state.selectedLibrarySessionId) {
  const session = state.sessionLibrary.find(item => item.session_id === sessionId);
  if (!session) return;
  state.pendingRenameSessionId = session.session_id;
  $('#sessionRenameInput').value = session.title;
  $('#sessionRenameMessage').hidden = true;
  updateSessionRenameCount();
  $('#sessionRenameDialog').showModal();
  requestAnimationFrame(() => $('#sessionRenameInput').select());
}

async function renameSelectedLibrarySession() {
  if ($('#confirmSessionRename').disabled) return;
  const sessionId = state.pendingRenameSessionId;
  const session = state.sessionLibrary.find(item => item.session_id === sessionId);
  const title = $('#sessionRenameInput').value.trim();
  if (!session) return;
  if (!title) {
    $('#sessionRenameMessage').textContent = '会话标题不能为空。';
    $('#sessionRenameMessage').hidden = false;
    $('#sessionRenameInput').focus();
    return;
  }
  if (title === session.title) {
    $('#sessionRenameDialog').close();
    return;
  }
  $('#confirmSessionRename').disabled = true;
  $('#sessionRenameMessage').hidden = true;
  try {
    await api(`/api/sessions/${encodeURIComponent(session.session_id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title})});
    $('#sessionRenameDialog').close();
    await loadSessionLibrary();
    showToast('会话已重命名');
  } catch (error) {
    $('#sessionRenameMessage').textContent = `保存失败：${error.message}`;
    $('#sessionRenameMessage').hidden = false;
  } finally {
    $('#confirmSessionRename').disabled = false;
  }
}

function resetConversationDraft(message = '已准备新会话。') {
  state.sessionId = null;
  state.history = [];
  localStorage.removeItem('fabInsightSessionId');
  renderConversation([]);
  $('#agentMode').textContent = message;
}

async function archiveLibrarySession(sessionId) {
  const session = state.sessionLibrary.find(item => item.session_id === sessionId);
  if (!session || session.archived_at) return;
  const wasCurrent = session.session_id === state.sessionId;
  await api(`/api/sessions/${encodeURIComponent(session.session_id)}`, {method:'DELETE'});
  if (wasCurrent) resetConversationDraft('当前会话已归档');
  state.selectedLibrarySessionId = null;
  const refresh = loadSessionLibrary();
  showToast(`已归档“${session.title}”`, {
    actionLabel: '撤销',
    onAction: async () => {
      await api(`/api/sessions/${encodeURIComponent(session.session_id)}/restore`, {method:'POST'});
      state.selectedLibrarySessionId = session.session_id;
      if (wasCurrent) await openSession(session.session_id);
      await loadSessionLibrary();
      showToast('已撤销归档');
    },
  });
  await refresh;
}

async function restoreLibrarySession(sessionId) {
  const session = state.sessionLibrary.find(item => item.session_id === sessionId);
  if (!session || !session.archived_at) return;
  await api(`/api/sessions/${encodeURIComponent(session.session_id)}/restore`, {method:'POST'});
  state.selectedLibrarySessionId = null;
  const refresh = loadSessionLibrary();
  showToast(`已恢复“${session.title}”`, {
    actionLabel: '撤销',
    onAction: async () => {
      await api(`/api/sessions/${encodeURIComponent(session.session_id)}`, {method:'DELETE'});
      if (session.session_id === state.sessionId) resetConversationDraft('当前会话已归档');
      await loadSessionLibrary();
      showToast('已撤销恢复');
    },
  });
  await refresh;
}

function openSessionDeleteDialog(sessionId) {
  const session = state.sessionLibrary.find(item => item.session_id === sessionId);
  if (!session) return;
  state.pendingDeleteSessionId = session.session_id;
  $('#sessionDeleteMessage').textContent = `“${session.title}”将从本系统中永久删除。`;
  $('#sessionDeleteDialog').showModal();
}

async function permanentlyDeleteSelectedSession() {
  const sessionId = state.pendingDeleteSessionId;
  const session = state.sessionLibrary.find(item => item.session_id === sessionId);
  if (!sessionId || !session) return;
  $('#confirmSessionDelete').disabled = true;
  try {
    await api(`/api/sessions/${encodeURIComponent(sessionId)}/permanent`, {method:'DELETE'});
    if (session.session_id === state.sessionId) resetConversationDraft('当前会话已删除');
    state.pendingDeleteSessionId = null;
    state.selectedLibrarySessionId = null;
    $('#sessionDeleteDialog').close();
    const refresh = loadSessionLibrary();
    showToast(`已永久删除“${session.title}”`);
    await refresh;
  } finally {
    $('#confirmSessionDelete').disabled = false;
  }
}

async function runSessionLibraryAction(sessionId, action) {
  state.selectedLibrarySessionId = sessionId;
  try {
    if (action === 'rename') openSessionRenameDialog(sessionId);
    else if (action === 'archive') await archiveLibrarySession(sessionId);
    else if (action === 'restore') await restoreLibrarySession(sessionId);
    else if (action === 'delete') openSessionDeleteDialog(sessionId);
  } catch (error) {
    showToast(`操作失败：${error.message}`, {tone:'error'});
  }
}

async function toggleSelectedLibrarySessionArchive() {
  const session = state.sessionLibrary.find(item => item.session_id === state.selectedLibrarySessionId);
  if (!session) return;
  await runSessionLibraryAction(session.session_id, session.archived_at ? 'restore' : 'archive');
}

async function continueSelectedLibrarySession() {
  const session = state.sessionLibrary.find(item => item.session_id === state.selectedLibrarySessionId);
  if (!session || state.streaming) return;
  if (session.archived_at) {
    await api(`/api/sessions/${encodeURIComponent(session.session_id)}/restore`, {method:'POST'});
    showToast('会话已恢复到活跃列表');
  }
  await openSession(session.session_id);
  showView(state.previousView || 'dashboard');
  setAgentOpen(true);
}

function openSessionLibraryWorkspace() {
  if (state.streaming) return;
  showView('sessions');
  if (window.innerWidth <= 700) setAgentOpen(false, false);
  $('#sessionsView').scrollIntoView({behavior:'smooth', block:'start'});
}

function closeSessionLibraryWorkspace() {
  showView(state.previousView || 'dashboard');
}

function createLiveAnalysis() {
  const el = document.createElement('div'); el.className = 'message assistant live-analysis';
  el.innerHTML = '<div class="message-meta"><div class="message-label">FAB COPILOT · 分析中</div><span class="live-indicator">运行中</span></div><details class="live-path" open><summary><span class="live-path-title">正在建立分析路径</span><small class="live-path-count">准备中</small></summary><div class="live-path-body"><ol></ol><div class="trace-footer"><span>工具调用会在执行时实时更新</span><span class="live-run-id"></span></div></div></details><div class="message-content markdown-content streaming-answer" hidden></div>';
  $('#chatMessages').appendChild(el); $('#chatMessages').scrollTop = $('#chatMessages').scrollHeight;
  return {el, steps: [], runId: null, answer: '', renderTimer: null, firstToken: false};
}

function renderLiveAnalysis(live) {
  live.el.querySelector('.live-path-title').textContent = live.steps.at(-1)?.label || '正在建立分析路径';
  live.el.querySelector('.live-path-count').textContent = `${live.steps.length} 步`;
  live.el.querySelector('ol').innerHTML = live.steps.map((item, index) => {
    const status = item.status === 'error' ? '失败' : (item.status === 'running' ? '进行中' : '完成');
    const statusClass = item.status === 'error' ? 'error' : (item.status === 'running' ? 'running' : 'ok');
    const argumentsText = item.arguments && Object.keys(item.arguments).length
      ? Object.entries(item.arguments).map(([key, value]) => `${key}=${typeof value === 'string' ? value : JSON.stringify(value)}`).join(' · ')
      : '';
    const result = item.rows == null ? status : `${status} · ${item.rows} 条结果`;
    return `<li><div class="trace-step-heading"><span>${index + 1}. ${escapeHtml(item.label)}</span><small class="trace-status-${statusClass}">${result}</small></div>${argumentsText ? `<code>${escapeHtml(argumentsText)}</code>` : ''}${item.error ? `<p class="trace-error">${escapeHtml(item.error)}</p>` : ''}</li>`;
  }).join('');
  live.el.querySelector('.live-run-id').textContent = live.runId ? `运行 ${live.runId.slice(0, 8)}` : '';
  const container = $('#chatMessages');
  if (container.scrollHeight - container.scrollTop - container.clientHeight < 120) container.scrollTop = container.scrollHeight;
}

function appendLiveAnswer(live, delta) {
  if (!delta) return;
  const container = $('#chatMessages');
  const follow = container.scrollHeight - container.scrollTop - container.clientHeight < 120;
  live.answer += delta;
  if (!live.firstToken) {
    live.firstToken = true;
    const running = live.steps.at(-1); if (running?.status === 'running') running.status = 'ok';
    const path = live.el.querySelector('.live-path');
    path.open = false;
    live.el.querySelector('.live-path-title').textContent = `执行路径已完成 · ${live.steps.filter(step => step.tool).length} 个工具`;
    live.el.querySelector('.live-path-count').textContent = '可展开';
    live.el.querySelector('.streaming-answer').hidden = false;
    live.el.classList.add('answer-streaming');
  }
  if (live.renderTimer) return;
  live.renderTimer = window.setTimeout(() => {
    live.renderTimer = null;
    const answer = live.el.querySelector('.streaming-answer');
    answer.innerHTML = renderMarkdown(live.answer);
    if (follow) container.scrollTop = container.scrollHeight;
  }, 45);
}

function updateLiveAnalysis(live, event) {
  if (event.event === 'run_started') {
    live.runId = event.run_id;
    live.steps.push({label:'建立分析任务', status:'ok'});
  } else if (event.event === 'stage') {
    const previous = live.steps.at(-1); if (previous?.status === 'running') previous.status = 'ok';
    live.steps.push({label:event.message || '规划下一步', status:'running'});
  } else if (event.event === 'tool_started') {
    const previous = live.steps.at(-1); if (previous?.status === 'running') previous.status = 'ok';
    live.steps.push({tool:event.tool, label:toolLabels[event.tool] || event.tool, arguments:event.arguments || {}, status:'running'});
  } else if (event.event === 'tool_finished') {
    const item = [...live.steps].reverse().find(step => step.tool === event.tool && step.status === 'running');
    if (item) Object.assign(item, {status:event.status || 'ok', rows:event.rows, error:event.error});
  } else if (event.event === 'run_failed') {
    live.steps.push({label:event.message || '分析失败', status:'error'});
    live.el.querySelector('.live-path').open = true;
  } else if (event.event === 'answer_delta') {
    appendLiveAnswer(live, event.delta);
    return;
  }
  renderLiveAnalysis(live);
}

async function streamAgent(message, onProgress) {
  const response = await fetch('/api/chat/stream', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message, session_id:state.sessionId})});
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `请求失败 (${response.status})`);
  }
  if (!response.body) throw new Error('浏览器不支持流式响应');
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = '', finalResult = null;
  while (true) {
    const {value, done} = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
    const lines = buffer.split('\n'); buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === 'session') {
        state.sessionId = event.session_id; localStorage.setItem('fabInsightSessionId', state.sessionId);
      } else if (event.type === 'progress') onProgress(event);
      else if (event.type === 'result') finalResult = event.result;
      else if (event.type === 'error') throw new Error(event.detail || '分析失败');
    }
    if (done) break;
  }
  if (!finalResult) throw new Error('分析结束但未收到结果');
  return finalResult;
}

async function loadMonitor() {
  const hours = $('#monitorHours').value;
  try {
    const data = await api(`/api/monitor/summary?hours=${hours}&recent_limit=30`);
    const items = [
      ['Agent 运行', data.runs, '次', `${data.success_runs} 成功 / ${data.failed_runs} 失败`],
      ['成功率', data.success_rate_pct ?? '—', data.success_rate_pct == null ? '' : '%', '完成运行统计'],
      ['平均耗时', data.avg_duration_ms == null ? '—' : (data.avg_duration_ms / 1000).toFixed(2), data.avg_duration_ms == null ? '' : 's', `P95 ${formatDuration(data.p95_duration_ms)}`],
      ['模型 Token', data.input_tokens + data.output_tokens, '', `输入 ${formatNumber(data.input_tokens)} / 输出 ${formatNumber(data.output_tokens)}`],
      ['工具调用', data.tool_calls, '次', `${data.model_calls} 次模型请求`],
    ];
    $('#monitorKpis').innerHTML = items.map(([label,value,unit,meta]) => `<div class="kpi"><span class="kpi-label">${label}</span><span class="kpi-value">${formatNumber(value)}<span class="kpi-unit">${unit}</span></span><span class="kpi-meta">${meta}</span></div>`).join('');
    $('#recentRunsBody').innerHTML = data.recent_runs.map(run => {
      const success = run.status === 'success';
      const localTime = new Date(run.timestamp).toLocaleString('zh-CN', {hour12:false});
      return `<tr><td>${localTime}</td><td title="${run.run_id}"><code>${run.run_id.slice(0,8)}</code></td><td><span class="status-pill ${success ? 'status-healthy' : 'status-critical'}">${success ? '成功' : '失败'}</span></td><td>${escapeHtml(run.mode || '—')}</td><td>${formatDuration(run.duration_ms)}</td><td>${run.tool_count ?? 0}</td></tr>`;
    }).join('') || '<tr><td colspan="6">当前时间范围内尚无 Agent 运行记录</td></tr>';
    const max = Math.max(...data.tool_usage.map(item => item.count), 1);
    $('#toolUsage').innerHTML = data.tool_usage.map(item => `<div class="bar-row"><span class="bar-label" title="${escapeHtml(item.tool)}">${escapeHtml(item.tool)}</span><span class="bar-track"><span class="bar-fill" style="width:${item.count/max*100}%;background:#087f70"></span></span><span class="bar-value">${item.count}</span></div>`).join('') || '<p class="empty">尚无工具调用记录</p>';
    $('#logPath').textContent = data.log_path;
    $('#monitorWindow').textContent = `最近 ${hours} 小时 · 每 30 秒自动刷新`;
    $('#monitorUpdated').textContent = `更新于 ${new Date().toLocaleTimeString('zh-CN',{hour12:false})}`;
  } catch (error) {
    $('#recentRunsBody').innerHTML = `<tr><td colspan="6">监控数据加载失败：${escapeHtml(error.message)}</td></tr>`;
  }
}

function renderAssistantInto(el, content, extra = {}) {
  const sourceReferences = new Map();
  for (const source of (extra.sources || [])) {
    if (source.reference_id) sourceReferences.set(source.reference_id, source);
    if (source.chunk_id) sourceReferences.set(String(source.chunk_id), source);
  }
  const renderedContent = renderMarkdown(content, sourceReferences);
  const copyButton = '<button type="button" class="copy-answer" title="复制回答" aria-label="复制回答"><span aria-hidden="true">⧉</span><span>复制</span></button>';
  el.className = 'message assistant';
  el.innerHTML = `<div class="message-meta"><div class="message-label">FAB COPILOT</div></div>${renderToolTrace(extra.tool_trace, extra.run_id)}<div class="message-content markdown-content">${renderedContent}</div><div class="message-actions">${copyButton}</div>`;
  const copyAnswer = el.querySelector('.copy-answer');
  copyAnswer.addEventListener('click', async () => {
    try {
      await copyText(content);
      copyAnswer.innerHTML = '<span aria-hidden="true">✓</span><span>已复制</span>'; copyAnswer.classList.add('copied'); copyAnswer.title = '已复制';
      window.setTimeout(() => { copyAnswer.innerHTML = '<span aria-hidden="true">⧉</span><span>复制</span>'; copyAnswer.classList.remove('copied'); copyAnswer.title = '复制回答'; }, 1600);
    } catch (error) {
      copyAnswer.title = error.message; copyAnswer.classList.add('copy-error');
      window.setTimeout(() => copyAnswer.classList.remove('copy-error'), 1600);
    }
  });
  if (extra.sources?.length) {
    const sourceHtml = extra.sources.map(source => {
      const referenceId = source.reference_id || `KB-${source.chunk_id}`;
      const attribute = source.source_type === 'case' ? `data-case-id="${escapeHtml(source.case_id)}"` : `data-knowledge-chunk="${source.chunk_id}"`;
      const retrieval = source.retrieval || {};
      const scoreTitle = retrieval.final_score != null ? `${retrieval.confidence} · score ${retrieval.final_score} · ${(retrieval.selection_reason || []).join(' · ')}` : '';
      return `<button type="button" class="source-link" ${attribute} title="${escapeHtml(scoreTitle)}">[来源 ${escapeHtml(referenceId)}] ${escapeHtml(source.source)} · ${escapeHtml(source.section)}</button>`;
    }).join('');
    el.querySelector('.message-content').insertAdjacentHTML('beforeend', `<div class="source-list"><strong>知识来源</strong>${sourceHtml}</div>`);
  }
}

function addMessage(role, content, extra = {}) {
  const el = document.createElement('div');
  if (role === 'assistant') {
    renderAssistantInto(el, content, extra);
  } else {
    el.className = 'message user';
    el.innerHTML = `<div class="message-meta"><div class="message-label">YOU</div></div><div class="message-content">${escapeHtml(content).replace(/\n/g,'<br>')}</div>`;
  }
  $('#chatMessages').appendChild(el);
  $('#chatMessages').scrollTop = $('#chatMessages').scrollHeight;
  return el;
}

async function sendChat(message) {
  const text = message.trim(); if (!text || state.streaming) return;
  if (!state.sessionId) await createConversation();
  $('.suggestions')?.remove();
  addMessage('user', text); state.history.push({role:'user', content:text});
  $('#chatInput').value = ''; $('#sendButton').disabled = true; state.streaming = true;
  const live = createLiveAnalysis();
  try {
    const result = await streamAgent(text, event => updateLiveAnalysis(live, event));
    if (live.renderTimer) { window.clearTimeout(live.renderTimer); live.renderTimer = null; }
    renderAssistantInto(live.el, result.answer, result);
    state.history.push({role:'assistant', content:result.answer});
    $('#agentMode').textContent = result.mode === 'deepseek' ? `${state.modelConfig?.model || 'DeepSeek'} · 工具分析` : '本地规则分析';
  } catch (error) {
    updateLiveAnalysis(live, {event:'run_failed', message:error.message});
    const answer = live.el.querySelector('.streaming-answer'); answer.hidden = false;
    answer.innerHTML = `<p class="stream-error">分析请求失败：${escapeHtml(error.message)}</p>`;
    live.el.querySelector('.live-indicator').textContent = '失败';
  }
  finally {
    state.streaming = false; $('#sendButton').disabled = false; $('#chatInput').focus();
    if ($('#sessionsView').classList.contains('active')) loadSessionLibrary().catch(() => {});
  }
}

function showView(name) {
  if (name !== 'sessions') state.previousView = name;
  state.activeView = name;
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(v => v.classList.remove('active'));
  $(`#${name}View`).classList.add('active'); document.querySelector(`[data-view="${name}"]`)?.classList.add('active');
  const historyActive = name === 'sessions';
  $('#sessionHistoryButton').classList.toggle('active', historyActive);
  $('#sessionHistoryButton').setAttribute('aria-expanded', String(historyActive));
  $('#sessionHistoryButton').setAttribute('aria-label', historyActive ? '关闭历史会话' : '打开历史会话');
  $('#sessionHistoryButton').title = historyActive ? '关闭历史会话' : '打开历史会话';
  if (!document.querySelector('.app-shell').classList.contains('agent-collapsed')) $('#focusAgent').classList.add('active');
  if (name === 'capability') loadCapability();
  else if (name === 'knowledge') loadKnowledgeIndex();
  else if (name === 'cases') loadCaseIndex();
  else if (name === 'sessions') loadSessionLibrary();
  else if (name === 'monitor') loadMonitor();
  else requestAnimationFrame(() => state.dashboard && drawYieldChart(state.dashboard.yield_trend));
}

function setAgentOpen(open, focusInput = true) {
  const shell = document.querySelector('.app-shell');
  const panel = document.querySelector('.agent-panel');
  shell.classList.toggle('agent-collapsed', !open);
  $('#focusAgent').classList.toggle('active', open);
  $('#focusAgent').setAttribute('aria-expanded', String(open));
  $('#mobileAgentToggle').setAttribute('aria-expanded', String(open));
  $('#collapseAgent').setAttribute('aria-label', open ? '收起分析助手' : '展开分析助手');
  if (!open) return;
  panel.classList.remove('agent-panel-focus');
  void panel.offsetWidth;
  panel.classList.add('agent-panel-focus');
  if (focusInput) {
    panel.scrollIntoView({behavior:'smooth', block:window.innerWidth <= 980 ? 'start' : 'nearest'});
    window.setTimeout(() => $('#chatInput').focus({preventScroll:true}), 350);
  }
}

function toggleAgentPanel() {
  const isCollapsed = document.querySelector('.app-shell').classList.contains('agent-collapsed');
  setAgentOpen(isCollapsed);
}

function getAgentWidthBounds() {
  const sidebarWidth = $('.sidebar').getBoundingClientRect().width;
  const minimumMainWidth = window.innerWidth <= 1280 ? 600 : 660;
  return {
    min: AGENT_MIN_WIDTH,
    max: Math.max(AGENT_MIN_WIDTH, Math.min(AGENT_MAX_WIDTH, window.innerWidth - sidebarWidth - minimumMainWidth)),
  };
}

function updateAgentResizeAria(width) {
  const handle = $('#agentResizeHandle');
  const bounds = getAgentWidthBounds();
  handle.setAttribute('aria-valuemin', String(bounds.min));
  handle.setAttribute('aria-valuemax', String(Math.round(bounds.max)));
  handle.setAttribute('aria-valuenow', String(Math.round(width)));
}

function setAgentPanelWidth(width, persist = true) {
  if (window.innerWidth <= 980 || !Number.isFinite(width)) return;
  const bounds = getAgentWidthBounds();
  const clampedWidth = Math.round(Math.min(bounds.max, Math.max(bounds.min, width)));
  document.querySelector('.app-shell').style.setProperty('--agent-width', `${clampedWidth}px`);
  updateAgentResizeAria(clampedWidth);
  if (persist) localStorage.setItem(AGENT_WIDTH_KEY, String(clampedWidth));
  requestAnimationFrame(() => state.dashboard && drawYieldChart(state.dashboard.yield_trend));
}

function restoreAgentPanelWidth() {
  if (window.innerWidth <= 980) return;
  const savedWidth = Number(localStorage.getItem(AGENT_WIDTH_KEY));
  if (Number.isFinite(savedWidth) && savedWidth > 0) setAgentPanelWidth(savedWidth, false);
  else updateAgentResizeAria(document.querySelector('.agent-panel').getBoundingClientRect().width);
}

function resetAgentPanelWidth() {
  const shell = document.querySelector('.app-shell');
  shell.style.removeProperty('--agent-width');
  localStorage.removeItem(AGENT_WIDTH_KEY);
  requestAnimationFrame(() => {
    updateAgentResizeAria(document.querySelector('.agent-panel').getBoundingClientRect().width);
    state.dashboard && drawYieldChart(state.dashboard.yield_trend);
  });
}

function initializeAgentResize() {
  const handle = $('#agentResizeHandle');
  let drag = null;

  const finishDrag = event => {
    if (!drag || (event.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
    const width = document.querySelector('.agent-panel').getBoundingClientRect().width;
    localStorage.setItem(AGENT_WIDTH_KEY, String(Math.round(width)));
    if (handle.hasPointerCapture?.(drag.pointerId)) handle.releasePointerCapture(drag.pointerId);
    drag = null;
    handle.classList.remove('dragging');
    document.body.classList.remove('agent-resizing');
  };

  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0 || window.innerWidth <= 980) return;
    drag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: document.querySelector('.agent-panel').getBoundingClientRect().width,
    };
    handle.setPointerCapture(event.pointerId);
    handle.classList.add('dragging');
    document.body.classList.add('agent-resizing');
    event.preventDefault();
  });
  handle.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    setAgentPanelWidth(drag.startWidth + drag.startX - event.clientX, false);
  });
  handle.addEventListener('pointerup', finishDrag);
  handle.addEventListener('pointercancel', finishDrag);
  handle.addEventListener('dblclick', resetAgentPanelWidth);
  handle.addEventListener('keydown', event => {
    if (window.innerWidth <= 980 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const width = document.querySelector('.agent-panel').getBoundingClientRect().width;
    const bounds = getAgentWidthBounds();
    const nextWidth = event.key === 'Home' ? bounds.min
      : event.key === 'End' ? bounds.max
        : width + (event.key === 'ArrowLeft' ? 20 : -20);
    setAgentPanelWidth(nextWidth);
    event.preventDefault();
  });
}

async function init() {
  setInitialDates();
  initializeAgentResize();
  restoreAgentPanelWidth();
  try {
    const [health, modelConfig] = await Promise.all([api('/api/health'), loadModelConfig()]);
    $('#systemStatus').textContent = `${formatNumber(health.database.lots)} 批次 · ${modelConfig.api_key_configured ? modelConfig.model : '离线模式'}`;
  } catch { $('#systemStatus').textContent='数据源不可用'; }
  await loadDashboard();
  await restoreConversation();
  setAgentOpen(true, false);
  const requestedView = new URLSearchParams(window.location.search).get('view');
  if (['dashboard', 'capability', 'knowledge', 'cases', 'sessions', 'monitor'].includes(requestedView)) showView(requestedView);
  $('#dateForm').addEventListener('submit', e => { e.preventDefault(); state.capabilityCache.clear(); loadDashboard(); if ($('#capabilityView').classList.contains('active')) loadCapability(); });
  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));
  $('#focusAgent').addEventListener('click', toggleAgentPanel);
  $('#mobileAgentToggle').addEventListener('click', toggleAgentPanel);
  $('#collapseAgent').addEventListener('click', () => setAgentOpen(false));
  $('#sessionHistoryButton').addEventListener('click', () => state.activeView === 'sessions' ? closeSessionLibraryWorkspace() : openSessionLibraryWorkspace());
  $('#closeSessionLibrary').addEventListener('click', closeSessionLibraryWorkspace);
  $('#stepSelector').addEventListener('click', e => { if (!e.target.dataset.step) return; document.querySelectorAll('#stepSelector button').forEach(b=>b.classList.remove('active')); e.target.classList.add('active'); loadCapability(e.target.dataset.step); });
  $('#refreshMonitor').addEventListener('click', loadMonitor);
  $('#monitorHours').addEventListener('change', loadMonitor);
  $('#knowledgeFilter').addEventListener('input', event => renderKnowledgeDocuments(event.target.value));
  $('#knowledgeDocuments').addEventListener('click', event => { const target=event.target.closest('[data-knowledge-chunk]'); if (target) openKnowledgeChunk(Number(target.dataset.knowledgeChunk)); });
  $('#caseFilter').addEventListener('input', renderCaseList);
  $('#caseStepFilter').addEventListener('change', renderCaseList);
  $('#caseList').addEventListener('click', event => { const target=event.target.closest('[data-case-id]'); if (target) openHistoricalCase(target.dataset.caseId); });
  let sessionLibrarySearchTimer = null;
  $('#sessionLibrarySearch').addEventListener('input', event => {
    window.clearTimeout(sessionLibrarySearchTimer);
    sessionLibrarySearchTimer = window.setTimeout(() => loadSessionLibrary(event.target.value), 180);
  });
  $('#sessionLibraryFilter').addEventListener('click', async event => {
    const button = event.target.closest('[data-session-filter]');
    if (!button) return;
    state.sessionLibraryFilter = button.dataset.sessionFilter;
    document.querySelectorAll('[data-session-filter]').forEach(item => item.classList.toggle('active', item === button));
    await loadSessionLibrary();
  });
  $('#sessionLibraryList').addEventListener('click', event => {
    const item = event.target.closest('[data-library-session-id]');
    if (!item) return;
    const action = event.target.closest('[data-library-action]')?.dataset.libraryAction;
    if (action) {
      item.querySelector('.session-item-menu').open = false;
      runSessionLibraryAction(item.dataset.librarySessionId, action);
    } else if (!event.target.closest('summary')) {
      openSessionLibraryPreview(item.dataset.librarySessionId);
    }
  });
  $('#sessionLibraryMessages').addEventListener('click', event => {
    const knowledgeTarget = event.target.closest('[data-knowledge-chunk]');
    const caseTarget = event.target.closest('[data-case-id]');
    if (knowledgeTarget) openKnowledgeChunk(Number(knowledgeTarget.dataset.knowledgeChunk));
    else if (caseTarget) openHistoricalCase(caseTarget.dataset.caseId);
  });
  $('#renameLibrarySession').addEventListener('click', () => openSessionRenameDialog());
  $('#archiveLibrarySession').addEventListener('click', toggleSelectedLibrarySessionArchive);
  $('#deleteLibrarySession').addEventListener('click', () => openSessionDeleteDialog(state.selectedLibrarySessionId));
  $('#continueLibrarySession').addEventListener('click', continueSelectedLibrarySession);
  $('#sessionRenameForm').addEventListener('submit', event => { event.preventDefault(); renameSelectedLibrarySession(); });
  $('#sessionRenameInput').addEventListener('input', () => { updateSessionRenameCount(); $('#sessionRenameMessage').hidden = true; });
  $('#closeSessionRenameDialog').addEventListener('click', () => $('#sessionRenameDialog').close());
  $('#cancelSessionRename').addEventListener('click', () => $('#sessionRenameDialog').close());
  $('#sessionRenameDialog').addEventListener('close', () => { state.pendingRenameSessionId = null; $('#sessionRenameMessage').hidden = true; });
  $('#sessionDeleteForm').addEventListener('submit', event => { event.preventDefault(); permanentlyDeleteSelectedSession().catch(error => showToast(`删除失败：${error.message}`, {tone:'error'})); });
  $('#closeSessionDeleteDialog').addEventListener('click', () => $('#sessionDeleteDialog').close());
  $('#cancelSessionDelete').addEventListener('click', () => $('#sessionDeleteDialog').close());
  $('#sessionDeleteDialog').addEventListener('close', () => { state.pendingDeleteSessionId = null; });
  $('#newSessionFromLibrary').addEventListener('click', async () => {
    if (state.streaming) return;
    const session = await createConversation('已创建新会话。');
    state.selectedLibrarySessionId = session.session_id;
    setAgentOpen(true);
    await loadSessionLibrary();
    showToast('已创建新会话');
  });
  document.addEventListener('click', event => {
    document.querySelectorAll('.session-item-menu[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  $('#chatMessages').addEventListener('click', event => {
    const knowledgeTarget=event.target.closest('[data-knowledge-chunk]');
    const caseTarget=event.target.closest('[data-case-id]');
    const suggestion = event.target.closest('.suggestions button');
    if (knowledgeTarget) openKnowledgeChunk(Number(knowledgeTarget.dataset.knowledgeChunk));
    else if (caseTarget) openHistoricalCase(caseTarget.dataset.caseId);
    else if (suggestion) sendChat(suggestion.textContent);
  });
  $('#chatForm').addEventListener('submit', e => { e.preventDefault(); sendChat($('#chatInput').value); });
  $('#clearChat').addEventListener('click', async () => { if (!state.streaming) await createConversation('已创建新会话。'); });
  $('#modelSettingsButton').addEventListener('click', openModelSettings);
  $('#modelSettingsForm').addEventListener('submit', saveModelSettings);
  $('#closeModelDialog').addEventListener('click', () => $('#modelDialog').close());
  $('#cancelModelSettings').addEventListener('click', () => $('#modelDialog').close());
  $('#toggleApiKey').addEventListener('click', () => { const input=$('#apiKeyInput'); input.type=input.type === 'password' ? 'text' : 'password'; });
  $('#yieldChart').addEventListener('mousemove', e => { const rect=e.currentTarget.getBoundingClientRect(), mx=e.clientX-rect.left; const point=state.chartPoints.reduce((a,b)=>Math.abs(b.x-mx)<Math.abs(a.x-mx)?b:a,state.chartPoints[0]); const tip=$('#chartTooltip'); if (!point || Math.abs(point.x-mx)>18) {tip.hidden=true;return;} tip.hidden=false; tip.style.left=`${point.x}px`; tip.style.top=`${point.y}px`; tip.textContent=`${point.row.week_start} · ${point.row.yield_pct}% · ${point.row.lots}批`; });
  $('#yieldChart').addEventListener('mouseleave', () => $('#chartTooltip').hidden=true);
  window.addEventListener('resize', () => {
    restoreAgentPanelWidth();
    state.dashboard && drawYieldChart(state.dashboard.yield_trend);
  });
  state.monitorTimer = window.setInterval(() => $('#monitorView').classList.contains('active') && loadMonitor(), 30000);
}

document.addEventListener('DOMContentLoaded', init);
