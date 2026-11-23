const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const model = require('../app/static/app/commonality/model.js');

const FIXTURE = path.join(__dirname, 'fixtures/lot_commonality/contract_examples.json');
const PUBLISHED = path.join(__dirname, '../display_mock_data/lot_commonality/contract_examples.json');
const document = JSON.parse(fs.readFileSync(FIXTURE, 'utf8'));
const examples = document.examples;
const REF = examples.create_analysis.response.analysis_ref;

test('published sample is a byte-identical copy of the contract fixture', () => {
  assert.ok(fs.readFileSync(PUBLISHED).equals(fs.readFileSync(FIXTURE)));
});

test('lot input accepts newline, tab and comma separated Excel columns and reports duplicates', () => {
  assert.deepEqual(model.splitLotInput(' A \r\nB\tC,D，E\n\n  \nA'), ['A', 'B', 'C', 'D', 'E', 'A']);
  const summary = model.summarizeLots('A\nB\n\n A \nC\nB\nA');
  assert.deepEqual(summary.lot_ids, ['A', 'B', 'A', 'C', 'B', 'A']);
  assert.deepEqual(summary.unique, ['A', 'B', 'C']);
  assert.deepEqual(summary.duplicates, ['A', 'B']);
  assert.equal(model.describeGroupSummary(summary), '输入 6 个，去重后 3 个，重复：A、B');
  assert.equal(model.describeGroupSummary(model.summarizeLots('')), '输入 0 个，去重后 0 个，无重复');
});

test('cross-group overlaps keep membership in every group', () => {
  const overlaps = model.findOverlaps([
    { key: 'g1', text: 'A\nB\nB\nC' }, { key: 'g2', text: 'B\nJ' }, { key: 'g3', text: 'C, B' },
  ]);
  assert.deepEqual(overlaps, [{ lot_id: 'B', keys: ['g1', 'g2', 'g3'] }, { lot_id: 'C', keys: ['g1', 'g3'] }]);
});

test('group ids follow the contract pattern, stay unique and never use union', () => {
  const ids = model.assignGroupIds([
    { role: 'primary' }, { role: 'concurrent_abnormal' }, { role: 'concurrent_abnormal' }, { role: 'historical_abnormal' }, { role: 'normal_reference' },
  ]);
  assert.deepEqual(ids, ['main', 'concurrent', 'concurrent-2', 'historical', 'normal']);
  for (const id of ids) assert.match(id, model.GROUP_ID_PATTERN);
  assert.equal(model.isValidGroupId('union'), false);
  assert.equal(model.isValidGroupId('9main'), false);
});

test('create request assembled from the editor equals the contract example request', () => {
  const draft = model.draftFromRequest(examples.create_analysis.request);
  const { errors, request } = model.buildCreateRequest(draft);
  assert.deepEqual(errors, []);
  assert.deepEqual(request, examples.create_analysis.request);
});

test('create request carries optional scope and omits an empty description', () => {
  const { request } = model.buildCreateRequest({
    groups: [{ name: '', role: 'primary', text: 'A\nB' }], dimensions: ['path_adjacent', 'equipment'], description: '  ',
    scope: { timeStart: '2026-11-10T08:00', timeEnd: '2026-11-11T08:00', cutoffMode: 'operation', cutoffOperation: ' GATE/ETCH ', cutoffOccurrence: '2' },
  });
  assert.deepEqual(request, {
    groups: [{ group_id: 'main', name: '本次异常', role: 'primary', lot_ids: ['A', 'B'] }],
    dimensions: ['equipment', 'path_adjacent'],
    scope: { time_range: { start: '2026-11-10T08:00:00+08:00', end: '2026-11-11T08:00:00+08:00' }, cutoff: { mode: 'operation', operation_key: 'GATE/ETCH', occurrence: 2, per_lot: {} } },
    timezone: 'Asia/Shanghai',
  });
  assert.equal(model.describeScope(request.scope, request.timezone), '加工时间 2026-11-10T08:00:00+08:00 至 2026-11-11T08:00:00+08:00（含开始、不含结束） · 截止工序 GATE/ETCH 第 2 次（含该过站） · 时区 Asia/Shanghai');
});

test('time conditions carry the timezone offset the server requires', () => {
  const base = { groups: [{ name: '', role: 'primary', text: 'A' }], dimensions: ['equipment'] };
  const { request } = model.buildCreateRequest({ ...base, scope: { cutoffMode: 'time', cutoffAt: '2026-11-10T09:30' } });
  assert.deepEqual(request.scope.cutoff, { mode: 'time', at: '2026-11-10T09:30:00+08:00' });
  const rejected = model.buildCreateRequest({ ...base, timezone: 'Europe/Paris', scope: { timeStart: '2026-11-10T08:00', timeEnd: '2026-11-11T08:00' } });
  assert.equal(rejected.request, null);
  assert.deepEqual(rejected.errors, ['所选时区没有固定偏移，无法提交时间条件']);
});

test('invalid drafts are rejected before any request is built', () => {
  const { errors, request } = model.buildCreateRequest({
    groups: [{ name: '本次异常', role: 'primary', text: '\n \n' }, { name: '同期异常', role: 'concurrent_abnormal', text: '' }],
    dimensions: [], scope: { timeStart: '2026-11-11T08:00', timeEnd: '2026-11-10T08:00', cutoffMode: 'operation', cutoffOperation: '', cutoffOccurrence: '0' },
  });
  assert.equal(request, null);
  assert.deepEqual(errors, [
    '「本次异常」至少需要一个 lot', '对比组「同期异常」没有 lot，请填写或删除该组', '至少选择一个分析维度',
    '加工时间范围的开始必须早于结束', '请填写截止工序（operation_key）', '截止工序的出现次数必须是正整数',
  ]);
});

test('latest gate drops responses from requests superseded by a newer one', async () => {
  const gate = model.createLatestGate();
  const applied = [];
  const run = async (label, delay) => {
    const token = gate.begin();
    await new Promise(resolve => setTimeout(resolve, delay));
    if (gate.isCurrent(token)) applied.push(label);
  };
  await Promise.all([run('older', 30), run('newer', 5)]);
  assert.deepEqual(applied, ['newer']);
  const token = gate.begin();
  gate.invalidate();
  assert.equal(gate.isCurrent(token), false);
});

test('sample client answers create, members and records only from contract examples', async () => {
  const client = model.createSampleClient(document);
  const analysis = await client.createAnalysis(examples.create_analysis.request);
  assert.equal(analysis.analysis_ref, REF);
  assert.deepEqual(analysis.candidates, examples.create_analysis.response.candidates);
  assert.deepEqual(analysis.sample_source, { example: 'create_analysis', projection: null });

  const members = await client.readMembers(REF, examples.members_chamber_b.request);
  assert.deepEqual(members.members, examples.members_chamber_b.response.members);
  const rework = await client.readMembers(REF, examples.members_chamber_b_rework_same_pass.request);
  assert.deepEqual(rework.counts, { hit: 1, miss: 7, unknown: 0, denominator: 8 });
  assert.equal(rework.query.match_scope, 'same_pass');
  const page2 = await client.readMembers(REF, examples.members_path_etch_metrology_page_2.request);
  assert.deepEqual(page2.members.map(member => member.lot_id), ['E', 'F', 'G', 'H']);

  const records = await client.readRecords(REF, examples.records_chamber_b.request);
  assert.deepEqual(records.passes, examples.records_chamber_b.response.passes);
});

test('sample client status and lot projections keep server counts and source records unchanged', async () => {
  const client = model.createSampleClient(document);
  const unknown = await client.readMembers(REF, { ...examples.members_chamber_b.request, status: 'unknown' });
  assert.deepEqual(unknown.counts, examples.members_chamber_b.response.counts);
  assert.deepEqual(unknown.members, [{ lot_id: 'H', status: 'unknown', record_refs: ['pass:H-02'], reasons: [{ code: 'FIELD_MISSING', field: 'chamber' }] }]);
  assert.equal(unknown.query.status, 'unknown');
  assert.deepEqual(unknown.sample_source, { example: 'members_chamber_b', projection: 'status' });

  const lotB = await client.readRecords(REF, { ...examples.records_chamber_b.request, lot_ids: ['B'] });
  assert.deepEqual(lotB.lots.map(lot => lot.lot_id), ['B']);
  const split = lotB.passes.find(item => item.record_ref === 'pass:B-02');
  assert.deepEqual(split.chambers.map(chamber => [chamber.chamber, chamber.wafer_count]), [['CH-A', 12], ['CH-B', 13]]);
  assert.deepEqual(lotB.passes, examples.records_chamber_b.response.passes.filter(item => item.lot_id === 'B'));
  assert.equal(lotB.page.total, 3);
});

test('sample client reports unmatched queries and replays contract error examples', async () => {
  const client = model.createSampleClient(document);
  const missing = [
    client.createAnalysis({ ...examples.create_analysis.request, dimensions: ['chamber'] }),
    client.readMembers(REF, { ...examples.members_chamber_b.request, group_id: 'concurrent' }),
    client.readMembers(REF, { ...examples.members_chamber_b.request, match_scope: 'same_pass' }),
    client.readMembers(REF, { ...examples.members_path_etch_metrology_page_1.request, status: 'hit' }),
    client.readRecords(REF, { ...examples.records_chamber_b.request, lot_ids: ['A'] }),
    client.readRecords(REF, { ...examples.records_chamber_b.request, lot_ids: ['B'], group_id: 'concurrent' }),
  ];
  for (const pending of missing) {
    await assert.rejects(pending, error => error.code === 'SAMPLE_NOT_INCLUDED' && model.errorText(error) === '样例未包含该查询');
  }
  await assert.rejects(client.readMembers(REF, document.errors.same_pass_with_path.request), error => error.code === 'VALIDATION_ERROR' && error.status === 422);
  await assert.rejects(client.createAnalysis(document.errors.cutoff_ambiguous.request), error => error.code === 'CUTOFF_AMBIGUOUS' && error.context.lots[0].lot_id === 'E');
  await assert.rejects(client.readAnalysis('lca_ffffffffffffffffffffffffffffffff'), error => error.code === 'RESULT_UNAVAILABLE');
});

test('http client posts the contract body and keeps the error envelope', async () => {
  const calls = [];
  const client = model.createHttpClient({
    identityHeaders: initial => ({ ...initial, 'X-User-ID': 'u1' }),
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      if (url.endsWith('/members')) return { ok: false, status: 422, headers: { get: () => '' }, json: async () => document.errors.same_pass_with_path.response };
      return { ok: false, status: 404, headers: { get: () => '' }, json: async () => ({ error_code: 'NOT_FOUND', detail: 'Not Found' }) };
    },
  });
  await assert.rejects(client.createAnalysis(examples.create_analysis.request), error => model.isServiceMissing(error) && model.errorText(error) === '相关性分析查询服务尚未接入');
  assert.equal(calls[0].url, '/api/lot-commonality/analyses');
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body), examples.create_analysis.request);
  assert.equal(calls[0].options.headers['X-User-ID'], 'u1');
  await assert.rejects(client.readMembers(REF, document.errors.same_pass_with_path.request), error => {
    assert.equal(model.isServiceMissing(error), false);
    assert.equal(model.errorText(error), '请求参数不符合要求（VALIDATION_ERROR）：same_pass 只接受单次过站可判断的条件。');
    return true;
  });
  assert.equal(calls[1].url, `/api/lot-commonality/analyses/${REF}/members`);
  const unavailable = new model.CommonalityClientError('结果当前不可读取。', { code: 'RESULT_UNAVAILABLE', status: 404, detail: '结果当前不可读取。' });
  assert.equal(model.isServiceMissing(unavailable), false);
});

test('reason codes, path order and candidate stations are presented from contract fields', () => {
  assert.equal(model.reasonText({ code: 'FIELD_MISSING', field: 'chamber' }), '字段缺失（chamber）');
  for (const code of ['SEQUENCE_UNKNOWN', 'LOT_NOT_FOUND', 'SOURCE_TRUNCATED', 'SOURCE_PAGE_FAILED', 'CUTOFF_NOT_FOUND', 'OTHER_VALUE', 'OPERATION_NOT_VISITED', 'NOT_ADJACENT', 'CONDITIONS_NOT_MET']) {
    assert.notEqual(model.reasonText({ code }), code);
  }
  const records = examples.records_chamber_b.response;
  const grouped = model.passesByLot(records);
  const { ordered, unordered } = model.splitPathOrder(grouped.get('H'));
  assert.deepEqual(ordered.map(item => item.record_ref), ['pass:H-01']);
  assert.deepEqual(unordered.map(item => item.record_ref), ['pass:H-02', 'pass:H-03']);
  const candidates = examples.create_analysis.response.candidates;
  assert.deepEqual(model.candidateOperations(candidates.find(item => item.dimension === 'path_adjacent')), ['GATE/CLEAN', 'GATE/ETCH']);
  assert.deepEqual(model.candidateOperations(candidates.find(item => item.dimension === 'chamber')), ['GATE/ETCH']);
});
