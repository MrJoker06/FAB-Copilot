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
