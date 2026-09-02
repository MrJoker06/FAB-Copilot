const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const stateCore = require('../app/static/app/core/state.js');
const dom = require('../app/static/app/core/dom.js');
const apiCore = require('../app/static/app/core/api.js');
const toastCore = require('../app/static/app/core/toast.js');
const versionCore = require('../app/static/app/core/version.js');

const storage = (values = {}) => ({ getItem: (key) => values[key] || null });

test('state factories isolate mutable containers and preserve key fields', () => {
  const first = stateCore.createState();
  const second = stateCore.createState();
  assert.notEqual(first, second);
  assert.notEqual(first.history, second.history);
  assert.notEqual(first.selectedSessionIds, second.selectedSessionIds);
  assert.notEqual(first.capabilityCache, second.capabilityCache);
  assert.deepEqual(Object.keys(first).sort(), [
    'activeStep', 'activeView', 'capabilityCache', 'capabilityController', 'capabilityRequestId', 'cases', 'casesPromise', 'chartPoints',
    'dashboard', 'enterpriseContext', 'history', 'knowledgeDocuments', 'knowledgeIndexPromise', 'knowledgeMode', 'modelConfig',
    'pendingDeleteSessionIds', 'pendingPersonalDeleteId', 'pendingPersonalMetadataId', 'pendingRenameSessionId', 'personalJobEventsController',
    'personalJobEventsFallback', 'personalJobEventsLastId', 'personalJobEventsPolicy', 'personalJobEventsProbeTimer', 'personalJobEventsRefreshTimer',
    'personalJobEventsRetryTimer', 'personalJobEventsStableTimer', 'personalKnowledgeDocuments', 'personalKnowledgePollTimer',
    'personalKnowledgeRequestId', 'personalUploadInProgress', 'personalUploadQueue', 'previousView', 'selectedLibrarySessionId',
    'selectedPersonalDocument', 'selectedPersonalDocumentId', 'selectedSessionIds', 'sessionBatchMode', 'sessionId', 'sessionLibrary',
    'sessionLibraryFilter', 'sessionLibraryPreviewRequestId', 'sessionLibraryRequestId', 'streaming', 'toastTimer',
  ].sort());
  assert.equal(first.knowledgeMode, 'factory');
  assert.equal(first.selectedSessionIds.size, 0);
});

test('DOM helpers escape and format values', () => {
  assert.equal(dom.escapeHtml(`<x>'&"`), '&lt;x&gt;&#39;&amp;&quot;');
  assert.equal(dom.formatNumber(12345), '12,345');
  assert.equal(dom.formatFileSize(1536), '1.5 KB');
  assert.equal(dom.isoDate(new Date('2026-09-01T12:00:00Z')), '2026-09-01');
});

test('identity headers retain initial values and use nonempty identity storage values', () => {
  const headers = apiCore.identityHeaders({ Accept: 'application/json', 'X-Tenant-ID': 'initial' }, {
    HeadersImpl: Headers,
    storage: storage({ fabInsightTenantId: 'tenant', fabInsightUserId: 'user' }),
  });
  assert.equal(headers.get('accept'), 'application/json');
  assert.equal(headers.get('x-tenant-id'), 'tenant');
  assert.equal(headers.get('x-user-id'), 'user');
});

test('api preserves success, HTTP error and network error contracts', async () => {
  const headersOptions = { HeadersImpl: Headers, storage: storage() };
  assert.deepEqual(await apiCore.api('/ok', {}, { headersOptions, fetchImpl: async () => ({ ok: true, json: async () => ({ ok: true }) }) }), { ok: true });
  await assert.rejects(
    apiCore.api('/bad', {}, { headersOptions, fetchImpl: async () => ({ ok: false, status: 429, headers: new Headers({ 'x-request-id': 'req-1' }), json: async () => ({ detail: '慢一点', error_code: 'RATE', retryable: true }) }) }),
    error => error instanceof apiCore.FabApiError && error.code === 'RATE' && error.requestId === 'req-1' && error.retryable && error.status === 429,
  );
  await assert.rejects(
    apiCore.api('/offline', {}, { headersOptions, fetchImpl: async () => { throw new Error('offline'); } }),
    error => error.code === 'NETWORK_ERROR' && error.retryable && error.status === 0,
  );
});

test('toast dismisses timers and action failures produce an error toast', async () => {
  const state = { toastTimer: 7 };
  const region = { innerHTML: 'old', appendChild(node) { this.node = node; } };
  const handlers = {};
  const action = { addEventListener: (_type, listener) => { handlers.action = listener; } };
  const close = { addEventListener: (_type, listener) => { handlers.close = listener; } };
  const documentImpl = { createElement: () => ({ className: '', innerHTML: '', querySelector: selector => selector === '.toast-action' ? action : close }) };
  const timers = [];
  const windowImpl = { clearTimeout: timer => timers.push(['clear', timer]), setTimeout: (callback, duration) => { timers.push(['set', duration, callback]); return 9; } };
  const toast = toastCore.createToast(state, { $: selector => { assert.equal(selector, '#toastRegion'); return region; }, escapeHtml: dom.escapeHtml, documentImpl, windowImpl });
  try {
    toast.showToast('<first>', { actionLabel: 'retry', duration: 33, onAction: async () => { throw new Error('bad'); } });
    assert.equal(region.node.className, 'toast');
    assert.match(region.node.innerHTML, /&lt;first&gt;/);
    assert.deepEqual(timers[0], ['clear', 7]);
    assert.equal(timers[1][1], 33);
    await handlers.action();
    assert.equal(region.node.className, 'toast error');
    assert.equal(timers.at(-1)[1], 5200);
    handlers.close();
    assert.equal(region.innerHTML, '');
    assert.equal(state.toastTimer, null);
    toast.dismissToast();
    assert.equal(region.innerHTML, '');
    assert.equal(state.toastTimer, null);
  } finally { /* injected fakes do not change global document */ }
});

test('version checking handles same, dismissed, new and silent failure paths', async () => {
  const banner = { dataset: {}, hidden: true };
  const documentImpl = { querySelector: selector => selector.includes('meta') ? { content: '1.0.0' } : banner };
  const $ = selector => { assert.equal(selector, '#versionBanner'); return banner; };
  const stable = versionCore.createVersion({ api: async () => ({ version: '1.0.0' }), $, documentImpl, storage: storage() });
  stable.handleBuildVersion({ version: '1.0.0' });
  assert.equal(banner.hidden, true);
  const dismissed = versionCore.createVersion({ api: async () => ({ version: '2.0.0' }), $, documentImpl, storage: storage({ fabInsightDismissedVersion: '2.0.0' }) });
  await dismissed.checkAppVersion();
  assert.equal(banner.hidden, true);
  const fresh = versionCore.createVersion({ api: async () => ({ version: '3.0.0' }), $, documentImpl, storage: storage() });
  await fresh.checkAppVersion();
  assert.equal(banner.dataset.version, '3.0.0');
  assert.equal(banner.hidden, false);
  const silent = versionCore.createVersion({ api: async () => { throw new Error('offline'); }, $, documentImpl, storage: storage() });
  await silent.checkAppVersion();
});

test('index loads core scripts in dependency order and keeps app last', () => {
  const html = fs.readFileSync(path.join(__dirname, '../app/static/index.html'), 'utf8');
  const sources = [...html.matchAll(/<script src="([^"]+)" defer><\/script>/g)].map(match => match[1]);
  assert.deepEqual(sources, [
    ...['state', 'dom', 'api', 'toast', 'version'].map(name => `/static/app/core/${name}.js?v=__APP_VERSION__`),
    '/static/stream_diagnostics.js?v=__APP_VERSION__', '/static/stream_buffer.js?v=__APP_VERSION__',
    '/static/stream_markdown.js?v=__APP_VERSION__', '/static/source_presenter.js?v=__APP_VERSION__',
    '/static/personal_upload_queue.js?v=__APP_VERSION__', '/static/personal_knowledge_metadata.js?v=__APP_VERSION__',
    '/static/personal_job_events.js?v=__APP_VERSION__', '/static/thinking_control.js?v=__APP_VERSION__',
    '/static/app/knowledge/controller.js?v=__APP_VERSION__', '/static/app/model/controller.js?v=__APP_VERSION__',
    '/static/app/dashboard/controller.js?v=__APP_VERSION__',
    '/static/app.js?v=__APP_VERSION__',
  ]);
});

test('business controller factories expose isolated public facades', () => {
  const knowledge = require('../app/static/app/knowledge/controller.js');
  const model = require('../app/static/app/model/controller.js');
  const dashboard = require('../app/static/app/dashboard/controller.js');
  assert.notEqual(knowledge.createKnowledgeController({}), knowledge.createKnowledgeController({}));
  assert.equal(typeof model.createModelController, 'function');
  assert.equal(typeof dashboard.createDashboardController, 'function');
});

test('app uses all five core facades without retaining extracted implementations', () => {
  const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
  for (const name of ['FabAppState', 'FabAppDom', 'FabAppApi', 'FabAppToast', 'FabAppVersion']) assert.match(source, new RegExp(`globalThis\\.${name}`));
  for (const duplicate of ['const state = {', 'class FabApiError', 'function showToast', 'function checkAppVersion']) assert.equal(source.includes(duplicate), false);
});
