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
  await expect(page.locator('#toastRegion')).toContainText('Autosystem 地址尚未配置');
});

test('report catalog filters and opens real report pages, with actual recent history', async ({page}) => {
  await ready(page, 'reports');
  await expect(page.locator('.shift-report-card')).toHaveCount(6);
  await expect(page.locator('#reportsView')).not.toContainText('演示');
  await page.locator('[data-report-role="PE"]').click();
  await expect(page.locator('.shift-report-card')).toHaveCount(3);
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

test('case search opens a linked SOP and hands content to an editable assistant draft without sending', async ({page}) => {
  await ready(page, 'procedures');
  await expect(page.locator('.shift-document-item')).toHaveCount(3);
  await page.locator('#shiftDocumentSearch').fill('膜厚');
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

test('malformed materials are reported as unavailable and can be retried', async ({page}) => {
  await page.route('**/display_mock_data/catalog.json', route => route.fulfill({contentType: 'application/json', body: '{"reports": null}'}));
  await ready(page, 'reports');
  await expect(page.locator('#shiftReportsStatus')).toHaveText('资料格式不正确');
  await expect(page.locator('.shift-report-card')).toHaveCount(0);
  await page.unroute('**/display_mock_data/catalog.json');
  await page.locator('[data-view="reports"]').click();
  await expect(page.locator('.shift-report-card')).toHaveCount(6);
});
