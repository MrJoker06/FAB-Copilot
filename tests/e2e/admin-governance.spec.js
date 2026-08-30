const { test, expect } = require('./support/fixture');

const ADMIN_TOKEN = 'browser-test-admin-token';

async function authenticate(page, token = ADMIN_TOKEN) {
  await page.locator('#adminToken').fill(token);
  await page.locator('#adminAuthForm button[type="submit"]').click();
}

async function openModels(page) {
  await page.locator('[data-admin-view="models"]').click();
  await expect(page.locator('#modelsView')).toHaveClass(/active/);
}

async function publishFixtureModel(page, {modelId, displayName, baseUrl, nativeMultimodal = false}) {
  await page.locator('#openPublishModel').click();
  await page.locator('#publishDisplayName').fill(displayName);
  await page.locator('#publishModelId').fill(modelId);
  await page.locator('#publishProvider').selectOption('openai-compatible');
  await page.locator('#publishProviderModel').fill('fixture-compatibility');
  await page.locator('#publishBaseUrl').fill(baseUrl);
  if (nativeMultimodal) await page.locator('#publishNativeMultimodal').check();
  await page.locator('#confirmPublishModel').click();
  const row = page.getByText(modelId, {exact: true}).locator('..');
  await expect(row).toBeVisible();
  return row;
}

test('E2E-ADMIN-001 admin token form locks, unlocks, logs out, and relocks after a real stale-token 401', async ({ page, browserFailures }) => {
  browserFailures.allowResponse({method: 'GET', pathname: '/api/admin/overview', status: 401});
  browserFailures.allowConsoleError({errorText: /401/i});
  await page.goto('/admin');
  await expect(page.locator('#adminAuthDialog')).toBeVisible();
  await authenticate(page, 'wrong-admin-token');
  await expect(page.locator('#adminWorkspace')).toBeHidden();
  await expect(page.locator('#adminAuthMessage')).toBeVisible();
  await authenticate(page);
  await expect(page.locator('#adminWorkspace')).toBeVisible();
  await page.locator('#adminLogout').click();
  await expect(page.locator('#adminWorkspace')).toBeHidden();
  await expect(page.locator('#adminAuthDialog')).toBeVisible();
  await authenticate(page);
  await page.route('**/api/admin/overview?*', async route => {
    await route.continue({headers: {...route.request().headers(), authorization: 'Bearer stale-admin-token'}});
    await page.unroute('**/api/admin/overview?*');
  });
  await page.locator('#refreshRuntime').click();
  await expect(page.locator('#adminWorkspace')).toBeHidden();
  await expect(page.locator('#adminAuthDialog')).toBeVisible();
});

test('E2E-ADMIN-002 disposable admin catalog publishes, probes, invalidates, retires, and republishes a model', async ({ page, browserFailures }, testInfo) => {
  await page.addInitScript(({tenant, user}) => {
    localStorage.setItem('fabInsightTenantId', tenant);
    localStorage.setItem('fabInsightUserId', user);
  }, {tenant: `admin-e2e-${testInfo.workerIndex}`, user: `admin-e2e-user-${testInfo.workerIndex}`});
  const suffix = `${test.info().workerIndex}-${Date.now()}`;
  const modelId = `e2e-admin-${suffix}`;
  const displayName = `E2E Admin ${suffix}`;
  const baseUrl = `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_PORT || 8899) + 1}/v1`;
  const createdModelIds = [];
  let userPage;
  try {
    await page.goto('/admin');
    await authenticate(page);
    await openModels(page);
  await page.locator('#openPublishModel').click();
  await page.locator('#publishDisplayName').fill(displayName);
  const modelIdInput = page.locator('#publishModelId');
  await modelIdInput.fill(`${modelId}-valid`);
  expect(await modelIdInput.evaluate(input => input.checkValidity())).toBe(true);
  await modelIdInput.fill('invalid model id');
  expect(await modelIdInput.evaluate(input => input.checkValidity())).toBe(false);
  await modelIdInput.fill(modelId);
  expect(await modelIdInput.evaluate(input => input.checkValidity())).toBe(true);
  await page.locator('#publishProvider').selectOption('openai-compatible');
  await page.locator('#publishProviderModel').fill('fixture-compatibility');
  await page.locator('#publishBaseUrl').fill(baseUrl);
  await page.locator('#publishThinking').check();
  const published = page.waitForRequest(request => request.url().endsWith('/api/admin/models') && request.method() === 'POST');
  await page.locator('#confirmPublishModel').click();
  const payload = (await published).postDataJSON();
  createdModelIds.push(modelId);
  expect(Object.keys(payload.capabilities).sort()).toEqual(['native_multimodal', 'streaming', 'thinking', 'tool_calls']);
  expect(JSON.stringify(payload)).not.toMatch(/api_key|token|secret/i);
  const row = page.getByText(modelId, {exact: true}).locator('..');
  await expect(row).toBeVisible();
  const before = await page.evaluate(async modelId => (await fetch('/api/admin/models', {headers: {Authorization: 'Bearer browser-test-admin-token'}})).json().then(items => items.find(item => item.model_id === modelId).health), modelId);
  const probe = page.waitForResponse(response => response.url().endsWith(`/api/admin/models/${modelId}/compatibility-check`) && response.request().method() === 'POST');
  await row.locator('[data-action="compatibility"]').click();
  expect((await probe).status()).toBe(200);
  await expect(row).toContainText('能力探针通过');
  const after = await page.evaluate(async modelId => (await fetch('/api/admin/models', {headers: {Authorization: 'Bearer browser-test-admin-token'}})).json().then(items => items.find(item => item.model_id === modelId)), modelId);
  expect(after.health).toEqual(before);
  expect(after.compatibility.status).toBe('passed');
  expect(after.compatibility_checked_at).toEqual(expect.any(String));
  await row.locator('[data-action="capabilities"]').click();
  await page.locator('#editNativeMultimodal').check();
  const changed = page.waitForResponse(response => response.url().endsWith(`/api/admin/models/${modelId}/capabilities`) && response.request().method() === 'PATCH');
  await page.locator('#confirmCapabilities').click();
  expect((await changed).status()).toBe(200);
  await expect(row).toContainText('能力配置已变更');
  const invalidated = await page.evaluate(async modelId => (await fetch('/api/admin/models', {headers: {Authorization: 'Bearer browser-test-admin-token'}})).json().then(items => items.find(item => item.model_id === modelId)), modelId);
  expect(invalidated.compatibility.status).toBe('unverified');
  const userVisible = await page.evaluate(async modelId => (await fetch('/api/settings/model')).json().then(item => item.allowed_models.includes(modelId)), modelId);
  expect(userVisible).toBe(true);
  userPage = await page.context().newPage();
  await userPage.goto('/');
  await expect(userPage.locator('html')).toHaveAttribute('data-app-ready', 'true');
  await userPage.locator('#modelSettingsButton').click();
  await expect(userPage.locator('#modelDialog')).toBeVisible();
  await userPage.locator('#modelSelect').selectOption(modelId);
  await userPage.locator('#saveModelSettings').click();
  await expect(userPage.locator('#thinkingToggle')).toHaveAttribute('aria-disabled', 'false');
  await userPage.close();
  userPage = undefined;
  await page.goto('/admin');
  await openModels(page);
  const scenarioBase = `http://127.0.0.1:${Number(process.env.PLAYWRIGHT_PORT || 8899) + 1}/v1`;
  for (const [scenario, expected] of [
    ['invalid-tool', {category: 'tool_arguments', retryable: false, message: 'JSON 参数'}],
    ['image-rejected', {category: 'multimodal', retryable: false, message: '图片输入被模型拒绝', nativeMultimodal: true}],
    ['upstream-unavailable', {category: 'http', retryable: true, message: 'HTTP 500'}],
  ]) {
    const failedId = `${modelId}-${scenario}`;
    const failedName = `${displayName} ${scenario}`;
    const failedRow = await publishFixtureModel(page, {modelId: failedId, displayName: failedName, baseUrl: `${scenarioBase}/${scenario}`, nativeMultimodal: expected.nativeMultimodal});
    createdModelIds.push(failedId);
    browserFailures.allowResponse({method: 'POST', pathname: `/api/admin/models/${failedId}/compatibility-check`, status: 422});
    browserFailures.allowConsoleError({errorText: /server responded with a status of 422/i});
    const failedProbe = page.waitForResponse(response => response.url().endsWith(`/api/admin/models/${failedId}/compatibility-check`) && response.request().method() === 'POST');
    await failedRow.locator('[data-action="compatibility"]').click();
    expect((await failedProbe).status()).toBe(422);
    await expect(page.locator('#modelNotice')).toContainText(expected.message);
    const persisted = await page.evaluate(async id => (await fetch('/api/admin/models', {headers: {Authorization: 'Bearer browser-test-admin-token'}})).json().then(items => items.find(item => item.model_id === id).compatibility), failedId);
    expect(persisted).toMatchObject({status: 'failed', category: expected.category, retryable: expected.retryable});
  }
  const retired = page.waitForResponse(response => response.url().endsWith(`/api/admin/models/${modelId}`) && response.request().method() === 'PATCH');
  await row.locator('[data-action="status"]').click();
  expect((await retired).status()).toBe(200);
  await expect.poll(async () => page.evaluate(async modelId => (await fetch('/api/settings/model')).json().then(item => item.allowed_models.includes(modelId)), modelId)).toBe(false);
  await row.locator('[data-action="status"]').click();
  await expect.poll(async () => page.evaluate(async modelId => (await fetch('/api/settings/model')).json().then(item => item.allowed_models.includes(modelId)), modelId)).toBe(true);
  } finally {
    if (userPage && !userPage.isClosed()) await userPage.close();
    if (createdModelIds.length && !page.isClosed()) {
      await page.goto('/admin');
      const statuses = await page.evaluate(async ids => Promise.all(ids.map(async modelId => {
          const response = await fetch(`/api/admin/models/${encodeURIComponent(modelId)}`, {
            method: 'PATCH', headers: {'Authorization': 'Bearer browser-test-admin-token', 'Content-Type': 'application/json'},
            body: JSON.stringify({status: 'retired'}),
          });
          return response.status;
        })), createdModelIds);
      expect(statuses).toEqual(createdModelIds.map(() => 200));
    }
  }
});
