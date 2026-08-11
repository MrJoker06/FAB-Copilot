const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const html = fs.readFileSync('app/static/admin.html', 'utf8');
const script = fs.readFileSync('app/static/admin.js', 'utf8');

test('admin catalog exposes separate declaration and explicit compatibility actions', () => {
  assert.match(html, /editCapabilitiesDialog/);
  assert.match(script, /data-action="capabilities"/);
  assert.match(script, /data-action="compatibility"/);
  assert.match(script, /\/compatibility-check/);
  assert.match(script, /\/capabilities/);
  assert.doesNotMatch(script, /正在执行兼容性检查/);
});
