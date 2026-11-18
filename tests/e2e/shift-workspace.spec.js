const { test, expect } = require('./support/fixture');
const AxeBuilder = require('@axe-core/playwright').default;

async function ready(page, view = '') {
  await page.goto(view ? `/?view=${view}` : '/');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
}

async function accessible(page) {
  const result = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  expect(result.violations, JSON.stringify(result.violations, null, 2)).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
}

test('duty navigation preserves the original dashboard, folds legacy views and toggles the assistant', async ({page}) => {
  await ready(page);
  await expect(page.locator('.sidebar > .nav-item')).toHaveText(['▥基础报表', '▤SOP&历史case', '↗Autosystem 平台', '◇值班智能助手']);
  await expect(page.locator('#allFunctions')).not.toHaveAttribute('open');
  await expect(page.locator('#dashboardView')).toBeVisible();
  await page.locator('#allFunctions summary').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('[data-view="capability"]')).toBeVisible();
  await page.locator('[data-view="capability"]').click();
  await expect(page.locator('#capabilityView')).toBeVisible();
  await page.locator('#allFunctions summary').click();
  await expect(page.locator('[data-view="knowledge"]')).toBeHidden();
  await page.locator('#focusAgent').click();
  await expect(page.locator('.app-shell')).toHaveClass(/agent-collapsed/);
  await page.locator('#focusAgent').click();
  await expect(page.locator('.agent-panel')).toBeVisible();
  await page.locator('#autosystemLink').click();
  await expect(page.locator('#autosystemView')).toBeVisible();
  await expect(page.locator('#autosystemView')).toContainText('建设中');
  await expect(page.locator('#autosystemLink')).toHaveAttribute('aria-current','page');
  await expect(page.locator('#capabilityView')).toBeHidden();
  await expect(page.locator('#toastRegion')).not.toContainText('地址尚未配置');
  await accessible(page);
  await page.locator('[data-view="reports"]').click();
  await expect(page.locator('#reportsView')).toBeVisible();
  await expect(page.locator('#autosystemView')).toBeHidden();
  await page.route('**/display_mock_data/catalog.json', route => route.fulfill({json:{autosystem_url:'/display_mock_data/reports/spc.html'}}));
  const opened = page.waitForEvent('popup');
  await page.locator('#autosystemLink').click();
  const external = await opened;
  await expect(external.locator('h1')).toHaveText('SPC 趋势报表');
  await expect(page.locator('#reportsView')).toBeVisible();
  await external.close();
});

test('report catalog filters and opens real report pages, with actual recent history', async ({page}) => {
  await ready(page, 'reports');
  await expect(page.locator('.shift-report-card')).toHaveCount(6);
  await expect(page.locator('#reportsView')).not.toContainText('演示');
  await expect(page.locator('[data-report-role]')).toHaveCount(0);
  await page.locator('#shiftReportSearch').fill('不存在的报表');
  await expect(page.locator('#shiftReportCards')).toContainText('没有符合条件的报表');
  await page.locator('#shiftReportSearch').fill('SPC');
  const opened = page.waitForEvent('popup');
  await page.locator('[data-open-report="spc"]').first().click();
  const report = await opened;
  await expect(report.locator('h1')).toHaveText('SPC 趋势报表');
  await expect(report.locator('table')).toContainText('LOT-017');
  await expect(page.locator('#shiftRecentReports')).toContainText('SPC 趋势报表');
  await report.close();
  await accessible(page);
});

test('reports is the first visible view even before the application script loads', async ({page}) => {
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  await page.route('**/static/app.js?*', async route => { await blocked; await route.continue(); });
  try {
    await page.goto('/?view=reports', {waitUntil:'commit'});
    await expect(page.locator('#reportsView')).toBeVisible();
    await expect(page.locator('#dashboardView')).toBeHidden();
    await expect(page.locator('[data-view="reports"]')).toHaveAttribute('aria-current','page');
    await expect(page.locator('html')).not.toHaveAttribute('data-app-ready','true');
    await expect(page.locator('#shiftReportsStatus')).toContainText('正在读取目录');
  } finally { release(); }
  await expect(page.locator('html')).toHaveAttribute('data-app-ready','true');
  await expect(page.locator('.shift-report-card')).toHaveCount(6);
});

test('returning from a report never paints dashboard while health is pending or during browser history navigation', async ({page,context}) => {
  await ready(page,'reports');
  await expect(page.locator('.shift-report-card')).toHaveCount(6);
  await context.addInitScript(() => {
    window.paintedViews = [];
    function sample() {
      if (document.styleSheets.length) {
        const active = [...document.querySelectorAll('.view.active')].filter(node => getComputedStyle(node).display !== 'none').map(node => node.id);
        for (const name of active) if (!window.paintedViews.includes(name)) window.paintedViews.push(name);
      }
      requestAnimationFrame(sample);
    }
    requestAnimationFrame(sample);
  });
  const popup = page.waitForEvent('popup');
  await page.locator('[data-open-report="spc"]').first().click();
  const report = await popup;
  await expect(report.locator('h1')).toHaveText('SPC 趋势报表');
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  await context.route('**/api/health', async route => { await blocked; await route.continue(); });
  try {
    await Promise.all([
      report.waitForURL('**/?view=reports',{waitUntil:'domcontentloaded'}),
      report.getByRole('link',{name:'返回基础报表',exact:false}).click(),
    ]);
    await expect(report.locator('#reportsView')).toBeVisible();
    await expect(report.locator('#dashboardView')).toBeHidden();
    await expect(report.locator('html')).not.toHaveAttribute('data-app-ready','true');
    await report.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    expect(await report.evaluate(() => window.paintedViews)).toEqual(['reportsView']);
  } finally { release(); }
  await expect(report.locator('html')).toHaveAttribute('data-app-ready','true');
  await expect(report.locator('.shift-report-card')).toHaveCount(6);
  expect(await report.evaluate(() => window.paintedViews)).toEqual(['reportsView']);
  await report.goBack();
  await expect(report.locator('h1')).toHaveText('SPC 趋势报表');
  await report.goForward();
  await expect(report.locator('#reportsView')).toBeVisible();
  await expect(report.locator('#dashboardView')).toBeHidden();
  await expect(report.locator('html')).toHaveAttribute('data-app-ready','true');
  expect(await report.evaluate(() => window.paintedViews)).toEqual(['reportsView']);
  await report.close();
});

test('case search opens a linked SOP and hands content to an editable assistant draft without sending', async ({page}) => {
  await ready(page, 'procedures');
  await expect(page.locator('[data-shift-document^="case:"]').first()).toBeVisible();
  await page.locator('#shiftDocumentSearch').fill('CASE-CVD-003');
  await expect(page.locator('.shift-document-item')).toHaveCount(1);
  await expect(page.locator('#shiftDocumentReader')).toContainText('保养后部分批次膜厚均值上移');
  await page.locator('[data-related-sop]').click();
  await expect(page.locator('[data-document-kind="sop"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#shiftDocumentReader')).toContainText('CVD 膜厚偏移复核流程');
  let sent = false;
  page.on('request', request => { if (request.method() === 'POST' && request.url().includes('/api/chat')) sent = true; });
  await page.locator('#askShiftAssistant').click();
  await expect(page.locator('#chatInput')).toHaveValue(/SOP-CVD-012/);
  await expect(page.locator('#chatInput')).toHaveValue(/核对批次/);
  expect(sent).toBe(false);
  await accessible(page);
});

test('malformed materials are reported separately while original cases remain available', async ({page}) => {
  await page.route('**/display_mock_data/catalog.json', route => route.fulfill({contentType: 'application/json', body: '{"documents": null}'}));
  await ready(page, 'procedures');
  await expect(page.locator('#shiftDocumentsStatus')).toContainText('展示资料格式不正确');
  await expect(page.locator('[data-shift-document^="sample:"]')).toHaveCount(0);
  await expect(page.locator('[data-shift-document^="case:"]').first()).toBeVisible();
  await page.unroute('**/display_mock_data/catalog.json');
  await page.locator('#refreshShiftDocuments').click();
  await expect(page.locator('[data-shift-document^="sample:"]')).toHaveCount(3);
});
