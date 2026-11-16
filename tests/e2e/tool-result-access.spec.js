const {test, expect} = require('./support/fixture');

test('E2E-RESULT-001 admin explicitly toggles persisted offloading for new runs', async ({page}) => {
  await page.goto('/admin');
  await page.locator('#adminToken').fill('browser-test-admin-token');
  await page.locator('#adminAuthForm button[type="submit"]').click();
  const toggle = page.locator('#toggleResultStorage');
  await expect(toggle).toHaveText('关闭卸载');
  await toggle.click();
  await expect(toggle).toHaveText('开启卸载');
  await expect(page.locator('#resultStorageDetail')).toContainText('省略内容不可回读');
  await page.reload();
  await expect(toggle).toHaveText('开启卸载');
  await toggle.click();
  await expect(toggle).toHaveText('关闭卸载');
  await expect(page.locator('#resultStorageNotice')).toContainText('对新运行生效');
});

test('E2E-RESULT-002 restored saved reference reads real pages without a source query', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('fabInsightTenantId','mod029-fixture');
    localStorage.setItem('fabInsightUserId','mod029-owner');
    localStorage.setItem('fabInsightSessionId','mod029-result-session');
  });
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready','true');
  const saved = page.getByRole('button',{name:'查看已保存结果'});
  await expect(saved).toBeVisible();
  const first = page.waitForRequest(request => request.url().endsWith('/api/chat/stream') && request.method()==='POST');
  await saved.click();
  const selected = (await first).postDataJSON();
  expect(selected.tool_result_ref).toMatch(/^tr_[a-f0-9]{32}$/);
  await expect(page.locator('#chatMessages')).toContainText('未重新查询业务来源');
  const next = page.getByRole('button',{name:'下一页已保存结果'});
  await expect(next).toBeVisible();
  const second = page.waitForRequest(request => request.url().endsWith('/api/chat/stream') && request.method()==='POST');
  await next.click();
  const continuation = (await second).postDataJSON();
  expect(continuation.tool_result_ref).toBe(selected.tool_result_ref);
  expect(continuation.tool_result_cursor).toBeTruthy();
  await expect(page.locator('#chatMessages .message.assistant').last()).toContainText('2026-11-15');
  await page.reload();
  await expect(page.getByRole('button',{name:'查看已保存结果'})).toBeVisible();
});
