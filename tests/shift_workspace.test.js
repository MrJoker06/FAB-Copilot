const assert = require('node:assert/strict');
const test = require('node:test');
const { safeLink, filterItems } = require('../app/static/app/shift/controller.js');

test('workspace links accept report paths and HTTP(S), reject executable or credential links', () => {
  assert.equal(safeLink('/display_mock_data/reports/spc.html'), '/display_mock_data/reports/spc.html');
  assert.equal(safeLink('https://reports.example.invalid/spc'), 'https://reports.example.invalid/spc');
  for (const value of [null, '', '//outside.invalid', '/\\outside.invalid', 'javascript:alert(1)', 'data:text/html,a', 'file:///etc/passwd', 'https://user:secret@example.invalid', 'https://example.invalid/ a']) {
    assert.equal(safeLink(value), null);
  }
});

test('report and document filters combine query, role and process without changing source records', () => {
  const items = [
    { id: 'one', title: '膜厚偏移', process: 'CVD', roles: ['PE', 'EE'] },
    { id: 'two', title: '压力报警', process: 'ETCH', roles: ['EE'] },
  ];
  assert.deepEqual(filterItems(items, '膜厚', 'PE', 'CVD'), [items[0]]);
  assert.deepEqual(filterItems(items, '报警', 'PE'), []);
  assert.deepEqual(filterItems(items, 'cvd', 'EE'), [items[0]]);
  assert.equal(items.length, 2);
});
