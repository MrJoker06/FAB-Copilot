const state = globalThis.FabAppState.createState();
const { $, escapeHtml, formatFileSize, formatNumber, isoDate, setInitialDates } = globalThis.FabAppDom;
const { FabApiError, identityHeaders, apiError, api } = globalThis.FabAppApi;
const { dismissToast, showToast } = globalThis.FabAppToast.createToast(state);
const { APP_VERSION, handleBuildVersion, checkAppVersion } = globalThis.FabAppVersion.createVersion({ api, $ });
const AGENT_WIDTH_KEY = 'fabInsightAgentWidth';
const CHAT_DRAFT_KEY = 'fabInsightChatDraft';
const AGENT_MIN_WIDTH = 300;
const AGENT_MAX_WIDTH = 620;
const processLabels = { LITHO: '光刻', ETCH: '刻蚀', CVD: '化学气相沉积', PVD: '物理气相沉积', DIFFUSION: '扩散/炉管', IMPLANT: '离子注入', CMP: '化学机械研磨', CLEAN: '湿法清洗', METROLOGY: '量测' };
const toolLabels = { get_enterprise_data_manifest: '查询企业数据目录', get_enterprise_fab_summary: '聚合企业模拟数据', query_enterprise_data: '抽取企业模拟数据', get_fab_overview: '查询工厂总览', get_yield_trend: '查询良率趋势', get_equipment_health: '查询设备健康', get_equipment_productivity: '查询设备生产状态', get_process_capability: '查询制程能力', get_defect_pareto: '查询缺陷 Pareto', get_recent_excursions: '查询近期异常', get_sensor_summary: '查询传感器摘要', search_knowledge: '检索知识与案例', query_manufacturing_data: '执行制造数据查询' };
const sourcePresenter = globalThis.FabSourcePresenter;
const personalKnowledgeMetadata = globalThis.FabPersonalKnowledgeMetadata;
const thinkingControl = globalThis.FabThinkingControl;
const personalJobEvents = globalThis.FabPersonalJobEvents;
const personalUploadQueue = globalThis.FabPersonalUploadQueue;


function updateSystemStatus(modelLabel) {
  const enterprise = state.enterpriseContext;
  $('#systemStatus').textContent = enterprise
    ? `${enterprise.tenant_id} · 企业模拟源 · ${modelLabel}`
    : `${formatNumber(state.dashboard?.overview?.lots ?? 0)} 批次 · ${modelLabel}`;
  if (enterprise) $('#systemStatus').title = `${formatNumber(enterprise.virtual_scale?.lots || 0)} 个虚拟批次；支持服务端聚合；数据不代表真实生产`;
}


function newClientMessageId() {
  return globalThis.crypto?.randomUUID?.() || `msg-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}


const presenter = globalThis.FabChatPresenter.createChatPresenter({
  $,
  escapeHtml,
  sourcePresenter,
  toolLabels,
});
const { sourceReferenceMap, renderSourcePanel, renderMarkdown } = presenter;
const knowledgeController = globalThis.FabKnowledgeController.createKnowledgeController({ state, $, escapeHtml, formatFileSize, api, identityHeaders, showToast, processLabels, renderMarkdown, showView, newClientMessageId, personalKnowledgeMetadata, personalJobEvents, personalUploadQueue });
const { renderKnowledgeDocuments, personalKnowledgeStatusLabel, resetKnowledgeReader, renderPersonalKnowledgeDocuments, schedulePersonalKnowledgeRefresh, personalKnowledgeProcessing, stopPersonalJobEvents, debouncePersonalKnowledgeEventRefresh, personalJobEventHeaders, enablePersonalJobEventsFallback, startPersonalJobEvents, loadPersonalKnowledgeDocuments, personalKnowledgeMeta, renderPersonalKnowledgeContent, openPersonalKnowledgeDocument, openPersonalKnowledgeChunk, setKnowledgeMode, renderKnowledgeUploadQueue, mergeKnowledgeUploadFiles, showKnowledgeUploadMessage, resetKnowledgeUploadForm, openKnowledgeUploadDialog, uploadPersonalKnowledge, retrySelectedPersonalKnowledge, openPersonalKnowledgeMetadataDialog, refreshRenderedPersonalSourceName, savePersonalKnowledgeMetadata, openPersonalKnowledgeDeleteDialog, deleteSelectedPersonalKnowledge, downloadSelectedPersonalKnowledge, loadKnowledgeIndex, openKnowledgeChunk, renderCaseList, loadCaseIndex, openHistoricalCase } = knowledgeController;
const modelController = globalThis.FabModelController.createModelController({ state, $, escapeHtml, api, showToast, updateSystemStatus, thinkingControl });
const { renderModelConfig, syncThinkingToggle, thinkingEnabled, toggleThinking, loadModelConfig, openModelSettings, saveModelSettings } = modelController;
const dashboardController = globalThis.FabDashboardController.createDashboardController({ state, $, escapeHtml, formatNumber, api, processLabels });
const { renderKpis, renderEquipment, renderDefects, renderExcursions, drawYieldChart, loadDashboard, capabilityRating, loadCapability, renderCapability } = dashboardController;
const sessionController = globalThis.FabSessionController.createSessionController({
  state,
  $,
  escapeHtml,
  api,
  showToast,
  sourcePresenter,
  presenter,
  getShowView: () => showView,
  getSetAgentOpen: () => setAgentOpen,
});
const {
  renderConversation, createConversation, restoreConversation, sessionGroup, openSession,
  filteredSessionLibrary, updateSessionBatchToolbar, setSessionBatchMode, clearSessionBatchSelection,
  renderSessionLibrary, renderSessionLibraryPreview, openSessionLibraryPreview, loadSessionLibrary,
  updateSessionRenameCount, openSessionRenameDialog, renameSelectedLibrarySession, resetConversationDraft,
  archiveLibrarySession, restoreLibrarySession, openSessionDeleteDialog, permanentlyDeleteSelectedSession,
  runSessionLibraryAction, toggleSelectedLibrarySessionArchive, continueSelectedLibrarySession,
  openSessionLibraryWorkspace, closeSessionLibraryWorkspace,
} = sessionController;
const chatController = globalThis.FabChatController.createChatController({
  state,
  $,
  escapeHtml,
  api,
  identityHeaders,
  FabApiError,
  apiError,
  thinkingControl,
  toolLabels,
  presenter,
  createConversation,
  loadSessionLibrary,
  newClientMessageId,
  thinkingEnabled,
  chatDraftKey: CHAT_DRAFT_KEY,
});
const {
  createLiveAnalysis, renderLiveAnalysis, startLiveAnswer, resolveLiveAnswerDrain,
  renderLiveAnswerFrame, scheduleLiveAnswerFrame, armLiveAnswerStall, appendLiveAnswer,
  finishLiveAnswer, cancelLiveAnswer, updateLiveAnalysis, streamAgent, reportStreamTelemetry,
  renderAgentRequestError, sendChat,
} = chatController;

function showView(name) {
  if (name !== 'sessions') state.previousView = name;
  state.activeView = name;
  if (name !== 'knowledge') stopPersonalJobEvents({complete:true});
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item[data-view]').forEach(v => v.removeAttribute('aria-current'));
  document.querySelector(`[data-view="${name}"]`)?.setAttribute('aria-current', 'page');
  $(`#${name}View`).classList.add('active'); document.querySelector(`[data-view="${name}"]`)?.classList.add('active');
  const historyActive = name === 'sessions';
  $('#sessionHistoryButton').classList.toggle('active', historyActive);
  $('#sessionHistoryButton').setAttribute('aria-expanded', String(historyActive));
  $('#sessionHistoryButton').setAttribute('aria-label', historyActive ? '关闭历史会话' : '打开历史会话');
  $('#sessionHistoryButton').title = historyActive ? '关闭历史会话' : '打开历史会话';
  if (!document.querySelector('.app-shell').classList.contains('agent-collapsed')) $('#focusAgent').classList.add('active');
  if (name === 'capability') loadCapability();
  else if (name === 'knowledge') state.knowledgeMode === 'personal' ? loadPersonalKnowledgeDocuments() : loadKnowledgeIndex();
  else if (name === 'cases') loadCaseIndex();
  else if (name === 'sessions') loadSessionLibrary();
  else requestAnimationFrame(() => state.dashboard && drawYieldChart(state.dashboard.yield_trend));
}

function setAgentOpen(open, focusInput = true) {
  const shell = document.querySelector('.app-shell');
  const panel = document.querySelector('.agent-panel');
  shell.classList.toggle('agent-collapsed', !open);
  $('#focusAgent').classList.toggle('active', open);
  $('#focusAgent').setAttribute('aria-expanded', String(open));
  $('#mobileAgentToggle').setAttribute('aria-expanded', String(open));
  $('#collapseAgent').setAttribute('aria-label', open ? '收起分析助手' : '展开分析助手');
  if (!open) return;
  panel.classList.remove('agent-panel-focus');
  void panel.offsetWidth;
  panel.classList.add('agent-panel-focus');
  if (focusInput) {
    panel.scrollIntoView({behavior:'smooth', block:window.innerWidth <= 980 ? 'start' : 'nearest'});
    window.setTimeout(() => $('#chatInput').focus({preventScroll:true}), 350);
  }
}

function toggleAgentPanel() {
  const isCollapsed = document.querySelector('.app-shell').classList.contains('agent-collapsed');
  setAgentOpen(isCollapsed);
}

function getAgentWidthBounds() {
  const sidebarWidth = $('.sidebar').getBoundingClientRect().width;
  const minimumMainWidth = window.innerWidth <= 1280 ? 600 : 660;
  return {
    min: AGENT_MIN_WIDTH,
    max: Math.max(AGENT_MIN_WIDTH, Math.min(AGENT_MAX_WIDTH, window.innerWidth - sidebarWidth - minimumMainWidth)),
  };
}

function updateAgentResizeAria(width) {
  const handle = $('#agentResizeHandle');
  const bounds = getAgentWidthBounds();
  handle.setAttribute('aria-valuemin', String(bounds.min));
  handle.setAttribute('aria-valuemax', String(Math.round(bounds.max)));
  handle.setAttribute('aria-valuenow', String(Math.round(width)));
}

function setAgentPanelWidth(width, persist = true) {
  if (window.innerWidth <= 980 || !Number.isFinite(width)) return;
  const bounds = getAgentWidthBounds();
  const clampedWidth = Math.round(Math.min(bounds.max, Math.max(bounds.min, width)));
  document.querySelector('.app-shell').style.setProperty('--agent-width', `${clampedWidth}px`);
  updateAgentResizeAria(clampedWidth);
  if (persist) localStorage.setItem(AGENT_WIDTH_KEY, String(clampedWidth));
  requestAnimationFrame(() => state.dashboard && drawYieldChart(state.dashboard.yield_trend));
}

function restoreAgentPanelWidth() {
  if (window.innerWidth <= 980) return;
  const savedWidth = Number(localStorage.getItem(AGENT_WIDTH_KEY));
  if (Number.isFinite(savedWidth) && savedWidth > 0) setAgentPanelWidth(savedWidth, false);
  else updateAgentResizeAria(document.querySelector('.agent-panel').getBoundingClientRect().width);
}

function resetAgentPanelWidth() {
  const shell = document.querySelector('.app-shell');
  shell.style.removeProperty('--agent-width');
  localStorage.removeItem(AGENT_WIDTH_KEY);
  requestAnimationFrame(() => {
    updateAgentResizeAria(document.querySelector('.agent-panel').getBoundingClientRect().width);
    state.dashboard && drawYieldChart(state.dashboard.yield_trend);
  });
}

function initializeAgentResize() {
  const handle = $('#agentResizeHandle');
  let drag = null;

  const finishDrag = event => {
    if (!drag || (event.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
    const width = document.querySelector('.agent-panel').getBoundingClientRect().width;
    localStorage.setItem(AGENT_WIDTH_KEY, String(Math.round(width)));
    if (handle.hasPointerCapture?.(drag.pointerId)) handle.releasePointerCapture(drag.pointerId);
    drag = null;
    handle.classList.remove('dragging');
    document.body.classList.remove('agent-resizing');
  };

  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0 || window.innerWidth <= 980) return;
    drag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: document.querySelector('.agent-panel').getBoundingClientRect().width,
    };
    handle.setPointerCapture(event.pointerId);
    handle.classList.add('dragging');
    document.body.classList.add('agent-resizing');
    event.preventDefault();
  });
  handle.addEventListener('pointermove', event => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    setAgentPanelWidth(drag.startWidth + drag.startX - event.clientX, false);
  });
  handle.addEventListener('pointerup', finishDrag);
  handle.addEventListener('pointercancel', finishDrag);
  handle.addEventListener('dblclick', resetAgentPanelWidth);
  handle.addEventListener('keydown', event => {
    if (window.innerWidth <= 980 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const width = document.querySelector('.agent-panel').getBoundingClientRect().width;
    const bounds = getAgentWidthBounds();
    const nextWidth = event.key === 'Home' ? bounds.min
      : event.key === 'End' ? bounds.max
        : width + (event.key === 'ArrowLeft' ? 20 : -20);
    setAgentPanelWidth(nextWidth);
    event.preventDefault();
  });
}

async function init() {
  setInitialDates();
  initializeAgentResize();
  restoreAgentPanelWidth();
  $('#chatInput').value = localStorage.getItem(CHAT_DRAFT_KEY) || '';
  try {
    const [health, modelConfig] = await Promise.all([api('/api/health'), loadModelConfig()]);
    state.enterpriseContext = health.enterprise || null;
    updateSystemStatus(modelConfig.api_key_configured ? (modelConfig.display_name || modelConfig.model) : '离线模式');
    handleBuildVersion(health.build);
  } catch { $('#systemStatus').textContent='数据源不可用'; }
  await loadDashboard();
  await restoreConversation();
  setAgentOpen(true, false);
  const requestedView = new URLSearchParams(window.location.search).get('view');
  if (['dashboard', 'capability', 'knowledge', 'cases', 'sessions'].includes(requestedView)) showView(requestedView);
  $('#dateForm').addEventListener('submit', e => { e.preventDefault(); state.capabilityCache.clear(); loadDashboard(); if ($('#capabilityView').classList.contains('active')) loadCapability(); });
  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));
  $('#focusAgent').addEventListener('click', toggleAgentPanel);
  $('#mobileAgentToggle').addEventListener('click', toggleAgentPanel);
  $('#collapseAgent').addEventListener('click', () => setAgentOpen(false));
  $('#sessionHistoryButton').addEventListener('click', () => state.activeView === 'sessions' ? closeSessionLibraryWorkspace() : openSessionLibraryWorkspace());
  $('#closeSessionLibrary').addEventListener('click', closeSessionLibraryWorkspace);
  $('#stepSelector').addEventListener('click', e => { if (!e.target.dataset.step) return; document.querySelectorAll('#stepSelector button').forEach(b=>b.classList.remove('active')); e.target.classList.add('active'); loadCapability(e.target.dataset.step); });
  let knowledgeSearchTimer = null;
  $('#knowledgeFilter').addEventListener('input', event => {
    window.clearTimeout(knowledgeSearchTimer);
    if (state.knowledgeMode === 'factory') renderKnowledgeDocuments(event.target.value);
    else knowledgeSearchTimer = window.setTimeout(() => loadPersonalKnowledgeDocuments({selectFirst:true}).catch(error => showToast(`搜索失败：${error.message}`, {tone:'error'})), 180);
  });
  $('#knowledgeSourceTabs').addEventListener('click', event => {
    const button = event.target.closest('[data-knowledge-mode]');
    if (button) setKnowledgeMode(button.dataset.knowledgeMode).catch(error => showToast(`知识库加载失败：${error.message}`, {tone:'error'}));
  });
  $('#knowledgeDocuments').addEventListener('click', event => {
    const factoryTarget = event.target.closest('[data-knowledge-chunk]');
    const personalTarget = event.target.closest('[data-personal-document-id]');
    if (factoryTarget) openKnowledgeChunk(Number(factoryTarget.dataset.knowledgeChunk));
    else if (personalTarget) openPersonalKnowledgeDocument(personalTarget.dataset.personalDocumentId).catch(error => showToast(`文档加载失败：${error.message}`, {tone:'error'}));
    else if (event.target.closest('[data-open-knowledge-upload]')) openKnowledgeUploadDialog();
  });
  $('#knowledgeUploadForm').addEventListener('submit', uploadPersonalKnowledge);
  $('#knowledgeUploadFile').addEventListener('change', event => { mergeKnowledgeUploadFiles(event.target.files); event.target.value = ''; });
  $('#knowledgeUploadDrop').addEventListener('keydown', event => {
    if (!['Enter', ' '].includes(event.key) || state.personalUploadInProgress) return;
    event.preventDefault();
    $('#knowledgeUploadFile').click();
  });
  $('#knowledgeUploadDrop').addEventListener('dragover', event => { event.preventDefault(); event.currentTarget.classList.add('dragging'); });
  $('#knowledgeUploadDrop').addEventListener('dragleave', event => event.currentTarget.classList.remove('dragging'));
  $('#knowledgeUploadDrop').addEventListener('drop', event => {
    event.preventDefault();
    event.currentTarget.classList.remove('dragging');
    const files = event.dataTransfer?.files;
    if (files?.length) mergeKnowledgeUploadFiles(files);
  });
  $('#knowledgeUploadQueue').addEventListener('click', event => {
    const button = event.target.closest('[data-upload-key]');
    if (!button || state.personalUploadInProgress) return;
    state.personalUploadQueue = personalUploadQueue.remove(state.personalUploadQueue, button.dataset.uploadKey);
    renderKnowledgeUploadQueue();
  });
  const closeKnowledgeUploadDialog = () => { if (!state.personalUploadInProgress) $('#knowledgeUploadDialog').close(); };
  $('#closeKnowledgeUploadDialog').addEventListener('click', closeKnowledgeUploadDialog);
  $('#cancelKnowledgeUpload').addEventListener('click', closeKnowledgeUploadDialog);
  $('#knowledgeUploadDialog').addEventListener('cancel', event => { if (state.personalUploadInProgress) event.preventDefault(); });
  $('#knowledgeUploadDialog').addEventListener('close', resetKnowledgeUploadForm);
  $('#downloadPersonalKnowledge').addEventListener('click', downloadSelectedPersonalKnowledge);
  $('#editPersonalKnowledge').addEventListener('click', openPersonalKnowledgeMetadataDialog);
  $('#retryPersonalKnowledge').addEventListener('click', retrySelectedPersonalKnowledge);
  $('#deletePersonalKnowledge').addEventListener('click', openPersonalKnowledgeDeleteDialog);
  $('#personalKnowledgeDeleteForm').addEventListener('submit', deleteSelectedPersonalKnowledge);
  $('#closePersonalKnowledgeDeleteDialog').addEventListener('click', () => $('#personalKnowledgeDeleteDialog').close());
  $('#cancelPersonalKnowledgeDelete').addEventListener('click', () => $('#personalKnowledgeDeleteDialog').close());
  $('#personalKnowledgeDeleteDialog').addEventListener('close', () => { state.pendingPersonalDeleteId = null; });
  $('#personalKnowledgeMetadataForm').addEventListener('submit', savePersonalKnowledgeMetadata);
  $('#closePersonalKnowledgeMetadataDialog').addEventListener('click', () => $('#personalKnowledgeMetadataDialog').close());
  $('#cancelPersonalKnowledgeMetadata').addEventListener('click', () => $('#personalKnowledgeMetadataDialog').close());
  $('#personalKnowledgeMetadataDialog').addEventListener('close', () => { state.pendingPersonalMetadataId = null; $('#personalKnowledgeMetadataMessage').hidden = true; });
  $('#caseFilter').addEventListener('input', renderCaseList);
  $('#caseStepFilter').addEventListener('change', renderCaseList);
  $('#caseList').addEventListener('click', event => { const target=event.target.closest('[data-case-id]'); if (target) openHistoricalCase(target.dataset.caseId); });
  let sessionLibrarySearchTimer = null;
  $('#sessionLibrarySearch').addEventListener('input', event => {
    window.clearTimeout(sessionLibrarySearchTimer);
    clearSessionBatchSelection();
    sessionLibrarySearchTimer = window.setTimeout(() => loadSessionLibrary(event.target.value), 180);
  });
  $('#sessionLibraryFilter').addEventListener('click', async event => {
    const button = event.target.closest('[data-session-filter]');
    if (!button) return;
    state.sessionLibraryFilter = button.dataset.sessionFilter;
    state.selectedSessionIds.clear();
    document.querySelectorAll('[data-session-filter]').forEach(item => item.classList.toggle('active', item === button));
    await loadSessionLibrary();
  });
  $('#sessionLibraryList').addEventListener('click', event => {
    const item = event.target.closest('[data-library-session-id]');
    if (!item) return;
    const sessionId = item.dataset.librarySessionId;
    const action = event.target.closest('[data-library-action]')?.dataset.libraryAction;
    if (action) {
      item.querySelector('.session-item-menu').open = false;
      runSessionLibraryAction(sessionId, action);
    } else if (state.sessionBatchMode && !event.target.closest('summary')) {
      const checkbox = event.target.closest('.session-select-checkbox');
      const selected = checkbox ? checkbox.checked : !state.selectedSessionIds.has(sessionId);
      if (selected) state.selectedSessionIds.add(sessionId);
      else state.selectedSessionIds.delete(sessionId);
      renderSessionLibrary();
    } else if (!event.target.closest('summary')) {
      openSessionLibraryPreview(sessionId);
    }
  });
  $('#sessionBatchManage').addEventListener('click', () => setSessionBatchMode(!state.sessionBatchMode));
  $('#cancelSessionBatch').addEventListener('click', () => setSessionBatchMode(false));
  $('#sessionBatchSelectAll').addEventListener('change', event => {
    for (const session of filteredSessionLibrary()) {
      if (event.target.checked) state.selectedSessionIds.add(session.session_id);
      else state.selectedSessionIds.delete(session.session_id);
    }
    renderSessionLibrary();
  });
  $('#deleteSelectedSessions').addEventListener('click', () => openSessionDeleteDialog([...state.selectedSessionIds]));
  $('#sessionLibraryMessages').addEventListener('click', event => {
    const knowledgeTarget = event.target.closest('[data-knowledge-chunk]');
    const personalTarget = event.target.closest('[data-personal-chunk]');
    const caseTarget = event.target.closest('[data-case-id]');
    if (knowledgeTarget) openKnowledgeChunk(Number(knowledgeTarget.dataset.knowledgeChunk));
    else if (personalTarget) openPersonalKnowledgeChunk(personalTarget.dataset.personalChunk).catch(error => showToast(`个人来源加载失败：${error.message}`, {tone:'error'}));
    else if (caseTarget) openHistoricalCase(caseTarget.dataset.caseId);
  });
  $('#renameLibrarySession').addEventListener('click', () => openSessionRenameDialog());
  $('#archiveLibrarySession').addEventListener('click', toggleSelectedLibrarySessionArchive);
  $('#deleteLibrarySession').addEventListener('click', () => openSessionDeleteDialog(state.selectedLibrarySessionId));
  $('#continueLibrarySession').addEventListener('click', continueSelectedLibrarySession);
  $('#sessionRenameForm').addEventListener('submit', event => { event.preventDefault(); renameSelectedLibrarySession(); });
  $('#sessionRenameInput').addEventListener('input', () => { updateSessionRenameCount(); $('#sessionRenameMessage').hidden = true; });
  $('#closeSessionRenameDialog').addEventListener('click', () => $('#sessionRenameDialog').close());
  $('#cancelSessionRename').addEventListener('click', () => $('#sessionRenameDialog').close());
  $('#sessionRenameDialog').addEventListener('close', () => { state.pendingRenameSessionId = null; $('#sessionRenameMessage').hidden = true; });
  $('#sessionDeleteForm').addEventListener('submit', event => { event.preventDefault(); permanentlyDeleteSelectedSession().catch(error => showToast(`删除失败：${error.message}`, {tone:'error'})); });
  $('#closeSessionDeleteDialog').addEventListener('click', () => $('#sessionDeleteDialog').close());
  $('#cancelSessionDelete').addEventListener('click', () => $('#sessionDeleteDialog').close());
  $('#sessionDeleteDialog').addEventListener('close', () => { state.pendingDeleteSessionIds = []; });
  $('#newSessionFromLibrary').addEventListener('click', async () => {
    if (state.streaming) return;
    setSessionBatchMode(false);
    const session = await createConversation('已创建新会话。');
    state.selectedLibrarySessionId = session.session_id;
    setAgentOpen(true);
    await loadSessionLibrary();
    showToast('已创建新会话');
  });
  document.addEventListener('click', event => {
    document.querySelectorAll('.session-item-menu[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  $('#chatMessages').addEventListener('click', event => {
    const knowledgeTarget=event.target.closest('[data-knowledge-chunk]');
    const personalTarget=event.target.closest('[data-personal-chunk]');
    const caseTarget=event.target.closest('[data-case-id]');
    const suggestion = event.target.closest('.suggestions button');
    if (knowledgeTarget) openKnowledgeChunk(Number(knowledgeTarget.dataset.knowledgeChunk));
    else if (personalTarget) openPersonalKnowledgeChunk(personalTarget.dataset.personalChunk).catch(error => showToast(`个人来源加载失败：${error.message}`, {tone:'error'}));
    else if (caseTarget) openHistoricalCase(caseTarget.dataset.caseId);
    else if (suggestion) sendChat(suggestion.textContent);
  });
  $('#chatForm').addEventListener('submit', e => { e.preventDefault(); sendChat($('#chatInput').value); });
  $('#thinkingToggle').addEventListener('click', toggleThinking);
  $('#chatInput').addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    if (!state.streaming) $('#chatForm').requestSubmit();
  });
  $('#chatInput').addEventListener('input', event => {
    const draft = event.target.value;
    if (draft) localStorage.setItem(CHAT_DRAFT_KEY, draft);
    else localStorage.removeItem(CHAT_DRAFT_KEY);
  });
  $('#reloadApp').addEventListener('click', () => window.location.reload());
  $('#dismissVersionBanner').addEventListener('click', () => {
    sessionStorage.setItem('fabInsightDismissedVersion', $('#versionBanner').dataset.version || 'unknown');
    $('#versionBanner').hidden = true;
  });
  window.addEventListener('focus', checkAppVersion);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) checkAppVersion(); });
  $('#clearChat').addEventListener('click', async () => { if (!state.streaming) await createConversation('已创建新会话。'); });
  $('#modelSettingsButton').addEventListener('click', openModelSettings);
  $('#modelSettingsForm').addEventListener('submit', saveModelSettings);
  $('#closeModelDialog').addEventListener('click', () => $('#modelDialog').close());
  $('#cancelModelSettings').addEventListener('click', () => $('#modelDialog').close());
  $('#yieldChart').addEventListener('mousemove', e => { const rect=e.currentTarget.getBoundingClientRect(), mx=e.clientX-rect.left; const point=state.chartPoints.reduce((a,b)=>Math.abs(b.x-mx)<Math.abs(a.x-mx)?b:a,state.chartPoints[0]); const tip=$('#chartTooltip'); if (!point || Math.abs(point.x-mx)>18) {tip.hidden=true;return;} tip.hidden=false; tip.style.left=`${point.x}px`; tip.style.top=`${point.y}px`; tip.textContent=`${point.row.week_start} · ${point.row.yield_pct}% · ${point.row.lots}批`; });
  $('#yieldChart').addEventListener('mouseleave', () => $('#chartTooltip').hidden=true);
  window.addEventListener('resize', () => {
    restoreAgentPanelWidth();
    state.dashboard && drawYieldChart(state.dashboard.yield_trend);
  });
  document.documentElement.dataset.appReady = 'true';
}

document.addEventListener('DOMContentLoaded', init);
