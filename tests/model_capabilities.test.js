const test = require('node:test');
const assert = require('node:assert/strict');
const capabilities = require('../app/static/model_capabilities.js');

test('publish payload always contains exactly four strict boolean capabilities', () => {
  assert.deepEqual(capabilities.publishPayload({streaming: true, thinking: 1, unexpected: true}), {
    streaming: true, tool_calls: false, thinking: false, native_multimodal: false,
  });
});

test('labels use fixed friendly order and do not expose extensions', () => {
  assert.deepEqual(capabilities.labels({thinking: true, streaming: true, injected: true, native_multimodal: true}), [
    '流式输出', 'Thinking', '原生多模态',
  ]);
});

test('enabled entries provide stable keys and labels while labels remain compatible', () => {
  const values = {streaming: true, tool_calls: true, thinking: true, native_multimodal: true};
  assert.deepEqual(capabilities.enabledEntries(values), [
    {key: 'streaming', label: '流式输出'},
    {key: 'tool_calls', label: '工具调用'},
    {key: 'thinking', label: 'Thinking'},
    {key: 'native_multimodal', label: '原生多模态'},
  ]);
  assert.deepEqual(capabilities.labels(values), capabilities.enabledEntries(values).map(entry => entry.label));
});
