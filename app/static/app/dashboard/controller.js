(function (root, factory) { const api = factory(root); if (typeof module === "object" && module.exports) module.exports = api; root.FabDashboardController = api; })(globalThis, (root) => {
  function createDashboardController(deps = {}) {
    const { state, $, escapeHtml, formatNumber, api, processLabels, windowImpl = root, AbortControllerImpl = root.AbortController } = deps;
    const window = windowImpl, AbortController = AbortControllerImpl;
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

    return { renderKpis, renderEquipment, renderDefects, renderExcursions, drawYieldChart, loadDashboard, capabilityRating, loadCapability, renderCapability };
  }
  return { createDashboardController };
});
