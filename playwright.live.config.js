const { defineConfig, devices } = require('@playwright/test');

const port = Number(process.env.PLAYWRIGHT_LIVE_PORT || 8900);
module.exports = defineConfig({
  testDir: './tests/e2e', testMatch: /live-(?:provider|admin-governance)\.spec\.js$/, timeout: Number(process.env.FAB_LIVE_E2E_TIMEOUT_MS || 900_000),
  retries: 0, workers: 1, forbidOnly: true,
  use: { baseURL: `http://127.0.0.1:${port}`, locale: 'zh-CN', timezoneId: 'Asia/Hong_Kong', actionTimeout: 30_000, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium-live-provider', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
});
