const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');
const AxeBuilder = require('@axe-core/playwright').default;
const { test, expect } = require('./support/fixture');

// The browser-test server serves a disposable copy of this reference database, so
// reading it directly gives expectations independent of the analysis code.
const REFERENCE_DB = path.resolve(__dirname, '../../data/departments/manufacturing_operations.db');
const ANALYSES = '/api/lot-commonality/analyses';
const MISSING_LOT = 'LCA-E2E-NOT-FOUND';
const TENANT_KEY = 'fabInsightTenantId';
const USER_KEY = 'fabInsightUserId';

function readOracle() {
  const db = new DatabaseSync(REFERENCE_DB, { readOnly: true });
  try {
    const lots = db.prepare('SELECT DISTINCT lot_id FROM process_runs ORDER BY lot_id LIMIT 60').all().map(row => row.lot_id);
    const runsOf = db.prepare(`SELECT run_id, lot_id, operation_seq, layer_name || '/' || process_step AS operation_key,
      equipment_id, chamber, recipe, run_time, queue_hours, rework_flag FROM process_runs WHERE lot_id = ? ORDER BY operation_seq`);
    for (let start = 0; start + 6 <= lots.length; start += 6) {
      const main = lots.slice(start, start + 4), reference = lots.slice(start + 4, start + 6);
      const runs = new Map([...main, ...reference].map(lot => [lot, runsOf.all(lot)]));
      const hitsOf = (group, op, eq) => group.filter(lot => runs.get(lot).some(run => run.operation_key === op && run.equipment_id === eq));
      const pairs = new Set([...runs.get(main[0]), ...runs.get(main[1])].map(run => `${run.operation_key}\u0000${run.equipment_id}`));
      for (const pair of [...pairs].sort()) {
        const [op, eq] = pair.split('\u0000');
        const hits = hitsOf(main, op, eq);
        if (hits.length >= 2 && hits.length < main.length) {
          return { main, reference, runs, op, eq, candidateId: `eq:${op}:${eq}`, mainHits: hits, referenceHits: hitsOf(reference, op, eq) };
        }
      }
    }
    throw new Error('reference database has no partially shared equipment among the sampled lots');
  } finally { db.close(); }
}

const oracle = readOracle();
const mainMisses = oracle.main.filter(lot => !oracle.mainHits.includes(lot));
const referenceMisses = oracle.reference.filter(lot => !oracle.referenceHits.includes(lot));

async function ready(page) {
  await page.goto('/?view=commonality');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  await expect(page.locator('html')).toHaveAttribute('data-commonality-ready', 'true');
}

async function fillGroups(page, main = [...oracle.main, MISSING_LOT], reference = oracle.reference) {
  await page.locator('[data-group-key] textarea').first().fill(main.join('\n'));
  if (reference) {
    await page.locator('#commonalityNewGroupRole').selectOption('normal_reference');
    await page.locator('#addCommonalityGroup').click();
    await page.locator('[data-group-key] textarea').nth(1).fill(reference.join('\n'));
  }
}

async function runReal(page) {
  const response = page.waitForResponse(item => item.url().endsWith(ANALYSES) && item.request().method() === 'POST');
  await page.locator('#runCommonality').click();
  const created = await (await response).json();
  await expect(page.locator('#commonalityStatus')).toContainText('查询完成');
  return created;
}

const row = page => page.locator(`[data-candidate-row="${oracle.candidateId}"]`);
const countButton = (page, group, status) => row(page).locator(`[data-group-id="${group}"][data-status="${status}"]`);
const memberPath = ref => `${ANALYSES}/${ref}/members`;

function expectedRow(run) {
  return [`process_runs:${run.run_id}`, run.lot_id, String(run.operation_seq), run.operation_key, run.equipment_id,
    `${run.chamber}（片数未知）`, run.recipe, `${run.run_time}+08:00`.replace('T', ' '), String(run.queue_hours), run.rework_flag ? '返工自 —' : '否'];
}
async function renderedRows(records) {
  return records.locator('[data-record-row]').evaluateAll(rows => rows.map(node => {
    const cells = [...node.children].map(cell => cell.textContent.trim());
    return [cells[0], cells[2], cells[3], node.children[4].querySelector('small').textContent, cells[5], cells[6], cells[7], cells[8], cells[9], cells[10]];
  }));
}

test('real HTTP query: page counts, members and raw passes equal the reference source', async ({page}) => {
  await ready(page);
  await fillGroups(page);
  const created = await runReal(page);
  expect(created.source.kind).toBe('sqlite');
  await expect(page.locator('#commonalitySampleBadge')).toBeHidden();
  const results = page.locator('#commonalityResults');
  await expect(results).not.toContainText('合成样例');
  await expect(results.locator('[data-receipt-group="main"]')).toContainText('输入 5 个 · 唯一 5 个');
  await expect(results.locator('[data-receipt-group="main"]')).toContainText(`未找到 1 ${MISSING_LOT}（未找到该 lot）`);
  await expect(results.locator('[data-receipt-group="normal"]')).toContainText('可分析 2');

  await expect(countButton(page, 'main', 'hit')).toHaveText(String(oracle.mainHits.length));
  await expect(countButton(page, 'main', 'miss')).toHaveText(String(mainMisses.length));
  await expect(countButton(page, 'main', 'unknown')).toHaveText('1');
  await expect(row(page).locator('.lc-denominator').first()).toHaveText('5');
  await expect(countButton(page, 'normal', 'hit')).toHaveText(String(oracle.referenceHits.length));
  await expect(countButton(page, 'normal', 'miss')).toHaveText(String(referenceMisses.length));
  await expect(countButton(page, 'normal', 'unknown')).toHaveText('0');
  await expect(row(page).locator('.lc-denominator').nth(1)).toHaveText('2');

  await countButton(page, 'main', 'hit').click();
  const members = page.locator('#commonalityMembers');
  await expect(members.locator('[data-member-lot]')).toHaveText(oracle.mainHits);
  await expect(members).toContainText(`命中 ${oracle.mainHits.length} · 确认未命中 ${mainMisses.length} · 未知 1 · 分母 5`);
  await members.locator('[data-member-control="status"]').selectOption('');
  await expect(members.locator('[data-member-lot]')).toHaveText([...oracle.mainHits, ...mainMisses, MISSING_LOT]);
  await expect(members.locator('tbody tr').last()).toContainText('未知原因：未找到该 lot');
  for (const lot of mainMisses) await expect(members.locator('tbody tr', {hasText: lot})).toContainText('未命中依据：');

  for (const lot of oracle.main) await members.locator(`[data-member-select="${lot}"]`).check();
  await members.locator('[data-member-compare]').click();
  const records = page.locator('#commonalityRecords');
  const requested = [...oracle.mainHits, ...mainMisses];
  const expected = requested.flatMap(lot => oracle.runs.get(lot)).map(expectedRow);
  await expect(records.locator('.lc-pager span')).toHaveText(`第 1 页 · 本页 ${Math.min(50, expected.length)} 条 · 共 ${expected.length} 条过站`);
  expect(await renderedRows(records)).toEqual(expected.slice(0, 50));
  for (const lot of oracle.mainHits) {
    await expect(records.locator(`[data-matrix-lot="${lot}"] .lc-value-hit`).first()).toHaveText(`机台 ${oracle.eq}`);
    await expect(records.locator(`[data-matrix-lot="${lot}"] td`).nth(0)).toHaveText('命中');
  }
  for (const lot of mainMisses) await expect(records.locator(`[data-matrix-lot="${lot}"] td`).nth(0)).toHaveText('确认未命中');
  await records.locator('[data-records-page="next"]').click();
  await expect(records.locator('.lc-pager span')).toHaveText(`第 2 页 · 本页 ${expected.length - 50} 条 · 共 ${expected.length} 条过站`);
  expect(await renderedRows(records)).toEqual(expected.slice(50));
  await expect(records.locator('[data-records-page="next"]')).toBeDisabled();
  await page.screenshot({path: 'runtime/quality/lot-commonality-real-records.png', fullPage: true});
});

test('real HTTP limits and scope are reported as failures without a result', async ({page, browserFailures}) => {
  browserFailures.allowConsoleError({errorText: /status of 422/});
  browserFailures.allowConsoleError({errorText: /status of 403/});
  await ready(page);
  await fillGroups(page, Array.from({length: 201}, (_, index) => `LCA-E2E-${String(index).padStart(3, '0')}`), null);
  await page.locator('#runCommonality').click();
  const status = page.locator('#commonalityStatus');
  await expect(status).toContainText('超过分析限额（ANALYSIS_LIMIT_EXCEEDED）');
  await expect(status).toContainText('限额 max_lots_per_group（组 main）：上限 200，实际 201');
  await expect(status).toHaveAttribute('data-tone', 'error');
  await expect(page.locator('#commonalityResults')).toBeHidden();

  await fillGroups(page, oracle.main, null);
  await page.evaluate(key => localStorage.setItem(key, 'lca-e2e-other-tenant'), TENANT_KEY);
  await page.locator('#runCommonality').click();
  await expect(status).toContainText('无权访问请求的数据范围（SCOPE_DENIED）');
  await expect(status).not.toContainText(oracle.main[0]);
  await expect(page.locator('#commonalityResults')).toBeHidden();
});

test('a result the current user can no longer read is marked unavailable until queried again', async ({page, browserFailures}) => {
  browserFailures.allowConsoleError({errorText: /status of 404/});
  await ready(page);
  await fillGroups(page);
  const first = await runReal(page);
  await page.evaluate(key => localStorage.setItem(key, 'lca-e2e-other-user'), USER_KEY);
  await countButton(page, 'main', 'hit').click();
  const members = page.locator('#commonalityMembers');
  await expect(members.locator('.lc-error')).toContainText('结果当前不可读取（RESULT_UNAVAILABLE）');
  await expect(members.locator('.lc-error')).toContainText('该结果已不可读取，请重新查询。');
  await expect(page.locator('#commonalityStatus')).toContainText('该结果已不可读取（已过期、无权访问或所属会话已删除），请重新查询');
  await expect(page.locator('#commonalityResults [data-lc-unavailable]')).toBeVisible();
  await expect(countButton(page, 'main', 'miss')).toBeDisabled();
  await page.locator('#commonalityDimensionFilter').selectOption('equipment');
  await expect(countButton(page, 'main', 'miss')).toBeDisabled();
  const axe = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  expect(axe.violations, JSON.stringify(axe.violations, null, 2)).toEqual([]);

  await page.evaluate(key => localStorage.removeItem(key), USER_KEY);
  const second = await runReal(page);
  expect(second.analysis_ref).not.toBe(first.analysis_ref);
  await expect(page.locator('#commonalityResults [data-lc-unavailable]')).toBeHidden();
  await countButton(page, 'main', 'hit').click();
  await expect(members.locator('[data-member-lot]')).toHaveText(oracle.mainHits);
});

test('a late members response never replaces the newer filter and retry recovers a store outage', async ({page, browserFailures}) => {
  browserFailures.allowConsoleError({errorText: /status of 503/});
  await ready(page);
  await fillGroups(page);
  const created = await runReal(page);
  browserFailures.allowResponse({method: 'POST', pathname: memberPath(created.analysis_ref), status: 503});
  let release;
  const held = new Promise(resolve => { release = resolve; });
  let calls = 0;
  await page.route(`**${memberPath(created.analysis_ref)}`, async route => {
    calls += 1;
    if (calls === 1) { await held; return route.continue(); }
    if (calls === 3) return route.fulfill({status: 503, json: {error_code: 'RESULT_STORE_UNAVAILABLE', detail: '结果库暂不可用。', request_id: 'req_e2e', retryable: true}});
    return route.continue();
  });
  await countButton(page, 'main', 'hit').click();
  const members = page.locator('#commonalityMembers');
  await expect(members.locator('.lc-loading')).toBeVisible();
  await members.locator('[data-member-control="status"]').selectOption('miss');
  await expect(members.locator('[data-member-lot]')).toHaveText(mainMisses);
  release();
  await expect.poll(() => calls).toBe(2);
  await page.waitForTimeout(300);
  await expect(members.locator('[data-member-lot]')).toHaveText(mainMisses);

  await members.locator('[data-member-control="status"]').selectOption('hit');
  await expect(members.locator('.lc-error')).toContainText('结果库暂不可用（RESULT_STORE_UNAVAILABLE）');
  await members.locator('[data-member-retry]').click();
  await expect(members.locator('[data-member-lot]')).toHaveText(oracle.mainHits);
  await expect(page.locator('#commonalityResults [data-lc-unavailable]')).toBeHidden();
});

test('a cursor the server rejects offers the first page again', async ({page, browserFailures}) => {
  browserFailures.allowConsoleError({errorText: /status of 400/});
  await ready(page);
  await fillGroups(page);
  const created = await runReal(page);
  await page.route(`**${memberPath(created.analysis_ref)}`, route => {
    const body = route.request().postDataJSON();
    return route.continue(body.cursor ? {postData: JSON.stringify({...body, cursor: `${body.cursor}x`})} : undefined);
  });
  await countButton(page, 'main', 'hit').click();
  const members = page.locator('#commonalityMembers');
  await members.locator('[data-member-control="status"]').selectOption('');
  await members.locator('[data-member-control="limit"]').selectOption('4');
  await expect(members.locator('[data-member-lot]')).toHaveCount(4);
  await members.locator('[data-member-page="next"]').click();
  await expect(members.locator('.lc-error')).toContainText('分页游标无效（RESULT_CURSOR_INVALID）');
  await expect(members.locator('.lc-error')).toContainText('分页位置已失效，请回到第一页。');
  await members.locator('.lc-error [data-member-page="first"]').click();
  await expect(members.locator('[data-member-lot]')).toHaveText([...oracle.mainHits, ...mainMisses].slice(0, 4));
});

// The local source never truncates or fails mid-read, so this case rewrites a real
// response into the contract's partial shape to check how the page presents it.
test('a partial analysis is flagged and names the lots whose source failed', async ({page}) => {
  await page.route(`**${ANALYSES}`, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    body.status = 'partial';
    const lot = body.groups[0].lot_states.find(item => item.lot_id === oracle.main[0]);
    Object.assign(lot, {state: 'source_failed', reasons: [{code: 'SOURCE_PAGE_FAILED'}]});
    return route.fulfill({response, json: body});
  });
  await ready(page);
  await fillGroups(page);
  await page.locator('#runCommonality').click();
  const status = page.locator('#commonalityStatus');
  await expect(status).toContainText('部分 lot 资料不足，见组回执');
  await expect(status).toHaveAttribute('data-tone', 'warn');
  await expect(page.locator('#commonalityResults .lc-warn-badge', {hasText: '部分返回'})).toBeVisible();
  await expect(page.locator('#commonalityResults [data-receipt-group="main"]')).toContainText(`来源失败 1 ${oracle.main[0]}（来源分页读取失败）`);
});
