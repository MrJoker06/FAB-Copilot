(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabCommonalityModel = api;
})(globalThis, (root) => {
  const ANALYSES_PATH = '/api/lot-commonality/analyses';
  const SAMPLE_URL = '/display_mock_data/lot_commonality/contract_examples.json';
  const DEFAULT_TIMEZONE = 'Asia/Shanghai';
  // The server rejects times without an offset and never guesses one.
  const TIMEZONE_OFFSETS = { 'Asia/Shanghai': '+08:00' };
  const GROUP_ID_PATTERN = /^[a-z][a-z0-9_-]{0,31}$/;
  const RESERVED_GROUP_IDS = new Set(['union']);
  const DIMENSIONS = ['equipment', 'chamber', 'recipe', 'path_adjacent'];
  const DIMENSION_LABELS = { equipment: '机台', chamber: '腔室', recipe: 'recipe', path_adjacent: '相邻路径' };
  const ROLES = ['primary', 'concurrent_abnormal', 'historical_abnormal', 'normal_reference'];
  const ROLE_LABELS = { primary: '本次异常', concurrent_abnormal: '同期异常', historical_abnormal: '历史异常', normal_reference: '正常参考' };
  const ROLE_ID_BASE = { primary: 'main', concurrent_abnormal: 'concurrent', historical_abnormal: 'historical', normal_reference: 'normal' };
  const LOT_STATE_LABELS = { complete: '可分析', incomplete: '资料不足', not_found: '未找到', source_failed: '来源失败' };
  const MEMBER_STATUS_LABELS = { hit: '命中', miss: '确认未命中', unknown: '未知' };
  const UNKNOWN_REASON_LABELS = {
    LOT_NOT_FOUND: '未找到该 lot', FIELD_MISSING: '字段缺失', CHAMBER_SET_INCOMPLETE: '腔室记录不完整', SEQUENCE_UNKNOWN: '顺序缺失',
    SOURCE_TRUNCATED: '来源记录截断', SOURCE_PAGE_FAILED: '来源分页读取失败', CUTOFF_NOT_FOUND: '未找到截止工序',
  };
  const MISS_BASIS_LABELS = {
    OTHER_VALUE: '为其他值', OPERATION_NOT_VISITED: '未经过该站', NOT_ADJACENT: '下一站不是目标站', CONDITIONS_NOT_MET: '条件未在同一范围内同时满足',
  };
  const MATCH_SCOPE_LABELS = { same_pass: '同一次过站', any_pass: '任意过站' };
  const GRANULARITY_LABELS = {
    not_applicable: '该站无腔室', unknown: '腔室缺失（来源未给出）', reported: '来源仅证明用过该腔',
    wafer_count: '各腔片数已知', wafer_ids: '各腔 wafer 号已知',
  };
  const COVERAGE_LABELS = { complete: '齐全', partial: '不完整' };
  const ANALYSIS_STATUS_LABELS = { complete: '完整', partial: '部分返回' };
  const ERROR_LABELS = {
    SCOPE_DENIED: '无权访问请求的数据范围', RESULT_UNAVAILABLE: '结果当前不可读取', RESULT_CURSOR_INVALID: '分页游标无效',
    VALIDATION_ERROR: '请求参数不符合要求', CUTOFF_AMBIGUOUS: '截止工序出现多次', ANALYSIS_LIMIT_EXCEEDED: '超过分析限额',
    DATA_SOURCE_FAILED: '数据来源失败', NETWORK_ERROR: '无法连接服务', INVALID_RESPONSE: '响应格式不符合契约',
    RESULT_STORAGE_LIMIT: '结果存储已达上限', RESULT_STORE_UNAVAILABLE: '结果库暂不可用', INTERNAL_ERROR: '服务器内部错误',
  };
  const SERVICE_MISSING_CODES = new Set(['NOT_FOUND', 'REQUEST_ERROR', 'HTTP_ERROR']);

  class CommonalityClientError extends Error {
    constructor(message, { code = 'REQUEST_ERROR', status = 0, detail = '', context = null, fields = [], requestId = '', retryable = false } = {}) {
      super(message);
      this.name = 'CommonalityClientError';
      Object.assign(this, { code, status, detail: detail || message, context, fields, requestId, retryable });
    }
  }

  function splitLotInput(text) {
    return String(text ?? '').split(/[\r\n\t,，]+/).map(value => value.trim()).filter(Boolean);
  }

  function summarizeLots(text) {
    const lotIds = splitLotInput(text);
    const seen = new Set(), repeated = new Set(), unique = [], duplicates = [];
    for (const lotId of lotIds) {
      if (!seen.has(lotId)) { seen.add(lotId); unique.push(lotId); }
      else if (!repeated.has(lotId)) { repeated.add(lotId); duplicates.push(lotId); }
    }
    return { lot_ids: lotIds, unique, duplicates, input_count: lotIds.length, unique_count: unique.length };
  }

  function describeGroupSummary(summary) {
    const base = `输入 ${summary.input_count} 个，去重后 ${summary.unique_count} 个`;
    return summary.duplicates.length ? `${base}，重复：${summary.duplicates.join('、')}` : `${base}，无重复`;
  }

  // groups: [{ key, text }] -> [{ lot_id, keys }] for lots that appear in two or more groups.
  function findOverlaps(groups) {
    const membership = new Map();
    for (const group of groups) {
      for (const lotId of summarizeLots(group.text).unique) {
        if (!membership.has(lotId)) membership.set(lotId, []);
        membership.get(lotId).push(group.key);
      }
    }
    return [...membership.entries()].filter(([, keys]) => keys.length > 1).map(([lotId, keys]) => ({ lot_id: lotId, keys }));
  }

  function assignGroupIds(groups) {
    const used = new Set(RESERVED_GROUP_IDS);
    return groups.map(group => {
      const base = ROLE_ID_BASE[group.role] || 'group';
      let id = base, suffix = 2;
      while (used.has(id)) id = `${base}-${suffix++}`;
      used.add(id);
      return id;
    });
  }

  function isValidGroupId(value) {
    return typeof value === 'string' && GROUP_ID_PATTERN.test(value) && !RESERVED_GROUP_IDS.has(value);
  }

  function localDateTime(value) {
    const text = String(value || '').trim();
    if (!text) return null;
    return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text) ? `${text}:00` : text;
  }

  function offsetDateTime(value, timezone) {
    const text = localDateTime(value);
    if (!text) return null;
    if (/(Z|[+-]\d{2}:\d{2})$/.test(text)) return text;
    const offset = TIMEZONE_OFFSETS[timezone || DEFAULT_TIMEZONE];
    return offset ? `${text}${offset}` : null;
  }

  function buildCutoff(scope = {}, timezone = DEFAULT_TIMEZONE) {
    if (scope.cutoffMode === 'time') return { mode: 'time', at: offsetDateTime(scope.cutoffAt, timezone) };
    if (scope.cutoffMode === 'operation') {
      const occurrence = String(scope.cutoffOccurrence ?? '').trim();
      return { mode: 'operation', operation_key: String(scope.cutoffOperation || '').trim(), occurrence: occurrence ? Number(occurrence) : null, per_lot: {} };
    }
    return null;
  }

  function validateDraft(draft) {
    const errors = [];
    const groups = draft.groups || [];
    const primary = groups.filter(group => group.role === 'primary');
    if (primary.length !== 1) errors.push('必须有且只有一个「本次异常」组');
    for (const group of groups) {
      if (!ROLES.includes(group.role)) errors.push(`组「${group.name || '未命名'}」的用途无效`);
      const name = String(group.name || '').trim() || ROLE_LABELS[group.role] || '未命名';
      if (!summarizeLots(group.text).input_count) {
        errors.push(group.role === 'primary' ? `「${name}」至少需要一个 lot` : `对比组「${name}」没有 lot，请填写或删除该组`);
      }
    }
    if (!(draft.dimensions || []).some(item => DIMENSIONS.includes(item))) errors.push('至少选择一个分析维度');
    const scope = draft.scope || {};
    const start = localDateTime(scope.timeStart), end = localDateTime(scope.timeEnd);
    if ((start && !end) || (!start && end)) errors.push('加工时间范围需要同时填写开始和结束');
    if (start && end && start >= end) errors.push('加工时间范围的开始必须早于结束');
    if (scope.cutoffMode === 'time' && !localDateTime(scope.cutoffAt)) errors.push('请选择异常截止时间');
    const timed = start || end || (scope.cutoffMode === 'time' && localDateTime(scope.cutoffAt));
    if (timed && !TIMEZONE_OFFSETS[draft.timezone || DEFAULT_TIMEZONE]) errors.push('所选时区没有固定偏移，无法提交时间条件');
    if (scope.cutoffMode === 'operation') {
      if (!String(scope.cutoffOperation || '').trim()) errors.push('请填写截止工序（operation_key）');
      const occurrence = String(scope.cutoffOccurrence ?? '').trim();
      if (occurrence && !/^[1-9]\d*$/.test(occurrence)) errors.push('截止工序的出现次数必须是正整数');
    }
    return errors;
  }

  function buildCreateRequest(draft) {
    const errors = validateDraft(draft);
    if (errors.length) return { errors, request: null };
    const ids = assignGroupIds(draft.groups);
    if (!ids.every(isValidGroupId)) return { errors: ['组编号生成失败'], request: null };
    const scope = draft.scope || {};
    const timezone = draft.timezone || DEFAULT_TIMEZONE;
    const start = offsetDateTime(scope.timeStart, timezone), end = offsetDateTime(scope.timeEnd, timezone);
    const request = {
      groups: draft.groups.map((group, index) => ({
        group_id: ids[index],
        name: String(group.name || '').trim() || ROLE_LABELS[group.role],
        role: group.role,
        lot_ids: summarizeLots(group.text).lot_ids,
      })),
      dimensions: DIMENSIONS.filter(item => draft.dimensions.includes(item)),
      scope: { time_range: start && end ? { start, end } : null, cutoff: buildCutoff(scope, timezone) },
      timezone,
    };
    const description = String(draft.description || '').trim();
    if (description) request.description = description;
    return { errors: [], request };
  }

  function describeScope(scope, timezone) {
    const range = scope?.time_range;
    const cutoff = scope?.cutoff;
    const rangeText = range ? `加工时间 ${range.start} 至 ${range.end}（含开始、不含结束）` : '加工时间：全部';
    let cutoffText = '截止：不设截止';
    if (cutoff?.mode === 'time') cutoffText = `截止时间 ${cutoff.at}（含截止时刻）`;
    else if (cutoff?.mode === 'operation') cutoffText = `截止工序 ${cutoff.operation_key}${cutoff.occurrence ? ` 第 ${cutoff.occurrence} 次` : ''}（含该过站）`;
    return `${rangeText} · ${cutoffText} · 时区 ${timezone || DEFAULT_TIMEZONE}`;
  }

  function reasonText(reason) {
    const code = typeof reason === 'string' ? reason : reason?.code;
    const label = UNKNOWN_REASON_LABELS[code] || MISS_BASIS_LABELS[code] || code || '未说明';
    return code === 'FIELD_MISSING' && reason?.field ? `${label}（${reason.field}）` : label;
  }

  // The server answers RESULT_UNAVAILABLE alike for expired, foreign and session-deleted results.
  function isResultUnavailable(error) {
    return error?.code === 'RESULT_UNAVAILABLE';
  }

  function isServiceMissing(error) {
    return Number(error?.status) === 404 && SERVICE_MISSING_CODES.has(error.code);
  }

  function errorText(error) {
    if (isServiceMissing(error)) return '相关性分析查询服务尚未接入';
    if (error?.code === 'SAMPLE_NOT_INCLUDED') return '样例未包含该查询';
    const label = ERROR_LABELS[error?.code];
    const detail = error?.detail || error?.message || '';
    const head = label ? `${label}（${error.code}）` : `请求失败${error?.code ? `（${error.code}）` : ''}`;
    return detail && detail !== label ? `${head}：${detail}` : head;
  }

  function createLatestGate() {
    let current = 0;
    return {
      begin() { current += 1; return current; },
      isCurrent(token) { return token === current; },
      invalidate() { current += 1; },
      get current() { return current; },
    };
  }

  function canonical(value) {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === 'object') {
      return Object.keys(value).sort().reduce((result, key) => { result[key] = canonical(value[key]); return result; }, {});
    }
    return value;
  }
  const sameJson = (left, right) => JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
  const clone = value => JSON.parse(JSON.stringify(value));

  function assertAnalysisShape(payload) {
    if (!payload || typeof payload.analysis_ref !== 'string' || !Array.isArray(payload.groups) || !Array.isArray(payload.candidates)) {
      throw new CommonalityClientError('响应格式不符合契约', { code: 'INVALID_RESPONSE' });
    }
    return payload;
  }

  function createHttpClient({ fetchImpl = root.fetch?.bind(root), identityHeaders = initial => initial } = {}) {
    async function request(url, body) {
      const options = body === undefined ? { method: 'GET' } : { method: 'POST', body: JSON.stringify(body) };
      options.headers = identityHeaders(body === undefined ? {} : { 'Content-Type': 'application/json' });
      let response;
      try { response = await fetchImpl(url, options); }
      catch { throw new CommonalityClientError('无法连接 Fab Insight 服务', { code: 'NETWORK_ERROR', retryable: true }); }
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new CommonalityClientError(payload.detail || `请求失败 (${response.status})`, {
          code: payload.error_code || 'REQUEST_ERROR', status: response.status, detail: payload.detail || '',
          context: payload.context || null, fields: Array.isArray(payload.fields) ? payload.fields : [],
          requestId: payload.request_id || response.headers?.get?.('x-request-id') || '',
          retryable: Boolean(payload.retryable),
        });
      }
      return payload;
    }
    const at = ref => `${ANALYSES_PATH}/${encodeURIComponent(ref)}`;
    return {
      kind: 'http',
      createAnalysis: async body => assertAnalysisShape(await request(ANALYSES_PATH, body)),
      readAnalysis: async ref => assertAnalysisShape(await request(at(ref))),
      readMembers: (ref, body) => request(`${at(ref)}/members`, body),
      readRecords: (ref, body) => request(`${at(ref)}/records`, body),
    };
  }

  function validateSampleDocument(document) {
    const create = document?.examples?.create_analysis;
    if (!create?.request || !create?.response || !Array.isArray(create.response.candidates)) {
      throw new CommonalityClientError('契约样例格式不正确', { code: 'INVALID_RESPONSE' });
    }
    return document;
  }

  // Answers only with requests present in the contract examples. Two projections are allowed because
  // the source example is a complete single page: a status filter over members and a lot subset over records.
  function createSampleClient(document) {
    validateSampleDocument(document);
    const examples = Object.entries(document.examples || {});
    const errors = Object.values(document.errors || {});
    const notIncluded = () => Promise.reject(new CommonalityClientError('样例未包含该查询', { code: 'SAMPLE_NOT_INCLUDED' }));
    const fromError = example => Promise.reject(new CommonalityClientError(example.response.detail, {
      code: example.response.error_code, status: example.status, detail: example.response.detail,
      context: example.response.context || null, requestId: example.response.request_id || '', retryable: Boolean(example.response.retryable),
    }));
    const at = ref => `${ANALYSES_PATH}/${ref}`;
    const withSource = (response, example, projection = null) => Object.assign(clone(response), { sample_source: { example, projection } });

    function exact(method, path, body) {
      const found = examples.find(([, example]) => example.method === method && example.path === path && sameJson(example.request, body));
      if (found) return Promise.resolve(withSource(found[1].response, found[0]));
      const failure = errors.find(example => example.method === method && example.path === path && example.request !== null && sameJson(example.request, body));
      return failure ? fromError(failure) : null;
    }

    return {
      kind: 'sample',
      createAnalysis(body) { return exact('POST', ANALYSES_PATH, body) || notIncluded(); },
      readAnalysis(ref) {
        const path = at(ref);
        const found = examples.find(([, example]) => example.method === 'GET' && example.path === path);
        if (found) return Promise.resolve(withSource(found[1].response, found[0]));
        const failure = errors.find(example => example.method === 'GET' && example.path === path);
        return failure ? fromError(failure) : notIncluded();
      },
      readMembers(ref, body) {
        const path = `${at(ref)}/members`;
        const matched = exact('POST', path, body);
        if (matched) return matched;
        if (body?.status && body.cursor === null) {
          const found = examples.find(([, example]) => example.path === path && example.response?.page?.next_cursor === null
            && sameJson(example.request, { ...body, status: null }));
          if (found) {
            const response = withSource(found[1].response, found[0], 'status');
            response.query.status = body.status;
            response.members = response.members.filter(member => member.status === body.status);
            response.page = { ...response.page, returned: response.members.length, total: response.members.length };
            return Promise.resolve(response);
          }
        }
        return notIncluded();
      },
      readRecords(ref, body) {
        const path = `${at(ref)}/records`;
        const matched = exact('POST', path, body);
        if (matched) return matched;
        const lotIds = Array.isArray(body?.lot_ids) ? body.lot_ids : [];
        if (lotIds.length && new Set(lotIds).size === lotIds.length && body.cursor === null) {
          const found = examples.find(([, example]) => example.path === path && example.response?.page?.next_cursor === null
            && example.request.group_id === body.group_id && (example.request.candidate_id ?? null) === (body.candidate_id ?? null)
            && example.request.limit === body.limit && lotIds.every(lotId => example.request.lot_ids.includes(lotId)));
          if (found) {
            const response = withSource(found[1].response, found[0], 'lot_ids');
            response.lots = lotIds.map(lotId => response.lots.find(lot => lot.lot_id === lotId)).filter(Boolean);
            response.passes = lotIds.flatMap(lotId => response.passes.filter(item => item.lot_id === lotId));
            response.page = { ...response.page, returned: response.passes.length, total: response.passes.length };
            return Promise.resolve(response);
          }
        }
        return notIncluded();
      },
    };
  }

  function draftFromRequest(request) {
    const range = request.scope?.time_range, cutoff = request.scope?.cutoff;
    return {
      groups: request.groups.map(group => ({ name: group.name, role: group.role, text: group.lot_ids.join('\n') })),
      dimensions: [...request.dimensions],
      scope: {
        timeStart: range?.start || '', timeEnd: range?.end || '',
        cutoffMode: cutoff?.mode || 'none', cutoffAt: cutoff?.mode === 'time' ? cutoff.at : '',
        cutoffOperation: cutoff?.mode === 'operation' ? cutoff.operation_key : '',
        cutoffOccurrence: cutoff?.mode === 'operation' && cutoff.occurrence ? String(cutoff.occurrence) : '',
      },
      description: request.description || '',
      timezone: request.timezone || DEFAULT_TIMEZONE,
    };
  }

  function candidateOperations(candidate) {
    const subject = candidate?.subject || {};
    if (candidate?.dimension === 'path_adjacent') return [subject.from_operation_key, subject.to_operation_key].filter(Boolean);
    return subject.operation_key ? [subject.operation_key] : [];
  }

  // Server order is lot order, then pass_seq ascending with unknown sequence last; keep it as delivered.
  function passesByLot(records) {
    const grouped = new Map((records?.lots || []).map(lot => [lot.lot_id, []]));
    for (const item of records?.passes || []) {
      if (!grouped.has(item.lot_id)) grouped.set(item.lot_id, []);
      grouped.get(item.lot_id).push(item);
    }
    return grouped;
  }

  function splitPathOrder(passes) {
    return {
      ordered: passes.filter(item => item.pass_seq !== null && item.pass_seq !== undefined),
      unordered: passes.filter(item => item.pass_seq === null || item.pass_seq === undefined),
    };
  }

  return {
    ANALYSES_PATH, SAMPLE_URL, DEFAULT_TIMEZONE, GROUP_ID_PATTERN, DIMENSIONS, DIMENSION_LABELS, ROLES, ROLE_LABELS,
    LOT_STATE_LABELS, MEMBER_STATUS_LABELS, UNKNOWN_REASON_LABELS, MISS_BASIS_LABELS, MATCH_SCOPE_LABELS,
    GRANULARITY_LABELS, COVERAGE_LABELS, ANALYSIS_STATUS_LABELS, CommonalityClientError,
    splitLotInput, summarizeLots, describeGroupSummary, findOverlaps, assignGroupIds, isValidGroupId,
    localDateTime, buildCutoff, validateDraft, buildCreateRequest, describeScope, reasonText, isResultUnavailable, isServiceMissing, errorText, createLatestGate,
    createHttpClient, createSampleClient, validateSampleDocument, draftFromRequest, candidateOperations,
    passesByLot, splitPathOrder,
  };
});
