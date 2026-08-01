const test = require('node:test');
const assert = require('node:assert/strict');
const metadata = require('../app/static/personal_knowledge_metadata.js');

const automatic = {title: '原题', process_steps: ['ETCH'], equipment_ids: ['ETCH-01'], effective_date: '2026-01-01', tags: ['自动'], tags_source: 'auto'};
function values(overrides = {}) { return {title:'原题', process_step:'ETCH', equipment_ids:'ETCH-01', effective_date:'2026-01-01', tags:'自动', ...overrides}; }

test('title-only edit does not patch tags or change automatic source', () => {
  const result = metadata.buildPatch(automatic, values({title:' 新题 '}));
  assert.deepEqual(result.patch, {title:'新题'});
  assert.equal('tags' in result.patch, false);
});
test('tags change and explicit clear are patches; stable arrays and empty date normalize', () => {
  assert.deepEqual(metadata.buildPatch(automatic, values({tags:'手动, 手动, 新'})).patch.tags, ['手动', '新']);
  assert.deepEqual(metadata.buildPatch(automatic, values({tags:''})).patch, {tags:[]});
  assert.deepEqual(metadata.buildPatch(automatic, values({process_step:'', equipment_ids:'', effective_date:''})).patch, {process_steps:[], equipment_ids:[], effective_date:null});
});
test('no changes produces no patch and title is required', () => {
  assert.deepEqual(metadata.buildPatch(automatic, values()).patch, {});
  assert.equal(metadata.buildPatch(automatic, values({title:' '})).error, '知识名称不能为空。');
});
