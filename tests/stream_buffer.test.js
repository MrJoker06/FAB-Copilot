const test = require('node:test');
const assert = require('node:assert/strict');
const {FabSmoothTextBuffer} = require('../app/static/stream_buffer.js');

test('a batched answer is revealed over multiple frames', () => {
  const buffer = new FabSmoothTextBuffer();
  const answer = 'GaN 相比 Si 的优势。'.repeat(100);
  buffer.append(answer);
  buffer.finish(answer);

  const firstFrame = buffer.takeNext();
  assert.ok(firstFrame.length > 0);
  assert.ok(firstFrame.length < answer.length);
  assert.equal(buffer.done, false);

  let frames = 1;
  while (!buffer.done) {
    buffer.takeNext();
    frames += 1;
  }
  assert.ok(frames >= 3);
  assert.ok(frames <= 10);
  assert.equal(buffer.visible, answer);
});

test('a long burst drains in bounded frames without losing unicode text', () => {
  const buffer = new FabSmoothTextBuffer();
  const answer = '# 光刻分析\n\n- 套刻精度\n- CD 均匀性\n'.repeat(500);
  buffer.append(answer);
  buffer.finish(answer);

  let frames = 0;
  while (!buffer.done && frames < 100) {
    buffer.takeNext({targetFrames: 3, maxChars: 2000});
    frames += 1;
  }
  assert.ok(frames < 20);
  assert.equal(buffer.visible, answer);
});

test('the final result only appends content missing from streamed deltas', () => {
  const buffer = new FabSmoothTextBuffer();
  buffer.append('第一段');
  buffer.takeNext();
  buffer.finish('第一段和第二段');

  while (!buffer.done) buffer.takeNext();
  assert.equal(buffer.received, '第一段和第二段');
  assert.equal(buffer.visible, '第一段和第二段');
});

test('a normalized final answer replaces an incompatible pending stream', () => {
  const buffer = new FabSmoothTextBuffer();
  buffer.append('临时内容');
  buffer.finish('最终内容');

  while (!buffer.done) buffer.takeNext();
  assert.equal(buffer.visible, '最终内容');
});
