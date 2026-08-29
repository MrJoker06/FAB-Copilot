// Selected only by playwright.live.config.js; this process has no provider or
// admin credential.  The browser drives the product UI, not a test-only fetch.
const { test, expect } = require('./support/fixture');
const turnTimeout = Number(process.env.FAB_LIVE_E2E_TURN_TIMEOUT_MS || 300_000);

async function sendThroughUi(page, message, thinking) {
  const toggle = page.locator('#thinkingToggle');
  await expect(toggle).toBeEnabled();
  if ((await toggle.getAttribute('aria-pressed')) !== String(thinking)) await toggle.click();
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/chat/stream') && response.request().method() === 'POST');
  await page.locator('#chatInput').fill(message);
  await page.locator('#sendButton').click();
  const response = await responsePromise;
  const events = (await response.text()).trim().split('\n').filter(Boolean).map(line => JSON.parse(line));
  expect(Boolean(response.request().postDataJSON().thinking)).toBe(thinking);
  await expect(page.locator('#sendButton')).toBeEnabled({ timeout: turnTimeout });
  await expect(page.locator('.request-error')).toHaveCount(0);
  const result = events.find(event => event.type === 'result')?.result;
  expect(result).toBeTruthy();
  expect(result.status).toBe('success');
  expect(result.run_id).toEqual(expect.any(String));
  expect(result.answer?.trim()).not.toBe('');
  return result;
}

test('LIVE-PROVIDER-001 real provider completes the five-turn UI matrix without fallback', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  const config = await page.evaluate(() => fetch('/api/settings/model').then(response => response.json()));
  expect(config.model).toBe(process.env.FAB_LIVE_MODEL_ID);
  expect(config.capabilities.thinking).toBe(true);
  await page.locator('#modelSettingsButton').click();
  await expect(page.locator('#modelSelect')).toHaveValue(config.model);
  await page.locator('#closeModelDialog').click();
  await expect(page.locator('#modelDialog')).toBeHidden();
  const turns = [
    ['请用简洁语言说明光刻的基本作用。', false],
    ['请分析 2026-12-25 的 CMP 产线状态。', false],
    ['综合比较 CVD、ETCH 和 CMP 的当前风险与优先级。', false],
    ['请按证据分步骤分析 CVD 与刻蚀之间的产能风险。', true],
    ['基于刚才的结论，给出一个可执行的首要验证动作。', false],
  ];
  for (const [message, thinking] of turns) {
    const result = await sendThroughUi(page, message, thinking);
    expect(result.model).toBe(config.provider_model);
    expect(result.model_health?.fallback_reason).toBeFalsy();
    expect(result.mode).not.toMatch(/fallback|offline|deterministic/i);
    const persisted = await page.evaluate(sessionId => fetch(`/api/sessions/${sessionId}`).then(item => item.json()), result.session_id);
    const assistant = persisted.messages.filter(item => item.role === 'assistant').at(-1);
    expect(assistant.content).toBe(result.answer);
    expect(assistant.metadata.run_id).toBe(result.run_id);
    const audit = await page.evaluate(runId => fetch(`/api/agent-runs/${runId}/audit`).then(async response => ({ok: response.ok, payload: await response.json()})), result.run_id);
    expect(audit.ok).toBe(true);
    expect(audit.payload.run.run_id).toBe(result.run_id);
    expect(audit.payload.run.status).toBe('success');
    expect(audit.payload.timeline).toContainEqual(expect.objectContaining({event: 'run_finished', status: 'success'}));
  }
});
