const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

test('accessibility scans cover supported WCAG 2.x tags without rule exemptions', () => {
  const source = fs.readFileSync('tests/e2e/desktop-accessibility.spec.js', 'utf8');
  for (const tag of ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']) assert.match(source, new RegExp(`['"]${tag}['"]`));
  assert.doesNotMatch(source, /\.(?:disableRules|exclude)\s*\(/);
});
