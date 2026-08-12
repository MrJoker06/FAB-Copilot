const assert = require('node:assert/strict');
const test = require('node:test');
const config = require('../playwright.config.js');

test('Playwright remains a single isolated desktop Chromium contract', () => {
  assert.equal(config.webServer.timeout, 300_000);
  assert.equal(config.webServer.reuseExistingServer, false);
  assert.equal(config.projects.length, 1);
  assert.deepEqual(config.projects[0].use.viewport, { width: 1440, height: 900 });
  assert.doesNotMatch(config.projects[0].name, /mobile/i);
  assert.equal(config.projects.some(project => /mobile/i.test(project.name)), false);
});
