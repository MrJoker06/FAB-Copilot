const assert = require('node:assert/strict');
const test = require('node:test');
const layoutModule = require('../app/static/app/layout/controller.js');
const bootstrapModule = require('../app/static/app/bootstrap.js');

test('layout controller updates view ARIA and clamps persisted panel widths', () => {
  const attributes = {};
  const shellClasses = new Set();
  const fakeShell = {
    classList: {
      contains: name => shellClasses.has(name),
      toggle: (name, enabled) => enabled ? shellClasses.add(name) : shellClasses.delete(name),
    },
    style: {
      setProperty: (name, value) => { attributes[name] = value; },
      removeProperty: name => { delete attributes[name]; },
    },
  };
  const fakeResizeHandle = {
    setAttribute: (name, value) => { attributes[name] = value; },
    addEventListener() {},
  };
  const fakePanel = {
    classList: { remove() {}, add() {} },
    getBoundingClientRect: () => ({ width: 400 }),
    offsetWidth: 0,
  };
  const fakeNode = {
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {},
    removeAttribute() {},
  };
  const fakeNodes = {
    '#agentResizeHandle': fakeResizeHandle,
    '.sidebar': { getBoundingClientRect: () => ({ width: 120 }) },
    '#sessionHistoryButton': fakeNode,
    '#focusAgent': fakeNode,
    '#mobileAgentToggle': fakeNode,
    '#collapseAgent': fakeNode,
    '#dashboardView': fakeNode,
  };
  const fakeDocument = {
    querySelector: selector => {
      if (selector === '.app-shell') return fakeShell;
      if (selector === '.agent-panel') return fakePanel;
      return fakeNodes[selector] || fakeNode;
    },
    querySelectorAll: () => [fakeNode],
    body: { classList: { remove() {} } },
  };
  const persistedWidths = [];
  const fakeStorage = {
    setItem: (key, value) => persistedWidths.push([key, value]),
    getItem: () => null,
    removeItem() {},
  };
  const controller = layoutModule.createLayoutController({
    state: { knowledgeMode: 'factory' },
    $: selector => fakeNodes[selector] || fakeNode,
    documentImpl: fakeDocument,
    windowImpl: { innerWidth: 1400 },
    localStorageImpl: fakeStorage,
    requestAnimationFrameImpl: callback => callback(),
  });

  controller.showView('dashboard');
  controller.setAgentPanelWidth(999);

  assert.equal(attributes['--agent-width'], '620px');
  assert.deepEqual(persistedWidths[0], ['fabInsightAgentWidth', '620']);
  assert.equal(attributes['aria-valuenow'], '620');
});

test('bootstrap initializes in order and marks the document ready', async () => {
  const calls = [];
  const fakeNode = {
    addEventListener() {},
    value: '',
    classList: { contains: () => false },
  };
  const fakeDocument = {
    documentElement: { dataset: {} },
    querySelectorAll: () => [],
    addEventListener() {},
  };
  const app = bootstrapModule.createBootstrap({
    state: { capabilityCache: new Map() },
    $: () => fakeNode,
    documentImpl: fakeDocument,
    windowImpl: {
      location: { search: '' },
      addEventListener() {},
      clearTimeout() {},
      setTimeout() {},
    },
    localStorageImpl: { getItem: () => null },
    setInitialDates: () => calls.push('dates'),
    initializeAgentResize: () => calls.push('resize'),
    restoreAgentPanelWidth: () => calls.push('restore'),
    api: async () => ({}),
    loadModelConfig: async () => ({ api_key_configured: false }),
    updateSystemStatus: () => calls.push('status'),
    handleBuildVersion() {},
    loadDashboard: async () => calls.push('dashboard'),
    restoreConversation: async () => calls.push('conversation'),
    setAgentOpen: () => calls.push('open'),
  });

  await app.init();

  assert.deepEqual(calls, ['dates', 'resize', 'restore', 'status', 'dashboard', 'conversation', 'open']);
  assert.equal(fakeDocument.documentElement.dataset.appReady, 'true');
});

test('bootstrap retains the migrated dialog, session, source, and chart bindings', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const source = fs.readFileSync(path.join(__dirname, '../app/static/app/bootstrap.js'), 'utf8');
  const requiredSelectors = [
    '#personalKnowledgeDeleteForm',
    '#personalKnowledgeMetadataForm',
    '#sessionRenameForm',
    '#sessionDeleteForm',
    '#newSessionFromLibrary',
    '#sessionLibraryMessages',
    '#chatMessages',
    '#yieldChart',
    '#knowledgeUploadDrop',
    '#sessionLibraryList',
  ];
  for (const selector of requiredSelectors) {
    assert.match(source, new RegExp(selector.replace(/[#$]/g, '\\$&')));
  }
  const requiredEventNames = ['mousemove', 'mouseleave', 'visibilitychange', 'resize'];
  for (const eventName of requiredEventNames) {
    assert.match(source, new RegExp(`['"]${eventName}['"]`));
  }
  assert.match(source, /document\.addEventListener\('click'/);
});
