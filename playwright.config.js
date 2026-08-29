const { defineConfig, devices } = require('@playwright/test');

const port = Number(process.env.PLAYWRIGHT_PORT || 8899);

module.exports = defineConfig({
  testDir: './tests/e2e',
  testIgnore: /live-provider\.spec\.js$/,
  timeout: 30_000,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    locale: 'zh-CN',
    timezoneId: 'Asia/Hong_Kong',
    colorScheme: 'light',
    deviceScaleFactor: 1,
    reducedMotion: 'reduce',
  },
  expect: {
    toHaveScreenshot: {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      maxDiffPixelRatio: 0.0005,
    },
  },
  projects: [{
    name: 'chromium-desktop',
    use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
  }],
  webServer: {
    command: `python scripts/run_browser_test_server.py --port ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 300_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
