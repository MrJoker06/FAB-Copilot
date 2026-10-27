const { test, expect } = require("./support/fixture");

const IDENTITY = {
  tenant: "qa009-journey",
  user: "qa009-user",
};
const SOURCE_SESSION = "qa009-sources-session";

async function open(page, identity = IDENTITY, session = "") {
  await page.addInitScript(
    (value) => {
      localStorage.setItem("fabInsightTenantId", value.tenant);
      localStorage.setItem("fabInsightUserId", value.user);
      if (value.session)
        localStorage.setItem("fabInsightSessionId", value.session);
    },
    { ...identity, session },
  );
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-app-ready", "true");
}
async function restoreSources(page) {
  await page.evaluate(
    (id) => localStorage.setItem("fabInsightSessionId", id),
    SOURCE_SESSION,
  );
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-app-ready", "true");
  return page.locator(".source-list");
}

async function noOverflow(page) {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
}

test(
  "E2E-JOURNEY-001 desktop session lifecycle persists, restores, and deletes through real APIs",
  async ({ page, request }, testInfo) => {
    const identity = {
    tenant: `qa009-life-${testInfo.workerIndex}`,
    user: `qa009-user-${testInfo.workerIndex}`,
    };
    await open(page, identity);
    const ids = [];
  for (const question of [
    "QA009 first persisted session",
    "QA009 second persisted session",
  ]) {
    if (ids.length) {
      const created = page.waitForResponse(
        (r) => r.url().endsWith("/api/sessions") && r.request().method() === "POST",
      );
      await page.locator("#clearChat").click();
      const response = await created;
      expect(response.status()).toBe(200);
      const nextSessionId = (await response.json()).session_id;
      expect(nextSessionId).not.toBe(ids.at(-1));
      await expect
        .poll(() => page.evaluate(() => localStorage.getItem("fabInsightSessionId")))
        .toBe(nextSessionId);
      await expect(page.locator("#chatMessages")).toContainText("已创建新会话。");
    }
    const activeSessionId = await page.evaluate(
      () => localStorage.getItem("fabInsightSessionId"),
    );
    const stream = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/chat/stream") && r.request().method() === "POST",
    );
    await page.locator("#chatInput").fill(question);
    await page.locator("#sendButton").click();
    const streamed = await stream;
    expect(streamed.status()).toBe(200);
    expect(streamed.request().postDataJSON().session_id).toBe(activeSessionId);
    await expect(page.locator("#sendButton")).toBeEnabled();
    ids.push(
      await page.evaluate(() => localStorage.getItem("fabInsightSessionId")),
    );
  }
  expect(new Set(ids).size).toBe(2);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-app-ready", "true");
  await expect(page.locator("#chatMessages")).toContainText(
    "QA009 second persisted session",
  );
  await page.locator("#sessionHistoryButton").click();
  const current = page.locator(`[data-library-session-id="${ids[1]}"]`);
  await current.click();
  await page.locator("#renameLibrarySession").click();
  await page.locator("#sessionRenameInput").fill("QA009 renamed session");
  const rename = page.waitForResponse(
    (r) =>
      r.url().includes(`/api/sessions/${ids[1]}`) &&
      r.request().method() === "PATCH",
  );
  await page.locator("#confirmSessionRename").click();
  expect((await rename).status()).toBe(200);
  await page.locator("#archiveLibrarySession").click();
  await page.locator('[data-session-filter="archived"]').click();
  await expect(current).toBeVisible();
  await current.click();
  await page.locator("#archiveLibrarySession").click();
  await page.locator('[data-session-filter="active"]').click();
  await expect(current).toBeVisible();
  await current.click();
  await expect(page.locator("#continueLibrarySession")).toBeVisible();
  await page.locator("#continueLibrarySession").click();
  await expect(page.locator("#chatMessages")).toContainText(
    "QA009 second persisted session",
  );
  await page.locator("#sessionHistoryButton").click();
  await page.locator("#sessionBatchManage").click();
  for (const id of ids)
    await page
      .locator(`[data-library-session-id="${id}"] input[type="checkbox"]`)
      .check();
  const bulk = page.waitForResponse(
    (r) =>
      r.url().endsWith("/api/sessions/bulk-delete") &&
      r.request().method() === "POST",
  );
  await page.locator("#deleteSelectedSessions").click();
  await page.locator("#confirmSessionDelete").click();
  const response = await bulk;
  expect(response.status()).toBe(200);
    expect((await response.json()).deleted_count).toBe(2);
    for (const id of ids) {
      const missing = await request.get(`/api/sessions/${id}`, {
        headers: {
          "X-Tenant-ID": identity.tenant,
          "X-User-ID": identity.user,
        },
      });
      expect(missing.status()).toBe(404);
    }
  },
);

test(
  "E2E-JOURNEY-002 desktop source groups, trace, safe copy and all source navigation work",
  async ({ page }) => {
    await open(page, IDENTITY, SOURCE_SESSION);
    let sources = page.locator(".source-list");
  await expect(sources).not.toHaveAttribute("open", "");
  await sources.locator("summary").click();
  await expect(sources.locator(".source-group")).toHaveCount(3);
  for (const title of [
    "QA009 个人 CVD 复核笔记",
    "QA009 CVD 工厂 SOP",
    "QA009 CVD 历史案例",
  ])
    await expect(sources).toContainText(title);
  expect(await sources.locator("[data-personal-chunk]").count()).toBe(2);
  expect(await sources.locator("[data-knowledge-chunk]").count()).toBe(2);
  await expect(page.locator(".analysis-trace")).toContainText("query_metrics");
  await expect(page.locator(".analysis-trace")).toContainText("qa009-tr");
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.locator(".copy-answer").click();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toContain("QA009 CVD 复核完成");
  for (const id of [
    "qa009-personal-document",
    "qa009-personal-chunk-1",
    "QA009-P-1",
    "QA009-CVD-CASE",
  ])
    expect(copied).not.toContain(id);
  const personal = page.waitForResponse((r) =>
    r.url().includes("/api/knowledge/personal/chunks/qa009-personal-chunk-1"),
  );
  await sources
    .locator('[data-personal-chunk="qa009-personal-chunk-1"]')
    .click();
  expect((await personal).status()).toBe(200);
  await expect(page.locator("#knowledgeTitle")).toContainText(
    "QA009 个人 CVD 复核笔记",
  );
  sources = await restoreSources(page);
  await sources.locator("summary").click();
  const factory = page.waitForResponse((r) =>
    r.url().endsWith("/api/knowledge/chunks/900901"),
  );
  await sources.locator('[data-knowledge-chunk="900901"]').click();
  expect((await factory).status()).toBe(200);
  await expect(page.locator("#knowledgeTitle")).toContainText(
    "QA009 CVD 工厂 SOP",
  );
  sources = await restoreSources(page);
  await sources.locator("summary").click();
  const item = sources.locator('[data-case-id="QA009-CVD-CASE"]');
  const caseResponse = page.waitForResponse((r) =>
    r.url().endsWith("/api/cases/QA009-CVD-CASE"),
  );
    await item.click();
    expect((await caseResponse).status()).toBe(200);
    await expect(page.locator("#caseTitle")).toContainText(
      "QA009 CVD 历史案例",
    );
  },
);

test(
  "E2E-JOURNEY-003 desktop cross-view uses dated dashboard, capability, knowledge and case APIs",
  async ({ page }) => {
    await open(page);
    await page.locator("#startDate").fill("2026-06-01");
  await page.locator("#endDate").fill("2026-06-30");
  const dashboard = page.waitForResponse(
    (r) =>
      r.url().includes("/api/reports/dashboard") &&
      r.url().includes("start=2026-06-01"),
  );
  await page.locator('#dateForm button[type="submit"]').click();
  expect((await dashboard).status()).toBe(200);
  await noOverflow(page);
  const initialCapability = page.waitForResponse(
    (r) =>
      r.url().includes("/api/reports/capability") &&
      !r.url().includes("process_step=ETCH"),
  );
  const capability = page.waitForResponse(
    (r) =>
      r.url().includes("/api/reports/capability") &&
      r.url().includes("process_step=ETCH"),
  );
  await page.locator('[data-view="capability"]').click();
  const initialCapabilityResponse = await initialCapability;
  expect(initialCapabilityResponse.status()).toBe(200);
  await initialCapabilityResponse.finished();
  await expect(page.locator("#capabilityBody").locator("xpath=..")).not.toHaveAttribute(
    "aria-busy",
    "true",
  );
  await page.locator('#stepSelector [data-step="ETCH"]').click();
  expect((await capability).status()).toBe(200);
  await expect(page.locator("#capabilityView")).toContainText(/ETCH|刻蚀/);
  await noOverflow(page);
  const index = page.waitForResponse((r) =>
    r.url().endsWith("/api/knowledge/documents"),
  );
  await page.locator('[data-view="knowledge"]').click();
  expect((await index).status()).toBe(200);
  const chunk = page.locator("[data-knowledge-chunk]").first();
  const id = await chunk.getAttribute("data-knowledge-chunk");
  const detail = page.waitForResponse((r) =>
    r.url().endsWith(`/api/knowledge/chunks/${id}`),
  );
  await chunk.click();
  expect((await detail).status()).toBe(200);
  await expect(page.locator("#knowledgeContent")).not.toBeEmpty();
  await noOverflow(page);
  const cases = page.waitForResponse((r) => r.url().endsWith("/api/cases"));
  await page.locator('[data-view="cases"]').click();
  expect((await cases).status()).toBe(200);
  const caseItem = page.locator("[data-case-id]").first();
  const caseId = await caseItem.getAttribute("data-case-id");
  const detailCase = page.waitForResponse((r) =>
    r.url().endsWith(`/api/cases/${caseId}`),
  );
    await caseItem.click();
    expect((await detailCase).status()).toBe(200);
    await expect(page.locator("#caseContent")).not.toBeEmpty();
    await noOverflow(page);
  },
);
