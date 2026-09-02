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


function sourceNavigationAttributes(source) {
  const documentAttribute = source.document_id ? ` data-source-document-id="${escapeHtml(source.document_id)}"` : '';
  if (source.source_type === 'case' || source.case_id) return `data-case-id="${escapeHtml(source.case_id)}"${documentAttribute}`;
  if (source.source_type === 'personal') return `data-personal-chunk="${escapeHtml(source.chunk_id)}"${documentAttribute}`;
  return `data-knowledge-chunk="${Number(source.chunk_id)}"${documentAttribute}`;
}

function sourceLink(source, label = '') {
  const attributes = sourceNavigationAttributes(source);
  if (label) return `<button type="button" class="source-link" ${attributes}>${escapeHtml(label)}</button>`;
  const name = sourcePresenter.displayName(source);
  const location = sourcePresenter.locationLabel(source);
  const documentAttribute = source.document_id ? ` data-source-document-id="${escapeHtml(source.document_id)}"` : '';
  return `<button type="button" class="citation-link" ${attributes}>[来源：<span class="source-document-name"${documentAttribute}>${escapeHtml(name)}</span>${location ? ` · ${escapeHtml(location)}` : ''}]</button>`;
}

function sourceReferenceMap(sources = []) {
  return sourcePresenter.referenceMap(sources);
}

function renderSourcePanel(sources = []) {
  const groups = sourcePresenter.groupSources(sources);
  if (!groups.length) return '';
  const body = groups.map(group => {
    const documentAttribute = group.documentId ? ` data-source-document-id="${escapeHtml(group.documentId)}"` : '';
    const links = group.items.map(source => sourceLink(source, sourcePresenter.locationLabel(source) || '打开来源')).join('');
    return `<section class="source-group"><div class="source-group-heading"><strong class="source-document-name"${documentAttribute}>${escapeHtml(group.name)}</strong><span>${escapeHtml(group.type)}</span></div><div class="source-locations">${links}</div></section>`;
  }).join('');
  return `<details class="source-list"><summary><span>知识来源</span><small>${groups.length} 份资料 · ${sources.length} 处引用</small></summary><div class="source-list-body">${body}</div></details>`;
}

function inlineMarkdown(value, sourceReferences = new Map()) {
  let text = escapeHtml(value);
  text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  text = text.replace(/\[来源(?:\s+chunk_id\s*:)?\s*([A-Za-z0-9,，、\-\s]+)\]/gi, (match, ids) => {
    const references = ids.split(/[,，、\s]+/).filter(Boolean).map(id => sourceReferences.get(id) || sourceReferences.get(`KB-${id}`)).filter(Boolean);
    return references.length ? references.map(source => sourceLink(source)).join(' ') : match;
  });
  return text;
}

function markdownCells(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
}

function renderMarkdown(markdown, sourceReferences = new Map()) {
  const lines = String(markdown || '').replace(/\r/g, '').split('\n');
  const output = [];
  let index = 0;
  const isBlockStart = line => /^(#{1,4})\s+/.test(line) || /^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line) || /^>\s?/.test(line) || /^```/.test(line) || /^\s*---+\s*$/.test(line);
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }
    if (/^```/.test(line)) {
      const code = []; index += 1;
      while (index < lines.length && !/^```/.test(lines[index])) { code.push(lines[index]); index += 1; }
      index += index < lines.length ? 1 : 0;
      output.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`); continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) { const level = Math.min(4, heading[1].length + 1); output.push(`<h${level}>${inlineMarkdown(heading[2], sourceReferences)}</h${level}>`); index += 1; continue; }
    if (/^\s*---+\s*$/.test(line)) { output.push('<hr>'); index += 1; continue; }
    if (line.includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) {
      const headers = markdownCells(line); index += 2; const rows = [];
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) { rows.push(markdownCells(lines[index])); index += 1; }
      output.push(`<div class="markdown-table-wrap"><table><thead><tr>${headers.map(cell => `<th>${inlineMarkdown(cell, sourceReferences)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${headers.map((_, i) => `<td>${inlineMarkdown(row[i] || '', sourceReferences)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`); continue;
    }
    if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line), tag = ordered ? 'ol' : 'ul', items = [];
      const pattern = ordered ? /^\s*\d+\.\s+(.+)$/ : /^\s*[-*]\s+(.+)$/;
      while (index < lines.length) { const match = lines[index].match(pattern); if (!match) break; items.push(match[1]); index += 1; }
      output.push(`<${tag}>${items.map(item => `<li>${inlineMarkdown(item, sourceReferences)}</li>`).join('')}</${tag}>`); continue;
    }
    if (/^>\s?/.test(line)) {
      const quote = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) { quote.push(lines[index].replace(/^>\s?/, '')); index += 1; }
      output.push(`<blockquote>${quote.map(item => inlineMarkdown(item, sourceReferences)).join('<br>')}</blockquote>`); continue;
    }
    const paragraph = [line.trim()]; index += 1;
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index]) && !(lines[index].includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1]))) { paragraph.push(lines[index].trim()); index += 1; }
    output.push(`<p>${inlineMarkdown(paragraph.join(' '), sourceReferences)}</p>`);
  }
  return output.join('');
}

const knowledgeController = globalThis.FabKnowledgeController.createKnowledgeController({ state, $, escapeHtml, formatFileSize, api, identityHeaders, showToast, processLabels, renderMarkdown, showView, newClientMessageId, personalKnowledgeMetadata, personalJobEvents, personalUploadQueue });
const { renderKnowledgeDocuments, personalKnowledgeStatusLabel, resetKnowledgeReader, renderPersonalKnowledgeDocuments, schedulePersonalKnowledgeRefresh, personalKnowledgeProcessing, stopPersonalJobEvents, debouncePersonalKnowledgeEventRefresh, personalJobEventHeaders, enablePersonalJobEventsFallback, startPersonalJobEvents, loadPersonalKnowledgeDocuments, personalKnowledgeMeta, renderPersonalKnowledgeContent, openPersonalKnowledgeDocument, openPersonalKnowledgeChunk, setKnowledgeMode, renderKnowledgeUploadQueue, mergeKnowledgeUploadFiles, showKnowledgeUploadMessage, resetKnowledgeUploadForm, openKnowledgeUploadDialog, uploadPersonalKnowledge, retrySelectedPersonalKnowledge, openPersonalKnowledgeMetadataDialog, refreshRenderedPersonalSourceName, savePersonalKnowledgeMetadata, openPersonalKnowledgeDeleteDialog, deleteSelectedPersonalKnowledge, downloadSelectedPersonalKnowledge, loadKnowledgeIndex, openKnowledgeChunk, renderCaseList, loadCaseIndex, openHistoricalCase } = knowledgeController;
const modelController = globalThis.FabModelController.createModelController({ state, $, escapeHtml, api, showToast, updateSystemStatus, thinkingControl });
const { renderModelConfig, syncThinkingToggle, thinkingEnabled, toggleThinking, loadModelConfig, openModelSettings, saveModelSettings } = modelController;
const dashboardController = globalThis.FabDashboardController.createDashboardController({ state, $, escapeHtml, formatNumber, api, processLabels });
const { renderKpis, renderEquipment, renderDefects, renderExcursions, drawYieldChart, loadDashboard, capabilityRating, loadCapability, renderCapability } = dashboardController;
function formatDuration(milliseconds) {
  if (milliseconds == null) return '—';
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  return `${(milliseconds / 1000).toFixed(2)} s`;
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall through when Clipboard API exists but the browser denies permission.
    }
  }
  const textarea = document.createElement('textarea');
  textarea.value = text; textarea.setAttribute('readonly', ''); textarea.style.position = 'fixed'; textarea.style.opacity = '0';
  document.body.appendChild(textarea); textarea.select();
  const copied = document.execCommand('copy'); textarea.remove();
  if (!copied) throw new Error('浏览器未允许复制');
}

function renderToolTrace(trace, runId) {
  if (!trace?.length) return '';
  const items = trace.map((item, index) => {
    const status = item.status === 'error' ? '失败' : (item.status === 'blocked' ? '已拦截' : (item.status === 'local' ? '本地' : (item.status === 'running' ? '进行中' : '成功')));
    const result = item.rows == null ? status : `${status} · ${item.rows} 条结果`;
    const error = item.error ? `<p class="trace-error">${escapeHtml(item.error)}</p>` : '';
    const statusClass = item.status === 'error' ? 'error' : (item.status === 'blocked' ? 'blocked' : (item.status === 'running' ? 'running' : 'ok'));
    return `<li><div class="trace-step-heading"><span>${index + 1}. ${escapeHtml(item.label || toolLabels[item.tool] || item.tool || '未知工具')}</span><small class="trace-status-${statusClass}">${result}</small></div>${error}</li>`;
  }).join('');
  const failed = trace.some(item => item.status === 'error');
  const blocked = trace.some(item => item.status === 'blocked');
  const duration = trace.reduce((sum, item) => sum + Number(item.duration_ms || 0), 0);
  const summary = failed ? `执行路径异常 · ${trace.length} 个工具` : (blocked ? `执行路径受限 · ${trace.length} 个工具` : `执行路径已完成 · ${trace.length} 个工具${duration ? ` · ${formatDuration(duration)}` : ''}`);
  const runLabel = runId ? `<span title="${escapeHtml(runId)}">运行 ${escapeHtml(runId.slice(0, 8))}</span>` : '';
  return `<details class="analysis-trace" ${failed ? 'open' : ''}><summary><span>${summary}</span><small>可展开</small></summary><ol>${items}</ol><div class="trace-footer"><span>可审计工具路径，不包含模型内部草稿</span>${runLabel}</div></details>`;
}

function welcomeMarkup(message = '我可以查询制造报表、定位设备异常，并结合厂内 SOP 给出分析建议。') {
  return `<div class="message assistant"><div class="message-meta"><div class="message-label">FAB COPILOT</div></div><div class="message-content">${escapeHtml(message)}</div></div><div class="suggestions"><button>最近三个月哪些设备风险最高？</button><button>CVD-02 的膜厚是否发生漂移？</button><button>分析刻蚀设备 CD 偏移的潜在原因</button></div>`;
}

function renderConversation(messages = []) {
  const container = $('#chatMessages'); container.innerHTML = ''; state.history = [];
  if (!messages.length) { container.innerHTML = welcomeMarkup(); return; }
  for (const item of messages) {
    addMessage(item.role, item.content, item.metadata || {});
    state.history.push({role:item.role, content:item.content});
  }
}

async function createConversation(message) {
  const session = await api('/api/sessions', {method:'POST'});
  state.sessionId = session.session_id; state.history = [];
  localStorage.setItem('fabInsightSessionId', state.sessionId);
  renderConversation([]);
  if (message) $('#chatMessages').innerHTML = welcomeMarkup(message);
  return session;
}

async function restoreConversation() {
  const savedSessionId = localStorage.getItem('fabInsightSessionId');
  if (savedSessionId) {
    try {
      const session = await api(`/api/sessions/${encodeURIComponent(savedSessionId)}`);
      state.sessionId = session.session_id; renderConversation(session.messages);
      $('#agentMode').textContent = session.messages.length ? `已恢复 · ${session.messages.length} 条消息` : '数据分析助手';
      return;
    } catch { localStorage.removeItem('fabInsightSessionId'); }
  }
  await createConversation();
}

function sessionGroup(timestamp) {
  const value = new Date(timestamp);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const day = new Date(value); day.setHours(0, 0, 0, 0);
  const distance = Math.round((today - day) / 86400000);
  if (distance === 0) return '今天';
  if (distance === 1) return '昨天';
  if (distance < 7) return '最近 7 天';
  return '更早';
}

async function openSession(sessionId) {
  const session = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
  state.sessionId = session.session_id;
  localStorage.setItem('fabInsightSessionId', state.sessionId);
  renderConversation(session.messages);
  $('#agentMode').textContent = session.messages.length ? `已恢复 · ${session.messages.length} 条消息` : '数据分析助手';
}

function filteredSessionLibrary() {
  if (state.sessionLibraryFilter === 'archived') return state.sessionLibrary.filter(item => item.archived_at);
  if (state.sessionLibraryFilter === 'active') return state.sessionLibrary.filter(item => !item.archived_at);
  return state.sessionLibrary;
}

function updateSessionBatchToolbar() {
  const visible = filteredSessionLibrary();
  const selectedVisible = visible.filter(item => state.selectedSessionIds.has(item.session_id));
  const selectAll = $('#sessionBatchSelectAll');
  selectAll.checked = visible.length > 0 && selectedVisible.length === visible.length;
  selectAll.indeterminate = selectedVisible.length > 0 && selectedVisible.length < visible.length;
  selectAll.disabled = visible.length === 0;
  $('#sessionBatchCount').textContent = `已选 ${state.selectedSessionIds.size} 个会话`;
  $('#deleteSelectedSessions').disabled = state.selectedSessionIds.size === 0;
}

function setSessionBatchMode(active) {
  state.sessionBatchMode = Boolean(active);
  if (!state.sessionBatchMode) state.selectedSessionIds.clear();
  $('#sessionsView').classList.toggle('batch-mode', state.sessionBatchMode);
  $('#sessionBatchToolbar').hidden = !state.sessionBatchMode;
  $('#sessionBatchManage').textContent = state.sessionBatchMode ? '结束批量管理' : '批量管理';
  $('#sessionBatchManage').setAttribute('aria-pressed', String(state.sessionBatchMode));
  renderSessionLibrary();
}

function clearSessionBatchSelection() {
  if (!state.selectedSessionIds.size) return;
  state.selectedSessionIds.clear();
  renderSessionLibrary();
}

function renderSessionLibrary() {
  const sessions = filteredSessionLibrary();
  const groups = new Map();
  for (const session of sessions) {
    const group = sessionGroup(session.updated_at);
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(session);
  }
  const archivedCount = state.sessionLibrary.filter(item => item.archived_at).length;
  $('#sessionLibraryCount').textContent = `${sessions.length} 个结果 · ${archivedCount} 个已归档`;
  $('#sessionBatchManage').disabled = sessions.length === 0 && !state.sessionBatchMode;
  $('#sessionLibraryNotice').textContent = state.sessionLibraryFilter === 'archived'
    ? '已归档会话仍保存在 AI 运营库中；恢复后会重新出现在活跃会话中。'
    : state.sessionLibraryFilter === 'all'
      ? '这里同时显示活跃与归档会话；归档可以恢复，删除无法撤销。'
      : '归档只会将会话移出活跃列表；删除会移除全部消息和分析记录。';
  $('#sessionLibraryList').innerHTML = [...groups.entries()].map(([group, items]) => `
    <section class="session-library-group"><h3>${group}</h3>${items.map(session => {
      const active = session.session_id === state.selectedLibrarySessionId ? ' active' : '';
      const selected = state.selectedSessionIds.has(session.session_id) ? ' batch-selected' : '';
      const timestamp = new Date(session.updated_at).toLocaleString('zh-CN', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false});
      const archived = Boolean(session.archived_at);
      const actions = archived
        ? '<button type="button" data-library-action="restore">恢复会话</button><button type="button" class="danger-action" data-library-action="delete">删除</button>'
        : '<button type="button" data-library-action="rename">重命名</button><button type="button" data-library-action="archive">归档</button><button type="button" class="danger-action" data-library-action="delete">删除</button>';
      return `<article class="session-library-item${active}${selected}" data-library-session-id="${escapeHtml(session.session_id)}"><input class="session-select-checkbox" type="checkbox" aria-label="选择 ${escapeHtml(session.title)}" ${selected ? 'checked' : ''}><button class="session-library-open" type="button"><strong>${escapeHtml(session.title)}</strong><span>${timestamp} · ${session.message_count} 条消息${session.model ? ` · ${escapeHtml(session.model)}` : ''}</span><small>${escapeHtml(session.last_message_preview || '空会话')}</small></button><span class="session-state${archived ? ' archived' : ''}">${archived ? '已归档' : '活跃'}</span><details class="session-item-menu"><summary title="会话操作" aria-label="会话操作">⋯</summary><div>${actions}</div></details></article>`;
    }).join('')}</section>`).join('') || '<p class="empty session-empty">没有匹配的历史会话</p>';
  updateSessionBatchToolbar();
}

function renderSessionLibraryPreview(session) {
  state.selectedLibrarySessionId = session.session_id;
  renderSessionLibrary();
  $('#sessionLibraryReference').textContent = `CONVERSATION · ${session.session_id.slice(0, 8)}`;
  $('#sessionLibraryTitle').textContent = session.title;
  const created = new Date(session.created_at).toLocaleString('zh-CN', {hour12:false});
  const updated = new Date(session.updated_at).toLocaleString('zh-CN', {hour12:false});
  $('#sessionLibraryMeta').innerHTML = `<span>${session.archived_at ? '已归档' : '活跃会话'}</span><span>${session.messages.length} 条消息</span>${session.model ? `<span>${escapeHtml(session.model)}</span>` : ''}<span>创建 ${created}</span><span>更新 ${updated}</span>`;
  $('#sessionLibraryActions').hidden = false;
  $('#archiveLibrarySession').textContent = session.archived_at ? '恢复会话' : '归档';
  $('#deleteLibrarySession').hidden = false;
  $('#continueLibrarySession').textContent = session.archived_at ? '恢复并继续' : '在助手中继续';
  $('#sessionLibraryMessages').innerHTML = session.messages.map(item => {
    const assistant = item.role === 'assistant';
    const messageSources = item.metadata?.sources || [];
    const content = assistant
      ? renderMarkdown(sourcePresenter.stripSourceAppendix(item.content), sourceReferenceMap(messageSources))
      : escapeHtml(item.content).replace(/\n/g, '<br>');
    const timestamp = new Date(item.created_at).toLocaleString('zh-CN', {hour12:false});
    const sources = assistant ? renderSourcePanel(messageSources) : '';
    return `<section class="session-transcript-item ${assistant ? 'assistant' : 'user'}"><div class="session-transcript-heading"><strong>${assistant ? 'FAB COPILOT' : '使用者'}</strong><time>${timestamp}</time></div><div class="session-transcript-content markdown-content">${content}${sources}</div></section>`;
  }).join('') || '<p class="empty">该会话尚无消息。</p>';
}

async function openSessionLibraryPreview(sessionId) {
  const requestId = ++state.sessionLibraryPreviewRequestId;
  const session = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
  if (requestId !== state.sessionLibraryPreviewRequestId) return;
  renderSessionLibraryPreview(session);
}

async function loadSessionLibrary(query = $('#sessionLibrarySearch').value) {
  const requestId = ++state.sessionLibraryRequestId;
  const sessions = await api(`/api/sessions?q=${encodeURIComponent(query)}&limit=200&include_archived=true`);
  if (requestId !== state.sessionLibraryRequestId) return;
  state.sessionLibrary = sessions;
  const visible = filteredSessionLibrary();
  const visibleIds = new Set(visible.map(item => item.session_id));
  state.selectedSessionIds = new Set([...state.selectedSessionIds].filter(sessionId => visibleIds.has(sessionId)));
  const selected = visible.find(item => item.session_id === state.selectedLibrarySessionId) || visible[0];
  if (selected) await openSessionLibraryPreview(selected.session_id);
  else {
    state.selectedLibrarySessionId = null;
    renderSessionLibrary();
    $('#sessionLibraryReference').textContent = 'CONVERSATION';
    $('#sessionLibraryTitle').textContent = '选择一个历史会话';
    $('#sessionLibraryMeta').innerHTML = '';
    $('#sessionLibraryActions').hidden = true;
    $('#deleteLibrarySession').hidden = true;
    $('#sessionLibraryMessages').innerHTML = '<p class="empty">当前筛选条件下没有会话。</p>';
  }
}

function updateSessionRenameCount() {
  $('#sessionRenameCount').textContent = `${$('#sessionRenameInput').value.length} / 80`;
}

function openSessionRenameDialog(sessionId = state.selectedLibrarySessionId) {
  const session = state.sessionLibrary.find(item => item.session_id === sessionId);
  if (!session) return;
  state.pendingRenameSessionId = session.session_id;
  $('#sessionRenameInput').value = session.title;
  $('#sessionRenameMessage').hidden = true;
  updateSessionRenameCount();
  $('#sessionRenameDialog').showModal();
  requestAnimationFrame(() => $('#sessionRenameInput').select());
}

async function renameSelectedLibrarySession() {
  if ($('#confirmSessionRename').disabled) return;
  const sessionId = state.pendingRenameSessionId;
  const session = state.sessionLibrary.find(item => item.session_id === sessionId);
  const title = $('#sessionRenameInput').value.trim();
  if (!session) return;
  if (!title) {
    $('#sessionRenameMessage').textContent = '会话标题不能为空。';
    $('#sessionRenameMessage').hidden = false;
    $('#sessionRenameInput').focus();
    return;
  }
  if (title === session.title) {
    $('#sessionRenameDialog').close();
    return;
  }
  $('#confirmSessionRename').disabled = true;
  $('#sessionRenameMessage').hidden = true;
  try {
    await api(`/api/sessions/${encodeURIComponent(session.session_id)}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title})});
    $('#sessionRenameDialog').close();
    await loadSessionLibrary();
    showToast('会话已重命名');
  } catch (error) {
    $('#sessionRenameMessage').textContent = `保存失败：${error.message}`;
    $('#sessionRenameMessage').hidden = false;
  } finally {
    $('#confirmSessionRename').disabled = false;
  }
}

function resetConversationDraft(message = '已准备新会话。') {
  state.sessionId = null;
  state.history = [];
  localStorage.removeItem('fabInsightSessionId');
  renderConversation([]);
  $('#agentMode').textContent = message;
}

async function archiveLibrarySession(sessionId) {
  const session = state.sessionLibrary.find(item => item.session_id === sessionId);
  if (!session || session.archived_at) return;
  const wasCurrent = session.session_id === state.sessionId;
  await api(`/api/sessions/${encodeURIComponent(session.session_id)}`, {method:'DELETE'});
  if (wasCurrent) resetConversationDraft('当前会话已归档');
  state.selectedLibrarySessionId = null;
  const refresh = loadSessionLibrary();
  showToast(`已归档“${session.title}”`, {
    actionLabel: '撤销',
    onAction: async () => {
      await api(`/api/sessions/${encodeURIComponent(session.session_id)}/restore`, {method:'POST'});
      state.selectedLibrarySessionId = session.session_id;
      if (wasCurrent) await openSession(session.session_id);
      await loadSessionLibrary();
      showToast('已撤销归档');
    },
  });
  await refresh;
}

async function restoreLibrarySession(sessionId) {
  const session = state.sessionLibrary.find(item => item.session_id === sessionId);
  if (!session || !session.archived_at) return;
  await api(`/api/sessions/${encodeURIComponent(session.session_id)}/restore`, {method:'POST'});
  state.selectedLibrarySessionId = null;
  const refresh = loadSessionLibrary();
  showToast(`已恢复“${session.title}”`, {
    actionLabel: '撤销',
    onAction: async () => {
      await api(`/api/sessions/${encodeURIComponent(session.session_id)}`, {method:'DELETE'});
      if (session.session_id === state.sessionId) resetConversationDraft('当前会话已归档');
      await loadSessionLibrary();
      showToast('已撤销恢复');
    },
  });
  await refresh;
}

function openSessionDeleteDialog(sessionIds) {
  const requestedIds = Array.isArray(sessionIds) ? sessionIds : [sessionIds];
  const requested = new Set(requestedIds.filter(Boolean));
  const sessions = state.sessionLibrary.filter(item => requested.has(item.session_id));
  if (!sessions.length) return;
  state.pendingDeleteSessionIds = sessions.map(item => item.session_id);
  if (sessions.length === 1) {
    $('#sessionDeleteMessage').textContent = `“${sessions[0].title}”将从本系统中删除。`;
  } else {
    const archivedCount = sessions.filter(item => item.archived_at).length;
    const activeCount = sessions.length - archivedCount;
    $('#sessionDeleteMessage').textContent = `将删除 ${sessions.length} 个会话，其中 ${activeCount} 个活跃会话、${archivedCount} 个已归档会话。`;
  }
  $('#sessionDeleteDialog').showModal();
}

async function permanentlyDeleteSelectedSession() {
  const sessionIds = [...state.pendingDeleteSessionIds];
  const sessionIdSet = new Set(sessionIds);
  const sessions = state.sessionLibrary.filter(item => sessionIdSet.has(item.session_id));
  if (!sessionIds.length || !sessions.length) return;
  $('#confirmSessionDelete').disabled = true;
  try {
    if (sessionIds.length === 1) {
      await api(`/api/sessions/${encodeURIComponent(sessionIds[0])}/permanent`, {method:'DELETE'});
    } else {
      await api('/api/sessions/bulk-delete', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_ids:sessionIds})});
    }
    if (sessionIdSet.has(state.sessionId)) resetConversationDraft('当前会话已删除');
    state.pendingDeleteSessionIds = [];
    state.selectedLibrarySessionId = null;
    state.selectedSessionIds.clear();
    $('#sessionDeleteDialog').close();
    setSessionBatchMode(false);
    const refresh = loadSessionLibrary();
    showToast(sessions.length === 1 ? `已删除“${sessions[0].title}”` : `已删除 ${sessions.length} 个会话`);
    await refresh;
  } finally {
    $('#confirmSessionDelete').disabled = false;
  }
}

async function runSessionLibraryAction(sessionId, action) {
  state.selectedLibrarySessionId = sessionId;
  try {
    if (action === 'rename') openSessionRenameDialog(sessionId);
    else if (action === 'archive') await archiveLibrarySession(sessionId);
    else if (action === 'restore') await restoreLibrarySession(sessionId);
    else if (action === 'delete') openSessionDeleteDialog(sessionId);
  } catch (error) {
    showToast(`操作失败：${error.message}`, {tone:'error'});
  }
}

async function toggleSelectedLibrarySessionArchive() {
  const session = state.sessionLibrary.find(item => item.session_id === state.selectedLibrarySessionId);
  if (!session) return;
  await runSessionLibraryAction(session.session_id, session.archived_at ? 'restore' : 'archive');
}

async function continueSelectedLibrarySession() {
  const session = state.sessionLibrary.find(item => item.session_id === state.selectedLibrarySessionId);
  if (!session || state.streaming) return;
  if (session.archived_at) {
    await api(`/api/sessions/${encodeURIComponent(session.session_id)}/restore`, {method:'POST'});
    showToast('会话已恢复到活跃列表');
  }
  await openSession(session.session_id);
  showView(state.previousView || 'dashboard');
  setAgentOpen(true);
}

function openSessionLibraryWorkspace() {
  if (state.streaming) return;
  showView('sessions');
  if (window.innerWidth <= 700) setAgentOpen(false, false);
  $('#sessionsView').scrollIntoView({behavior:'smooth', block:'start'});
}

function closeSessionLibraryWorkspace() {
  showView(state.previousView || 'dashboard');
}

function createLiveAnalysis() {
  const el = document.createElement('div'); el.className = 'message assistant live-analysis';
  el.innerHTML = '<div class="message-meta"><div class="message-label">FAB COPILOT · 分析中</div><span class="live-indicator">运行中</span></div><details class="live-path" open><summary><span class="live-path-title">正在建立分析路径</span><small class="live-path-count">准备中</small></summary><div class="live-path-body"><ol></ol><div class="trace-footer"><span>工具调用会在执行时实时更新</span><span class="live-run-id"></span></div></div></details><div class="message-content markdown-content streaming-answer" hidden></div>';
  $('#chatMessages').appendChild(el); $('#chatMessages').scrollTop = $('#chatMessages').scrollHeight;
  const live = {
    el, steps: [], runId: null, buffer: new FabSmoothTextBuffer(), telemetry: new FabStreamDiagnostics(),
    markdownStream: new FabIncrementalMarkdown(), markdownNodes: null,
    renderTimer: null, drainResolvers: [], firstToken: false, cancelled: false,
    renderDelay: 32, lastRenderedText: '', stallTimer: null, visibilityHandler: null, caret: null,
  };
  live.visibilityHandler = () => {
    if (document.hidden || live.cancelled || !live.buffer.pendingLength) return;
    live.telemetry.markVisibleResume();
    if (live.renderTimer) window.clearTimeout(live.renderTimer);
    live.renderTimer = null;
    scheduleLiveAnswerFrame(live, 0);
  };
  document.addEventListener('visibilitychange', live.visibilityHandler);
  return live;
}

function renderLiveAnalysis(live) {
  live.el.querySelector('.live-path-title').textContent = live.steps.at(-1)?.label || '正在建立分析路径';
  live.el.querySelector('.live-path-count').textContent = `${live.steps.length} 步`;
  live.el.querySelector('ol').innerHTML = live.steps.map((item, index) => {
    const status = item.status === 'error' ? '失败' : (item.status === 'blocked' ? '已拦截' : (item.status === 'running' ? '进行中' : '完成'));
    const statusClass = item.status === 'error' ? 'error' : (item.status === 'blocked' ? 'blocked' : (item.status === 'running' ? 'running' : 'ok'));
    const result = item.rows == null ? status : `${status} · ${item.rows} 条结果`;
    return `<li><div class="trace-step-heading"><span>${index + 1}. ${escapeHtml(item.label)}</span><small class="trace-status-${statusClass}">${result}</small></div>${item.error ? `<p class="trace-error">${escapeHtml(item.error)}</p>` : ''}</li>`;
  }).join('');
  live.el.querySelector('.live-run-id').textContent = live.runId ? `运行 ${live.runId.slice(0, 8)}` : '';
  const container = $('#chatMessages');
  if (container.scrollHeight - container.scrollTop - container.clientHeight < 120) container.scrollTop = container.scrollHeight;
}

function startLiveAnswer(live) {
  if (live.firstToken) return;
  live.firstToken = true;
  live.el.querySelector('.live-indicator').textContent = '生成中';
  const running = live.steps.at(-1); if (running?.status === 'running') running.status = 'ok';
  const path = live.el.querySelector('.live-path');
  path.open = false;
  const toolSteps = live.steps.filter(step => step.tool);
  const pathLabel = toolSteps.some(step => step.status === 'error') ? '执行路径异常' : (toolSteps.some(step => step.status === 'blocked') ? '执行路径受限' : '执行路径已完成');
  live.el.querySelector('.live-path-title').textContent = `${pathLabel} · ${toolSteps.length} 个工具`;
  live.el.querySelector('.live-path-count').textContent = '可展开';
  live.el.querySelector('.streaming-answer').hidden = false;
  live.el.querySelector('.streaming-answer').setAttribute('aria-busy', 'true');
  live.el.classList.add('answer-streaming');
}

function resolveLiveAnswerDrain(live) {
  if (!live.buffer.done) return;
  for (const resolve of live.drainResolvers.splice(0)) resolve();
}

function renderLiveAnswerFrame(live) {
  live.renderTimer = null;
  if (live.cancelled) return;
  const container = $('#chatMessages');
  const follow = container.scrollHeight - container.scrollTop - container.clientHeight < 120;
  const answer = live.el.querySelector('.streaming-answer');
  const renderStarted = performance.now();
  const visible = live.buffer.takeNext({
    targetFrames: live.buffer.complete ? 24 : 14,
    minChars: 2,
    maxChars: live.buffer.complete ? 32 : 24,
  });
  if (visible !== live.lastRenderedText) {
    if (!live.markdownNodes) {
      answer.innerHTML = '<div class="streaming-stable"></div><div class="streaming-tail"></div>';
      live.markdownNodes = {
        stable: answer.querySelector('.streaming-stable'),
        tail: answer.querySelector('.streaming-tail'),
      };
    }
    const patch = live.markdownStream.update(visible);
    live.caret?.remove();
    if (patch.reset) live.markdownNodes.stable.replaceChildren();
    if (patch.stableDelta) {
      live.markdownNodes.stable.insertAdjacentHTML('beforeend', renderMarkdown(patch.stableDelta));
    }
    live.markdownNodes.tail.innerHTML = renderMarkdown(patch.presentableTail);
    const caretTarget = live.markdownNodes.tail.lastElementChild || live.markdownNodes.stable.lastElementChild;
    if (caretTarget) {
      live.caret = document.createElement('span');
      live.caret.className = 'streaming-caret';
      live.caret.setAttribute('aria-hidden', 'true');
      caretTarget.appendChild(live.caret);
    }
    const visibleStep = patch.reset ? visible.length : visible.length - live.lastRenderedText.length;
    live.telemetry.markIncrementalRender(patch.stableDelta.length, patch.tail.length, visibleStep, patch.reset);
    live.lastRenderedText = visible;
  }
  const renderDuration = performance.now() - renderStarted;
  live.telemetry.markRender(renderDuration);
  live.renderDelay = Math.min(80, Math.max(28, renderDuration * 3));
  if (follow) container.scrollTop = container.scrollHeight;
  if (live.buffer.pendingLength) {
    live.renderTimer = window.setTimeout(() => renderLiveAnswerFrame(live), live.renderDelay);
  } else {
    resolveLiveAnswerDrain(live);
  }
}

function scheduleLiveAnswerFrame(live, delay = live.renderDelay) {
  if (live.cancelled || live.renderTimer || !live.buffer.pendingLength) return;
  live.renderTimer = window.setTimeout(() => renderLiveAnswerFrame(live), delay);
}

function armLiveAnswerStall(live) {
  if (live.stallTimer) window.clearTimeout(live.stallTimer);
  live.el.querySelector('.live-indicator').textContent = '生成中';
  live.stallTimer = window.setTimeout(() => {
    if (!live.cancelled && live.firstToken && !live.buffer.complete) {
      live.el.querySelector('.live-indicator').textContent = '模型继续生成中';
    }
  }, 1500);
}

function appendLiveAnswer(live, delta) {
  if (!delta || live.cancelled) return;
  live.buffer.append(delta);
  live.telemetry.markPending(live.buffer.pendingLength);
  if (!live.firstToken) {
    startLiveAnswer(live);
  }
  armLiveAnswerStall(live);
  scheduleLiveAnswerFrame(live);
}

async function finishLiveAnswer(live, finalAnswer) {
  live.buffer.finish(finalAnswer);
  live.telemetry.markPending(live.buffer.pendingLength);
  if (live.buffer.received && !live.firstToken) startLiveAnswer(live);
  live.el.querySelector('.live-indicator').textContent = live.buffer.done ? '完成' : '输出中';
  if (live.stallTimer) window.clearTimeout(live.stallTimer);
  live.stallTimer = null;
  scheduleLiveAnswerFrame(live, 0);
  if (!live.buffer.done) await new Promise(resolve => live.drainResolvers.push(resolve));
  live.el.querySelector('.streaming-answer').setAttribute('aria-busy', 'false');
  document.removeEventListener('visibilitychange', live.visibilityHandler);
}

function cancelLiveAnswer(live) {
  live.cancelled = true;
  if (live.renderTimer) window.clearTimeout(live.renderTimer);
  if (live.stallTimer) window.clearTimeout(live.stallTimer);
  live.renderTimer = null;
  live.stallTimer = null;
  document.removeEventListener('visibilitychange', live.visibilityHandler);
  for (const resolve of live.drainResolvers.splice(0)) resolve();
}

function updateLiveAnalysis(live, event) {
  if (event.event === 'run_started') {
    live.runId = event.run_id;
    live.steps.push({label:'建立分析任务', status:'ok'});
  } else if (event.event === 'stage') {
    const previous = live.steps.at(-1); if (previous?.status === 'running') previous.status = 'ok';
    live.steps.push({label:event.message || '规划下一步', status:'running'});
  } else if (event.event === 'tool_started') {
    const previous = live.steps.at(-1); if (previous?.status === 'running') previous.status = 'ok';
    live.steps.push({tool:event.tool, label:toolLabels[event.tool] || event.tool, status:'running'});
  } else if (event.event === 'tool_finished') {
    const item = [...live.steps].reverse().find(step => step.tool === event.tool && step.status === 'running');
    if (item) Object.assign(item, {status:event.status || 'ok', rows:event.rows, error:event.error});
  } else if (event.event === 'run_failed') {
    live.steps.push({label:event.message || '分析失败', status:'error'});
    live.el.querySelector('.live-path').open = true;
  } else if (event.event === 'answer_delta') {
    appendLiveAnswer(live, event.delta);
    return;
  }
  renderLiveAnalysis(live);
}

async function streamAgent(message, clientMessageId, onProgress, diagnostics, useThinking = false) {
  let response;
  try {
    const payload = thinkingControl.requestPayload({message, session_id:state.sessionId, client_message_id:clientMessageId}, state.modelConfig, useThinking);
    const headers = identityHeaders({'Content-Type':'application/json'});
    response = await fetch('/api/chat/stream', {method:'POST', headers, body:JSON.stringify(payload)});
  } catch {
    throw new FabApiError('无法连接 Fab Insight 服务', {code:'NETWORK_ERROR', retryable:true});
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw apiError(payload, response);
  }
  if (!response.body) throw new FabApiError('浏览器不支持流式响应', {code:'STREAM_UNSUPPORTED'});
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = '', finalResult = null;
  while (true) {
    const {value, done} = await reader.read();
    if (value?.length) diagnostics.markRead();
    buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
    const lines = buffer.split('\n'); buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === 'session') {
        state.sessionId = event.session_id; localStorage.setItem('fabInsightSessionId', state.sessionId);
      } else if (event.type === 'progress') {
        diagnostics.markProgress(event);
        onProgress(event);
      }
      else if (event.type === 'result') finalResult = event.result;
      else if (event.type === 'error') throw apiError(event.error || {detail:event.detail || '分析失败'}, response);
    }
    if (done) break;
  }
  if (!finalResult) throw new FabApiError('分析结束但未收到结果', {code:'STREAM_INCOMPLETE', requestId:response.headers.get('x-request-id') || '', retryable:true});
  return finalResult;
}

function reportStreamTelemetry(live, finalAnswer) {
  const payload = live.telemetry.finish(live.buffer.received === String(finalAnswer || ''));
  if (!payload.run_id) return;
  fetch('/api/telemetry/stream', {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload), keepalive: true,
  }).catch(() => {});
}

function renderAssistantInto(el, content, extra = {}) {
  const sources = extra.sources || [];
  const renderedContent = renderMarkdown(sourcePresenter.stripSourceAppendix(content), sourceReferenceMap(sources));
  const sourcePanel = renderSourcePanel(sources);
  const copyButton = '<button type="button" class="copy-answer" title="复制回答" aria-label="复制回答"><span aria-hidden="true">⧉</span><span>复制</span></button>';
  el.className = 'message assistant';
  el.innerHTML = `<div class="message-meta"><div class="message-label">FAB COPILOT</div></div>${renderToolTrace(extra.tool_trace, extra.run_id)}<div class="message-content markdown-content">${renderedContent}</div><div class="message-actions">${copyButton}</div>${sourcePanel}`;
  const copyAnswer = el.querySelector('.copy-answer');
  copyAnswer.addEventListener('click', async () => {
    try {
      await copyText(sourcePresenter.replaceReferenceIds(content, sources));
      copyAnswer.innerHTML = '<span aria-hidden="true">✓</span><span>已复制</span>'; copyAnswer.classList.add('copied'); copyAnswer.title = '已复制';
      window.setTimeout(() => { copyAnswer.innerHTML = '<span aria-hidden="true">⧉</span><span>复制</span>'; copyAnswer.classList.remove('copied'); copyAnswer.title = '复制回答'; }, 1600);
    } catch (error) {
      copyAnswer.title = error.message; copyAnswer.classList.add('copy-error');
      window.setTimeout(() => copyAnswer.classList.remove('copy-error'), 1600);
    }
  });
}

function addMessage(role, content, extra = {}) {
  const el = document.createElement('div');
  if (role === 'assistant') {
    renderAssistantInto(el, content, extra);
  } else {
    el.className = 'message user';
    el.innerHTML = `<div class="message-meta"><div class="message-label">YOU</div></div><div class="message-content">${escapeHtml(content).replace(/\n/g,'<br>')}</div>`;
  }
  $('#chatMessages').appendChild(el);
  $('#chatMessages').scrollTop = $('#chatMessages').scrollHeight;
  return el;
}

function renderAgentRequestError(live, error, retry) {
  const labels = {
    MODEL_UPSTREAM_ERROR: '模型服务暂时不可用',
    MODEL_NETWORK_ERROR: '模型服务连接失败',
    NETWORK_ERROR: 'Fab Insight 服务连接失败',
    SESSION_NOT_FOUND: '当前会话已经失效',
  };
  const title = labels[error.code] || '分析请求未完成';
  const technical = [error.code, error.requestId ? `请求 ${error.requestId}` : ''].filter(Boolean).join(' · ');
  const answer = live.el.querySelector('.streaming-answer');
  live.el.classList.remove('answer-streaming');
  answer.hidden = false;
  answer.innerHTML = `<div class="request-error"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(error.message)}</span><div class="request-error-actions">${error.retryable ? '<button type="button" class="retry-request">重试</button>' : ''}<details><summary>错误详情</summary><code>${escapeHtml(technical || '无请求编号')}</code></details></div></div>`;
  answer.querySelector('.retry-request')?.addEventListener('click', retry);
  live.el.querySelector('.live-indicator').textContent = '失败';
}

async function sendChat(message, {clientMessageId = newClientMessageId(), isRetry = false, useThinking = thinkingEnabled()} = {}) {
  const text = message.trim(); if (!text || state.streaming) return;
  if (!state.sessionId) await createConversation();
  $('.suggestions')?.remove();
  if (!isRetry) {
    addMessage('user', text); state.history.push({role:'user', content:text});
    $('#chatInput').value = '';
    localStorage.removeItem(CHAT_DRAFT_KEY);
  }
  $('#sendButton').disabled = true; state.streaming = true;
  const live = createLiveAnalysis();
  try {
    const result = await streamAgent(text, clientMessageId, event => updateLiveAnalysis(live, event), live.telemetry, useThinking);
    await finishLiveAnswer(live, result.answer);
    reportStreamTelemetry(live, result.answer);
    renderAssistantInto(live.el, result.answer, result);
    state.history.push({role:'assistant', content:result.answer});
    $('#agentMode').textContent = result.mode === 'deepseek' ? `${state.modelConfig?.model || 'DeepSeek'} · 工具分析` : '本地规则分析';
  } catch (error) {
    cancelLiveAnswer(live);
    updateLiveAnalysis(live, {event:'run_failed', message:error.message});
    renderAgentRequestError(live, error, () => {
      live.el.remove();
      sendChat(text, {clientMessageId, isRetry:true, useThinking});
    });
  }
  finally {
    state.streaming = false; $('#sendButton').disabled = false; $('#chatInput').focus();
    if ($('#sessionsView').classList.contains('active')) loadSessionLibrary().catch(() => {});
  }
}

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
