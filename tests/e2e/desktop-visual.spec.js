const { test, expect } = require('./support/fixture');

const VISUAL_IDENTITY = { tenant: 'browser-test', user: 'browser-test-user' };
const VISUAL_SESSION_ID = 'ux015-visual-session';
const VISUAL_DOCUMENT_ID = 'ux015-visual-document';
const VISUAL_ASSISTANT_HEADING = 'CVD-02 膜厚漂移复核建议';

async function openVisualFixture(page) {
  await page.addInitScript(({ tenant, user, sessionId }) => {
    localStorage.setItem('fabInsightTenantId', tenant);
    localStorage.setItem('fabInsightUserId', user);
    localStorage.setItem('fabInsightSessionId', sessionId);
  }, {...VISUAL_IDENTITY, sessionId: VISUAL_SESSION_ID});
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
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

test('E2E-VISUAL-001 desktop long assistant answer keeps Markdown readable without horizontal clipping', async ({ page }) => {
  await openVisualFixture(page);
  const answer = page.locator('#chatMessages .message.assistant .message-content').last();
  await expect(answer).toContainText(VISUAL_ASSISTANT_HEADING);
  await expect(answer).toContainText('工程动作');
  await expect(answer.locator('table')).toBeVisible();
  await expectNoHorizontalOverflow(page, answer);
  await expectPageHasNoHorizontalOverflow(page);
  await expect(answer).toHaveScreenshot('desktop-long-assistant-answer.png');
});

test('E2E-VISUAL-002 desktop personal knowledge renders a long multilingual filename and ready content', async ({ page }) => {
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
});
