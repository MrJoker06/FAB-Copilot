(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabCommonalityController = api;
})(globalThis, (root) => {
  const PAGE_SIZES = [4, 10, 20, 50, 100, 200];
  const STATUSES = ['hit', 'miss', 'unknown'];

  function createCommonalityController(deps = {}) {
    const {
      $, escapeHtml: esc, identityHeaders, model = root.FabCommonalityModel, askAssistant, showView,
      fetchImpl = root.fetch?.bind(root), documentImpl = root.document,
    } = deps;
    const document = documentImpl;
    const {
      SAMPLE_URL, DEFAULT_TIMEZONE, DIMENSIONS, DIMENSION_LABELS, ROLES, ROLE_LABELS, LOT_STATE_LABELS,
      MEMBER_STATUS_LABELS, MATCH_SCOPE_LABELS, GRANULARITY_LABELS, COVERAGE_LABELS, ANALYSIS_STATUS_LABELS,
    } = model;
    const httpClient = model.createHttpClient({ fetchImpl, identityHeaders });
    const queryGate = model.createLatestGate();
    const membersGate = model.createLatestGate();
    const recordsGate = model.createLatestGate();
    let groupSequence = 0;
    let sampleDocument = null;
    let bound = false;
    const ui = {
      groups: [], inputVersion: 0, result: null, filters: { dimension: '', share: '' }, members: null, records: null,
    };

    const view = () => $('#commonalityView');
    const textOrDash = value => (value === null || value === undefined || value === '' ? '—' : esc(value));
    const listText = values => (Array.isArray(values) && values.length ? values.map(esc).join('、') : '—');
    const timeText = value => (value ? esc(String(value).replace('T', ' ')) : '时间缺失');

    function defaultName(role, groups = ui.groups) {
      const base = ROLE_LABELS[role] || '对比组';
      const names = new Set(groups.map(group => group.name));
      if (!names.has(base)) return base;
      let index = 2;
      while (names.has(`${base} ${index}`)) index += 1;
      return `${base} ${index}`;
    }
    function newGroup(role, groups = ui.groups) {
      groupSequence += 1;
      return { key: `g${groupSequence}`, role, name: defaultName(role, groups), text: '' };
    }
    function groupNode(key) {
      return [...$('#commonalityGroups').querySelectorAll('[data-group-key]')].find(node => node.dataset.groupKey === key);
    }

    function isStale() {
      return Boolean(ui.result) && (ui.result.token !== queryGate.current || ui.result.inputVersion !== ui.inputVersion);
    }
    function updateBadges() {
      const stale = isStale();
      view().querySelectorAll('[data-lc-stale]').forEach(node => { node.hidden = !stale; });
      view().querySelectorAll('[data-lc-unavailable]').forEach(node => { node.hidden = !ui.result?.unavailable; });
      $('#commonalitySampleBadge').hidden = !ui.result?.sample;
    }
    function setStatus(message, tone = 'info', extraHtml = '') {
      const node = $('#commonalityStatus');
      node.dataset.tone = tone;
      node.innerHTML = `${esc(message)}${extraHtml}`;
    }
    function markInputChanged() {
      ui.inputVersion += 1;
      updateBadges();
      updateScopeSummary();
    }

    function groupTemplate(group) {
      const primary = group.role === 'primary';
      const roles = primary ? ['primary'] : ROLES.filter(role => role !== 'primary');
      const options = roles.map(role => `<option value="${esc(role)}"${role === group.role ? ' selected' : ''}>${esc(ROLE_LABELS[role])}</option>`).join('');
      return `<article class="lc-group${primary ? ' lc-group-primary' : ''}" data-group-key="${esc(group.key)}">
        <div class="lc-group-head">
          <label class="lc-field"><span>组名</span><input type="text" maxlength="40" data-group-field="name" value="${esc(group.name)}"></label>
          <label class="lc-field"><span>用途</span><select data-group-field="role"${primary ? ' disabled' : ''}>${options}</select></label>
          ${primary ? '' : `<button type="button" class="secondary-btn lc-small-btn" data-remove-group="${esc(group.key)}">删除该组</button>`}
        </div>
        <label class="lc-field lc-lot-field"><span>lot 清单</span><textarea rows="5" spellcheck="false" data-group-field="text" placeholder="每行一个 lot，可直接粘贴 Excel 单列">${esc(group.text)}</textarea></label>
        <p class="lc-group-summary" data-group-summary></p>
        <p class="lc-group-overlap" data-group-overlap hidden></p>
      </article>`;
    }
    function renderGroups() {
      $('#commonalityGroups').innerHTML = ui.groups.map(groupTemplate).join('');
      updateGroupSummaries();
    }
    function updateGroupSummaries() {
      const overlaps = model.findOverlaps(ui.groups);
      const names = new Map(ui.groups.map(group => [group.key, group.name || ROLE_LABELS[group.role]]));
      for (const group of ui.groups) {
        const node = groupNode(group.key);
        if (!node) continue;
        node.querySelector('[data-group-summary]').textContent = model.describeGroupSummary(model.summarizeLots(group.text));
        const shared = overlaps.filter(item => item.keys.includes(group.key));
        const overlap = node.querySelector('[data-group-overlap]');
        overlap.hidden = !shared.length;
        overlap.textContent = shared.length
          ? `跨组交集：${shared.map(item => `${item.lot_id}（同在 ${item.keys.filter(key => key !== group.key).map(key => names.get(key)).join('、')}）`).join('；')}`
          : '';
      }
    }

    function readScope() {
      const mode = view().querySelector('input[name="commonalityCutoffMode"]:checked')?.value || 'none';
      return {
        timeStart: $('#commonalityTimeStart').value, timeEnd: $('#commonalityTimeEnd').value,
        cutoffMode: mode, cutoffAt: $('#commonalityCutoffAt').value,
        cutoffOperation: $('#commonalityCutoffOperation').value, cutoffOccurrence: $('#commonalityCutoffOccurrence').value,
      };
    }
    function readDraft() {
      return {
        groups: ui.groups.map(group => ({ name: group.name, role: group.role, text: group.text })),
        dimensions: [...view().querySelectorAll('[data-commonality-dimension]:checked')].map(node => node.value),
        scope: readScope(),
        description: $('#commonalityDescription').value,
        timezone: DEFAULT_TIMEZONE,
      };
    }
    function updateScopeSummary() {
      const scope = readScope();
      const start = model.localDateTime(scope.timeStart), end = model.localDateTime(scope.timeEnd);
      $('#commonalityCutoffAt').disabled = scope.cutoffMode !== 'time';
      $('#commonalityCutoffOperation').disabled = scope.cutoffMode !== 'operation';
      $('#commonalityCutoffOccurrence').disabled = scope.cutoffMode !== 'operation';
      const summary = model.describeScope({ time_range: start || end ? { start: start || '未填', end: end || '未填' } : null, cutoff: model.buildCutoff(scope) }, DEFAULT_TIMEZONE);
      $('#commonalityScopeSummary').textContent = `提交范围：${summary}`;
    }
    function applyDraft(draft) {
      const groups = [];
      for (const item of draft.groups) {
        const group = newGroup(item.role, groups);
        groups.push(Object.assign(group, { name: item.name, text: item.text }));
      }
      ui.groups = groups;
      view().querySelectorAll('[data-commonality-dimension]').forEach(node => { node.checked = draft.dimensions.includes(node.value); });
      $('#commonalityTimeStart').value = draft.scope.timeStart || '';
      $('#commonalityTimeEnd').value = draft.scope.timeEnd || '';
      view().querySelectorAll('input[name="commonalityCutoffMode"]').forEach(node => { node.checked = node.value === draft.scope.cutoffMode; });
      $('#commonalityCutoffAt').value = draft.scope.cutoffAt || '';
      $('#commonalityCutoffOperation').value = draft.scope.cutoffOperation || '';
      $('#commonalityCutoffOccurrence').value = draft.scope.cutoffOccurrence || '';
      $('#commonalityDescription').value = draft.description || '';
      renderGroups();
      markInputChanged();
    }

    function failureDetails(error) {
      const context = error?.context;
      const parts = [];
      if (error?.code === 'CUTOFF_AMBIGUOUS' && Array.isArray(context?.lots)) {
        parts.push(`需指定出现次数的 lot：${context.lots.map(lot => `${lot.lot_id}（${(lot.record_refs || []).join('、')}）`).join('；')}`);
      } else if (error?.code === 'ANALYSIS_LIMIT_EXCEEDED' && context) {
        parts.push(`限额 ${context.limit}${context.group_id ? `（组 ${context.group_id}）` : ''}：上限 ${context.max}，实际 ${context.actual}`);
      }
      if (error?.fields?.length) parts.push(`字段：${error.fields.join('、')}`);
      if (error?.retryable) parts.push('可稍后重试');
      if (error?.requestId) parts.push(`请求编号 ${error.requestId}`);
      return parts.length ? `<span class="lc-status-detail">${parts.map(esc).join(' · ')}</span>` : '';
    }

    async function execute(client, request, sample) {
      const token = queryGate.begin();
      const inputVersion = ui.inputVersion;
      setStatus(sample ? '正在载入契约样例…' : '正在查询…', 'info');
      updateBadges();
      try {
        const analysis = await client.createAnalysis(request);
        if (!queryGate.isCurrent(token)) return;
        ui.result = { analysis, client, sample, token, inputVersion };
        ui.filters = { dimension: '', share: '' };
        ui.members = null; ui.records = null;
        membersGate.invalidate(); recordsGate.invalidate();
        const partial = analysis.status === 'partial';
        const message = `${sample ? '已载入合成样例结果' : '查询完成'}：${analysis.candidates.length} 个共性项${partial ? '；部分 lot 资料不足，见组回执' : ''}`;
        setStatus(message, partial ? 'warn' : 'info');
        renderAll();
      } catch (error) {
        if (!queryGate.isCurrent(token)) return;
        setStatus(`查询失败：${model.errorText(error)}`, 'error', failureDetails(error));
        updateBadges();
      }
    }

    async function runQuery(event) {
      event?.preventDefault();
      const { errors, request } = model.buildCreateRequest(readDraft());
      if (errors.length) { setStatus(`无法查询：${errors.join('；')}`, 'error'); return; }
      await execute(httpClient, request, false);
    }

    async function loadSample() {
      try {
        if (!sampleDocument) {
          const response = await fetchImpl(SAMPLE_URL, { cache: 'no-store' });
          if (!response.ok) throw new Error('契约样例暂不可用');
          sampleDocument = model.validateSampleDocument(await response.json());
        }
      } catch (error) {
        setStatus(`契约样例读取失败：${error.message}`, 'error');
        return;
      }
      applyDraft(model.draftFromRequest(sampleDocument.examples.create_analysis.request));
      const { errors, request } = model.buildCreateRequest(readDraft());
      if (errors.length) { setStatus(`契约样例无法组装请求：${errors.join('；')}`, 'error'); return; }
      await execute(model.createSampleClient(sampleDocument), request, true);
    }

    const sampleBadge = () => (ui.result?.sample ? '<span class="lc-sample-badge">合成样例</span>' : '');
    const staleBadge = () => '<span class="lc-stale-badge" data-lc-stale hidden>上次查询</span><span class="lc-warn-badge" data-lc-unavailable hidden>已失效</span>';
    const askButton = () => {
      const blocked = ui.result?.sample ? '合成样例未保存到服务端，不能附带给助手' : ui.result?.unavailable ? '该结果已不可读取' : '';
      return `<button type="button" class="secondary-btn lc-small-btn" data-lc-ask${blocked ? ` disabled title="${esc(blocked)}"` : ' title="把该结果作为引用附带到对话草稿"'}>问助手</button>`;
    };

    function markUnavailable(error) {
      if (ui.result.unavailable) return;
      ui.result.unavailable = true;
      setStatus('该结果已不可读取（已过期、无权访问或所属会话已删除），请重新查询', 'error', failureDetails(error));
      view().querySelectorAll('[data-lc-count], [data-lc-ask]').forEach(node => { node.disabled = true; });
    }
    function drillError(error, kind) {
      const hint = model.isResultUnavailable(error) ? '该结果已不可读取，请重新查询。'
        : error?.code === 'RESULT_CURSOR_INVALID' ? '分页位置已失效，请回到第一页。' : '';
      const action = error?.code === 'RESULT_CURSOR_INVALID'
        ? `<button type="button" class="secondary-btn lc-small-btn" data-${kind}-page="first">回到第一页</button>`
        : error?.retryable ? `<button type="button" class="secondary-btn lc-small-btn" data-${kind}-retry>重试</button>` : '';
      return `<div class="lc-error" role="alert"><p>${esc(model.errorText(error))}</p>${hint ? `<p>${esc(hint)}</p>` : ''}${action}</div>`;
    }
    function sampleSourceNote(response) {
      const source = response?.sample_source;
      if (!source) return '';
      const projection = source.projection === 'status' ? '，按成员状态筛选' : source.projection === 'lot_ids' ? '，按所选 lot 截取' : '';
      return `<p class="lc-hint">样例来源：${esc(source.example)}${projection}</p>`;
    }
    const groupName = groupId => (groupId === 'union' ? '合并（union）' : ui.result?.analysis.groups.find(group => group.group_id === groupId)?.name || groupId);
    const findCandidate = candidateId => ui.result?.analysis.candidates.find(candidate => candidate.candidate_id === candidateId) || null;
    const defaultLimit = () => Number(ui.result?.analysis.limits?.page_limit_default) || 50;

    function receiptsTemplate(analysis) {
      const receipts = analysis.groups.map(group => {
        const byState = new Map();
        for (const lot of group.lot_states || []) {
          if (!byState.has(lot.state)) byState.set(lot.state, []);
          byState.get(lot.state).push(lot);
        }
        const rows = [...byState.entries()].map(([state, lots]) => `<li><span class="lc-state lc-state-${esc(state)}">${esc(LOT_STATE_LABELS[state] || state)} ${lots.length}</span> ${lots.map(lot => `${esc(lot.lot_id)}${lot.reasons?.length ? `（${lot.reasons.map(reason => esc(model.reasonText(reason))).join('、')}）` : ''}`).join('、')}</li>`).join('');
        return `<article class="lc-receipt" data-receipt-group="${esc(group.group_id)}"><h3>${esc(group.name)} <small>${esc(ROLE_LABELS[group.role] || group.role)}</small></h3>
          <p>输入 ${esc(group.input_count)} 个 · 唯一 ${esc(group.unique_count)} 个 · 重复：${listText(group.duplicates)}</p><ul class="lc-state-list">${rows || '<li>无 lot 状态</li>'}</ul></article>`;
      }).join('');
      const overlaps = (analysis.overlaps || []).map(item => `${esc(item.lot_id)}（${item.group_ids.map(id => esc(groupName(id))).join('、')}）`).join('；');
      return `<div class="lc-receipts">${receipts}</div><p class="lc-overlaps">跨组交集：${overlaps || '无'}${analysis.union ? ` · 合并后唯一 lot：${esc(analysis.union.unique_count)}` : ''}</p>`;
    }

    function resultColumns(analysis) {
      const columns = analysis.groups.map(group => ({ id: group.group_id, name: group.name }));
      if (analysis.candidates.some(candidate => candidate.counts?.union)) columns.push({ id: 'union', name: '合并（union）' });
      return columns;
    }
    function countCells(candidate, column) {
      const counts = candidate.counts?.[column.id];
      if (!counts) return '<td>—</td><td>—</td><td>—</td><td>—</td>';
      const disabled = ui.result?.unavailable ? ' disabled' : '';
      return `${STATUSES.map(status => `<td><button type="button" class="lc-count lc-count-${status}"${disabled} data-lc-count data-candidate-id="${esc(candidate.candidate_id)}" data-group-id="${esc(column.id)}" data-status="${status}" aria-label="${esc(column.name)} ${esc(MEMBER_STATUS_LABELS[status])} ${esc(counts[status])}，查看成员">${esc(counts[status])}</button></td>`).join('')}<td class="lc-denominator">${esc(counts.denominator)}</td>`;
    }
    function candidateTableTemplate() {
      const { analysis } = ui.result;
      if (!analysis.candidates.length) return '<p class="empty">无共同项：主组中没有至少两个 lot 共同命中的值。</p>';
      const items = analysis.candidates.filter(candidate => (!ui.filters.dimension || candidate.dimension === ui.filters.dimension)
        && (!ui.filters.share || (ui.filters.share === 'all') === Boolean(candidate.all_shared)));
      if (!items.length) return '<p class="empty">没有符合筛选条件的共性项</p>';
      const columns = resultColumns(analysis);
      const head = `<thead><tr><th rowspan="2" scope="col">维度</th><th rowspan="2" scope="col">发现</th><th rowspan="2" scope="col">共有</th>${columns.map(column => `<th colspan="4" scope="colgroup" class="lc-group-col">${esc(column.name)}</th>`).join('')}</tr><tr>${columns.map(() => '<th scope="col">命中</th><th scope="col">确认未命中</th><th scope="col">未知</th><th scope="col">分母</th>').join('')}</tr></thead>`;
      const rows = items.map(candidate => `<tr data-candidate-row="${esc(candidate.candidate_id)}"><td>${esc(DIMENSION_LABELS[candidate.dimension] || candidate.dimension)}</td><td class="lc-label">${esc(candidate.label)}</td><td>${candidate.all_shared ? '<span class="lc-share lc-share-all">全部共有</span>' : '<span class="lc-share">部分共有</span>'}</td>${columns.map(column => countCells(candidate, column)).join('')}</tr>`).join('');
      return `<div class="table-wrap" tabindex="0" role="region" aria-labelledby="commonalityResultTitle"><table class="lc-table lc-candidates">${head}<tbody>${rows}</tbody></table></div>${analysis.candidates_truncated ? '<p class="lc-hint">候选数超过限额，已按排序截取。</p>' : ''}`;
    }

    function renderResults() {
      const node = $('#commonalityResults');
      if (!ui.result) { node.hidden = true; node.innerHTML = ''; return; }
      const { analysis } = ui.result;
      const dimensions = DIMENSIONS.filter(item => analysis.candidates.some(candidate => candidate.dimension === item));
      node.hidden = false;
      node.innerHTML = `<section class="panel lc-panel" aria-labelledby="commonalityResultTitle">
        <div class="panel-heading"><div><h2 id="commonalityResultTitle">共性结果</h2><p>排序只反映主组命中数和未知数，不代表根因判断</p></div><div class="lc-badges">${sampleBadge()}${staleBadge()}${analysis.status === 'partial' ? '<span class="lc-warn-badge">部分返回</span>' : ''}${askButton()}</div></div>
        <dl class="lc-meta">
          <div><dt>结果引用</dt><dd>${esc(analysis.analysis_ref)}</dd></div>
          <div><dt>状态</dt><dd>${esc(ANALYSIS_STATUS_LABELS[analysis.status] || analysis.status)}</dd></div>
          <div><dt>来源</dt><dd>${esc(analysis.source?.source_id)}${analysis.source?.kind === 'synthetic' ? '（合成来源）' : ''}</dd></div>
          <div><dt>来源时区</dt><dd>${textOrDash(analysis.source?.timezone)}</dd></div>
          <div><dt>维度</dt><dd>${(analysis.dimensions || []).map(item => esc(DIMENSION_LABELS[item] || item)).join('、')}</dd></div>
          <div><dt>实际范围</dt><dd>${esc(model.describeScope(analysis.scope, analysis.timezone))}</dd></div>
          <div><dt>创建时间</dt><dd>${timeText(analysis.created_at)}</dd></div>
          <div><dt>有效期至</dt><dd>${analysis.expires_at ? timeText(analysis.expires_at) : '随所属会话删除'}</dd></div>
        </dl>
        ${receiptsTemplate(analysis)}
        <div class="lc-filters">
          <label class="lc-field"><span>维度</span><select id="commonalityDimensionFilter"><option value="">全部维度</option>${dimensions.map(item => `<option value="${esc(item)}">${esc(DIMENSION_LABELS[item])}</option>`).join('')}</select></label>
          <label class="lc-field"><span>共有程度</span><select id="commonalityShareFilter"><option value="">全部共有与部分共有</option><option value="all">全部共有</option><option value="partial">部分共有</option></select></label>
        </div>
        <div id="commonalityCandidateTable">${candidateTableTemplate()}</div>
      </section>`;
    }

    function membersBody() {
      const state = ui.members;
      if (state.loading) return '<p class="lc-loading" role="status">正在读取成员…</p>';
      if (state.error) return drillError(state.error, 'member');
      const response = state.response;
      if (!response) return '';
      const counts = response.counts || {};
      const range = response.hit_time_range;
      const scope = response.query?.match_scope;
      const rows = (response.members || []).map(member => {
        const reasons = (member.reasons || []).map(reason => esc(model.reasonText(reason))).join('、');
        const reasonCell = reasons ? `${member.status === 'miss' ? '未命中依据：' : member.status === 'unknown' ? '未知原因：' : ''}${reasons}` : '—';
        return `<tr><td><input type="checkbox" data-member-select="${esc(member.lot_id)}" aria-label="选择 lot ${esc(member.lot_id)}"></td><td><button type="button" class="lc-link" data-member-lot="${esc(member.lot_id)}" aria-label="查看 lot ${esc(member.lot_id)} 的矩阵与履历">${esc(member.lot_id)}</button></td><td><span class="lc-member-status lc-member-${esc(member.status)}">${esc(MEMBER_STATUS_LABELS[member.status] || member.status)}</span></td><td>${listText(member.record_refs)}</td><td class="lc-wrap">${reasonCell}</td></tr>`;
      }).join('');
      const page = response.page || {};
      return `${sampleSourceNote(response)}
        <p class="lc-member-summary">命中 ${esc(counts.hit)} · 确认未命中 ${esc(counts.miss)} · 未知 ${esc(counts.unknown)} · 分母 ${esc(counts.denominator)}<small>（计数不受成员状态筛选影响）</small></p>
        <p class="lc-hint">实际判定范围：${esc(MATCH_SCOPE_LABELS[scope] || scope)}（${esc(scope)}） · 命中证据时间：${range ? `${timeText(range.first)} 至 ${timeText(range.last)}（${esc(range.timezone)}）` : '无命中证据'}</p>
        ${rows ? `<div class="table-wrap"><table class="lc-table lc-members"><thead><tr><th scope="col"><span class="lc-sr-only">选择</span></th><th scope="col">lot</th><th scope="col">状态</th><th scope="col">证据记录</th><th scope="col">未命中依据 / 未知原因</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="empty">本页没有符合条件的成员</p>'}
        <div class="lc-pager"><span>第 ${state.cursors.length + 1} 页 · 本页 ${esc(page.returned)} 个 · 共 ${esc(page.total)} 个</span>
          <button type="button" class="secondary-btn lc-small-btn" data-member-page="first"${state.cursors.length ? '' : ' disabled'}>回到第一页</button>
          <button type="button" class="secondary-btn lc-small-btn" data-member-page="next"${page.next_cursor ? '' : ' disabled'}>下一页</button>
          <button type="button" class="secondary-btn lc-small-btn" data-member-compare>查看所选 lot 履历</button></div>`;
    }

    function focusedKey(container, attribute) {
      const active = document.activeElement;
      if (!active || !container.contains(active) || !active.hasAttribute(attribute)) return null;
      return { value: active.getAttribute(attribute), radio: active.type === 'radio' ? active.value : null };
    }
    function restoreFocus(container, attribute, key) {
      if (!key) return;
      const target = [...container.querySelectorAll(`[${attribute}]`)].find(node => node.getAttribute(attribute) === key.value && (key.radio === null || node.value === key.radio));
      target?.focus({ preventScroll: true });
    }

    function renderMembers() {
      const node = $('#commonalityMembers');
      const state = ui.members;
      if (!state || !ui.result) { node.hidden = true; node.innerHTML = ''; return; }
      const focused = focusedKey(node, 'data-member-control');
      const candidate = findCandidate(state.candidateId);
      const isPath = candidate?.dimension === 'path_adjacent';
      node.hidden = false;
      node.innerHTML = `<div class="panel-heading"><div><h2 id="commonalityMembersTitle">成员清单</h2><p>${esc(candidate?.label || state.candidateId)} · ${esc(groupName(state.groupId))}</p></div><div class="lc-badges">${sampleBadge()}${staleBadge()}<button type="button" class="secondary-btn lc-small-btn" data-lc-back="results">返回共性结果</button></div></div>
        <div class="lc-member-controls">
          <label class="lc-field"><span>成员状态</span><select data-member-control="status"><option value="">全部</option>${STATUSES.map(status => `<option value="${status}"${state.status === status ? ' selected' : ''}>${esc(MEMBER_STATUS_LABELS[status])}</option>`).join('')}</select></label>
          <label class="lc-check"><input type="checkbox" data-member-control="rework"${state.rework ? ' checked' : ''}><span>同时满足：返工</span></label>
          <fieldset class="lc-inline-fieldset"${state.rework ? '' : ' disabled'}><legend>组合判定范围</legend>
            <label class="lc-check"><input type="radio" name="commonalityMatchScope" value="same_pass" data-member-control="matchScope"${state.matchScope === 'same_pass' ? ' checked' : ''}${isPath ? ' disabled' : ''}><span>同一次过站</span></label>
            <label class="lc-check"><input type="radio" name="commonalityMatchScope" value="any_pass" data-member-control="matchScope"${state.matchScope === 'any_pass' ? ' checked' : ''}><span>任意过站</span></label>
          </fieldset>
          <label class="lc-field"><span>每页</span><select data-member-control="limit">${PAGE_SIZES.map(size => `<option value="${size}"${state.limit === size ? ' selected' : ''}>${size}</option>`).join('')}</select></label>
          ${isPath ? '<p class="lc-hint">路径候选涉及两次过站，不能用于同一次过站</p>' : ''}
        </div>
        <div class="lc-drill-body">${membersBody()}</div>`;
      restoreFocus(node, 'data-member-control', focused);
      updateBadges();
    }

    function membersRequest(state) {
      const conditions = [{ candidate_id: state.candidateId }];
      if (state.rework) conditions.push({ attribute: 'rework', value: true });
      return {
        group_id: state.groupId, conditions, match_scope: state.rework ? state.matchScope : 'any_pass',
        status: state.status || null, limit: state.limit, cursor: state.cursor,
      };
    }
    async function loadMembers() {
      const state = ui.members, result = ui.result;
      const token = membersGate.begin();
      state.loading = true; state.error = null;
      renderMembers();
      try {
        const response = await result.client.readMembers(result.analysis.analysis_ref, membersRequest(state));
        if (!membersGate.isCurrent(token) || ui.members !== state) return;
        state.response = response;
      } catch (error) {
        if (!membersGate.isCurrent(token) || ui.members !== state) return;
        state.response = null; state.error = error;
        if (model.isResultUnavailable(error) && ui.result === result) markUnavailable(error);
      }
      state.loading = false;
      renderMembers();
    }
    function openMembers({ candidateId, groupId, status }) {
      ui.members = { candidateId, groupId, status, rework: false, matchScope: 'any_pass', limit: defaultLimit(), cursor: null, cursors: [], response: null, error: null, loading: true, origin: { candidateId, groupId, status } };
      ui.records = null; recordsGate.invalidate();
      renderRecords();
      loadMembers();
      $('#commonalityMembers').scrollIntoView?.({ block: 'start' });
    }

    function coverageNotes(lot, passes) {
      const coverage = lot.coverage || {};
      const notes = [];
      if (!passes.length) notes.push('<span class="lc-note lc-note-empty">范围内没有该 lot 的过站记录（零命中）</span>');
      if (coverage.truncated) notes.push('<span class="lc-note lc-note-truncated">来源记录已截断：已取到记录中的命中仍有效，确认未命中改判为未知</span>');
      for (const failure of coverage.failures || []) {
        const label = typeof failure === 'string' ? failure : model.reasonText(failure.reason || failure.code || failure);
        notes.push(`<span class="lc-note lc-note-failed">来源读取故障：${esc(label)}${failure?.record_refs?.length ? `（${listText(failure.record_refs)}）` : ''}</span>`);
      }
      for (const gap of coverage.gaps || []) {
        notes.push(`<span class="lc-note lc-note-order">顺序缺口：${listText(gap.record_refs)} 缺少来源序号（${esc(model.reasonText(gap.reason))}，位于 ${textOrDash(gap.after_record_ref)} 之后）</span>`);
      }
      const missing = [...new Set(passes.flatMap(item => item.missing_fields || []))];
      if (missing.length) notes.push(`<span class="lc-note lc-note-missing">缺字段：${listText(missing)}</span>`);
      return notes.join('');
    }

    function chamberTemplate(item, candidate) {
      const chamberKey = candidate?.subject?.chamber_key;
      const chambers = (item.chambers || []).map(chamber => {
        const count = chamber.wafer_count === null || chamber.wafer_count === undefined ? '片数未知' : `${chamber.wafer_count} 片`;
        return `<span class="lc-chamber${chamberKey && chamber.chamber_key === chamberKey ? ' lc-chamber-hit' : ''}">${esc(chamber.chamber)} · ${esc(count)}</span>`;
      }).join('');
      const notes = [];
      if (item.chamber_granularity === 'reported') notes.push('<span class="lc-note">来源仅证明用过该腔</span>');
      else if (item.chamber_granularity === 'unknown') notes.push('<span class="lc-note lc-note-missing">腔室缺失（来源未给出）</span>');
      else if (item.chamber_granularity === 'not_applicable') notes.push('<span class="lc-note">该站无腔室</span>');
      if (item.chamber_set_complete === false && item.chamber_granularity !== 'unknown') notes.push('<span class="lc-note lc-note-missing">腔室集合不完整</span>');
      if (item.allocated_wafer_total !== null && item.allocated_wafer_total !== undefined) notes.push(`<span class="lc-note">已分配 ${esc(item.allocated_wafer_total)} 片</span>`);
      return chambers + notes.join('');
    }
    const reworkTag = item => (item.rework?.is_rework ? `<span class="lc-rework-tag">返工（返工自 ${item.rework.rework_of_record_ref ? esc(item.rework.rework_of_record_ref) : '来源未关联'}）</span>` : '');
    function wafersTemplate(item) {
      return (item.chambers || []).filter(chamber => Array.isArray(chamber.wafer_ids) && chamber.wafer_ids.length).map(chamber => `<details class="lc-wafers"><summary>${esc(chamber.chamber)} wafer（${esc(chamber.wafer_ids.length)}）</summary><p>${chamber.wafer_ids.map(esc).join('、')}</p></details>`).join('');
    }
    function cellTemplate(item, candidate) {
      const subject = candidate?.subject || {};
      const equipmentHit = subject.equipment_id && item.equipment_id === subject.equipment_id;
      return `<td class="lc-cell${item.rework?.is_rework ? ' lc-cell-rework' : ''}"><button type="button" class="lc-cell-button" data-record-ref="${esc(item.record_ref)}" aria-label="查看 ${esc(item.record_ref)} 履历明细">
        <span class="lc-cell-ref">${esc(item.record_ref)}</span>${reworkTag(item)}
        <span class="${equipmentHit ? 'lc-value-hit' : ''}">机台 ${textOrDash(item.equipment_id)}</span>
        <span class="lc-chambers">${chamberTemplate(item, candidate)}</span>
        <span>recipe ${textOrDash(item.recipe)}</span>
        ${item.missing_fields?.length ? `<span class="lc-note lc-note-missing">缺字段：${listText(item.missing_fields)}</span>` : ''}
      </button>${wafersTemplate(item)}</td>`;
    }

    function matrixTemplate(response, candidate, grouped) {
      let operations = model.candidateOperations(candidate);
      if (!operations.length) operations = [...new Set((response.passes || []).map(item => item.operation_key))];
      const widths = operations.map(operation => Math.max(1, ...[...grouped.values()].map(passes => passes.filter(item => item.operation_key === operation).length)));
      const head = `<thead><tr><th rowspan="2" scope="col">lot</th><th rowspan="2" scope="col">候选判定</th>${operations.map((operation, index) => `<th colspan="${widths[index]}" scope="colgroup">${esc(operation)}</th>`).join('')}</tr><tr>${widths.map(width => Array.from({ length: width }, (_, index) => `<th scope="col">${index === 0 ? '过站 1' : `过站 ${index + 1}（重复 / 返工）`}</th>`).join('')).join('')}</tr></thead>`;
      const rows = (response.lots || []).map(lot => {
        const passes = grouped.get(lot.lot_id) || [];
        const cells = operations.map((operation, index) => {
          const atStation = passes.filter(item => item.operation_key === operation);
          return Array.from({ length: widths[index] }, (_, occurrence) => (atStation[occurrence] ? cellTemplate(atStation[occurrence], candidate) : `<td class="lc-empty-cell">${occurrence === 0 ? '未经过' : '—'}</td>`)).join('');
        }).join('');
        return `<tr data-matrix-lot="${esc(lot.lot_id)}"><th scope="row">${esc(lot.lot_id)}</th><td><span class="lc-member-status lc-member-${esc(lot.candidate_status)}">${esc(MEMBER_STATUS_LABELS[lot.candidate_status] || lot.candidate_status || '—')}</span></td>${cells}</tr>`;
      }).join('');
      return `<div class="table-wrap"><table class="lc-table lc-matrix">${head}<tbody>${rows}</tbody></table></div>`;
    }

    function stepTemplate(item, operations) {
      const highlight = operations.includes(item.operation_key) ? ' lc-step-candidate' : '';
      return `<li><button type="button" class="lc-step${highlight}" data-record-ref="${esc(item.record_ref)}"><span>${item.pass_seq === null || item.pass_seq === undefined ? '序号缺失' : `#${esc(item.pass_seq)}`}</span> ${esc(item.operation_key)} · ${textOrDash(item.equipment_id)}${reworkTag(item)}</button></li>`;
    }
    function pathTemplate(response, candidate, grouped) {
      const operations = model.candidateOperations(candidate);
      return `<div class="lc-paths">${(response.lots || []).map(lot => {
        const { ordered, unordered } = model.splitPathOrder(grouped.get(lot.lot_id) || []);
        return `<section class="lc-path" data-path-lot="${esc(lot.lot_id)}"><h4>${esc(lot.lot_id)}</h4>
          ${ordered.length ? `<ol class="lc-path-steps">${ordered.map(item => stepTemplate(item, operations)).join('')}</ol>` : '<p class="lc-hint">没有带来源序号的过站</p>'}
          ${unordered.length ? `<div class="lc-path-unknown"><h5>顺序未知</h5><ul class="lc-path-steps">${unordered.map(item => stepTemplate(item, operations)).join('')}</ul></div>` : ''}</section>`;
      }).join('')}</div>`;
    }

    function passesTableTemplate(response, timezone) {
      const selected = new Set(ui.records.selectedRefs);
      const rows = (response.passes || []).map(item => `<tr data-record-row="${esc(item.record_ref)}"${selected.has(item.record_ref) ? ' class="lc-selected"' : ''}>
        <th scope="row">${esc(item.record_ref)}</th><td class="lc-wrap">${textOrDash(item.source_pass_id)} · ${listText(item.source_record_refs)}</td><td>${esc(item.lot_id)}</td>
        <td>${item.pass_seq === null || item.pass_seq === undefined ? '序号缺失' : esc(item.pass_seq)}</td><td>${textOrDash(item.layer)} / ${textOrDash(item.step)}<br><small>${esc(item.operation_key)}</small></td>
        <td>${textOrDash(item.equipment_id)}</td><td class="lc-wrap">${(item.chambers || []).map(chamber => `${esc(chamber.chamber)}（${chamber.wafer_count === null || chamber.wafer_count === undefined ? '片数未知' : `${esc(chamber.wafer_count)} 片`}）`).join('、') || esc(GRANULARITY_LABELS[item.chamber_granularity] || '—')}</td>
        <td>${textOrDash(item.recipe)}</td><td>${timeText(item.track_in_at)}</td><td>${item.queue_hours === null || item.queue_hours === undefined ? '缺失' : esc(item.queue_hours)}</td>
        <td>${item.rework?.is_rework ? `返工自 ${textOrDash(item.rework.rework_of_record_ref)}` : '否'}</td><td>${listText(item.missing_fields)}</td></tr>`).join('');
      return `<h3 class="lc-subheading" id="commonalityPassesTitle">履历明细</h3>${rows ? `<div class="table-wrap" tabindex="0" role="region" aria-labelledby="commonalityPassesTitle"><table class="lc-table lc-passes"><thead><tr><th scope="col">记录</th><th scope="col">来源批号 · 来源记录</th><th scope="col">lot</th><th scope="col">序号</th><th scope="col">层别 / 工序</th><th scope="col">机台</th><th scope="col">腔室（片数）</th><th scope="col">recipe</th><th scope="col">加工时间（来源时区 ${textOrDash(timezone)}）</th><th scope="col">等待（小时）</th><th scope="col">返工</th><th scope="col">缺失字段</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="empty">本页没有过站记录（零命中）</p>'}`;
    }

    function recordsBody() {
      const state = ui.records;
      if (state.loading) return '<p class="lc-loading" role="status">正在读取履历…</p>';
      if (state.error) return drillError(state.error, 'records');
      const response = state.response;
      if (!response) return '';
      const candidate = findCandidate(response.candidate_id ?? state.candidateId);
      const grouped = model.passesByLot(response);
      const coverage = (response.lots || []).map(lot => {
        const coverageInfo = lot.coverage || {};
        return `<li data-coverage-lot="${esc(lot.lot_id)}"><strong>${esc(lot.lot_id)}</strong> 候选判定：${esc(MEMBER_STATUS_LABELS[lot.candidate_status] || lot.candidate_status || '—')} · lot 片数 ${textOrDash(lot.wafer_count)} · 记录${esc(COVERAGE_LABELS[coverageInfo.records] || coverageInfo.records || '—')} · 顺序${esc(COVERAGE_LABELS[coverageInfo.order] || coverageInfo.order || '—')} ${coverageNotes(lot, grouped.get(lot.lot_id) || [])}</li>`;
      }).join('');
      const page = response.page || {};
      return `${sampleSourceNote(response)}<ul class="lc-coverage">${coverage}</ul>
        <div class="segmented lc-view-toggle" role="group" aria-label="切换矩阵或路径视图"><button type="button" data-records-view="matrix" class="${state.view === 'matrix' ? 'active' : ''}" aria-pressed="${state.view === 'matrix'}">矩阵</button><button type="button" data-records-view="path" class="${state.view === 'path' ? 'active' : ''}" aria-pressed="${state.view === 'path'}">路径</button></div>
        ${state.view === 'path' ? pathTemplate(response, candidate, grouped) : matrixTemplate(response, candidate, grouped)}
        ${passesTableTemplate(response, ui.result.analysis.source?.timezone)}
        <div class="lc-pager"><span>第 ${state.cursors.length + 1} 页 · 本页 ${esc(page.returned)} 条 · 共 ${esc(page.total)} 条过站</span>
          <button type="button" class="secondary-btn lc-small-btn" data-records-page="first"${state.cursors.length ? '' : ' disabled'}>回到第一页</button>
          <button type="button" class="secondary-btn lc-small-btn" data-records-page="next"${page.next_cursor ? '' : ' disabled'}>下一页</button></div>`;
    }

    function renderRecords() {
      const node = $('#commonalityRecords');
      const state = ui.records;
      if (!state || !ui.result) { node.hidden = true; node.innerHTML = ''; return; }
      const candidate = findCandidate(state.candidateId);
      const focused = focusedKey(node, 'data-records-view');
      node.hidden = false;
      node.innerHTML = `<div class="panel-heading"><div><h2 id="commonalityRecordsTitle">Lot 矩阵与履历</h2><p>lot：${state.lotIds.map(esc).join('、')}${candidate ? ` · 候选：${esc(candidate.label)}` : ''}</p></div><div class="lc-badges">${sampleBadge()}${staleBadge()}<button type="button" class="secondary-btn lc-small-btn" data-lc-back="members">返回成员清单</button></div></div>
        <div class="lc-drill-body">${recordsBody()}</div>`;
      restoreFocus(node, 'data-records-view', focused);
      updateBadges();
    }

    async function loadRecords() {
      const state = ui.records, result = ui.result;
      const token = recordsGate.begin();
      state.loading = true; state.error = null;
      renderRecords();
      const body = { group_id: state.groupId, lot_ids: state.lotIds, candidate_id: state.candidateId, limit: defaultLimit(), cursor: state.cursor };
      try {
        const response = await result.client.readRecords(result.analysis.analysis_ref, body);
        if (!recordsGate.isCurrent(token) || ui.records !== state) return;
        state.response = response;
      } catch (error) {
        if (!recordsGate.isCurrent(token) || ui.records !== state) return;
        state.response = null; state.error = error;
        if (model.isResultUnavailable(error) && ui.result === result) markUnavailable(error);
      }
      state.loading = false;
      renderRecords();
    }
    function openRecords(lotIds) {
      const members = ui.members;
      const evidence = (members?.response?.members || []).filter(member => lotIds.includes(member.lot_id)).flatMap(member => member.record_refs || []);
      ui.records = { lotIds, groupId: members.groupId, candidateId: members.candidateId, cursor: null, cursors: [], response: null, error: null, loading: true, view: 'matrix', selectedRefs: evidence, originLot: lotIds[0] };
      loadRecords();
      $('#commonalityRecords').scrollIntoView?.({ block: 'start' });
    }

    function renderAll() {
      renderResults(); renderMembers(); renderRecords(); updateBadges();
    }

    function focusMatching(selector, predicate) {
      const target = [...view().querySelectorAll(selector)].find(predicate);
      target?.focus();
      target?.scrollIntoView?.({ block: 'center' });
    }

    function onResultsChange(event) {
      if (event.target.id === 'commonalityDimensionFilter') ui.filters.dimension = event.target.value;
      else if (event.target.id === 'commonalityShareFilter') ui.filters.share = event.target.value;
      else return;
      $('#commonalityCandidateTable').innerHTML = candidateTableTemplate();
    }
    function onResultsClick(event) {
      if (event.target.closest('[data-lc-ask]') && ui.result && !ui.result.sample && !ui.result.unavailable) {
        askAssistant?.(model.assistantDraft(ui.result.analysis));
        return;
      }
      const count = event.target.closest('[data-lc-count]');
      if (count) openMembers({ candidateId: count.dataset.candidateId, groupId: count.dataset.groupId, status: count.dataset.status });
    }
    function onMembersChange(event) {
      const control = event.target.closest('[data-member-control]');
      if (!control || !ui.members) return;
      const state = ui.members;
      const field = control.dataset.memberControl;
      if (field === 'status') state.status = control.value || null;
      else if (field === 'limit') state.limit = Number(control.value);
      else if (field === 'matchScope') state.matchScope = control.value;
      else if (field === 'rework') {
        state.rework = control.checked;
        const isPath = findCandidate(state.candidateId)?.dimension === 'path_adjacent';
        state.matchScope = state.rework && !isPath ? 'same_pass' : 'any_pass';
      }
      state.cursor = null; state.cursors = [];
      ui.records = null; recordsGate.invalidate(); renderRecords();
      loadMembers();
    }
    function onMembersClick(event) {
      const state = ui.members;
      if (!state) return;
      if (event.target.closest('[data-lc-back="results"]')) {
        const { origin } = state;
        ui.members = null; ui.records = null; membersGate.invalidate(); recordsGate.invalidate();
        renderMembers(); renderRecords();
        focusMatching('[data-lc-count]', node => node.dataset.candidateId === origin.candidateId && node.dataset.groupId === origin.groupId && node.dataset.status === origin.status);
        return;
      }
      if (event.target.closest('[data-member-retry]')) { loadMembers(); return; }
      const lot = event.target.closest('[data-member-lot]');
      if (lot) { openRecords([lot.dataset.memberLot]); return; }
      if (event.target.closest('[data-member-compare]')) {
        const selected = [...$('#commonalityMembers').querySelectorAll('[data-member-select]:checked')].map(node => node.dataset.memberSelect);
        if (selected.length) openRecords(selected);
        else $('#commonalityMembers .lc-pager span').textContent = '请先勾选要对比的 lot';
        return;
      }
      const page = event.target.closest('[data-member-page]');
      if (page && !page.disabled) {
        if (page.dataset.memberPage === 'next' && state.response?.page?.next_cursor) { state.cursors.push(state.cursor); state.cursor = state.response.page.next_cursor; }
        else if (page.dataset.memberPage === 'first') { state.cursor = null; state.cursors = []; }
        loadMembers();
      }
    }
    function onRecordsClick(event) {
      const state = ui.records;
      if (!state) return;
      if (event.target.closest('[data-lc-back="members"]')) {
        const lotId = state.originLot;
        ui.records = null; recordsGate.invalidate(); renderRecords();
        focusMatching('[data-member-lot]', node => node.dataset.memberLot === lotId);
        return;
      }
      if (event.target.closest('[data-records-retry]')) { loadRecords(); return; }
      const toggle = event.target.closest('[data-records-view]');
      if (toggle) { state.view = toggle.dataset.recordsView; renderRecords(); return; }
      const ref = event.target.closest('[data-record-ref]');
      if (ref) {
        state.selectedRefs = [ref.dataset.recordRef];
        $('#commonalityRecords').querySelectorAll('[data-record-row]').forEach(row => row.classList.toggle('lc-selected', row.dataset.recordRow === ref.dataset.recordRef));
        const row = [...$('#commonalityRecords').querySelectorAll('[data-record-row]')].find(node => node.dataset.recordRow === ref.dataset.recordRef);
        row?.scrollIntoView?.({ block: 'center' });
        return;
      }
      const page = event.target.closest('[data-records-page]');
      if (page && !page.disabled) {
        if (page.dataset.recordsPage === 'next' && state.response?.page?.next_cursor) { state.cursors.push(state.cursor); state.cursor = state.response.page.next_cursor; }
        else if (page.dataset.recordsPage === 'first') { state.cursor = null; state.cursors = []; }
        loadRecords();
      }
    }

    function onGroupsInput(event) {
      const field = event.target.dataset.groupField;
      const node = event.target.closest('[data-group-key]');
      if (!field || !node || field === 'role') return;
      const group = ui.groups.find(item => item.key === node.dataset.groupKey);
      if (!group) return;
      group[field] = event.target.value;
      updateGroupSummaries();
      markInputChanged();
    }
    function onGroupsChange(event) {
      if (event.target.dataset.groupField !== 'role') return;
      const group = ui.groups.find(item => item.key === event.target.closest('[data-group-key]').dataset.groupKey);
      const others = ui.groups.filter(item => item !== group);
      const wasDefault = group.name === defaultName(group.role, others) || group.name === ROLE_LABELS[group.role];
      group.role = event.target.value;
      if (wasDefault) {
        group.name = defaultName(group.role, others);
        groupNode(group.key).querySelector('[data-group-field="name"]').value = group.name;
      }
      updateGroupSummaries();
      markInputChanged();
    }
    function onGroupsClick(event) {
      const remove = event.target.closest('[data-remove-group]');
      if (!remove) return;
      ui.groups = ui.groups.filter(group => group.key !== remove.dataset.removeGroup);
      renderGroups();
      markInputChanged();
      $('#addCommonalityGroup').focus();
    }
    function addGroup() {
      const group = newGroup($('#commonalityNewGroupRole').value);
      ui.groups.push(group);
      renderGroups();
      markInputChanged();
      groupNode(group.key)?.querySelector('textarea')?.focus();
    }

    async function openAnalysis(analysisRef) {
      showView?.('commonality', { history: 'push' });
      const shown = ui.result && !ui.result.sample && !ui.result.unavailable && ui.result.analysis.analysis_ref === analysisRef;
      if (shown && !isStale()) { $('#commonalityResults').scrollIntoView?.({ block: 'start' }); return; }
      const token = queryGate.begin();
      setStatus('正在打开对话中的分析结果…', 'info');
      updateBadges();
      try {
        const analysis = await httpClient.readAnalysis(analysisRef);
        if (!queryGate.isCurrent(token)) return;
        applyDraft(model.draftFromAnalysis(analysis));
        ui.result = { analysis, client: httpClient, sample: false, token, inputVersion: ui.inputVersion };
        ui.filters = { dimension: '', share: '' };
        ui.members = null; ui.records = null;
        membersGate.invalidate(); recordsGate.invalidate();
        const partial = analysis.status === 'partial';
        setStatus(`已打开分析结果：${analysis.candidates.length} 个共性项；输入区已按该结果回填${partial ? '；部分 lot 资料不足，见组回执' : ''}`, partial ? 'warn' : 'info');
        renderAll();
        $('#commonalityResults').scrollIntoView?.({ block: 'start' });
      } catch (error) {
        if (!queryGate.isCurrent(token)) return;
        if (model.isResultUnavailable(error) && ui.result?.analysis.analysis_ref === analysisRef && !ui.result.sample) {
          markUnavailable(error);
        } else if (model.isResultUnavailable(error)) {
          setStatus('该结果已不可读取（已过期、无权访问或所属会话已删除），请重新查询', 'error', failureDetails(error));
        } else {
          setStatus(`打开结果失败：${model.errorText(error)}`, 'error', failureDetails(error));
        }
        updateBadges();
      }
    }
    function bindCommonalityEvents() {
      if (bound || !$('#commonalityView')) return;
      bound = true;
      ui.groups = [newGroup('primary', [])];
      renderGroups();
      updateScopeSummary();
      $('#commonalityGroups').addEventListener('input', onGroupsInput);
      $('#commonalityGroups').addEventListener('change', onGroupsChange);
      $('#commonalityGroups').addEventListener('click', onGroupsClick);
      $('#addCommonalityGroup').addEventListener('click', addGroup);
      $('#commonalityScope').addEventListener('input', markInputChanged);
      $('#commonalityScope').addEventListener('change', markInputChanged);
      $('#commonalityForm').addEventListener('submit', runQuery);
      $('#loadCommonalitySample').addEventListener('click', loadSample);
      $('#commonalityResults').addEventListener('change', onResultsChange);
      $('#commonalityResults').addEventListener('click', onResultsClick);
      $('#commonalityMembers').addEventListener('change', onMembersChange);
      $('#commonalityMembers').addEventListener('click', onMembersClick);
      $('#commonalityRecords').addEventListener('click', onRecordsClick);
      document.documentElement.dataset.commonalityReady = 'true';
    }

    return { bindCommonalityEvents, openAnalysis };
  }

  return { createCommonalityController };
});
