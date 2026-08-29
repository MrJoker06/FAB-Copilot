const { test, expect } = require('./support/fixture');
const fs = require('node:fs/promises');

function isolatedIdentity(testInfo) {
  const suffix = `${testInfo.workerIndex}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  return { tenant: `e2e-knowledge-${suffix}`, user: `user-${suffix}` };
}

async function openPersonalKnowledge(page, testInfo) {
  const identity = isolatedIdentity(testInfo);
  await page.addInitScript(({ tenant, user }) => {
    localStorage.setItem('fabInsightTenantId', tenant);
    localStorage.setItem('fabInsightUserId', user);
  }, identity);
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  await page.locator('[data-view="knowledge"]').click();
  await page.locator('[data-knowledge-mode="personal"]').click();
  await expect(page.locator('[data-open-knowledge-upload]')).toHaveCount(1);
  return identity;
}

async function openUpload(page) {
  await page.locator('[data-open-knowledge-upload]').click();
  await expect(page.locator('#knowledgeUploadDialog')).toBeVisible();
}

async function waitForDocumentStatus(page, filename, status) {
  const document = page.locator('[data-personal-document-id]').filter({ hasText: filename });
  await expect(document).toHaveCount(1);
  await expect.poll(async () => document.locator('.personal-status').textContent(), { timeout: 20_000 }).toMatch(status);
  return document;
}

async function preview(page, query, identity) {
  return page.evaluate(async ({ query, identity }) => {
    const response = await fetch('/api/knowledge/personal/search-preview', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tenant-ID': identity.tenant, 'X-User-ID': identity.user},
      body: JSON.stringify({query, limit: 10}),
    });
    return {status: response.status, body: await response.json()};
  }, {query, identity});
}

async function personalDocuments(page, identity) {
  return page.evaluate(async identity => {
    const response = await fetch('/api/knowledge/personal/documents?limit=100', {
      headers: {'X-Tenant-ID': identity.tenant, 'X-User-ID': identity.user},
    });
    return {status: response.status, body: await response.json()};
  }, identity);
}

async function personalJob(page, jobId, identity) {
  return page.evaluate(async ({jobId, identity}) => {
    const response = await fetch(`/api/knowledge/jobs/${encodeURIComponent(jobId)}`, {
      headers: {'X-Tenant-ID': identity.tenant, 'X-User-ID': identity.user},
    });
    return {status: response.status, body: await response.json()};
  }, {jobId, identity});
}

test('E2E-KNOWLEDGE-001 personal knowledge accumulates, deduplicates, edits metadata, and deletes through real APIs', async ({ page, browserFailures }, testInfo) => {
  browserFailures.allowRequestFailed({ method: 'GET', pathname: '/api/knowledge/personal/jobs/events', errorText: /ERR_ABORTED/i });
  const identity = await openPersonalKnowledge(page, testInfo);
  const prefix = `knowledge-${testInfo.workerIndex}-${Date.now()}`;
  const first = `${prefix}-first.txt`;
  const second = `${prefix}-second.txt`;
  const removed = `${prefix}-remove.txt`;
  const uniqueFact = `CMP-UNIQUE-${prefix}`;
  let firstDocumentId;
  let secondDocumentId;

  await test.step('multi-select upload has shared metadata and a repeated filesystem selection is deduplicated', async () => {
    const firstPath = testInfo.outputPath(first);
    const secondPath = testInfo.outputPath(second);
    const removedPath = testInfo.outputPath(removed);
    await fs.writeFile(firstPath, `${uniqueFact} first document`);
    await fs.writeFile(secondPath, `${uniqueFact} second document`);
    await fs.writeFile(removedPath, 'this real temporary file must be removed before upload');
    const stableTime = new Date(1_000);
    await fs.utimes(firstPath, stableTime, stableTime);
    await openUpload(page);
    await page.locator('#knowledgeUploadStep').selectOption('CMP');
    await page.locator('#knowledgeUploadEquipment').fill('CMP-17, CMP-18');
    await page.locator('#knowledgeUploadEffectiveDate').fill('2026-08-30');
    await page.locator('#knowledgeUploadTags').fill('spc, 复核');
    await page.locator('#knowledgeUploadFile').setInputFiles([firstPath, removedPath]);
    await page.locator('#knowledgeUploadFile').setInputFiles([secondPath, firstPath]);
    await expect(page.locator('#knowledgeUploadQueue .knowledge-upload-item')).toHaveCount(3);
    await page.locator(`button[aria-label="移除 ${removed}"]`).click();
    await expect(page.locator('#knowledgeUploadQueue .knowledge-upload-item')).toHaveCount(2);
    const uploaded = page.waitForResponse(response => response.url().endsWith('/api/knowledge/personal/documents') && response.request().method() === 'POST' && response.status() === 202);
    await page.locator('#confirmKnowledgeUpload').click();
    await uploaded;
    await expect(page.locator('#knowledgeUploadDialog')).toBeHidden();
  });

  await test.step('real background jobs reach ready and FTS returns both documents', async () => {
    await waitForDocumentStatus(page, first, /可检索/);
    await waitForDocumentStatus(page, second, /可检索/);
    const result = await preview(page, uniqueFact, identity);
    expect(result.status).toBe(200);
    expect(result.body.count).toBe(2);
    const documents = await personalDocuments(page, identity);
    expect(documents.status).toBe(200);
    expect(documents.body.items).toHaveLength(2);
    expect(documents.body.items.map(item => item.filename)).toEqual(expect.arrayContaining([first, second]));
    expect(documents.body.items.map(item => item.filename)).not.toContain(removed);
    const firstDocument = documents.body.items.find(item => item.filename === first);
    const secondDocument = documents.body.items.find(item => item.filename === second);
    expect(firstDocument).toEqual(expect.objectContaining({process_steps: ['CMP'], equipment_ids: ['CMP-17', 'CMP-18'], effective_date: '2026-08-30', tags: ['spc', '复核'], tags_source: 'user'}));
    expect(secondDocument).toEqual(expect.objectContaining({process_steps: ['CMP'], equipment_ids: ['CMP-17', 'CMP-18'], effective_date: '2026-08-30', tags: ['spc', '复核'], tags_source: 'user'}));
    firstDocumentId = firstDocument.document_id;
    secondDocumentId = secondDocument.document_id;
    expect(result.body.results.map(item => item.document_id)).toEqual(expect.arrayContaining([firstDocumentId, secondDocumentId]));
  });

  await test.step('metadata update is persisted for the selected document', async () => {
    const firstItem = await waitForDocumentStatus(page, first, /可检索/);
    await firstItem.click();
    await expect(page.locator('#knowledgeContent')).toContainText(uniqueFact);
    await page.locator('#editPersonalKnowledge').click();
    await page.locator('#personalKnowledgeMetadataTitle').fill('CMP 个人知识重命名');
    await page.locator('#personalKnowledgeMetadataStep').selectOption('CMP');
    await page.locator('#personalKnowledgeMetadataEquipment').fill('CMP-19');
    await page.locator('#personalKnowledgeMetadataEffectiveDate').fill('2026-08-29');
    await page.locator('#personalKnowledgeMetadataTags').fill('spc, 已确认');
    const saved = page.waitForResponse(response => response.url().includes('/api/knowledge/personal/documents/') && response.request().method() === 'PATCH');
    await page.locator('#confirmPersonalKnowledgeMetadata').click();
    expect((await saved).status()).toBe(200);
    await expect(page.locator('#knowledgeTitle')).toHaveText('CMP 个人知识重命名');
    await expect(page.locator('#knowledgeMeta')).toContainText('CMP-19');
    await expect(page.locator('#knowledgeMeta')).toContainText('2026-08-29');
    await expect(page.locator('#knowledgeMeta')).toContainText('#已确认');
  });

  await test.step('a later upload accumulates and real deletion removes its FTS entries', async () => {
    const third = `${prefix}-third.txt`;
    const thirdFact = `removalonly${Date.now()}${Math.random().toString(36).slice(2, 10)}`;
    await openUpload(page);
    await page.locator('#knowledgeUploadFile').setInputFiles({name: third, mimeType: 'text/plain', buffer: Buffer.from(`${thirdFact} third document`)});
    await page.locator('#confirmKnowledgeUpload').click();
    await expect(page.locator('#knowledgeUploadDialog')).toBeHidden();
    const thirdItem = await waitForDocumentStatus(page, third, /可检索/);
    await thirdItem.click();
    const thirdId = await thirdItem.getAttribute('data-personal-document-id');
    browserFailures.allowResponse({method: 'GET', pathname: `/api/knowledge/personal/documents/${thirdId}/content`, status: 404});
    browserFailures.allowConsoleError({errorText: /server responded with a status of 404/i});
    const deleting = page.waitForResponse(response => response.url().includes('/api/knowledge/personal/documents/') && response.request().method() === 'DELETE');
    await page.locator('#deletePersonalKnowledge').click();
    await page.locator('#confirmPersonalKnowledgeDelete').click();
    expect((await deleting).status()).toBe(202);
    await expect.poll(async () => (await preview(page, thirdFact, identity)).body.count, { timeout: 20_000 }).toBe(0);
    await expect(page.locator('[data-personal-document-id]').filter({hasText: third})).toHaveCount(0);
  });
});

test('E2E-KNOWLEDGE-002 failed upload retains only its item for retry and failed processing uses the real retry lifecycle', async ({ page, browserFailures }, testInfo) => {
  browserFailures.allowRequestFailed({ method: 'GET', pathname: '/api/knowledge/personal/jobs/events', errorText: /ERR_ABORTED/i });
  browserFailures.allowResponse({ method: 'POST', pathname: '/api/knowledge/personal/documents', status: 503 });
  browserFailures.allowConsoleError({errorText: /server responded with a status of 503/i});
  const identity = await openPersonalKnowledge(page, testInfo);
  const prefix = `knowledge-failure-${testInfo.workerIndex}-${Date.now()}`;
  const failedUpload = `${prefix}-retry.txt`;
  const laterUpload = `${prefix}-later.txt`;

  await test.step('only the first upload is explicitly failed, later file is real and retry sends only the failed item', async () => {
    let intercepted = false;
    await page.route('**/api/knowledge/personal/documents', async route => {
      if (!intercepted && route.request().method() === 'POST') {
        intercepted = true;
        await route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({detail: 'QA-007 exact expected upload failure'})});
        return;
      }
      await route.continue();
    });
    await openUpload(page);
    await page.locator('#knowledgeUploadFile').setInputFiles([
      {name: failedUpload, mimeType: 'text/plain', buffer: Buffer.from('retry this exact failed upload')},
      {name: laterUpload, mimeType: 'text/plain', buffer: Buffer.from('later file must use the real API')},
    ]);
    await page.locator('#confirmKnowledgeUpload').click();
    await expect(page.locator('#knowledgeUploadDialog')).toBeVisible();
    await expect(page.locator('#knowledgeUploadQueue .knowledge-upload-item')).toHaveCount(1);
    await expect(page.locator('#knowledgeUploadQueue')).toContainText(failedUpload);
    await waitForDocumentStatus(page, laterUpload, /可检索/);
    await page.unroute('**/api/knowledge/personal/documents');
    const retry = page.waitForResponse(response => response.url().endsWith('/api/knowledge/personal/documents') && response.request().method() === 'POST');
    await page.locator('#confirmKnowledgeUpload').click();
    expect((await retry).status()).toBe(202);
    await expect(page.locator('#knowledgeUploadDialog')).toBeHidden();
    await waitForDocumentStatus(page, failedUpload, /可检索/);
  });

  await test.step('empty text fails naturally and the UI retry creates a real 202 attempt', async () => {
    const empty = `${prefix}-empty.txt`;
    await openUpload(page);
    await page.locator('#knowledgeUploadFile').setInputFiles({name: empty, mimeType: 'text/plain', buffer: Buffer.from(' \n\t ')});
    const initial = page.waitForResponse(response => response.url().endsWith('/api/knowledge/personal/documents') && response.request().method() === 'POST');
    await page.locator('#confirmKnowledgeUpload').click();
    const initialPayload = await (await initial).json();
    await expect(page.locator('#knowledgeUploadDialog')).toBeHidden();
    const emptyItem = await waitForDocumentStatus(page, empty, /处理失败/);
    await emptyItem.click();
    await expect(page.locator('#retryPersonalKnowledge')).toBeVisible();
    const retry = page.waitForResponse(response => /\/api\/knowledge\/personal\/documents\/[^/]+\/retry$/.test(new URL(response.url()).pathname) && response.request().method() === 'POST');
    await page.locator('#retryPersonalKnowledge').click();
    const retryResponse = await retry;
    expect(retryResponse.status()).toBe(202);
    const retryPayload = await retryResponse.json();
    expect(retryPayload.document_id).toBe(initialPayload.document_id);
    await expect.poll(async () => (await personalJob(page, retryPayload.job_id, identity)).body, { timeout: 20_000 }).toEqual(expect.objectContaining({attempt: 2, status: 'failed', error: expect.objectContaining({error_code: 'INVALID_FILE_CONTENT'})}));
  });
});
