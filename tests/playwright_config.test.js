const assert = require('node:assert/strict');
const test = require('node:test');
const config = require('../playwright.config.js');

test('Playwright remains a single isolated desktop Chromium contract', () => {
  assert.equal(config.webServer.timeout, 300_000);
  assert.equal(config.webServer.reuseExistingServer, false);
  assert.equal(config.projects.length, 1);
  assert.deepEqual(config.projects[0].use.viewport, { width: 1440, height: 900 });
  assert.equal(config.use.locale, 'zh-CN');
  assert.equal(config.use.timezoneId, 'Asia/Hong_Kong');
  assert.equal(config.use.colorScheme, 'light');
  assert.equal(config.use.deviceScaleFactor, 1);
  assert.equal(config.use.reducedMotion, 'reduce');
  assert.equal(config.expect.toHaveScreenshot.animations, 'disabled');
  assert.equal(config.expect.toHaveScreenshot.caret, 'hide');
  assert.equal(config.expect.toHaveScreenshot.scale, 'css');
  assert.ok(config.expect.toHaveScreenshot.maxDiffPixelRatio <= 0.001);
  assert.doesNotMatch(config.projects[0].name, /mobile/i);
  assert.equal(config.projects.some(project => /mobile/i.test(project.name)), false);
});
