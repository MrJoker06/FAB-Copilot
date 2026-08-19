const { test, expect } = require('@playwright/test');

const VISUAL_IDENTITY = { tenant: 'browser-test', user: 'browser-test-user' };
const VISUAL_SESSION_ID = 'ux015-visual-session';
const VISUAL_DOCUMENT_ID = 'ux015-visual-document';
const VISUAL_ASSISTANT_HEADING = 'CVD-02 膜厚漂移复核建议';

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

async function openVisualFixture(page) {
  await page.addInitScript(({ tenant, user, sessionId }) => {
    localStorage.setItem('fabInsightTenantId', tenant);
    localStorage.setItem('fabInsightUserId', user);
    localStorage.setItem('fabInsightSessionId', sessionId);
  }, {...VISUAL_IDENTITY, sessionId: VISUAL_SESSION_ID});
  await page.goto('/');
  await expect(page.locator('#systemStatus')).not.toHaveText(/正在连接数据源/);
  await expect(page.locator('#chatMessages .message.assistant .message-content').last())
    .toContainText(VISUAL_ASSISTANT_HEADING);
}

async function expectNoHorizontalOverflow(page, locator) {
  await expect(locator).toBeVisible();
  const overflow = await locator.evaluate(element => element.scrollWidth - element.clientWidth);
  expect(overflow, 'visual fixture must not introduce horizontal content overflow').toBeLessThanOrEqual(1);
}

async function expectPageHasNoHorizontalOverflow(page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test('desktop long assistant answer keeps Markdown readable without horizontal clipping', async ({ page }) => {
  const assertNoFailures = captureBrowserFailures(page);
  await openVisualFixture(page);
  const answer = page.locator('#chatMessages .message.assistant .message-content').last();
  await expect(answer).toContainText(VISUAL_ASSISTANT_HEADING);
  await expect(answer).toContainText('工程动作');
  await expect(answer.locator('table')).toBeVisible();
  await expectNoHorizontalOverflow(page, answer);
  await expectPageHasNoHorizontalOverflow(page);
  await expect(answer).toHaveScreenshot('desktop-long-assistant-answer.png');
  assertNoFailures();
});

test('desktop personal knowledge renders a long multilingual filename and ready content', async ({ page }) => {
  const assertNoFailures = captureBrowserFailures(page);
  await openVisualFixture(page);
  await page.locator('[data-view="knowledge"]').click();
  await page.locator('[data-knowledge-mode="personal"]').click();
  const document = page.locator(`[data-personal-document-id="${VISUAL_DOCUMENT_ID}"]`);
  await expect(document).toBeVisible();
  await expect(document).toContainText('2026-Q3-CMP-Polishing-超长文件名');
  await expect(document).toContainText('可检索');
  await document.click();
  const layout = page.locator('.knowledge-layout');
  await expect(layout).toContainText('CMP 抛光异常处置 / CMP polishing response');
  await expect(layout).toContainText('wafer surface defect');
  await expect(page.locator('#knowledgeMeta')).toContainText('2026-Q3-CMP-Polishing-超长文件名-多语言术语');
  await expectNoHorizontalOverflow(page, layout);
  await expectPageHasNoHorizontalOverflow(page);
  await expect(layout).toHaveScreenshot('desktop-personal-knowledge-long-filename.png');
  assertNoFailures();
});
