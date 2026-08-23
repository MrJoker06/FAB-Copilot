const { test, expect } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;

const ADMIN_TOKEN = 'browser-test-admin-token';
const WCAG_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

async function expectNoAxeViolations(page) {
  const results = await new AxeBuilder({page}).withTags(WCAG_TAGS).analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
}

async function readyUser(page) {
  await page.goto('/');
  await expect(page.locator('#kpiGrid')).not.toBeEmpty();
  // The initial HTML has a static welcome message, but suggestions are rendered
  // only after init awaits restoreConversation (or creates a fresh session).
  await expect(page.locator('#chatMessages .suggestions')).toBeVisible();
}

async function tabUntilFocused(page, locator, limit = 16) {
  for (let index = 0; index < limit; index += 1) {
    await page.keyboard.press('Tab');
    if (await locator.evaluate(element => element === document.activeElement)) return;
  }
  await expect(locator).toBeFocused();
}

async function expectVisibleFocusRing(locator) {
  const style = await locator.evaluate(element => {
    const computed = getComputedStyle(element);
    return {outlineWidth: Number.parseFloat(computed.outlineWidth), boxShadow: computed.boxShadow};
  });
  expect(style.outlineWidth).toBeGreaterThanOrEqual(2);
  expect(style.boxShadow).not.toBe('none');
}

test('desktop user views and model dialog have no WCAG A/AA violations', async ({page}) => {
  await readyUser(page);
  await expectNoAxeViolations(page);
  await page.locator('[data-view="knowledge"]').click();
  await page.locator('[data-knowledge-mode="personal"]').click();
  // The sole upload entry intentionally follows the personal-document list and
  // can sit below the desktop viewport when the seeded library is populated.
  await expect(page.locator('[data-open-knowledge-upload]')).toHaveCount(1);
  await expectNoAxeViolations(page);
  await page.locator('#modelSettingsButton').click();
  await expect(page.locator('#modelDialog')).toBeVisible();
  await expectNoAxeViolations(page);
});

test('desktop keyboard navigation keeps modal focus and activates navigation', async ({page}) => {
  await readyUser(page);
  await page.keyboard.press('Tab');
  await expect(page.locator('#modelSettingsButton')).toBeFocused();
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await expect(page.locator('[data-view="knowledge"]')).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#knowledgeView')).toHaveClass(/active/);
  await expectVisibleFocusRing(page.locator('[data-view="knowledge"]'));
  await page.locator('#modelSettingsButton').click();
  await expect(page.locator('#modelDialog')).toBeVisible();
  await expect(page.locator('#modelSelect')).toBeFocused();
  await expectVisibleFocusRing(page.locator('#modelSelect'));
  for (let index = 0; index < 6; index += 1) {
    await page.keyboard.press(index % 2 ? 'Shift+Tab' : 'Tab');
    expect(await page.locator('#modelDialog').evaluate(dialog => dialog.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press('Escape');
  await expect(page.locator('#modelDialog')).toBeHidden();
  await expect(page.locator('#modelSettingsButton')).toBeFocused();
  await page.locator('[data-knowledge-mode="personal"]').click();
  await page.locator('[data-open-knowledge-upload]').click();
  await page.locator('#knowledgeUploadDrop').focus();
  const fileChooser = page.waitForEvent('filechooser');
  await page.keyboard.press('Enter');
  await fileChooser;
});

test('desktop admin auth, runtime, and models meet accessibility requirements', async ({page}) => {
  await page.goto('/admin');
  await expect(page.locator('#adminAuthDialog')).toBeVisible();
  await expectNoAxeViolations(page);
  await page.keyboard.press('Escape');
  await expect(page.locator('#adminAuthDialog')).toBeVisible();
  await page.addInitScript(token => sessionStorage.setItem('fabInsightAdminToken', token), ADMIN_TOKEN);
  await page.reload();
  await expect(page.locator('#adminWorkspace')).toBeVisible();
  await expectNoAxeViolations(page);
  await tabUntilFocused(page, page.locator('[data-admin-view="models"]'));
  await expectVisibleFocusRing(page.locator('[data-admin-view="models"]'));
  await page.keyboard.press('Enter');
  await expect(page.locator('#modelsView')).toHaveClass(/active/);
  await expect(page.locator('[data-admin-view="models"]')).toHaveAttribute('aria-current', 'page');
  await expectNoAxeViolations(page);
  await page.locator('#openPublishModel').click();
  await expect(page.locator('#publishModelDialog')).toBeVisible();
  await expect(page.locator('#publishDisplayName')).toBeFocused();
  await expectVisibleFocusRing(page.locator('#publishDisplayName'));
  await expectNoAxeViolations(page);
  for (let index = 0; index < 8; index += 1) {
    await page.keyboard.press('Tab');
    expect(await page.locator('#publishModelDialog').evaluate(dialog => dialog.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press('Escape');
  await expect(page.locator('#publishModelDialog')).toBeHidden();
  await expect(page.locator('#openPublishModel')).toBeFocused();
});
