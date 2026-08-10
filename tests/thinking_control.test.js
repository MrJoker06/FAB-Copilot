const test = require('node:test');
const assert = require('node:assert/strict');
const thinking = require('../app/static/thinking_control.js');

test('normalizes Thinking capability to a strict boolean', () => {
  assert.deepEqual(thinking.normalizeCapabilities({thinking: true, injected: true}), {thinking: true});
  assert.deepEqual(thinking.normalizeCapabilities({thinking: 1}), {thinking: false});
  assert.deepEqual(thinking.normalizeCapabilities(), {thinking: false});
});

test('reconcile preserves an enabled control only for a supported selected model', () => {
  assert.deepEqual(thinking.reconcile({capabilities: {thinking: true}}, true), {supported: true, enabled: true});
  assert.deepEqual(thinking.reconcile({capabilities: {thinking: false}}, true), {supported: false, enabled: false});
});

test('model changes clear invalid Thinking state', () => {
  const enabledOnFirstModel = thinking.reconcile({capabilities: {thinking: true}}, true).enabled;
  assert.deepEqual(thinking.reconcile({capabilities: {thinking: false}}, enabledOnFirstModel), {supported: false, enabled: false});
});

test('request payload sends Thinking only when the current model supports an enabled control', () => {
  const base = {message: '分析 CVD-02', session_id: 'session-1', thinking: false};
  assert.deepEqual(thinking.requestPayload(base, {capabilities: {thinking: true}}, true), {...base, thinking: true});
  assert.deepEqual(thinking.requestPayload(base, {capabilities: {thinking: false}}, true), {message: '分析 CVD-02', session_id: 'session-1'});
  assert.deepEqual(thinking.requestPayload(base, {capabilities: {thinking: true}}, false), {message: '分析 CVD-02', session_id: 'session-1'});
});
