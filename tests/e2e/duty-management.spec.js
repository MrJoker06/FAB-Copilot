const { test, expect } = require('./support/fixture');
const AxeBuilder = require('@axe-core/playwright').default;
const adminHeaders = {Authorization:'Bearer browser-test-admin-token'};

async function admin(page) {
  await page.goto('/admin');
  await page.locator('#adminToken').fill('browser-test-admin-token');
  await page.locator('#adminAuthForm button[type="submit"]').click();
  await expect(page.locator('#adminWorkspace')).toBeVisible();
}

test('platform admin registers a common skill and can restrict it to a department', async ({page}) => {
  const name = 'litho-cpk-diagnostic';
  await admin(page);
  await page.locator('[data-admin-view="abilities"]').click();
  await page.locator('[data-ability-kind="skill"]').click();
  await page.locator('[data-register-ability]').click();
  const form = page.locator('[data-ability-form]');
  await form.locator('[name=candidate]').selectOption(name);
  await form.locator('[name=scope]').selectOption('common');
  await form.locator('[name=groups]').fill('值班排查');
  await form.locator('[name=enabled]').check();
  await form.getByRole('button', {name:'保存'}).click();
  await expect(page.locator('[data-ability-rows]')).toContainText('值班排查');
  const row = page.locator('[data-ability-rows] tr').filter({hasText:name});
  const title = await row.locator('strong').innerText();
  await page.goto('/');
  await page.locator('#allFunctions summary').click();
  await page.locator('[data-my-capabilities]').click();
  await expect(page.locator('[data-my-catalog-body]')).toContainText(title);
  await page.goto('/admin');
  await page.locator('[data-admin-view="abilities"]').click();
  await page.locator('[data-ability-kind="skill"]').click();
  await row.locator('button').click();
  await form.locator('[name=scope]').selectOption('module');
  await form.locator('[name=owner]').fill('Litho');
  await form.getByRole('button', {name:'保存'}).click();
  await expect(row).toContainText('Litho');
  const visible = await page.request.get('/api/capabilities');
  expect(visible.ok()).toBeTruthy();
  expect((await visible.json()).items.map(item => item.name)).not.toContain(name);
});

test('engineer can apply a duty skill for one chat turn', async ({page}) => {
  const skill = 'litho-cpk-diagnostic';
  const trend = 'get_capability_trend';
  async function set(kind, name, enabled) {
    const response = await page.request.put(`/api/admin/capabilities/${kind}/${name}`, {
      headers: adminHeaders, data: {access: null, groups: [], enabled},
    });
    expect(response.ok()).toBe(true);
  }

  try {
    await set('tool', trend, true);
    await set('skill', skill, true);
    await page.goto('/');
    await expect(page.locator('html')).toHaveAttribute('data-app-ready', 'true');
    const picker = page.locator('[data-chat-skill]');
    await picker.click();
    const dialog = page.getByRole('dialog', {name: '选择值班技能'});
    await dialog.getByRole('combobox').selectOption(skill);
    await dialog.getByRole('button', {name: '应用'}).click();
    await expect(picker).toHaveText('Lithography Cpk diagnostic');
    await page.locator('#chatInput').fill('排查光刻 Cpk 异常');
    const sent = page.waitForRequest(request => request.url().endsWith('/api/chat/stream'));
    await page.getByRole('button', {name: '发送', exact: true}).click();
    expect((await sent).postDataJSON().skill_id).toBe(skill);
    await expect(page.locator('[data-skill-execution]')).toContainText('待补充');
    await expect(page.locator('#chatMessages')).toContainText('日期');
    await expect(picker).toHaveText('选择技能');
  } finally {
    await set('skill', skill, false);
    await set('tool', trend, false);
  }
});

test('admin report folders persist and manage flat user report links without changing models',async ({page}) => {
  const before = await (await page.request.get('/api/admin/report-directory',{headers:adminHeaders})).json();
  const modelsBefore = await (await page.request.get('/api/admin/models',{headers:adminHeaders})).json();
  try {
    await admin(page);
    await page.locator('[data-admin-view="reports"]').click();
    await expect(page.locator('#reportDirectoryBody tr')).toHaveCount(6);
    await page.locator('#addReportFolder').click();
    await page.locator('#reportFolderName').fill('工程报表');
    await page.locator('#reportFolderForm button[type="submit"]').click();
    await page.locator('#addReportFolder').click();
    await page.locator('#reportFolderName').fill('SPC');
    await page.locator('#reportFolderForm button[type="submit"]').click();
    await expect(page.locator('#reportFolderTree ul ul').first()).toContainText('SPC');
    await page.getByRole('button', {name:'＋ 新增报表'}).click();
    await page.locator('#reportTitle').fill('当班 SPC 扩展链接');
    await page.locator('#reportUrl').fill('/display_mock_data/reports/spc.html');
    await page.locator('#reportEditorForm button[type="submit"]').click();
    await page.locator('#saveReportDirectory').click();
    await expect(page.locator('#reportDirectoryNotice')).toContainText('目录已保存');
    const violations = await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21a','wcag21aa']).analyze();
    expect(violations.violations).toEqual([]);
    await page.screenshot({path:'runtime/quality/duty-admin-report-folders.png',fullPage:true});
    await page.reload();
    await page.locator('[data-admin-view="reports"]').click();
    await expect(page.locator('#reportFolderTree')).toContainText('工程报表');
    await expect(page.locator('#reportFolderTree')).toContainText('SPC');
    await page.goto('/?view=reports');
    await expect(page.locator('.shift-report-card')).toHaveCount(7);
    await expect(page.locator('.shift-report-card').filter({hasText:'当班 SPC 扩展链接'})).toBeVisible();
    await expect(page.locator('[data-report-role]')).toHaveCount(0);
    await page.goto('/admin');
    await page.locator('[data-admin-view="reports"]').click();
    await page.getByRole('button', {name:'工程报表', exact:false}).first().click();
    await page.locator('#editReportFolder').click();
    await page.locator('#reportOwnerModule').fill('光刻');
    await page.locator('#reportReaderModules').fill('质量');
    await page.locator('#reportFolderForm button[type="submit"]').click();
    await page.locator('#saveReportDirectory').click();
    await expect(page.locator('#reportDirectoryNotice')).toContainText('目录已保存');
    await page.locator('#previewReportModules').fill('质量');
    await page.locator('#reportAccessPreview button').click();
    await expect(page.locator('#reportAccessResult')).toContainText('当班 SPC 扩展链接');
    await page.locator('#previewReportModules').fill('整合');
    await page.locator('#reportAccessPreview button').click();
    await expect(page.locator('#reportAccessResult')).toContainText('整合 · 6 份报表');
    await expect(page.locator('#reportAccessResult')).not.toContainText('当班 SPC 扩展链接');
    await page.goto('/?view=reports');
    await expect(page.locator('.shift-report-card')).toHaveCount(6);
    const modelsAfter = await (await page.request.get('/api/admin/models',{headers:adminHeaders})).json();
    expect(modelsAfter).toEqual(modelsBefore);
  } finally {
    const latest = await (await page.request.get('/api/admin/report-directory',{headers:adminHeaders})).json();
    const restored = await page.request.put('/api/admin/report-directory',{headers:adminHeaders,data:{...before,revision:latest.revision}});
    expect(restored.ok()).toBe(true);
  }
});

test('user upload becomes shared, admin edits and disables it, other users lose content access',async ({page,browser,baseURL}) => {
  await page.goto('/?view=procedures');
  await expect(page.locator('html')).toHaveAttribute('data-app-ready','true');
  await page.locator('#openSharedUpload').click();
  await page.locator('#sharedUploadKind').selectOption('case');
  await page.locator('#sharedUploadTitle').fill('值班共享上传验收记录');
  await page.locator('#sharedUploadFile').setInputFiles({name:'shift-handoff.md',mimeType:'text/markdown',buffer:Buffer.from('# 交接记录\n\n核对设备报警、批次窗口和维护记录，保留工程师复核结论。')});
  const upload = page.waitForResponse(response => response.url().endsWith('/api/knowledge/shared/documents') && response.request().method() === 'POST');
  await page.locator('#confirmSharedUpload').click();
  const id = (await (await upload).json()).document_id;
  await expect(page.locator('#shiftDocumentReader')).toContainText('保留工程师复核结论');
  const context = await browser.newContext({baseURL});
  try {
    await context.addInitScript(() => {localStorage.setItem('fabInsightTenantId','browser-test');localStorage.setItem('fabInsightUserId','shared-reader');});
    const reader = await context.newPage();
    await reader.goto('/?view=procedures');
    await reader.locator(`#shiftDocumentList [data-shift-document="shared:${id}"]`).click();
    await expect(reader.locator('#shiftDocumentReader')).toContainText('核对设备报警');
    await reader.screenshot({path:'runtime/quality/duty-shared-case.png',fullPage:true});
    await admin(page);
    await page.locator('[data-admin-view="documents"]').click();
    await page.locator(`[data-manage-document="${id}"]`).click();
    await expect(page.locator('#sharedDocumentPreview')).toContainText('保留工程师复核结论');
    await page.locator('#closeSharedDocument').click();
    await page.getByText('配置部门资料区', {exact:true}).click();
    await page.locator('[data-doc-area-form] [name=owner]').fill('光刻');
    await page.locator('[data-doc-area-form] [name=readers]').fill('质量');
    await page.getByRole('button',{name:'保存资料区'}).click();
    await expect(page.locator('[data-doc-areas]')).toContainText('质量');
    await page.locator(`[data-manage-document="${id}"]`).click();
    await page.locator('#sharedDocumentTitle').fill('已复核的交接案例');
    await page.locator('[data-doc-destination]').selectOption('光刻');
    await page.locator('#sharedDocumentForm button[type="submit"]').click();
    await expect(page.locator('#sharedDocumentDialog')).not.toBeVisible();
    await reader.locator('#refreshShiftDocuments').click();
    await expect(reader.locator(`[data-shift-document="shared:${id}"]`)).toHaveCount(0);
    await page.getByText('预览部门可见资料', {exact:true}).click();
    await page.locator('[data-doc-preview] [name=modules]').fill('质量');
    await page.locator('[data-doc-preview] button').click();
    await expect(page.locator('[data-doc-preview-result]')).toContainText('已复核的交接案例');
    await page.locator(`[data-manage-document="${id}"]`).click();
    await page.locator('#sharedDocumentEnabled').uncheck();
    await page.locator('#sharedDocumentForm button[type="submit"]').click();
    await expect(page.locator('#sharedDocumentDialog')).not.toBeVisible();
    await reader.locator('#refreshShiftDocuments').click();
    await expect(reader.locator(`[data-shift-document="shared:${id}"]`)).toHaveCount(0);
    expect((await context.request.get(`/api/knowledge/shared/documents/${id}`)).status()).toBe(404);
    expect((await context.request.get(`/api/knowledge/shared/documents/${id}/file`)).status()).toBe(404);
    const retained = await (await page.request.get(`/api/admin/shared-documents/${id}`,{headers:adminHeaders})).json();
    expect(retained.title).toBe('已复核的交接案例'); expect(retained.enabled).toBe(false);
    await page.getByText('上传到指定资料区', {exact:true}).click();
    const uploadForm = page.locator('[data-admin-upload]');
    await uploadForm.locator('[name=area]').selectOption('光刻');
    await uploadForm.locator('[name=file]').setInputFiles({name:'private-sop.txt',mimeType:'text/plain',buffer:Buffer.from('部门交接步骤')});
    const restrictedUpload = page.waitForResponse(response => response.url().endsWith('/api/admin/shared-documents') && response.request().method() === 'POST');
    await uploadForm.getByRole('button', {name:'上传资料'}).click();
    const restricted = await restrictedUpload;
    expect(restricted.status()).toBe(202);
    const restrictedId = (await restricted.json()).document_id;
    await expect(page.locator('#sharedDocumentsBody')).toContainText('private-sop.txt');
    expect((await context.request.get(`/api/knowledge/shared/documents/${restrictedId}/file`)).status()).toBe(404);

  } finally {await context.close();}
});
