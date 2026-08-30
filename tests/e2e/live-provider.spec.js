// Selected only by playwright.live.config.js; this process has no provider or
// admin credential.  The browser drives the product UI, not a test-only fetch.
const { test, expect } = require('./support/fixture');
const sourcePresenter = require('../../app/static/source_presenter.js');
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

async function assertRenderedResult(page, result) {
  const assistant = page.locator('.message.assistant').last();
  const normalizeVisibleText = value => value
    .replace(/\[[^\]]+\]\([^)]*\)/g, match => match.replace(/\]\([^)]*\)/, ''))
    .replace(/^[\t ]*(?:[-+*]\s+|\d+[.)]\s+|>\s*|#{1,6}\s+)/gm, '')
    .replace(/[#*_`]/g, '')
    .replace(/\s+/g, ' ').trim();
  const visibleAnswer = normalizeVisibleText(sourcePresenter.replaceReferenceIds(result.answer, result.sources));
  const actualAnswer = normalizeVisibleText(await assistant.locator('.message-content').innerText());
  expect(actualAnswer).toContain(visibleAnswer.slice(0, Math.min(40, visibleAnswer.length)));
  expect(actualAnswer).toContain(visibleAnswer.slice(-Math.min(40, visibleAnswer.length)));
  const trace = assistant.locator('.analysis-trace');
  if (result.tool_trace?.length) {
    await expect(trace).toHaveCount(1);
    await expect(trace).toContainText(result.run_id.slice(0, 8));
    await trace.locator('summary').click();
    await expect(trace.locator('li')).toHaveCount(result.tool_trace.length);
  } else await expect(trace).toHaveCount(0);
  const sourcePanel = assistant.locator('.source-list');
  if (!result.sources?.length) return;
  await expect(sourcePanel).toHaveCount(1);
  await expect(sourcePanel).not.toHaveAttribute('open', '');
  await sourcePanel.locator('summary').click();
  const groups = sourcePresenter.groupSources(result.sources);
  expect(await sourcePanel.locator('.source-group').count()).toBe(groups.length);
  for (let index = 0; index < groups.length; index += 1) {
    const group = sourcePanel.locator('.source-group').nth(index);
    await expect(group).toContainText(groups[index].name);
    expect(await group.locator('.source-link').count()).toBe(groups[index].items.length);
  }
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
    await assertRenderedResult(page, result);
    const audit = await page.evaluate(runId => fetch(`/api/agent-runs/${runId}/audit`).then(async response => ({ok: response.ok, payload: await response.json()})), result.run_id);
    expect(audit.ok).toBe(true);
    expect(audit.payload.run.run_id).toBe(result.run_id);
    expect(audit.payload.run.status).toBe('success');
    expect(audit.payload.timeline).toContainEqual(expect.objectContaining({event: 'run_finished', status: 'success'}));
  }
  const sessionId = await page.evaluate(() => localStorage.getItem('fabInsightSessionId'));
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  const restored = await page.evaluate(id => fetch(`/api/sessions/${id}`).then(response => response.json()), sessionId);
  expect(restored.messages.filter(item => item.role === 'user')).toHaveLength(turns.length);
  expect(restored.messages.filter(item => item.role === 'assistant')).toHaveLength(turns.length);
  await expect(page.locator('#chatMessages .message.assistant')).toHaveCount(turns.length);
});

test('LIVE-PROVIDER-002 real provider retrieves newly uploaded personal knowledge and removes it cleanly', async ({ page, browserFailures }, testInfo) => {
  browserFailures.allowRequestFailed({ method: 'GET', pathname: '/api/knowledge/personal/jobs/events', errorText: /ERR_ABORTED/i });
  const lookupKey = `LIVE-LOOKUP-${testInfo.workerIndex}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const secretValue = `LIVE-VALUE-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const filename = `live-personal-${testInfo.workerIndex}-${Date.now()}.txt`;
  const title = filename.replace(/\.txt$/, '');
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  const config = await page.evaluate(() => fetch('/api/settings/model').then(response => response.json()));
  await page.locator('[data-view="knowledge"]').click();
  await page.locator('[data-knowledge-mode="personal"]').click();
  await page.locator('[data-open-knowledge-upload]').click();
  await page.locator('#knowledgeUploadFile').setInputFiles({name: filename, mimeType: 'text/plain', buffer: Buffer.from(`For lookup key ${lookupKey}, the exact personal knowledge value is ${secretValue}.`)});
  await page.locator('#confirmKnowledgeUpload').click();
  await expect(page.locator('#knowledgeUploadDialog')).toBeHidden();
  const document = page.locator('[data-personal-document-id]').filter({hasText: filename});
  await expect(document).toHaveCount(1);
  await expect.poll(async () => document.locator('.personal-status').textContent(), {timeout: turnTimeout}).toMatch(/可检索/);
  await document.click();
  const documentId = await document.getAttribute('data-personal-document-id');
  await page.locator('[data-view="dashboard"]').click();
  const result = await sendThroughUi(page, `What is the exact personal knowledge value for lookup key ${lookupKey}?`, false);
  expect(result.model).toBe(config.provider_model);
  expect(result.model_health?.fallback_reason).toBeFalsy();
  expect(result.mode).not.toMatch(/fallback|offline|deterministic/i);
  expect(result.answer).toContain(secretValue);
  const personalSources = result.sources.filter(source => source.source_type === 'personal' && source.document_id === documentId);
  expect(personalSources).not.toHaveLength(0);
  await page.locator('.source-list summary').click();
  const personalSource = page.locator('.source-group').filter({hasText: /个人知识/}).filter({has: page.locator(`[data-source-document-id="${documentId}"]`)});
  await expect(personalSource).toBeVisible();
  const personalSourceLink = personalSource.locator('.source-link').first();
  await expect(personalSourceLink).toBeVisible();
  await personalSourceLink.click();
  await expect(page.locator('#knowledgeTitle')).toHaveText(title);
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.locator('.message.assistant .copy-answer').last().click();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  const internalIds = new Set(personalSources.flatMap(source => [source.document_id, source.chunk_id, source.reference_id]).filter(value => typeof value === 'string' && value));
  expect(internalIds.size).toBeGreaterThan(0);
  for (const internalId of internalIds) expect(copied).not.toContain(internalId);
  const deletion = page.waitForResponse(response => response.url().includes(`/api/knowledge/personal/documents/${documentId}`) && response.request().method() === 'DELETE');
  browserFailures.allowResponse({method: 'GET', pathname: `/api/knowledge/personal/documents/${documentId}/content`, status: 404});
  browserFailures.allowConsoleError({errorText: /server responded with a status of 404/i});
  await page.locator('#deletePersonalKnowledge').click();
  await page.locator('#confirmPersonalKnowledgeDelete').click();
  expect((await deletion).status()).toBe(202);
  await expect.poll(async () => page.evaluate(async ({lookupKey}) => {
    const response = await fetch('/api/knowledge/personal/search-preview', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({query: lookupKey, limit: 10})});
    return (await response.json()).count;
  }, {lookupKey}), {timeout: turnTimeout}).toBe(0);
});
