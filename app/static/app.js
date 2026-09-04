const state = globalThis.FabAppState.createState();
const { $, escapeHtml, formatFileSize, formatNumber, setInitialDates } = globalThis.FabAppDom;
const { FabApiError, identityHeaders, apiError, api } = globalThis.FabAppApi;
const { showToast } = globalThis.FabAppToast.createToast(state);
const { handleBuildVersion, checkAppVersion } = globalThis.FabAppVersion.createVersion({ api, $ });

const CHAT_DRAFT_KEY = 'fabInsightChatDraft';
const processLabels = {
  LITHO: '光刻', ETCH: '刻蚀', CVD: '化学气相沉积', PVD: '物理气相沉积',
  DIFFUSION: '扩散/炉管', IMPLANT: '离子注入', CMP: '化学机械研磨',
  CLEAN: '湿法清洗', METROLOGY: '量测',
};
const toolLabels = {
  get_enterprise_data_manifest: '查询企业数据目录',
  get_enterprise_fab_summary: '聚合企业模拟数据',
  query_enterprise_data: '抽取企业模拟数据',
  get_fab_overview: '查询工厂总览',
  get_yield_trend: '查询良率趋势',
  get_equipment_health: '查询设备健康',
  get_equipment_productivity: '查询设备生产状态',
  get_process_capability: '查询制程能力',
  get_defect_pareto: '查询缺陷 Pareto',
  get_recent_excursions: '查询近期异常',
  get_sensor_summary: '查询传感器摘要',
  search_knowledge: '检索知识与案例',
  query_manufacturing_data: '执行制造数据查询',
};

function updateSystemStatus(modelLabel) {
  const enterprise = state.enterpriseContext;
  $('#systemStatus').textContent = enterprise
    ? `${enterprise.tenant_id} · 企业模拟源 · ${modelLabel}`
    : `${formatNumber(state.dashboard?.overview?.lots ?? 0)} 批次 · ${modelLabel}`;
  if (enterprise) {
    $('#systemStatus').title = `${formatNumber(enterprise.virtual_scale?.lots || 0)} 个虚拟批次；支持服务端聚合；数据不代表真实生产`;
  }
}

function newClientMessageId() {
  return globalThis.crypto?.randomUUID?.()
    || `msg-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

const sourcePresenter = globalThis.FabSourcePresenter;
const presenter = globalThis.FabChatPresenter.createChatPresenter({
  $, escapeHtml, sourcePresenter, toolLabels,
});
let layout;

const knowledge = globalThis.FabKnowledgeController.createKnowledgeController({
  state, $, escapeHtml, formatFileSize, api, identityHeaders, showToast, processLabels,
  renderMarkdown: presenter.renderMarkdown,
  showView: (...args) => layout.showView(...args),
  newClientMessageId,
  personalKnowledgeMetadata: globalThis.FabPersonalKnowledgeMetadata,
  personalJobEvents: globalThis.FabPersonalJobEvents,
  personalUploadQueue: globalThis.FabPersonalUploadQueue,
});
const model = globalThis.FabModelController.createModelController({
  state, $, escapeHtml, api, showToast, updateSystemStatus,
  thinkingControl: globalThis.FabThinkingControl,
});
const dashboard = globalThis.FabDashboardController.createDashboardController({
  state, $, escapeHtml, formatNumber, api, processLabels,
});
const sessions = globalThis.FabSessionController.createSessionController({
  state, $, escapeHtml, api, showToast, sourcePresenter, presenter,
  getShowView: () => layout.showView,
  getSetAgentOpen: () => layout.setAgentOpen,
});
layout = globalThis.FabLayoutController.createLayoutController({
  state, $, ...knowledge, ...dashboard, ...sessions,
});
const chat = globalThis.FabChatController.createChatController({
  state, $, escapeHtml, api, identityHeaders, FabApiError, apiError,
  thinkingControl: globalThis.FabThinkingControl, toolLabels, presenter,
  createConversation: sessions.createConversation,
  loadSessionLibrary: sessions.loadSessionLibrary,
  newClientMessageId, thinkingEnabled: model.thinkingEnabled,
  chatDraftKey: CHAT_DRAFT_KEY,
});

const bootstrap = globalThis.FabAppBootstrap.createBootstrap({
  state, $, api, setInitialDates, updateSystemStatus, handleBuildVersion,
  checkAppVersion, showToast, personalUploadQueue: globalThis.FabPersonalUploadQueue,
  ...knowledge, ...model, ...dashboard, ...sessions, ...chat, ...layout,
});

document.addEventListener('DOMContentLoaded', bootstrap.init);
