const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');
const AxeBuilder = require('@axe-core/playwright').default;
const { test, expect } = require('./support/fixture');

// The chat model is the loopback protocol fixture's lot-commonality scenario: it calls the
// commonality tools deterministically, so these cases check page and chat wiring, not model quality.
const PORT = Number(process.env.PLAYWRIGHT_PORT || 8899);
const BASE_URL = `http://127.0.0.1:${PORT}`;
const FIXTURE_URL = `http://127.0.0.1:${PORT + 1}/v1/lot-commonality`;
const ADMIN = { Authorization: 'Bearer browser-test-admin-token' };
const MODEL_ID = 'lca-chat-fixture';
const USER = 'lca-chat-e2e-user';
const USER_KEY = 'fabInsightUserId';
const ANALYSES = '/api/lot-commonality/analyses';
const MISSING_REF = `lca_${'0'.repeat(32)}`;
const REFERENCE_DB = path.resolve(__dirname, '../../data/departments/manufacturing_operations.db');

function referenceLots() {
  const db = new DatabaseSync(REFERENCE_DB, { readOnly: true });
  try {
    return db.prepare('SELECT DISTINCT lot_id FROM process_runs ORDER BY lot_id LIMIT 3').all().map(row => row.lot_id);
  } finally { db.close(); }
}
const LOTS = referenceLots();

test.beforeAll(async ({ playwright }) => {
  expect(LOTS).toHaveLength(3);
  for (const lot of LOTS) expect(lot).toMatch(/^L\d{4,}-\d{3,}$/);
  const admin = await playwright.request.newContext({ baseURL: BASE_URL, extraHTTPHeaders: ADMIN });
  const published = await admin.post('/api/admin/models', { data: {
    model_id: MODEL_ID, display_name: 'LCA chat fixture', provider: 'openai-compatible', provider_model: 'fixture-lot-commonality',
    base_url: FIXTURE_URL, capabilities: { streaming: true, tool_calls: true, thinking: false, native_multimodal: false },
  } });
  expect(published.status(), await published.text()).toBe(201);
  const credential = await admin.put(`/api/admin/models/${MODEL_ID}/credential`, { data: { api_key: 'lca-chat-fixture-key' } });
  expect(credential.status(), await credential.text()).toBe(200);
  await admin.dispose();
  const user = await playwright.request.newContext({ baseURL: BASE_URL, extraHTTPHeaders: { 'X-User-ID': USER } });
  const selected = await user.post('/api/settings/model', { data: { model: MODEL_ID } });
  expect(selected.status(), await selected.text()).toBe(200);
  await user.dispose();
});

test.afterAll(async ({ playwright }) => {
  const admin = await playwright.request.newContext({ baseURL: BASE_URL, extraHTTPHeaders: ADMIN });
  expect((await admin.delete(`/api/admin/models/${MODEL_ID}/credential`)).status()).toBe(200);
  expect((await admin.patch(`/api/admin/models/${MODEL_ID}`, { data: { status: 'retired' } })).status()).toBe(200);
  await admin.dispose();
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript(([key, user]) => { if (!localStorage.getItem(key)) localStorage.setItem(key, user); }, [USER_KEY, USER]);
});

async function ready(page, view = '') {
  await page.goto(view ? `/?view=${view}` : '/');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  await expect(page.locator('html')).toHaveAttribute('data-commonality-ready', 'true');
}

async function send(page, message) {
  if (message !== undefined) await page.locator('#chatInput').fill(message);
  const request = page.waitForRequest(item => item.url().endsWith('/api/chat/stream') && item.method() === 'POST');
  const response = page.waitForResponse(item => item.url().endsWith('/api/chat/stream') && item.request().method() === 'POST');
  await page.locator('#sendButton').click();
  const body = (await request).postDataJSON();
  return { body, response: await response };
}

async function queryOnPage(page) {
  await page.locator('[data-group-key] textarea').first().fill(LOTS.join('\n'));
  const response = page.waitForResponse(item => item.url().endsWith(ANALYSES) && item.request().method() === 'POST');
  await page.locator('#runCommonality').click();
  const created = await (await response).json();
  await expect(page.locator('#commonalityStatus')).toContainText('查询完成');
  return created;
}

const lastAssistant = page => page.locator('#chatMessages .message.assistant:not(.live-analysis)').last();
const lastUser = page => page.locator('#chatMessages .message.user').last();

async function createInChat(page) {
  await send(page, `分析 ${LOTS.join('、')} 这几个 lot 的共性`);
  const created = lastAssistant(page).locator('[data-analysis-origin="created"]');
  await expect(created).toContainText('本轮创建的共性分析');
  const reference = (await created.locator('code').textContent()).trim();
  expect(reference).toMatch(/^lca_[a-f0-9]{32}$/);
  return { created, reference };
}

test('E2E-LCA-CHAT-001 an analysis created in chat reopens on the commonality page with the editor refilled', async ({ page }) => {
  await ready(page);
  const { created, reference } = await createInChat(page);
  await expect(lastAssistant(page)).toContainText(`共性分析已完成（${reference}）`);
  const read = page.waitForResponse(item => item.url().endsWith(`${ANALYSES}/${reference}`) && item.request().method() === 'GET');
  await created.getByRole('button', { name: '在共性分析页打开' }).click();
  expect((await read).status()).toBe(200);
  await expect(page).toHaveURL(/[?&]view=commonality\b/);
  await expect(page.locator('#commonalityView')).toHaveClass(/active/);
  await expect(page.locator('#commonalityStatus')).toContainText('已打开分析结果');
  await expect(page.locator('#commonalityResults .lc-meta')).toContainText(reference);
  await expect(page.locator('#commonalityResults [data-receipt-group="main"]')).toContainText(`输入 ${LOTS.length} 个`);
  await expect(page.locator('[data-group-key] textarea').first()).toHaveValue(LOTS.join('\n'));
  await expect(page.locator('#commonalityResults [data-lc-stale]')).toBeHidden();
  await expect(page.locator('#commonalityResults [data-lc-ask]')).toBeEnabled();

  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  await expect(lastAssistant(page).locator('[data-analysis-origin="created"] code')).toHaveText(reference);
});

test('E2E-LCA-CHAT-002 asking from the page sends the analysis as a structured reference the user can remove', async ({ page }) => {
  await ready(page, 'commonality');
  const analysis = await queryOnPage(page);
  const reference = analysis.analysis_ref;
  await page.locator('#commonalityResults [data-lc-ask]').click();
  const tag = page.locator('#chatAttachment');
  const input = page.locator('#chatInput');
  await expect(tag).toBeVisible();
  await expect(tag).toContainText(`附带共性分析${analysis.groups[0].name} ${LOTS.length} 个 lot · ${analysis.candidates.length} 个共性项`);
  await expect(input).toHaveValue(/^请解读附带的 Lot 共性分析结果/);
  await expect(input).toBeFocused();
  expect(await input.inputValue()).not.toContain(reference);
  const accessibility = await new AxeBuilder({ page }).include('#chatForm').withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  expect(accessibility.violations, JSON.stringify(accessibility.violations, null, 2)).toEqual([]);
  await page.locator('.agent-panel').screenshot({ path: 'runtime/quality/lot-commonality-chat-attached.png' });

  await tag.getByRole('button', { name: '移除附带的共性分析' }).click();
  await expect(tag).toBeHidden();
  await page.locator('#commonalityResults [data-lc-ask]').click();
  await expect(tag).toBeVisible();

  const { body, response } = await send(page);
  expect(response.status()).toBe(200);
  expect(body.analysis_ref).toBe(reference);
  expect(body.tool_result_ref).toBeUndefined();
  expect(body.message).not.toContain(reference);
  await expect(tag).toBeHidden();
  await expect(lastUser(page).locator('.message-attachment code')).toHaveText(reference);
  await expect(lastAssistant(page)).toContainText(`已读取附带分析 ${reference} 的成员`);
  await expect(lastAssistant(page).locator('[data-analysis-origin="attached"] code')).toHaveText(reference);
  await expect(lastAssistant(page).locator('[data-analysis-origin="read"]')).toHaveCount(0);
  await page.locator('.agent-panel').screenshot({ path: 'runtime/quality/lot-commonality-chat-answer.png' });

  const followUp = await send(page, '谢谢，先这样');
  expect(followUp.body.analysis_ref).toBeUndefined();

  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  const restored = page.locator('#chatMessages .message.user .message-attachment code');
  await expect(restored).toHaveCount(1);
  await expect(restored).toHaveText(reference);
});

test('E2E-LCA-CHAT-003 an unreadable reference is refused before storage and reported where it was opened', async ({ page, browserFailures }) => {
  browserFailures.allowResponse({ method: 'POST', pathname: '/api/chat/stream', status: 404 });
  browserFailures.allowConsoleError({ errorText: /status of 404/ });
  await ready(page, 'commonality');
  await queryOnPage(page);
  await page.locator('#commonalityResults [data-lc-ask]').click();
  // Expired, foreign and session-deleted results all answer RESULT_UNAVAILABLE; a well-formed unknown reference stands in for them.
  await page.route('**/api/chat/stream', route => route.continue({ postData: JSON.stringify({ ...route.request().postDataJSON(), analysis_ref: MISSING_REF }) }), { times: 1 });
  const { body, response } = await send(page);
  expect(body.analysis_ref).toMatch(/^lca_[a-f0-9]{32}$/);
  expect(response.status()).toBe(404);
  const error = page.locator('#chatMessages .request-error').last();
  await expect(error).toContainText('附带的分析结果已不可读取');
  await expect(error).toContainText('RESULT_UNAVAILABLE');
  await expect(error.locator('.retry-request')).toHaveCount(0);
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  await expect(page.locator('#chatMessages .message.user')).toHaveCount(0);

  const { reference } = await createInChat(page);
  await page.evaluate(key => localStorage.setItem(key, 'lca-chat-other-user'), USER_KEY);
  browserFailures.allowResponse({ method: 'GET', pathname: `${ANALYSES}/${reference}`, status: 404 });
  await lastAssistant(page).getByRole('button', { name: '在共性分析页打开' }).click();
  await expect(page.locator('#commonalityView')).toHaveClass(/active/);
  await expect(page.locator('#commonalityStatus')).toContainText('该结果已不可读取（已过期、无权访问或所属会话已删除），请重新查询');
  await expect(page.locator('#commonalityStatus')).toHaveAttribute('data-tone', 'error');
  await expect(page.locator('#commonalityResults')).toBeHidden();
});

test('E2E-LCA-CHAT-004 sample and unavailable results cannot be attached', async ({ page, browserFailures }) => {
  browserFailures.allowConsoleError({ errorText: /status of 404/ });
  await ready(page, 'commonality');
  await page.locator('#loadCommonalitySample').click();
  await expect(page.locator('#commonalityStatus')).toContainText('已载入合成样例结果');
  const ask = page.locator('#commonalityResults [data-lc-ask]');
  await expect(ask).toBeDisabled();
  await expect(ask).toHaveAttribute('title', '合成样例未保存到服务端，不能附带给助手');

  const analysis = await queryOnPage(page);
  await expect(ask).toBeEnabled();
  await page.evaluate(key => localStorage.setItem(key, 'lca-chat-other-user'), USER_KEY);
  browserFailures.allowResponse({ method: 'POST', pathname: `${ANALYSES}/${analysis.analysis_ref}/members`, status: 404 });
  await page.locator('#commonalityResults [data-lc-count]').first().click();
  await expect(page.locator('#commonalityResults [data-lc-unavailable]')).toBeVisible();
  await expect(ask).toBeDisabled();
  await expect(page.locator('#chatAttachment')).toBeHidden();
});
