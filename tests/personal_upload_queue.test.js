const test = require('node:test');
const assert = require('node:assert/strict');
const queue = require('../app/static/personal_upload_queue.js');

function file(name, size = 10, lastModified = 1, type = 'text/plain') { return {name, size, lastModified, type}; }

test('merge accumulates across selections, deduplicates and removes', () => {
  let result = queue.merge([], [file('a.txt'), file('b.md')]);
  result = queue.merge(result.items, [file('b.md'), file('c.csv')]);
  assert.equal(result.items.length, 3);
  assert.deepEqual(queue.remove(result.items, result.items[1].key).map(item => item.file.name), ['a.txt', 'c.csv']);
});

test('validates extension and size per file', () => {
  const result = queue.merge([], [file('bad.exe'), file('large.pdf', queue.MAX_BYTES + 1)]);
  assert.deepEqual(result.items.map(item => item.status), ['invalid', 'invalid']);
  assert.match(result.items[0].error, /不支持/);
  assert.match(result.items[1].error, /50 MB/);
  assert.equal(queue.hasInvalid(result.items), true);
  assert.equal(queue.canUpload(result.items), false);
  assert.equal(queue.canUpload(queue.merge([], [file('ok.txt')]).items), true);
});

test('uploads in order, continues after failure, and retries only failures', async () => {
  const items = queue.merge([], [file('a.txt'), file('b.txt'), file('c.txt')]).items;
  const calls = [];
  const first = await queue.uploadSequential(items, async current => {
    calls.push(current.name); if (current.name === 'b.txt') throw new Error('network'); return {document_id: current.name};
  });
  assert.deepEqual(calls, ['a.txt', 'b.txt', 'c.txt']);
  assert.equal(first.successes.length, 2); assert.equal(first.failures.length, 1);
  const retry = queue.retryable(items);
  assert.deepEqual(retry.map(item => item.file.name), ['b.txt']);
  const second = await queue.uploadSequential(retry, async current => ({document_id: current.name}));
  assert.equal(second.successes.length, 1); assert.equal(second.failures.length, 0);
});
