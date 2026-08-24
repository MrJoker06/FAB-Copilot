const { test, expect } = require('@playwright/test');

function captureBrowserFailures(page) {
  const failures = [];
  page.on('pageerror', error => failures.push(`pageerror: ${error.message}`));
  page.on('console', message => {
    if (message.type() === 'error') failures.push(`console: ${message.text()}`);
  });
  page.on('requestfailed', request => {
    const error = request.failure()?.errorText || 'failed';
    const url = new URL(request.url());
    const expectedPersonalJobEventAbort = request.method() === 'GET'
      && url.pathname === '/api/knowledge/personal/jobs/events'
      && /ERR_ABORTED/i.test(error);
    if (!expectedPersonalJobEventAbort && url.origin === new URL(page.url() || 'http://127.0.0.1').origin) {
      failures.push(`request: ${request.method()} ${url.pathname} ${error}`);
    }
  });
  return () => expect(failures, failures.join('\n')).toEqual([]);
}

async function openIsolatedUser(page, testInfo) {
  const titleFingerprint = [...testInfo.title].reduce((hash, character) => ((hash * 31) + character.charCodeAt(0)) >>> 0, 7).toString(36);
  const suffix = `${testInfo.workerIndex}-${titleFingerprint}`;
  const identities = {tenant: `ux013-${suffix}`, user: `user-${suffix}`};
  await page.addInitScript(({ tenant, user }) => {
    localStorage.setItem('fabInsightTenantId', tenant);
    localStorage.setItem('fabInsightUserId', user);
  }, identities);
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  await expect(page.locator('#systemStatus')).not.toHaveText(/正在连接数据源/);
  await expect(page.locator('#kpiGrid')).not.toBeEmpty();
  await expect(page.locator('#chatMessages .suggestions')).toBeVisible();
  return identities;
}

async function selectModel(page, modelId) {
  const response = page.waitForResponse(response => response.url().endsWith('/api/settings/model') && response.request().method() === 'POST');
  await page.locator('#modelSettingsButton').click();
  await expect(page.locator('#modelDialog')).toBeVisible();
  await page.locator('#modelSelect').selectOption(modelId);
  await page.locator('#saveModelSettings').click();
  const saved = await response;
  expect(saved.status()).toBe(200);
  expect((await saved.json()).model).toBe(modelId);
  await expect(page.locator('#modelDialog')).toBeHidden();
}

test('desktop settings switches Thinking from unsupported to supported through the real API', async ({ page }, testInfo) => {
  const assertNoFailures = captureBrowserFailures(page);
  await openIsolatedUser(page, testInfo);

  await test.step('select the unsupported model and verify the disabled control', async () => {
    await selectModel(page, 'deepseekv4-flash');
    await expect(page.locator('#thinkingToggle')).toHaveAttribute('aria-disabled', 'true');
    await expect(page.locator('#thinkingToggle')).toHaveAttribute('aria-pressed', 'false');
  });
  await test.step('select the Thinking-capable model and enable it', async () => {
    await selectModel(page, 'deepseekv4-pro');
    await expect(page.locator('#thinkingToggle')).toHaveAttribute('aria-disabled', 'false');
    await page.locator('#thinkingToggle').click();
    await expect(page.locator('#thinkingToggle')).toHaveAttribute('aria-pressed', 'true');
  });
  assertNoFailures();
});

test('desktop personal knowledge upload reaches ready content through the real ingestion workflow', async ({ page }, testInfo) => {
  const assertNoFailures = captureBrowserFailures(page);
  await openIsolatedUser(page, testInfo);
  const filename = `ux013-${testInfo.workerIndex}-upload.txt`;

  await test.step('open the sole personal-knowledge upload entry', async () => {
    await page.locator('[data-view="knowledge"]').click();
    await page.locator('[data-knowledge-mode="personal"]').click();
    await expect(page.locator('[data-open-knowledge-upload]')).toHaveCount(1);
    await page.locator('[data-open-knowledge-upload]').click();
    await expect(page.locator('#knowledgeUploadDialog')).toBeVisible();
  });
  await test.step('upload a memory-backed text document and wait for its terminal UI state', async () => {
    await page.locator('#knowledgeUploadFile').setInputFiles({name: filename, mimeType: 'text/plain', buffer: Buffer.from('UX-013 private knowledge: CMP polishing pressure is stable.')});
    const response = page.waitForResponse(response => response.url().endsWith('/api/knowledge/personal/documents') && response.request().method() === 'POST');
    await page.locator('#confirmKnowledgeUpload').click();
    expect((await response).status()).toBe(202);
    await expect(page.locator('#knowledgeUploadDialog')).toBeHidden();
    const document = page.locator(`[data-personal-document-id]`).filter({hasText: filename});
    await expect.poll(async () => document.count()).toBe(1);
    await expect.poll(async () => document.locator('.personal-status').textContent()).toMatch(/可检索/);
    await document.click();
    await expect(page.locator('#knowledgeContent')).toContainText('CMP polishing pressure is stable.');
    await expect(page.locator('[data-open-knowledge-upload]')).toHaveCount(1);
  });
  assertNoFailures();
});

test('desktop Thinking stream completes and the current session can be archived in its UI', async ({ page }, testInfo) => {
  const assertNoFailures = captureBrowserFailures(page);
  const identities = await openIsolatedUser(page, testInfo);
  const question = '请用本地规则分析 CVD-02 的膜厚是否发生漂移。';

  await test.step('enable Thinking and submit a real streaming request', async () => {
    await selectModel(page, 'deepseekv4-pro');
    await page.locator('#thinkingToggle').click();
    await expect(page.locator('#thinkingToggle')).toHaveAttribute('aria-pressed', 'true');
    const request = page.waitForRequest(request => request.url().endsWith('/api/chat/stream') && request.method() === 'POST');
    await page.locator('#chatInput').fill(question);
    await page.locator('#sendButton').click();
    const streamRequest = await request;
    const payload = JSON.parse(streamRequest.postData());
    expect(payload.thinking).toBe(true);
    expect(await streamRequest.headerValue('x-tenant-id')).toBe(identities.tenant);
    expect(await streamRequest.headerValue('x-user-id')).toBe(identities.user);
    await expect(page.locator('.live-analysis')).toBeVisible();
    await expect(page.locator('.message.assistant .message-content').last()).not.toBeEmpty();
    await expect(page.locator('.request-error')).toHaveCount(0);
    await expect(page.locator('#sendButton')).toBeEnabled();
  });
  await test.step('archive that same session and confirm it in the archived filter', async () => {
    await page.locator('#sessionHistoryButton').click();
    await expect(page.locator('#sessionsView')).toHaveClass(/active/);
    const current = page.locator('[data-library-session-id]').filter({hasText: question.slice(0, 20)}).first();
    await expect(current).toBeVisible();
    await current.click();
    await expect(page.locator('#archiveLibrarySession')).toBeVisible();
    await page.locator('#archiveLibrarySession').click();
    await page.locator('[data-session-filter="archived"]').click();
    await expect(page.locator('#sessionLibraryMeta')).toContainText('已归档');
    await expect(page.locator('#sessionLibraryMessages')).toContainText(question);
  });
  assertNoFailures();
});
