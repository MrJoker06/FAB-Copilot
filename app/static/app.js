const state = { dashboard: null, history: [], chartPoints: [], activeStep: 'CVD', monitorTimer: null, modelConfig: null, knowledgeDocuments: [], knowledgeIndexPromise: null, cases: [], casesPromise: null };
const $ = (selector) => document.querySelector(selector);
const processLabels = { LITHO: '光刻', ETCH: '刻蚀', CVD: '化学气相沉积', PVD: '物理气相沉积', DIFFUSION: '扩散/炉管', IMPLANT: '离子注入', CMP: '化学机械研磨', CLEAN: '湿法清洗', METROLOGY: '量测' };

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
  const rows = await api(`/api/reports/capability?process_step=${step}&start=${start}&end=${end}`);
  const metric = rows[0];
  $('#capabilityTitle').textContent = `${processLabels[step] || step} · ${metric?.metric_name || '关键量测'}能力`;
  const lower = metric?.spec_lsl == null ? null : `LSL ${metric.spec_lsl}`;
  const upper = metric?.spec_usl == null ? null : `USL ${metric.spec_usl}`;
  const specification = [lower, upper].filter(Boolean).join(' / ');
  $('#capabilityMetric').textContent = metric ? `${specification} ${metric.metric_unit}；Cpk < 1.33 需关注` : '当前范围没有可用量测';
  $('#capabilityBody').innerHTML = rows.map(row => { const [rating, cls] = capabilityRating(row.cpk); return `<tr><td><strong>${row.equipment_id}</strong></td><td>${row.samples}</td><td>${row.mean_value}</td><td>${row.sigma}</td><td>${row.min_value}</td><td>${row.max_value}</td><td class="${cls}">${row.cpk ?? '—'}</td><td class="${cls}">${rating}</td></tr>`; }).join('');
}

function formatDuration(milliseconds) {
  if (milliseconds == null) return '—';
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  return `${(milliseconds / 1000).toFixed(2)} s`;
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

function addMessage(role, content, extra = {}) {
  const el = document.createElement('div'); el.className = `message ${role}`;
  const label = role === 'user' ? 'YOU' : 'FAB COPILOT';
  const sourceReferences = new Map();
  for (const source of (extra.sources || [])) {
    if (source.reference_id) sourceReferences.set(source.reference_id, source);
    if (source.chunk_id) sourceReferences.set(String(source.chunk_id), source);
  }
  const renderedContent = role === 'assistant' ? renderMarkdown(content, sourceReferences) : escapeHtml(content).replace(/\n/g,'<br>');
  el.innerHTML = `<div class="message-label">${label}</div><div class="message-content markdown-content">${renderedContent}</div>`;
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
  $('#chatMessages').appendChild(el);
  if (extra.tool_trace?.length) {
    const trace = document.createElement('div'); trace.className = 'tool-trace';
    trace.textContent = `已调用：${extra.tool_trace.map(t => t.tool).join(' → ')}`;
    $('#chatMessages').appendChild(trace);
  }
  $('#chatMessages').scrollTop = $('#chatMessages').scrollHeight;
}

async function sendChat(message) {
  const text = message.trim(); if (!text) return;
  addMessage('user', text); state.history.push({role:'user', content:text});
  $('#chatInput').value = ''; $('#sendButton').disabled = true;
  const typing = document.createElement('div'); typing.className='typing'; typing.id='typing'; typing.innerHTML='<i></i><i></i><i></i>'; $('#chatMessages').appendChild(typing); $('#chatMessages').scrollTop=$('#chatMessages').scrollHeight;
  try {
    const result = await api('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:text, history:state.history.slice(-8,-1)})});
    typing.remove(); addMessage('assistant', result.answer, result); state.history.push({role:'assistant', content:result.answer});
    $('#agentMode').textContent = result.mode === 'deepseek' ? `${state.modelConfig?.model || 'DeepSeek'} · 工具分析` : '本地规则分析';
  } catch (error) { typing.remove(); addMessage('assistant', `分析请求失败：${error.message}`); }
  finally { $('#sendButton').disabled = false; $('#chatInput').focus(); }
}

function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(v => v.classList.remove('active'));
  $(`#${name}View`).classList.add('active'); document.querySelector(`[data-view="${name}"]`)?.classList.add('active');
  if (!document.querySelector('.app-shell').classList.contains('agent-collapsed')) $('#focusAgent').classList.add('active');
  if (name === 'capability') loadCapability();
  else if (name === 'knowledge') loadKnowledgeIndex();
  else if (name === 'cases') loadCaseIndex();
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
  panel.scrollIntoView({behavior:'smooth', block:window.innerWidth <= 980 ? 'start' : 'nearest'});
  if (focusInput) window.setTimeout(() => $('#chatInput').focus({preventScroll:true}), 350);
}

function toggleAgentPanel() {
  const isCollapsed = document.querySelector('.app-shell').classList.contains('agent-collapsed');
  setAgentOpen(isCollapsed);
}

async function init() {
  setInitialDates();
  try {
    const [health, modelConfig] = await Promise.all([api('/api/health'), loadModelConfig()]);
    $('#systemStatus').textContent = `${formatNumber(health.database.lots)} 批次 · ${modelConfig.api_key_configured ? modelConfig.model : '离线模式'}`;
  } catch { $('#systemStatus').textContent='数据源不可用'; }
  await loadDashboard();
  setAgentOpen(true, false);
  $('#dateForm').addEventListener('submit', e => { e.preventDefault(); loadDashboard(); if ($('#capabilityView').classList.contains('active')) loadCapability(); });
  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));
  $('#focusAgent').addEventListener('click', toggleAgentPanel);
  $('#mobileAgentToggle').addEventListener('click', toggleAgentPanel);
  $('#collapseAgent').addEventListener('click', () => setAgentOpen(false));
  $('#stepSelector').addEventListener('click', e => { if (!e.target.dataset.step) return; document.querySelectorAll('#stepSelector button').forEach(b=>b.classList.remove('active')); e.target.classList.add('active'); loadCapability(e.target.dataset.step); });
  $('#refreshMonitor').addEventListener('click', loadMonitor);
  $('#monitorHours').addEventListener('change', loadMonitor);
  $('#knowledgeFilter').addEventListener('input', event => renderKnowledgeDocuments(event.target.value));
  $('#knowledgeDocuments').addEventListener('click', event => { const target=event.target.closest('[data-knowledge-chunk]'); if (target) openKnowledgeChunk(Number(target.dataset.knowledgeChunk)); });
  $('#caseFilter').addEventListener('input', renderCaseList);
  $('#caseStepFilter').addEventListener('change', renderCaseList);
  $('#caseList').addEventListener('click', event => { const target=event.target.closest('[data-case-id]'); if (target) openHistoricalCase(target.dataset.caseId); });
  $('#chatMessages').addEventListener('click', event => {
    const knowledgeTarget=event.target.closest('[data-knowledge-chunk]');
    const caseTarget=event.target.closest('[data-case-id]');
    if (knowledgeTarget) openKnowledgeChunk(Number(knowledgeTarget.dataset.knowledgeChunk));
    else if (caseTarget) openHistoricalCase(caseTarget.dataset.caseId);
  });
  $('#chatForm').addEventListener('submit', e => { e.preventDefault(); sendChat($('#chatInput').value); });
  document.querySelectorAll('.suggestions button').forEach(button => button.addEventListener('click', () => sendChat(button.textContent)));
  $('#clearChat').addEventListener('click', () => { state.history=[]; $('#chatMessages').innerHTML='<div class="message assistant"><div class="message-label">FAB COPILOT</div><div class="message-content">对话已清空。可以开始新的制造分析。</div></div>'; });
  $('#modelSettingsButton').addEventListener('click', openModelSettings);
  $('#modelSettingsForm').addEventListener('submit', saveModelSettings);
  $('#closeModelDialog').addEventListener('click', () => $('#modelDialog').close());
  $('#cancelModelSettings').addEventListener('click', () => $('#modelDialog').close());
  $('#toggleApiKey').addEventListener('click', () => { const input=$('#apiKeyInput'); input.type=input.type === 'password' ? 'text' : 'password'; });
  $('#yieldChart').addEventListener('mousemove', e => { const rect=e.currentTarget.getBoundingClientRect(), mx=e.clientX-rect.left; const point=state.chartPoints.reduce((a,b)=>Math.abs(b.x-mx)<Math.abs(a.x-mx)?b:a,state.chartPoints[0]); const tip=$('#chartTooltip'); if (!point || Math.abs(point.x-mx)>18) {tip.hidden=true;return;} tip.hidden=false; tip.style.left=`${point.x}px`; tip.style.top=`${point.y}px`; tip.textContent=`${point.row.week_start} · ${point.row.yield_pct}% · ${point.row.lots}批`; });
  $('#yieldChart').addEventListener('mouseleave', () => $('#chartTooltip').hidden=true);
  window.addEventListener('resize', () => state.dashboard && drawYieldChart(state.dashboard.yield_trend));
  state.monitorTimer = window.setInterval(() => $('#monitorView').classList.contains('active') && loadMonitor(), 30000);
}

document.addEventListener('DOMContentLoaded', init);
