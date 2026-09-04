const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const knowledge = require('../app/static/app/knowledge/controller.js');
const model = require('../app/static/app/model/controller.js');
const dashboard = require('../app/static/app/dashboard/controller.js');

const element = (extra = {}) => ({
  value: '', textContent: '', innerHTML: '', hidden: false, disabled: false, classList: { add() {}, remove() {}, toggle() {} },
  setAttribute() {}, getAttribute() { return null; }, removeAttribute() {}, closest() { return this; }, ...extra,
});

test('knowledge controller preserves personal listing query, stale mode guard and SSE identity headers', async () => {
  const nodes = {
    '#knowledgeFilter': element({ value: 'SOP test' }), '#knowledgeCount': element(), '#knowledgeDocuments': element(),
    '#knowledgeSource': element(), '#knowledgeTitle': element(), '#knowledgeMeta': element(), '#personalKnowledgeActions': element(),
    '#knowledgeContent': element(), '#knowledgeIndexTitle': element(), '#knowledgeIndexHint': element(),
  };
  const state = { personalKnowledgeRequestId: 0, knowledgeMode: 'personal', personalKnowledgeDocuments: [], selectedPersonalDocumentId: null,
    activeView: 'dashboard', personalJobEventsFallback: false, personalKnowledgePollTimer: null, personalJobEventsController: null,
    personalJobEventsRetryTimer: null, personalJobEventsRefreshTimer: null, personalJobEventsProbeTimer: null, personalJobEventsStableTimer: null,
    personalJobEventsLastId: 'evt-9', personalJobEventsPolicy: null };
  const calls = [];
  const controller = knowledge.createKnowledgeController({
    state, $: selector => nodes[selector] || element(), escapeHtml: value => String(value), formatFileSize: value => String(value),
    api: async url => { calls.push(url); return { items: [{ document_id: 'doc-1', title: 'SOP', filename: 'sop.md', size_bytes: 1, status: 'ready' }] }; },
    identityHeaders: initial => new Headers(initial), personalJobEvents: { isActive: () => false }, personalUploadQueue: {},
    windowImpl: { clearTimeout() {}, setTimeout() { return 1; } }, documentImpl: { querySelectorAll: () => [] },
  });
  const headers = controller.personalJobEventHeaders();
  assert.equal(headers.get('accept'), 'text/event-stream');
  assert.equal(headers.get('last-event-id'), 'evt-9');
  const result = await controller.loadPersonalKnowledgeDocuments({ selectFirst: false });
  assert.equal(calls[0], '/api/knowledge/personal/documents?q=SOP%20test&limit=100');
  assert.equal(result[0].document_id, 'doc-1');
  state.knowledgeMode = 'factory';
  const stale = await controller.loadPersonalKnowledgeDocuments({ selectFirst: false });
  assert.deepEqual(stale, []);
});

test('model controller sends the original settings POST payload and reconciles Thinking through injected facade', async () => {
  const nodes = {
    '#activeModelLabel': element(), '#agentMode': element(), '#modelSelect': element({ value: 'model-b' }),
    '#thinkingToggle': element({ pressed: 'true', getAttribute(name) { return name === 'aria-pressed' ? this.pressed : null; }, setAttribute(name, value) { if (name === 'aria-pressed') this.pressed = value; this[name] = value; } }),
    '#saveModelSettings': element(), '#modelSettingsMessage': element(), '#modelDialog': element({ open: false }),
  };
  const requests = [];
  const controller = model.createModelController({
    state: { modelConfig: null }, $: selector => nodes[selector], escapeHtml: value => String(value), showToast() {}, updateSystemStatus() {},
    thinkingControl: { reconcile: (config, enabled) => ({ enabled: Boolean(enabled) && config.model === 'model-b', supported: config.model === 'model-b' }), supportsThinking: config => config.model === 'model-b' },
    api: async (url, options) => { requests.push([url, options]); return { model: 'model-b', display_name: 'Model B', allowed_models: ['model-b'] }; },
    windowImpl: { setTimeout() { return 1; } }, alertImpl() {},
  });
  await controller.saveModelSettings({ preventDefault() {} });
  assert.equal(requests[0][0], '/api/settings/model');
  assert.equal(requests[0][1].method, 'POST');
  assert.equal(requests[0][1].body, JSON.stringify({ model: 'model-b' }));
  assert.equal(nodes['#thinkingToggle']['aria-disabled'], 'false');
  assert.equal(nodes['#thinkingToggle'].pressed, 'true');
});

test('knowledge upload injects FormData and retains the personal-document POST contract', async () => {
  const nodes = Object.fromEntries([
    '#knowledgeUploadMessage', '#knowledgeUploadDrop', '#knowledgeUploadFile', '#knowledgeUploadFileState', '#knowledgeUploadQueue',
    '#confirmKnowledgeUpload', '#knowledgeUploadStep', '#knowledgeUploadEquipment', '#knowledgeUploadTags', '#knowledgeUploadEffectiveDate',
    '#knowledgeUploadDialog', '#knowledgeFilter', '#knowledgeCount', '#knowledgeDocuments',
  ].map(selector => [selector, element({ reset() {}, close() {}, showModal() {} })]));
  nodes['#knowledgeUploadStep'].value = 'ETCH';
  nodes['#knowledgeUploadTags'].value = 'priority, pilot';
  const forms = [];
  class FakeFormData { constructor() { this.entries = []; forms.push(this); } append(key, value) { this.entries.push([key, value]); } }
  const file = { name: 'a.md', size: 3 };
  const state = { personalUploadQueue: [{ key: 'a', file, status: 'queued' }], personalUploadInProgress: false };
  const queue = {
    hasInvalid: () => false, canUpload: () => true,
    uploadSequential: async (items, upload) => { await upload(items[0].file); return { successes: [], failures: [{ file: items[0].file, error: 'offline' }] }; },
  };
  const calls = [];
  const controller = knowledge.createKnowledgeController({
    state, $: selector => nodes[selector] || element(), escapeHtml: value => String(value), formatFileSize: value => String(value),
    api: async (url, options) => { calls.push([url, options]); return {}; }, newClientMessageId: () => 'message-1', personalUploadQueue: queue,
    personalJobEvents: { isActive: () => false }, windowImpl: { clearTimeout() {}, setTimeout() { return 1; } }, FormDataImpl: FakeFormData,
  });
  await controller.uploadPersonalKnowledge({ preventDefault() {} });
  assert.equal(calls[0][0], '/api/knowledge/personal/documents');
  assert.equal(calls[0][1].method, 'POST');
  assert.equal(calls[0][1].headers['Idempotency-Key'], 'message-1');
  assert.deepEqual(forms[0].entries, [['file', file], ['metadata', JSON.stringify({ process_steps: ['ETCH'], equipment_ids: [], tags: ['priority', 'pilot'] })]]);
});

test('dashboard controller requests the selected date range and stores the rendered dashboard state', async () => {
  const context = { clearRect() {}, scale() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, fillText() {}, setLineDash() {}, arc() {}, fill() {} };
  const nodes = {
    '#startDate': element({ value: '2026-01-01' }), '#endDate': element({ value: '2026-01-31' }), '#errorBanner': element(),
    '#kpiGrid': element(), '#equipmentCount': element(), '#equipmentBody': element(), '#defectBars': element(), '#excursionBody': element(),
    '#yieldChart': element({ getBoundingClientRect: () => ({ width: 200, height: 100 }), getContext: () => context }), '#rangeSummary': element(),
  };
  const state = { dashboard: null, chartPoints: [] };
  const controller = dashboard.createDashboardController({
    state, $: selector => nodes[selector], escapeHtml: value => String(value), formatNumber: value => String(value), processLabels: {},
    api: async url => { assert.equal(url, '/api/reports/dashboard?start=2026-01-01&end=2026-01-31'); return { overview: { yield_pct: 90, good_wafers: 1, lots: 2, wafers: 3, avg_cycle_hours: 4, avg_hold_hours: 5, excursions: 0, held_lots: 0 }, equipment: [], defects: [], excursions: [], yield_trend: [] }; },
    windowImpl: { devicePixelRatio: 1 },
  });
  await controller.loadDashboard();
  assert.equal(state.dashboard.overview.lots, 2);
  assert.equal(nodes['#rangeSummary'].textContent, '2026-01-01 至 2026-01-31 · 2 个批次');
});

test('app mounts business, session, and chat facades without retaining migrated implementations', () => {
  const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
  for (const factory of ['FabKnowledgeController', 'FabModelController', 'FabDashboardController', 'FabSessionController', 'FabChatController']) assert.match(source, new RegExp(`globalThis\\.${factory}\\.create`));
  for (const declaration of ['function loadPersonalKnowledgeDocuments', 'function saveModelSettings', 'function loadDashboard', 'function createConversation', 'function streamAgent']) assert.equal(source.includes(declaration), false);
  assert.match(source, /personalUploadQueue:\s*globalThis\.FabPersonalUploadQueue/);
  const sessionFactory = source.indexOf('FabSessionController.createSessionController');
  const layoutFactory = source.indexOf('FabLayoutController.createLayoutController');
  assert.ok(sessionFactory >= 0 && sessionFactory < layoutFactory);
  assert.match(source, /createLayoutController\(\{\s*state, \$, \.\.\.knowledge, \.\.\.dashboard, \.\.\.sessions,/s);
  const bootstrap = fs.readFileSync(path.join(__dirname, '../app/static/app/bootstrap.js'), 'utf8');
  assert.match(bootstrap, /personalUploadQueue\.remove\(/);
});
