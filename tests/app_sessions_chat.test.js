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
    toolLabels: {}, presenter: {}, createConversation: async () => {}, loadSessionLibrary: async () => {}, newClientMessageId: () => 'generated', thinkingEnabled: () => false,
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
