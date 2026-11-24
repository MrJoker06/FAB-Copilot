const test = require('node:test');
const assert = require('node:assert/strict');

const sessions = require('../app/static/app/sessions/controller.js');
const chat = require('../app/static/app/chat/controller.js');

test('session controller restores the saved session and preserves its local-storage key', async () => {
  const storage = new Map([['fabInsightSessionId', 'saved-session']]);
  const nodes = { '#chatMessages': { innerHTML: '' }, '#agentMode': { textContent: '' } };
  const state = { history: [] };
  const controller = sessions.createSessionController({
    state, $: selector => nodes[selector], escapeHtml: value => String(value), showToast: () => {}, sourcePresenter: {},
    presenter: { welcomeMarkup: () => 'welcome', addMessage: () => {}, sourceReferenceMap: () => new Map(), renderMarkdown: () => '', renderSourcePanel: () => '' },
    localStorageImpl: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    api: async url => { assert.equal(url, '/api/sessions/saved-session'); return { session_id: 'saved-session', messages: [{ role: 'user', content: 'hello' }] }; },
  });
  await controller.restoreConversation();
  assert.equal(state.sessionId, 'saved-session');
  assert.deepEqual(state.history, [{ role: 'user', content: 'hello' }]);
  assert.equal(nodes['#agentMode'].textContent, '已恢复 · 1 条消息');
});

test('chat stream keeps the supplied client message id, thinking payload, and streamed session id', async () => {
  const encoder = new TextEncoder();
  const chunks = [encoder.encode('{"type":"session","session_id":"stream-session"}\n{"type":"progress","event":"stage"}\n'), encoder.encode('{"type":"result","result":{"answer":"done"}}\n')];
  let request;
  const state = { sessionId: 'before-stream', modelConfig: { model: 'test' } };
  const controller = chat.createChatController({
    state, $: () => ({}), escapeHtml: value => String(value), identityHeaders: headers => headers, FabApiError: Error,
    apiError: payload => new Error(payload.detail), thinkingControl: { requestPayload: (payload, config, thinking) => ({ ...payload, model: config.model, thinking }) },
    toolLabels: {}, presenter: {}, createConversation: async () => {}, loadSessionLibrary: async () => {}, newClientMessageId: () => 'generated', thinkingEffort: () => 'off',
    localStorageImpl: { setItem: () => {} },
    fetchImpl: async (url, options) => { request = { url, options }; let index = 0; return { ok: true, headers: { get: () => 'request-1' }, body: { getReader: () => ({ read: async () => index < chunks.length ? { value: chunks[index++], done: false } : { value: undefined, done: true } }) } }; },
    TextDecoderImpl: TextDecoder,
  });
  const progress = [];
  const result = await controller.streamAgent('question', 'retry-id', event => progress.push(event), { markRead: () => {}, markProgress: event => progress.push(event) }, true);
  assert.equal(request.url, '/api/chat/stream');
  assert.equal(JSON.parse(request.options.body).client_message_id, 'retry-id');
  assert.equal(JSON.parse(request.options.body).thinking, true);
  assert.equal(state.sessionId, 'stream-session');
  assert.deepEqual(result, { answer: 'done' });
  assert.equal(progress.length, 2);
});

test('tool failures show the safe Chinese explanation and escaped error code in restored traces', () => {
  const {createChatPresenter} = require('../app/static/app/chat/presenter.js');
  const escapeHtml = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
  const presenter = createChatPresenter({escapeHtml,toolLabels:{},sourcePresenter:{}});
  const html = presenter.renderToolTrace([{tool:'native',status:'error',error:'technical message',
    error_code:'DATA_SOURCE_FAILED',user_message:'数据来源失败。'}],'run-test');
  assert.match(html,/DATA_SOURCE_FAILED/);
  assert.match(html,/数据来源失败/);
  assert.doesNotMatch(html,/technical message/);
  assert.doesNotMatch(presenter.renderToolFailure({error:'<img src=x>',error_code:'<script>'}), /<img|<script>/);
});

test('chat stream sends an attached analysis reference but never together with a tool result reference', async () => {
  const bodies = [];
  const encoder = new TextEncoder();
  const controller = chat.createChatController({
    state: { sessionId: 's1', modelConfig: {} }, $: () => ({}), escapeHtml: value => String(value), identityHeaders: headers => headers,
    FabApiError: Error, apiError: payload => new Error(payload.detail), thinkingControl: { requestPayload: payload => ({ ...payload }) },
    toolLabels: {}, presenter: {}, newClientMessageId: () => 'id', thinkingEffort: () => 'off', localStorageImpl: { setItem: () => {} },
    fetchImpl: async (url, options) => {
      bodies.push(JSON.parse(options.body));
      let sent = false;
      return { ok: true, headers: { get: () => '' }, body: { getReader: () => ({ read: async () => (sent ? { done: true } : (sent = true, { value: encoder.encode('{"type":"result","result":{"answer":"ok"}}\n'), done: false })) }) } };
    },
    TextDecoderImpl: TextDecoder,
  });
  const diagnostics = { markRead: () => {}, markProgress: () => {} };
  const ref = `lca_${'a'.repeat(32)}`;
  await controller.streamAgent('q', 'c1', () => {}, diagnostics, 'off', null, null, ref);
  await controller.streamAgent('q', 'c2', () => {}, diagnostics, 'off', 'tr_x', null, ref);
  assert.equal(bodies[0].analysis_ref, ref);
  assert.equal(bodies[0].tool_result_ref, undefined);
  assert.equal(bodies[1].tool_result_ref, 'tr_x');
  assert.equal(bodies[1].analysis_ref, undefined);
});

test('attaching an analysis writes the draft and a removable reference tag', () => {
  const events = [];
  const remove = { listeners: [], addEventListener(type, handler) { this.listeners.push(handler); } };
  const tag = { hidden: true, innerHTML: '', querySelector: () => remove };
  const input = { value: 'old', maxLength: 20, dispatchEvent: event => events.push(event.type), focus: () => events.push('focus') };
  const nodes = { '#chatAttachment': tag, '#chatInput': input };
  const escapeHtml = value => String(value).replaceAll('<', '&lt;');
  const controller = chat.createChatController({ state: {}, $: selector => nodes[selector], escapeHtml, presenter: {} });
  controller.attachAnalysis({ analysisRef: `lca_${'b'.repeat(32)}`, label: '<主组> 3 个 lot', message: '请解读附带的 Lot 共性分析结果，并给出建议与待确认信息' });
  assert.equal(tag.hidden, false);
  assert.match(tag.innerHTML, /附带共性分析/);
  assert.match(tag.innerHTML, /&lt;主组>/);
  assert.equal(input.value.length, 20);
  assert.deepEqual(events, ['input', 'focus']);
  remove.listeners[0]();
  assert.equal(tag.hidden, true);
  assert.equal(tag.innerHTML, '');
});

test('assistant messages offer to reopen every analysis the turn used, escaped', () => {
  const {createChatPresenter} = require('../app/static/app/chat/presenter.js');
  const escapeHtml = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const presenter = createChatPresenter({escapeHtml,toolLabels:{},sourcePresenter:{}});
  assert.equal(presenter.renderAnalysisRefs(undefined), '');
  assert.equal(presenter.renderAnalysisRefs([{origin:'created'}]), '');
  const html = presenter.renderAnalysisRefs([{analysis_ref:'lca_1',origin:'attached'},{analysis_ref:'"><img>',origin:'read'}]);
  assert.match(html, /本轮附带的共性分析/);
  assert.match(html, /本轮读取的共性分析/);
  assert.equal((html.match(/data-open-analysis=/g) || []).length, 2);
  assert.doesNotMatch(html, /<img>/);
});
