const test = require('node:test');
const assert = require('node:assert/strict');
const thinking = require('../app/static/thinking_control.js');

test('normalizes Thinking capability and effort options', () => {
  const enabled = thinking.normalizeCapabilities({thinking: true, thinking_effort: 'medium', thinking_effort_options: ['low', 'medium', 'xhigh']});
  assert.equal(enabled.thinking, true);
  assert.equal(enabled.effort, 'medium');
  assert.deepEqual(enabled.options, ['low', 'medium', 'xhigh']);
  assert.equal(thinking.normalizeCapabilities({thinking: 1}).thinking, false);
  assert.equal(thinking.normalizeCapabilities().effort, 'off');
});

test('reconcile keeps a supported effort and falls back for unsupported models', () => {
  assert.deepEqual(thinking.reconcile({capabilities: {thinking: true, thinking_effort_options: ['low', 'medium']}}, 'medium'), {supported: true, enabled: true, effort: 'medium', options: ['off', 'low', 'medium']});
  assert.deepEqual(thinking.reconcile({capabilities: {thinking: false}}, 'medium'), {supported: false, enabled: false, effort: 'off', options: ['off']});
});

test('model changes clear an effort that is no longer available', () => {
  const selected = thinking.reconcile({capabilities: {thinking: true, thinking_effort_options: ['low']}}, 'xhigh');
  assert.equal(selected.effort, 'low');
  assert.equal(selected.enabled, true);
});

test('top-level thinking settings override stale capability defaults', () => {
  const model = {
    capabilities: {thinking: true},
    thinking: {thinking: true, effort: 'xhigh', options: ['low', 'xhigh'], dialect: 'qwen'},
  };
  assert.deepEqual(thinking.reconcile(model, 'xhigh'), {
    supported: true, enabled: true, effort: 'xhigh', options: ['off', 'low', 'xhigh'],
  });
  assert.equal(thinking.defaultEffort(model), 'xhigh');
});

test('request payload always sends an explicit effort, including off', () => {
  const base = {message: '分析 CVD-02', session_id: 'session-1', thinking: false};
  assert.deepEqual(thinking.requestPayload(base, {capabilities: {thinking: true, thinking_effort_options: ['low', 'medium']}}, 'medium'), {
    message: '分析 CVD-02', session_id: 'session-1', thinking: true, thinking_effort: 'medium',
  });
  assert.deepEqual(thinking.requestPayload(base, {capabilities: {thinking: true}}, 'off'), {
    message: '分析 CVD-02', session_id: 'session-1', thinking: false, thinking_effort: 'off',
  });
  assert.deepEqual(thinking.requestPayload(base, {capabilities: {thinking: false}}, 'high'), {
    message: '分析 CVD-02', session_id: 'session-1', thinking: false, thinking_effort: 'off',
  });
});
