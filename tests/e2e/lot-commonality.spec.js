const { test, expect } = require('./support/fixture');
const AxeBuilder = require('@axe-core/playwright').default;

const CHAMBER_B = 'ch:GATE/ETCH:ETCH-07/CH-B';
const ANALYSES = '**/api/lot-commonality/analyses';

async function ready(page, view = 'commonality') {
  await page.goto(view ? `/?view=${view}` : '/');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  await expect(page.locator('html')).toHaveAttribute('data-commonality-ready', 'true');
}

async function accessible(page) {
  const result = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  expect(result.violations, JSON.stringify(result.violations, null, 2)).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

function samplePaintedViews() {
  window.paintedViews = [];
  function sample() {
    if (document.styleSheets.length) {
      const active = [...document.querySelectorAll('.view.active')].filter(node => getComputedStyle(node).display !== 'none').map(node => node.id);
      for (const name of active) if (!window.paintedViews.includes(name)) window.paintedViews.push(name);
    }
    requestAnimationFrame(sample);
  }
  requestAnimationFrame(sample);
}

async function loadSample(page) {
  await page.locator('#loadCommonalitySample').click();
  await expect(page.locator('#commonalityStatus')).toContainText('已载入合成样例结果');
  await expect(page.locator('#commonalitySampleBadge')).toBeVisible();
  await expect(page.locator('#commonalityResults')).toContainText('合成样例');
}

test('commonality entry sits under basic reports and survives refresh and browser history', async ({page}) => {
  await ready(page, 'reports');
  await expect(page.locator('.sidebar > .nav-item').nth(1)).toHaveText('◫相关性分析');
  await page.locator('[data-view="commonality"]').click();
  await expect(page.locator('#commonalityView')).toBeVisible();
  await expect(page.locator('#reportsView')).toBeHidden();
  await expect(page.locator('[data-view="commonality"]')).toHaveAttribute('aria-current', 'page');
  await expect(page).toHaveURL(/\/\?view=commonality$/);
  await page.locator('[data-group-field="text"]').first().fill('LOT-SECRET-1\nLOT-SECRET-2');
  expect(page.url()).not.toContain('LOT-SECRET');

  await page.addInitScript(samplePaintedViews);
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
  await expect(page.locator('#commonalityView')).toBeVisible();
  await expect(page.locator('#dashboardView')).toBeHidden();
  expect(await page.evaluate(() => window.paintedViews)).toEqual(['commonalityView']);

  await page.locator('[data-view="procedures"]').click();
  await expect(page).toHaveURL(/\/\?view=procedures$/);
  await page.goBack();
  await expect(page).toHaveURL(/\/\?view=commonality$/);
  await expect(page.locator('#commonalityView')).toBeVisible();
  await expect(page.locator('#proceduresView')).toBeHidden();
  await expect(page.locator('[data-view="commonality"]')).toHaveAttribute('aria-current', 'page');
  await page.goBack();
  await expect(page).toHaveURL(/\/\?view=reports$/);
  await expect(page.locator('#reportsView')).toBeVisible();
  await page.goForward();
  await expect(page.locator('#commonalityView')).toBeVisible();
  await expect(page.locator('#reportsView')).toBeHidden();
  expect(await page.evaluate(() => window.paintedViews)).not.toContain('dashboardView');
});

test('commonality is the first visible view before the application script loads', async ({page}) => {
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  await page.route('**/static/app.js?*', async route => { await blocked; await route.continue(); });
  try {
    await page.goto('/?view=commonality', {waitUntil: 'commit'});
    await expect(page.locator('#commonalityView')).toBeVisible();
    await expect(page.locator('#dashboardView')).toBeHidden();
    await expect(page.locator('[data-view="commonality"]')).toHaveAttribute('aria-current', 'page');
  } finally { release(); }
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
});

test('group editor deduplicates pasted columns and marks cross-group lots', async ({page}) => {
  await ready(page);
  const main = page.locator('[data-group-key]').first();
  await expect(main.locator('[data-group-field="name"]')).toHaveValue('本次异常');
  await main.locator('textarea').fill(' A \nB\tC,A\n\n B ');
  await expect(main.locator('[data-group-summary]')).toHaveText('输入 5 个，去重后 3 个，重复：A、B');
  await page.locator('#commonalityNewGroupRole').selectOption('historical_abnormal');
  await page.locator('#addCommonalityGroup').click();
  const second = page.locator('[data-group-key]').nth(1);
  await expect(second.locator('[data-group-field="name"]')).toHaveValue('历史异常');
  await second.locator('textarea').fill('B\nJ');
  await expect(main.locator('[data-group-overlap]')).toHaveText('跨组交集：B（同在 历史异常）');
  await expect(second.locator('[data-group-overlap]')).toHaveText('跨组交集：B（同在 本次异常）');
  await expect(page.locator('#commonalityScopeSummary')).toContainText('加工时间：全部 · 截止：不设截止 · 时区 Asia/Shanghai');
  await page.locator('input[name="commonalityCutoffMode"][value="operation"]').check();
  await page.locator('#commonalityCutoffOperation').fill('GATE/ETCH');
  await expect(page.locator('#commonalityScopeSummary')).toContainText('截止工序 GATE/ETCH（含该过站）');
  await second.locator('[data-remove-group]').click();
  await expect(page.locator('[data-group-key]')).toHaveCount(1);
  await expect(main.locator('[data-group-overlap]')).toBeHidden();
  await accessible(page);
});

test('an unavailable query service is reported as a failure and shows no result', async ({page, browserFailures}) => {
  browserFailures.allowConsoleError({errorText: /status of 404/});
  let body = null;
  await page.route(ANALYSES, route => {
    body = route.request().postDataJSON();
    return route.fulfill({status: 404, json: {error_code: 'NOT_FOUND', detail: 'Not Found', request_id: 'req_e2e', retryable: false}});
  });
  await ready(page);
  await page.locator('[data-group-key] textarea').first().fill('A\nB\nA');
  await page.locator('[data-commonality-dimension][value="recipe"]').uncheck();
  await page.locator('#commonalityDescription').fill('刻蚀后 CD 偏大');
  await page.locator('#runCommonality').click();
  await expect(page.locator('#commonalityStatus')).toContainText('相关性分析查询服务尚未接入');
  await expect(page.locator('#commonalityStatus')).toHaveAttribute('data-tone', 'error');
  await expect(page.locator('#commonalityResults')).toBeHidden();
  await expect(page.locator('#commonalitySampleBadge')).toBeHidden();
  expect(body).toEqual({
    groups: [{group_id: 'main', name: '本次异常', role: 'primary', lot_ids: ['A', 'B', 'A']}],
    dimensions: ['equipment', 'chamber', 'path_adjacent'],
    scope: {time_range: null, cutoff: null}, timezone: 'Asia/Shanghai', description: '刻蚀后 CD 偏大',
  });
  await page.screenshot({path: 'runtime/quality/lot-commonality-service-missing.png', fullPage: true});
});

test('an older query that returns late never replaces the newer failed query', async ({page, browserFailures}) => {
  browserFailures.allowResponse({method: 'POST', pathname: '/api/lot-commonality/analyses', status: 502});
  browserFailures.allowConsoleError({errorText: /status of 502/});
  const sample = await (await page.request.get('/display_mock_data/lot_commonality/contract_examples.json')).json();
  let releaseFirst;
  const firstHeld = new Promise(resolve => { releaseFirst = resolve; });
  let calls = 0;
  await page.route(ANALYSES, async route => {
    calls += 1;
    if (calls === 1) {
      await firstHeld;
      return route.fulfill({status: 200, json: sample.examples.create_analysis.response});
    }
    return route.fulfill({status: 502, json: sample.errors.source_failed.response});
  });
  await ready(page);
  const lots = page.locator('[data-group-key] textarea').first();
  await lots.fill('A\nB');
  await page.locator('#runCommonality').click();
  await expect(page.locator('#commonalityStatus')).toContainText('正在查询');
  await lots.fill('A\nC');
  await page.locator('#runCommonality').click();
  await expect(page.locator('#commonalityStatus')).toContainText('数据来源失败（DATA_SOURCE_FAILED）');
  releaseFirst();
  await expect.poll(() => calls).toBe(2);
  await page.waitForTimeout(300);
  await expect(page.locator('#commonalityStatus')).toContainText('数据来源失败（DATA_SOURCE_FAILED）');
  await expect(page.locator('#commonalityResults')).toBeHidden();
});

test('edited input marks the sample result as the previous query and a failed query keeps that label', async ({page, browserFailures}) => {
  browserFailures.allowResponse({method: 'POST', pathname: '/api/lot-commonality/analyses', status: 502});
  browserFailures.allowConsoleError({errorText: /status of 502/});
  await page.route(ANALYSES, route => route.fulfill({status: 502, json: {error_code: 'DATA_SOURCE_FAILED', detail: '数据来源失败，不能将其当作无数据或切换到模拟来源。', request_id: 'req_e2e', retryable: false}}));
  await ready(page);
  await loadSample(page);
  const stale = page.locator('#commonalityResults [data-lc-stale]');
  await expect(stale).toBeHidden();
  await page.locator('[data-group-key] textarea').first().fill('A\nB');
  await expect(stale).toBeVisible();
  await expect(stale).toHaveText('上次查询');
  await page.locator('#runCommonality').click();
  await expect(page.locator('#commonalityStatus')).toContainText('数据来源失败（DATA_SOURCE_FAILED）');
  await expect(page.locator('#commonalityStatus')).toContainText('请求编号 req_e2e');
  await expect(stale).toBeVisible();
  await expect(page.locator('#commonalityResults')).toContainText('合成样例');
});

test('sample flow with the assistant closed: CH-B hit 6 to split chambers of B and unknown 1 to H missing chamber', async ({page}) => {
  await ready(page);
  await page.locator('#collapseAgent').click();
  await expect(page.locator('.app-shell')).toHaveClass(/agent-collapsed/);
  await expect(page.locator('.agent-panel')).toBeHidden();
  await loadSample(page);

  const results = page.locator('#commonalityResults');
  await expect(results.locator('.lc-receipt').first()).toContainText('输入 9 个 · 唯一 8 个 · 重复：A');
  await expect(results.locator('.lc-receipt').first()).toContainText('资料不足 1 H（字段缺失、顺序缺失）');
  await expect(results).toContainText('跨组交集：B（本次异常、同期异常） · 合并后唯一 lot：10');
  await expect(results.locator('thead .lc-group-col')).toHaveText(['本次异常', '同期异常', '合并（union）']);
  const row = page.locator(`[data-candidate-row="${CHAMBER_B}"]`);
  await expect(row).toContainText('部分共有');
  await expect(row.locator('[data-group-id="main"][data-status="hit"]')).toHaveText('6');
  await expect(row.locator('[data-group-id="concurrent"][data-status="miss"]')).toHaveText('2');
  await expect(row.locator('[data-group-id="union"][data-status="hit"]')).toHaveText('6');
  await page.locator('#commonalityShareFilter').selectOption('all');
  await expect(results.locator('[data-candidate-row]')).toHaveCount(3);
  await page.locator('#commonalityShareFilter').selectOption('');
  await page.locator('#commonalityDimensionFilter').selectOption('chamber');
  await expect(results.locator('[data-candidate-row]')).toHaveCount(2);

  await row.locator('[data-group-id="main"][data-status="hit"]').click();
  const members = page.locator('#commonalityMembers');
  await expect(members.locator('[data-member-lot]')).toHaveText(['A', 'B', 'C', 'D', 'E', 'F']);
  await expect(members).toContainText('命中 6 · 确认未命中 1 · 未知 1 · 分母 8');
  await expect(members).toContainText('实际判定范围：任意过站（any_pass）');
  await expect(members).toContainText('2026-11-10 08:30:00+08:00 至 2026-11-10 13:30:00+08:00（Asia/Shanghai）');
  await expect(members.locator('.lc-sample-badge')).toBeVisible();
  await members.locator('[data-member-lot="B"]').click();

  const records = page.locator('#commonalityRecords');
  const split = records.locator('[data-matrix-lot="B"] [data-record-ref="pass:B-02"]');
  await expect(split).toContainText('CH-A · 12 片');
  await expect(split).toContainText('CH-B · 13 片');
  await expect(split).toContainText('已分配 25 片');
  await records.locator('[data-matrix-lot="B"] .lc-wafers summary').first().click();
  await expect(records.locator('[data-matrix-lot="B"] .lc-wafers').first()).toContainText('W01、W02');
  await expect(records.locator('[data-record-row="pass:B-02"]')).toHaveClass(/lc-selected/);
  await expect(records.locator('[data-record-row="pass:B-02"]')).toContainText('fx:B-02-CH-A、fx:B-02-CH-B');
  await expect(records.locator('.lc-sample-badge')).toBeVisible();
  await page.screenshot({path: 'runtime/quality/lot-commonality-chamber-b-split.png', fullPage: true});
  await results.screenshot({path: 'runtime/quality/lot-commonality-results-panel.png'});
  await records.screenshot({path: 'runtime/quality/lot-commonality-chamber-b-records.png'});
  await accessible(page);

  await records.locator('[data-lc-back="members"]').click();
  await expect(records).toBeHidden();
  await expect(members.locator('[data-member-lot="B"]')).toBeFocused();
  await members.locator('[data-lc-back="results"]').click();
  await expect(members).toBeHidden();
  await expect(row.locator('[data-group-id="main"][data-status="hit"]')).toBeFocused();
  const unknown = row.locator('[data-group-id="main"][data-status="unknown"]');
  await expect(unknown).toHaveText('1');
  await unknown.click();
  await expect(members.locator('[data-member-lot]')).toHaveText(['H']);
  await expect(members).toContainText('未知原因：字段缺失（chamber）');
  await expect(members).toContainText('命中 6 · 确认未命中 1 · 未知 1 · 分母 8');
  await members.locator('[data-member-lot="H"]').click();
  const missing = records.locator('[data-matrix-lot="H"] [data-record-ref="pass:H-02"]');
  await expect(missing).toContainText('腔室缺失（来源未给出）');
  await expect(missing).toContainText('缺字段：pass_seq、track_in_at、chamber');
  await expect(records.locator('[data-coverage-lot="H"]')).toContainText('顺序缺口：pass:H-02、pass:H-03 缺少来源序号');
  await expect(records.locator('[data-record-row="pass:H-02"]')).toContainText('时间缺失');
  await records.locator('[data-records-view="path"]').click();
  await expect(records.locator('[data-path-lot="H"] .lc-path-unknown')).toContainText('顺序未知');
  await expect(records.locator('[data-path-lot="H"] .lc-path-unknown')).toContainText('GATE/ETCH · ETCH-07');
  await page.screenshot({path: 'runtime/quality/lot-commonality-h-missing-chamber.png', fullPage: true});
  await members.screenshot({path: 'runtime/quality/lot-commonality-h-members.png'});
  await records.screenshot({path: 'runtime/quality/lot-commonality-h-records.png'});
});

test('rework combination uses the same-pass sample and pages, unmatched queries say so', async ({page}) => {
  await ready(page);
  await loadSample(page);
  await page.locator(`[data-candidate-row="${CHAMBER_B}"] [data-group-id="main"][data-status="hit"]`).click();
  const members = page.locator('#commonalityMembers');
  await expect(members.locator('[data-member-lot]')).toHaveCount(6);
  await members.locator('[data-member-control="status"]').selectOption('');
  await expect(members.locator('[data-member-lot]')).toHaveCount(8);
  await expect(members).toContainText('未命中依据：为其他值');
  await members.locator('[data-member-control="rework"]').check();
  await expect(members).toContainText('命中 1 · 确认未命中 7 · 未知 0 · 分母 8');
  await expect(members).toContainText('实际判定范围：同一次过站（same_pass）');
  await members.locator('[data-member-lot="E"]').click();
  await expect(page.locator('#commonalityRecords [data-record-ref="pass:E-03"]').first()).toContainText('返工（返工自 pass:E-02）');
  await members.locator('input[name="commonalityMatchScope"][value="any_pass"]').check();
  await expect(members.locator('.lc-error')).toHaveText('样例未包含该查询');

  await members.locator('[data-lc-back="results"]').click();
  await page.locator('[data-candidate-row="path:GATE/ETCH>GATE/METROLOGY"] [data-group-id="main"][data-status="hit"]').click();
  await expect(members.locator('.lc-error')).toHaveText('样例未包含该查询');
  await members.locator('[data-member-control="status"]').selectOption('');
  await members.locator('[data-member-control="limit"]').selectOption('4');
  await expect(members.locator('[data-member-lot]')).toHaveText(['A', 'B', 'C', 'D']);
  await members.locator('[data-member-page="next"]').click();
  await expect(members.locator('[data-member-lot]')).toHaveText(['E', 'F', 'G', 'H']);
  await expect(members).toContainText('未命中依据：下一站不是目标站');
  await expect(members).toContainText('未知原因：顺序缺失');
  await expect(members.locator('[data-member-page="next"]')).toBeDisabled();
});
