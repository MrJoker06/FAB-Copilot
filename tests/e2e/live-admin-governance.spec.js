// Selected only by playwright.live.config.js.  This browser has no host credentials.
const { test, expect } = require('./support/fixture');
const LIVE_ADMIN_TOKEN = 'live-browser-admin-token';
const turnTimeout = Number(process.env.FAB_LIVE_E2E_TURN_TIMEOUT_MS || 300_000);
let originalModelId;
let cloneModelId;

async function openUserApp(page) {
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
}

async function adminLogin(page) {
  await page.goto('/admin');
  await expect(page.locator('#adminAuthDialog')).toBeVisible();
  await page.locator('#adminToken').fill(LIVE_ADMIN_TOKEN);
  await page.locator('#adminAuthForm button[type="submit"]').click();
  await expect(page.locator('#adminWorkspace')).toBeVisible();
  await page.locator('[data-admin-view="models"]').click();
}

async function liveThinkingTurn(page, question) {
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/chat/stream') && response.request().method() === 'POST');
  await page.locator('#chatInput').fill(question);
  await page.locator('#sendButton').click();
  const response = await responsePromise;
  expect(response.request().postDataJSON().thinking).toBe(true);
  const events = (await response.text()).trim().split('\n').filter(Boolean).map(line => JSON.parse(line));
  await expect(page.locator('#sendButton')).toBeEnabled({timeout: turnTimeout});
  const result = events.find(event => event.type === 'result')?.result;
  expect(result).toEqual(expect.objectContaining({status: 'success', run_id: expect.any(String)}));
  return result;
}

test.afterEach(async ({ request }) => {
  const cleanupErrors = [];
  try {
    if (originalModelId) {
      const restored = await request.post('/api/settings/model', {data: {model: originalModelId}});
      if (restored.status() !== 200) cleanupErrors.push(new Error(`failed to restore selected model: ${restored.status()}`));
    }
  } catch (error) {
    cleanupErrors.push(error);
  }
  try {
    if (cloneModelId) {
      const retired = await request.patch(`/api/admin/models/${encodeURIComponent(cloneModelId)}`, {
        headers: {Authorization: `Bearer ${LIVE_ADMIN_TOKEN}`},
        data: {status: 'retired'},
      });
      if (![200, 404].includes(retired.status())) cleanupErrors.push(new Error(`failed to retire clone: ${retired.status()}`));
    }
  } catch (error) {
    cleanupErrors.push(error);
  } finally {
    originalModelId = undefined;
    cloneModelId = undefined;
  }
  if (cleanupErrors.length) throw new AggregateError(cleanupErrors, 'LIVE-ADMIN-001 cleanup failed');
});

test('LIVE-ADMIN-001 real admin governance clones the selected provider, probes, and controls user visibility', async ({ page }) => {
  await openUserApp(page);
  const selected = await page.evaluate(() => fetch('/api/settings/model').then(response => response.json()));
  expect(selected.model).toBe(process.env.FAB_LIVE_MODEL_ID);
  originalModelId = selected.model;
  const suffix = `${test.info().workerIndex}-${Date.now()}`;
  const modelId = `live-admin-${suffix}`;
  await adminLogin(page);
  await page.locator('#openPublishModel').click();
  await page.locator('#publishDisplayName').fill(`Live Admin ${suffix}`);
  await page.locator('#publishModelId').fill(modelId);
  await page.locator('#publishProvider').selectOption(selected.provider);
  await page.locator('#publishProviderModel').fill(selected.provider_model);
  await page.locator('#publishBaseUrl').fill(selected.base_url);
  for (const [name, key] of [['Streaming', 'streaming'], ['ToolCalls', 'tool_calls'], ['Thinking', 'thinking'], ['NativeMultimodal', 'native_multimodal']]) {
    const control = page.locator(`#publish${name}`);
    if (selected.capabilities[key]) await control.check(); else await control.uncheck();
  }
  const publishRequest = page.waitForRequest(request => request.url().endsWith('/api/admin/models') && request.method() === 'POST');
  const published = page.waitForResponse(response => response.url().endsWith('/api/admin/models') && response.request().method() === 'POST');
  await page.locator('#confirmPublishModel').click();
  const publishPayload = (await publishRequest).postDataJSON();
  expect(Object.keys(publishPayload.capabilities).sort()).toEqual(['native_multimodal', 'streaming', 'thinking', 'tool_calls']);
  expect(JSON.stringify(publishPayload)).not.toMatch(/api[_-]?key|authorization|secret|token/i);
  const publishResponse = await published;
  expect(publishResponse.status()).toBe(201);
  expect((await publishResponse.text())).not.toMatch(/api[_-]?key|authorization|secret/i);
  cloneModelId = modelId;
  const row = page.locator('#modelCatalogBody tr').filter({hasText: modelId});
  await expect(row).toBeVisible();
  await row.locator('[data-action="capabilities"]').click();
  const toggle = page.locator('#editNativeMultimodal');
  if (selected.capabilities.native_multimodal) await toggle.uncheck(); else await toggle.check();
  const changedRequest = page.waitForRequest(request => request.url().endsWith(`/api/admin/models/${modelId}/capabilities`) && request.method() === 'PATCH');
  await page.locator('#confirmCapabilities').click();
  const changedPayload = (await changedRequest).postDataJSON();
  expect(Object.keys(changedPayload).sort()).toEqual(['native_multimodal', 'streaming', 'thinking', 'tool_calls']);
  expect(JSON.stringify(changedPayload)).not.toMatch(/api[_-]?key|authorization|secret|token/i);
  await expect(row).toContainText('能力配置已变更');
  await row.locator('[data-action="capabilities"]').click();
  if (selected.capabilities.native_multimodal) await page.locator('#editNativeMultimodal').check(); else await page.locator('#editNativeMultimodal').uncheck();
  const restoredRequest = page.waitForRequest(request => request.url().endsWith(`/api/admin/models/${modelId}/capabilities`) && request.method() === 'PATCH');
  await page.locator('#confirmCapabilities').click();
  const restoredPayload = (await restoredRequest).postDataJSON();
  expect(restoredPayload).toEqual(selected.capabilities);
  await expect(row).toContainText('能力配置已变更');
  const beforeHealth = await row.locator('.model-health').innerText();
  const probe = page.waitForResponse(response => response.url().endsWith(`/api/admin/models/${modelId}/compatibility-check`) && response.request().method() === 'POST');
  await row.locator('[data-action="compatibility"]').click();
  expect((await probe).status()).toBe(200);
  await expect(row.locator('.model-health')).toHaveText(beforeHealth);
  const compatibility = row.locator('.compatibility-details');
  await expect(compatibility).toContainText('能力探针通过');
  await expect(compatibility).toContainText(/\d{4}/);
  await compatibility.locator('summary').click();
  const expectedChecks = ['基础流式连接', '工具调用', '上下文负载', '结构化上下文'];
  if (selected.capabilities.thinking) expectedChecks.push('Thinking 回答', 'Thinking 工具续接');
  if (selected.capabilities.native_multimodal) expectedChecks.push('原生多模态');
  expectedChecks.push('安全上限');
  const checkTexts = await compatibility.locator('li').allTextContents();
  expect(checkTexts).toHaveLength(expectedChecks.length);
  for (const label of expectedChecks) expect(checkTexts).toContain(`${label}：通过`);
  await page.locator('#adminLogout').click();
  await openUserApp(page);
  await page.locator('#modelSettingsButton').click();
  await expect(page.locator('#modelDialog')).toBeVisible();
  await page.locator('#modelSelect').selectOption(modelId);
  await page.locator('#saveModelSettings').click();
  await expect(page.locator('#thinkingToggle')).toHaveAttribute('aria-disabled', selected.capabilities.thinking ? 'false' : 'true');
  if (selected.capabilities.thinking) await page.locator('#thinkingToggle').click();
  const result = await liveThinkingTurn(page, '请用简洁语言说明光刻的基本作用。');
  expect(result.model).toBe(selected.provider_model);
  expect(result.model_health?.fallback_reason).toBeFalsy();
  expect(result.mode).not.toMatch(/fallback|offline|deterministic/i);
  const session = await page.evaluate(sessionId => fetch(`/api/sessions/${sessionId}`).then(response => response.json()), result.session_id);
  expect(session.messages.at(-1).metadata.run_id).toBe(result.run_id);
  const audit = await page.evaluate(runId => fetch(`/api/agent-runs/${runId}/audit`).then(response => response.json()), result.run_id);
  expect(audit.run.status).toBe('success');
  if (audit.run.model) expect(audit.run.model).toBe(selected.provider_model);
  await adminLogin(page);
  const current = page.locator('#modelCatalogBody tr').filter({hasText: modelId});
  await current.locator('[data-action="status"]').click();
  await expect.poll(async () => page.evaluate(async modelId => (await fetch('/api/settings/model')).json().then(item => item.allowed_models.includes(modelId)), modelId)).toBe(false);
  await current.locator('[data-action="status"]').click();
  await expect.poll(async () => page.evaluate(async modelId => (await fetch('/api/settings/model')).json().then(item => item.allowed_models.includes(modelId)), modelId)).toBe(true);
  await page.locator('#adminLogout').click();
  await openUserApp(page);
  await page.locator('#modelSettingsButton').click();
  await expect(page.locator('#modelDialog')).toBeVisible();
  await page.locator('#modelSelect').selectOption(selected.model);
  await page.locator('#saveModelSettings').click();
  await expect(page.locator('#modelDialog')).toBeHidden();
  await adminLogin(page);
  const cleanupRow = page.locator('#modelCatalogBody tr').filter({hasText: modelId});
  const cleanup = page.waitForResponse(response => response.url().endsWith(`/api/admin/models/${modelId}`) && response.request().method() === 'PATCH');
  await cleanupRow.locator('[data-action="status"]').click();
  expect((await cleanup).status()).toBe(200);
  await expect.poll(async () => page.evaluate(async id => (await fetch('/api/settings/model')).json().then(item => item.allowed_models.includes(id)), modelId)).toBe(false);
});
