const { test, expect } = require('@playwright/test');

const ADMIN_TOKEN = 'browser-test-admin-token';

function captureBrowserFailures(page) {
  const failures = [];
  page.on('pageerror', error => failures.push(`pageerror: ${error.message}`));
  page.on('console', message => {
    if (message.type() === 'error') failures.push(`console: ${message.text()}`);
  });
  page.on('requestfailed', request => {
    const url = new URL(request.url());
    if (url.origin === new URL(page.url() || 'http://127.0.0.1').origin) {
      failures.push(`request: ${request.method()} ${url.pathname} ${request.failure()?.errorText || 'failed'}`);
    }
  });
  return () => expect(failures, failures.join('\n')).toEqual([]);
}

async function expectDesktopLayout(page, selectors) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const boxes = [];
  for (const selector of selectors) {
    const box = await page.locator(selector).boundingBox();
    expect(box, `${selector} should be visible`).not.toBeNull();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(1441);
    boxes.push({ selector, ...box });
  }
  boxes.sort((left, right) => left.x - right.x);
  for (let index = 1; index < boxes.length; index += 1) {
    const left = boxes[index - 1];
    const right = boxes[index];
    expect(left.x + left.width, `${left.selector} overlaps ${right.selector}`).toBeLessThanOrEqual(right.x + 1);
  }
}

test('desktop user dashboard loads without overflow or critical overlap', async ({ page }) => {
  const assertNoFailures = captureBrowserFailures(page);
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  await expect(page.locator('.topbar')).toBeVisible();
  await expect(page.locator('.sidebar[aria-label="主导航"]')).toBeVisible();
  await expect(page.locator('.main-content')).toBeVisible();
  await expect(page.locator('.agent-panel[aria-label="Fab Copilot"]')).toBeVisible();
  await expect(page.locator('#kpiGrid')).not.toBeEmpty();
  await expect(page.locator('#systemStatus')).not.toHaveText(/正在连接数据源/);
  await expectDesktopLayout(page, ['.sidebar', '.main-content', '.agent-panel']);
  assertNoFailures();
});

test('desktop admin is locked until a test token opens the real workspace', async ({ page }) => {
  const assertNoFailures = captureBrowserFailures(page);
  await page.goto('/admin');
  await expect(page.locator('#adminAuthDialog')).toBeVisible();
  await expect(page.locator('#adminWorkspace')).toBeHidden();
  await page.addInitScript(token => sessionStorage.setItem('fabInsightAdminToken', token), ADMIN_TOKEN);
  await page.reload();
  await expect(page.locator('#adminWorkspace')).toBeVisible();
  await expect(page.locator('.admin-topbar')).toBeVisible();
  await expect(page.locator('.admin-sidebar[aria-label="管理导航"]')).toBeVisible();
  await expect(page.locator('.admin-main')).toBeVisible();
  await expect(page.locator('#runtimeKpis')).not.toBeEmpty();
  await expectDesktopLayout(page, ['.admin-sidebar', '.admin-main']);
  assertNoFailures();
});
