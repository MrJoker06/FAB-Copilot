const test = require('node:test');
const assert = require('node:assert/strict');
const presenter = require('../app/static/source_presenter.js');

const micronSources = [
  {
    reference_id: 'PERSONAL-chunk-001', source_type: 'personal',
    document_id: 'document-001', chunk_id: 'chunk-001',
    title: 'Micron 光刻入门', section: '第 5 页',
  },
  {
    reference_id: 'PERSONAL-chunk-002', source_type: 'personal',
    document_id: 'document-001', chunk_id: 'chunk-002',
    title: 'Micron 光刻入门', section: '第 17 页',
  },
];

test('citations use document names instead of internal reference ids', () => {
  const label = presenter.citationLabel(micronSources[0]);

  assert.equal(label, '[来源：Micron 光刻入门 · 第 5 页]');
  assert.equal(label.includes('PERSONAL-'), false);
});

test('multiple chunks from one document are grouped with locations retained', () => {
  const groups = presenter.groupSources(micronSources);

  assert.equal(groups.length, 1);
  assert.equal(groups[0].name, 'Micron 光刻入门');
  assert.deepEqual(groups[0].items.map(presenter.locationLabel), ['第 5 页', '第 17 页']);
});

test('copied answers replace ids and omit the duplicate source appendix', () => {
  const answer = '光刻用于图形转移。[来源 PERSONAL-chunk-001]\n\n## 来源\n- [来源 PERSONAL-chunk-001]';
  const copy = presenter.replaceReferenceIds(answer, micronSources);

  assert.equal(copy, '光刻用于图形转移。[来源：Micron 光刻入门 · 第 5 页]');
  assert.equal(copy.includes('PERSONAL-'), false);
  assert.equal(copy.includes('## 来源'), false);
});
