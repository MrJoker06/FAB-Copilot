const test = require('node:test');
const assert = require('node:assert/strict');
const {FabIncrementalMarkdown, stableMarkdownBoundary} = require('../app/static/stream_markdown.js');

test('completed markdown blocks are emitted once while only the tail changes', () => {
  const stream = new FabIncrementalMarkdown();
  let patch = stream.update('# 标题\n\n正在生成');
  assert.equal(patch.stableDelta, '# 标题\n\n');
  assert.equal(patch.tail, '正在生成');

  patch = stream.update('# 标题\n\n正在生成更多内容');
  assert.equal(patch.stableDelta, '');
  assert.equal(patch.tail, '正在生成更多内容');

  patch = stream.update('# 标题\n\n正在生成更多内容\n\n下一段');
  assert.equal(patch.stableDelta, '正在生成更多内容\n\n');
  assert.equal(patch.tail, '下一段');
});

test('blank lines inside an open code fence are not committed', () => {
  const text = '说明\n\n```python\nprint(1)\n\nprint(2)';
  assert.equal(stableMarkdownBoundary(text), '说明\n\n'.length);
  const closed = text + '\n```\n\n结论';
  assert.equal(stableMarkdownBoundary(closed), closed.indexOf('结论'));
});

test('a normalized final stream resets previously committed content', () => {
  const stream = new FabIncrementalMarkdown();
  stream.update('临时标题\n\n临时正文');
  const patch = stream.update('最终标题\n\n最终正文');
  assert.equal(patch.reset, true);
  assert.equal(patch.stableDelta, '最终标题\n\n');
  assert.equal(patch.tail, '最终正文');
});

test('long markdown appends every stable character exactly once', () => {
  const stream = new FabIncrementalMarkdown();
  let visible = '';
  let appended = '';
  for (let index = 0; index < 500; index += 1) {
    visible += `## 项目 ${index}\n\n这是第 ${index} 段制造分析。\n\n`;
    const patch = stream.update(visible);
    appended += patch.stableDelta;
    assert.equal(patch.reset, false);
    assert.ok(patch.tail.length < 80);
  }
  assert.equal(appended, visible);
});
