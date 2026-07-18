const state = { dashboard: null, history: [], sessionId: null, sessionLibrary: [], sessionLibraryFilter: 'active', selectedLibrarySessionId: null, selectedSessionIds: new Set(), sessionBatchMode: false, sessionLibraryRequestId: 0, sessionLibraryPreviewRequestId: 0, pendingRenameSessionId: null, pendingDeleteSessionIds: [], toastTimer: null, activeView: 'dashboard', previousView: 'dashboard', streaming: false, chartPoints: [], activeStep: 'CVD', modelConfig: null, enterpriseContext: null, knowledgeMode: 'factory', knowledgeDocuments: [], knowledgeIndexPromise: null, personalKnowledgeDocuments: [], selectedPersonalDocumentId: null, selectedPersonalDocument: null, personalKnowledgeRequestId: 0, personalKnowledgePollTimer: null, pendingPersonalDeleteId: null, cases: [], casesPromise: null, capabilityCache: new Map(), capabilityController: null, capabilityRequestId: 0 };
const $ = (selector) => document.querySelector(selector);
const AGENT_WIDTH_KEY = 'fabInsightAgentWidth';
const CHAT_DRAFT_KEY = 'fabInsightChatDraft';
const TENANT_ID_KEY = 'fabInsightTenantId';
const USER_ID_KEY = 'fabInsightUserId';
const AGENT_MIN_WIDTH = 300;
const AGENT_MAX_WIDTH = 620;
const APP_VERSION = document.querySelector('meta[name="app-version"]')?.content || 'unknown';
const processLabels = { LITHO: '光刻', ETCH: '刻蚀', CVD: '化学气相沉积', PVD: '物理气相沉积', DIFFUSION: '扩散/炉管', IMPLANT: '离子注入', CMP: '化学机械研磨', CLEAN: '湿法清洗', METROLOGY: '量测' };
const toolLabels = { get_enterprise_data_manifest: '查询企业数据目录', get_enterprise_fab_summary: '聚合企业模拟数据', query_enterprise_data: '抽取企业模拟数据', get_fab_overview: '查询工厂总览', get_yield_trend: '查询良率趋势', get_equipment_health: '查询设备健康', get_equipment_productivity: '查询设备生产状态', get_process_capability: '查询制程能力', get_defect_pareto: '查询缺陷 Pareto', get_recent_excursions: '查询近期异常', get_sensor_summary: '查询传感器摘要', search_knowledge: '检索知识与案例', query_manufacturing_data: '执行制造数据查询' };

function isoDate(date) { return date.toISOString().slice(0, 10); }
function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function formatNumber(value) { const number = Number(value); return Number.isFinite(number) ? number.toLocaleString('zh-CN') : String(value ?? '—'); }
function formatFileSize(value) { const bytes = Number(value) || 0; if (bytes < 1024) return `${bytes} B`; if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`; return `${(bytes / 1024 ** 2).toFixed(1)} MB`; }

class FabApiError extends Error {
  constructor(message, {code = 'REQUEST_ERROR', requestId = '', retryable = false, status = 0} = {}) {
    super(message);
    this.name = 'FabApiError';
    this.code = code;
    this.requestId = requestId;
    this.retryable = retryable;
    this.status = status;
  }
}

function apiError(payload = {}, response = null) {
  return new FabApiError(payload.detail || `请求失败 (${response?.status || '网络错误'})`, {
    code: payload.error_code || 'REQUEST_ERROR',
    requestId: payload.request_id || response?.headers?.get('x-request-id') || '',
    retryable: Boolean(payload.retryable),
    status: response?.status || 0,
  });
}

function setInitialDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - 89);
  $('#startDate').value = isoDate(start);
  $('#endDate').value = isoDate(end);
}

async function api(url, options) {
  const headers = new Headers(options?.headers || {});
  const tenantId = localStorage.getItem(TENANT_ID_KEY);
  const userId = localStorage.getItem(USER_ID_KEY);
  if (tenantId) headers.set('X-Tenant-ID', tenantId);
  if (userId) headers.set('X-User-ID', userId);
  let response;
  try { response = await fetch(url, {...(options || {}), headers}); }
  catch (error) { throw new FabApiError('无法连接 Fab Insight 服务', {code:'NETWORK_ERROR', retryable:true}); }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw apiError(payload, response);
  return payload;
}

function updateSystemStatus(modelLabel) {
  const enterprise = state.enterpriseContext;
  $('#systemStatus').textContent = enterprise
    ? `${enterprise.tenant_id} · 企业模拟源 · ${modelLabel}`
    : `${formatNumber(state.dashboard?.overview?.lots ?? 0)} 批次 · ${modelLabel}`;
  if (enterprise) $('#systemStatus').title = `${formatNumber(enterprise.virtual_scale?.lots || 0)} 个虚拟批次；支持服务端聚合；数据不代表真实生产`;
}

function handleBuildVersion(build) {
  if (!build?.version || build.version === APP_VERSION) return;
  if (sessionStorage.getItem('fabInsightDismissedVersion') === build.version) return;
  $('#versionBanner').dataset.version = build.version;
  $('#versionBanner').hidden = false;
}

async function checkAppVersion() {
  try { handleBuildVersion(await api('/api/version')); }
  catch { /* Keep version checks silent; normal API requests expose connectivity failures. */ }
}

function newClientMessageId() {
  return globalThis.crypto?.randomUUID?.() || `msg-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

function dismissToast() {
  window.clearTimeout(state.toastTimer);
  state.toastTimer = null;
  $('#toastRegion').innerHTML = '';
}

function showToast(message, {actionLabel = '', onAction = null, tone = 'default', duration = 5200} = {}) {
  dismissToast();
  const toast = document.createElement('div');
  toast.className = `toast${tone === 'error' ? ' error' : ''}`;
  toast.innerHTML = `<span class="toast-message">${escapeHtml(message)}</span>${actionLabel ? `<button type="button" class="toast-action">${escapeHtml(actionLabel)}</button>` : ''}<button type="button" class="toast-close" aria-label="关闭提示">×</button>`;
  $('#toastRegion').appendChild(toast);
  toast.querySelector('.toast-close').addEventListener('click', dismissToast);
  toast.querySelector('.toast-action')?.addEventListener('click', async () => {
    dismissToast();
    try { await onAction?.(); }
    catch (error) { showToast(`操作失败：${error.message}`, {tone:'error'}); }
  });
  state.toastTimer = window.setTimeout(dismissToast, duration);
}

function sourceLink(source, label) {
  if (source.source_type === 'case' || source.case_id) return `<button class="citation-link" data-case-id="${escapeHtml(source.case_id)}">${escapeHtml(label)}</button>`;
  if (source.source_type === 'personal') return `<button class="citation-link" data-personal-chunk="${escapeHtml(source.chunk_id)}">${escapeHtml(label)}</button>`;
  return `<button class="citation-link" data-knowledge-chunk="${Number(source.chunk_id)}">${escapeHtml(label)}</button>`;
}

function inlineMarkdown(value, sourceReferences = new Map()) {
  let text = escapeHtml(value);
  text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  text = text.replace(/\[来源(?:\s+chunk_id\s*:)?\s*([A-Za-z0-9,，、\-\s]+)\]/gi, (match, ids) => {
    const references = ids.split(/[,，、\s]+/).filter(Boolean).map(id => sourceReferences.get(id) || sourceReferences.get(`KB-${id}`)).filter(Boolean);
    return references.length ? references.map(source => sourceLink(source, `[来源 ${source.reference_id || `KB-${source.chunk_id}`}]`)).join(' ') : match;
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

function renderKnowledgeDocuments(filter = '') {
  const query = filter.trim().toLowerCase();
  const documents = state.knowledgeDocuments.filter(doc => `${doc.title} ${doc.source} ${doc.sections}`.toLowerCase().includes(query));
  $('#knowledgeCount').textContent = `${documents.length} 份文档`;
  $('#knowledgeDocuments').innerHTML = documents.map(doc => `<button class="knowledge-document" data-knowledge-chunk="${doc.first_chunk_id}" title="${escapeHtml(doc.sections)}"><strong>${escapeHtml(doc.title)}</strong><span>${escapeHtml(doc.doc_type)} · v${escapeHtml(doc.version)} · ${doc.section_count} 章</span></button>`).join('') || '<p class="empty">没有匹配的文档</p>';
}

const personalKnowledgeStatus = {
  uploaded: ['等待处理', 'processing'], parsing: ['正在解析', 'processing'], chunking: ['正在分段', 'processing'], indexing: ['正在索引', 'processing'],
  ready: ['可检索', 'ready'], failed: ['处理失败', 'failed'], deleting: ['正在删除', 'processing'],
};

function personalKnowledgeStatusLabel(status) {
  return personalKnowledgeStatus[status] || [status || '未知', 'processing'];
}

function resetKnowledgeReader(mode = state.knowledgeMode) {
  $('#knowledgeSource').textContent = mode === 'personal' ? 'PERSONAL KNOWLEDGE · 私有' : 'KNOWLEDGE BASE';
  $('#knowledgeTitle').textContent = mode === 'personal' ? '选择一份个人文档' : '选择一份知识文档';
  $('#knowledgeMeta').innerHTML = '';
  $('#personalKnowledgeActions').hidden = true;
  $('#knowledgeContent').innerHTML = `<p class="empty">${mode === 'personal' ? '上传文档后，可在这里查看解析内容与处理状态。' : '从左侧选择文档，或点击 Agent 回答中的来源。'}</p>`;
}

function renderPersonalKnowledgeDocuments() {
  const documents = state.personalKnowledgeDocuments;
  $('#knowledgeCount').textContent = `${documents.length} 份文档`;
  $('#knowledgeDocuments').innerHTML = documents.map(doc => {
    const [label, tone] = personalKnowledgeStatusLabel(doc.status);
    const details = [doc.filename, formatFileSize(doc.size_bytes), doc.chunk_count ? `${doc.chunk_count} 段` : ''].filter(Boolean).join(' · ');
    return `<button class="knowledge-document personal-document ${doc.document_id === state.selectedPersonalDocumentId ? 'active' : ''}" data-personal-document-id="${escapeHtml(doc.document_id)}"><span class="personal-document-title"><strong>${escapeHtml(doc.title)}</strong><em class="personal-status ${tone}">${escapeHtml(label)}</em></span><span>${escapeHtml(details)}</span></button>`;
  }).join('') || '<div class="personal-knowledge-empty"><strong>还没有个人文档</strong><span>上传 SOP、分析记录或设备资料后，可在此预览和检索。</span><button type="button" class="secondary-btn" data-open-knowledge-upload>上传文档</button></div>';
}

function schedulePersonalKnowledgeRefresh() {
  window.clearTimeout(state.personalKnowledgePollTimer);
  state.personalKnowledgePollTimer = null;
  const processing = state.personalKnowledgeDocuments.some(doc => ['uploaded', 'parsing', 'chunking', 'indexing', 'deleting'].includes(doc.status));
  if (state.knowledgeMode !== 'personal' || !processing) return;
  state.personalKnowledgePollTimer = window.setTimeout(async () => {
    try {
      await loadPersonalKnowledgeDocuments({selectFirst:false});
      if (state.selectedPersonalDocumentId && state.personalKnowledgeDocuments.some(doc => doc.document_id === state.selectedPersonalDocumentId)) {
        await openPersonalKnowledgeDocument(state.selectedPersonalDocumentId, {scroll:false});
      }
    } catch { /* A later user action can retry the refresh. */ }
  }, 1200);
}

async function loadPersonalKnowledgeDocuments({selectFirst = true} = {}) {
  const requestId = ++state.personalKnowledgeRequestId;
  const query = $('#knowledgeFilter').value.trim();
  const payload = await api(`/api/knowledge/personal/documents?q=${encodeURIComponent(query)}&limit=100`);
  if (requestId !== state.personalKnowledgeRequestId || state.knowledgeMode !== 'personal') return [];
  state.personalKnowledgeDocuments = payload.items || [];
  if (state.selectedPersonalDocumentId && !state.personalKnowledgeDocuments.some(doc => doc.document_id === state.selectedPersonalDocumentId)) {
    state.selectedPersonalDocumentId = null;
    state.selectedPersonalDocument = null;
    resetKnowledgeReader('personal');
  }
  renderPersonalKnowledgeDocuments();
  schedulePersonalKnowledgeRefresh();
  if (selectFirst && !state.selectedPersonalDocumentId && state.personalKnowledgeDocuments.length) {
    await openPersonalKnowledgeDocument(state.personalKnowledgeDocuments[0].document_id, {scroll:false});
  }
  return state.personalKnowledgeDocuments;
}

function personalKnowledgeMeta(document) {
  const [label, tone] = personalKnowledgeStatusLabel(document.status);
  const items = [`<span class="personal-status ${tone}">${escapeHtml(label)}</span>`, `<span>${escapeHtml(document.filename)}</span>`, `<span>${escapeHtml(formatFileSize(document.size_bytes))}</span>`];
  for (const step of document.process_steps || []) items.push(`<span>${escapeHtml(processLabels[step] || step)}</span>`);
  for (const equipment of document.equipment_ids || []) items.push(`<span>${escapeHtml(equipment)}</span>`);
  if (document.effective_date) items.push(`<span>生效 ${escapeHtml(document.effective_date)}</span>`);
  for (const tag of document.tags || []) items.push(`<span>#${escapeHtml(tag)}</span>`);
  return items.join('');
}

function renderPersonalKnowledgeContent(document) {
  const job = document.latest_job;
  const error = job?.error || (document.error_code ? {error_code:document.error_code, detail:document.error_message} : null);
  if (document.status === 'failed') {
    const ocrNote = error?.error_code === 'OCR_REQUIRED' ? '<p>当前文件可能是扫描件。OCR 尚未启用，请上传可复制文本的 PDF 或转换后的文档。</p>' : '';
    return `<div class="knowledge-processing failed"><strong>文档处理失败</strong><p>${escapeHtml(error?.detail || '解析或索引过程未完成。')}</p>${ocrNote}<code>${escapeHtml(error?.error_code || 'PROCESSING_FAILED')}</code></div>`;
  }
  if (document.status !== 'ready') {
    const progress = Math.max(0, Math.min(100, Number(job?.progress) || 0));
    return `<div class="knowledge-processing"><div class="knowledge-processing-heading"><strong>${escapeHtml(personalKnowledgeStatusLabel(document.status)[0])}</strong><span>${progress}%</span></div><div class="knowledge-progress"><span style="width:${progress}%"></span></div><p>系统正在提取文本并建立个人检索索引，此页面会自动更新。</p></div>`;
  }
  if (!document.chunks?.length) return '<p class="empty">文档已完成处理，但没有可显示的文本片段。</p>';
  return document.chunks.map((chunk, index) => `<section id="personal-knowledge-chunk-${escapeHtml(chunk.chunk_id)}" class="knowledge-chunk"><h3>${escapeHtml(chunk.section_path || `片段 ${index + 1}`)}${chunk.page_number ? `<span class="knowledge-page-number">第 ${chunk.page_number} 页</span>` : ''}</h3><div class="markdown-content">${renderMarkdown(chunk.content)}</div></section>`).join('');
}

async function openPersonalKnowledgeDocument(documentId, {scroll = true} = {}) {
  state.selectedPersonalDocumentId = documentId;
  renderPersonalKnowledgeDocuments();
  const requestId = ++state.personalKnowledgeRequestId;
  try {
    const personalDocument = await api(`/api/knowledge/personal/documents/${encodeURIComponent(documentId)}/content`);
    if (requestId !== state.personalKnowledgeRequestId || state.knowledgeMode !== 'personal' || state.selectedPersonalDocumentId !== documentId) return;
    state.selectedPersonalDocument = personalDocument;
    $('#knowledgeSource').textContent = 'PERSONAL KNOWLEDGE · 私有';
    $('#knowledgeTitle').textContent = personalDocument.title;
    $('#knowledgeMeta').innerHTML = personalKnowledgeMeta(personalDocument);
    $('#knowledgeContent').innerHTML = renderPersonalKnowledgeContent(personalDocument);
    $('#personalKnowledgeActions').hidden = false;
    $('#downloadPersonalKnowledge').disabled = personalDocument.status === 'deleting';
    $('#deletePersonalKnowledge').disabled = personalDocument.status === 'deleting';
    $('#retryPersonalKnowledge').hidden = personalDocument.status !== 'failed' || personalDocument.error_code === 'DELETE_FAILED';
    document.querySelectorAll('.personal-document').forEach(button => button.classList.toggle('active', button.dataset.personalDocumentId === documentId));
    if (scroll) document.querySelector('.knowledge-reader')?.scrollIntoView({behavior:'smooth', block:'start'});
  } catch (error) {
    if (error.status === 404) {
      state.selectedPersonalDocumentId = null;
      state.selectedPersonalDocument = null;
      await loadPersonalKnowledgeDocuments({selectFirst:true});
      return;
    }
    throw error;
  }
}

async function openPersonalKnowledgeChunk(chunkId) {
  showView('knowledge');
  const chunk = await api(`/api/knowledge/personal/chunks/${encodeURIComponent(chunkId)}`);
  if (state.knowledgeMode !== 'personal') await setKnowledgeMode('personal');
  await openPersonalKnowledgeDocument(chunk.document_id, {scroll:false});
  window.setTimeout(() => document.getElementById(`personal-knowledge-chunk-${chunkId}`)?.scrollIntoView({behavior:'smooth', block:'start'}), 80);
}

async function setKnowledgeMode(mode) {
  if (!['factory', 'personal'].includes(mode)) return;
  state.knowledgeMode = mode;
  window.clearTimeout(state.personalKnowledgePollTimer);
  state.personalKnowledgePollTimer = null;
  document.querySelectorAll('[data-knowledge-mode]').forEach(button => button.classList.toggle('active', button.dataset.knowledgeMode === mode));
  $('#knowledgeIndexTitle').textContent = mode === 'personal' ? '我的文档' : '文档目录';
  $('#knowledgeIndexHint').textContent = mode === 'personal' ? '仅当前用户可见' : '按文档浏览章节';
  $('#knowledgeFilter').placeholder = mode === 'personal' ? '搜索我的文档' : '筛选文档或章节';
  resetKnowledgeReader(mode);
  if (mode === 'personal') await loadPersonalKnowledgeDocuments();
  else await loadKnowledgeIndex();
}

function selectedUploadFile() {
  return $('#knowledgeUploadFile').files?.[0] || null;
}

function updateKnowledgeUploadFileState() {
  const file = selectedUploadFile();
  const stateLabel = $('#knowledgeUploadFileState');
  $('#knowledgeUploadDrop').classList.toggle('has-file', Boolean(file));
  stateLabel.textContent = file ? `${file.name} · ${formatFileSize(file.size)}` : '支持 PDF、DOCX、Markdown、TXT、CSV、XLSX，最大 50 MB';
}

function resetKnowledgeUploadForm() {
  $('#knowledgeUploadForm').reset();
  $('#knowledgeUploadMessage').hidden = true;
  $('#knowledgeUploadMessage').classList.remove('error');
  $('#confirmKnowledgeUpload').disabled = false;
  $('#confirmKnowledgeUpload').textContent = '上传并处理';
  updateKnowledgeUploadFileState();
}

function openKnowledgeUploadDialog() {
  resetKnowledgeUploadForm();
  $('#knowledgeUploadDialog').showModal();
}

function splitMetadataValues(value) {
  return [...new Set(value.split(/[,，、;；\n]+/).map(item => item.trim()).filter(Boolean))];
}

async function uploadPersonalKnowledge(event) {
  event.preventDefault();
  const file = selectedUploadFile();
  const message = $('#knowledgeUploadMessage');
  if (!file) return;
  if (file.size > 50 * 1024 * 1024) {
    message.textContent = '文件超过 50 MB，请选择更小的文件。';
    message.classList.add('error');
    message.hidden = false;
    return;
  }
  const metadata = {
    process_steps: $('#knowledgeUploadStep').value ? [$('#knowledgeUploadStep').value] : [],
    equipment_ids: splitMetadataValues($('#knowledgeUploadEquipment').value),
    tags: splitMetadataValues($('#knowledgeUploadTags').value),
  };
  const title = $('#knowledgeUploadTitle').value.trim();
  const effectiveDate = $('#knowledgeUploadEffectiveDate').value;
  if (title) metadata.title = title;
  if (effectiveDate) metadata.effective_date = effectiveDate;
  const form = new FormData();
  form.append('file', file);
  form.append('metadata', JSON.stringify(metadata));
  const button = $('#confirmKnowledgeUpload');
  button.disabled = true;
  button.textContent = '正在上传…';
  message.hidden = true;
  message.classList.remove('error');
  try {
    const result = await api('/api/knowledge/personal/documents', {method:'POST', headers:{'Idempotency-Key':newClientMessageId()}, body:form});
    $('#knowledgeUploadDialog').close();
    $('#knowledgeFilter').value = '';
    state.selectedPersonalDocumentId = result.document_id;
    await setKnowledgeMode('personal');
    await openPersonalKnowledgeDocument(result.document_id, {scroll:false});
    showToast('文档已上传，正在建立个人检索索引');
  } catch (error) {
    message.textContent = error.message;
    message.classList.add('error');
    message.hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = '上传并处理';
  }
}

async function retrySelectedPersonalKnowledge() {
  const documentId = state.selectedPersonalDocumentId;
  if (!documentId) return;
  $('#retryPersonalKnowledge').disabled = true;
  try {
    await api(`/api/knowledge/personal/documents/${encodeURIComponent(documentId)}/retry`, {method:'POST'});
    await loadPersonalKnowledgeDocuments({selectFirst:false});
    await openPersonalKnowledgeDocument(documentId, {scroll:false});
    showToast('已重新提交文档处理任务');
  } catch (error) {
    showToast(`重新处理失败：${error.message}`, {tone:'error'});
  } finally { $('#retryPersonalKnowledge').disabled = false; }
}

function openPersonalKnowledgeDeleteDialog() {
  if (!state.selectedPersonalDocumentId || !state.selectedPersonalDocument) return;
  state.pendingPersonalDeleteId = state.selectedPersonalDocumentId;
  $('#personalKnowledgeDeleteMessage').textContent = `“${state.selectedPersonalDocument.title}”将从我的知识中删除。`;
  $('#personalKnowledgeDeleteDialog').showModal();
}

async function deleteSelectedPersonalKnowledge(event) {
  event.preventDefault();
  const documentId = state.pendingPersonalDeleteId;
  if (!documentId) return;
  const button = $('#confirmPersonalKnowledgeDelete');
  button.disabled = true;
  try {
    await api(`/api/knowledge/personal/documents/${encodeURIComponent(documentId)}`, {method:'DELETE'});
    $('#personalKnowledgeDeleteDialog').close();
    state.selectedPersonalDocumentId = null;
    state.selectedPersonalDocument = null;
    resetKnowledgeReader('personal');
    await loadPersonalKnowledgeDocuments({selectFirst:true});
    showToast('个人文档已删除');
  } catch (error) {
    showToast(`删除失败：${error.message}`, {tone:'error'});
  } finally { button.disabled = false; }
}

function downloadSelectedPersonalKnowledge() {
  if (!state.selectedPersonalDocumentId) return;
  const link = document.createElement('a');
  link.href = `/api/knowledge/personal/documents/${encodeURIComponent(state.selectedPersonalDocumentId)}/file`;
  link.download = state.selectedPersonalDocument?.filename || '';
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function loadKnowledgeIndex() {
  if (!state.knowledgeDocuments.length) {
    state.knowledgeIndexPromise ||= api('/api/knowledge/documents');
    state.knowledgeDocuments = await state.knowledgeIndexPromise;
  }
  renderKnowledgeDocuments($('#knowledgeFilter').value);
  return state.knowledgeDocuments;
}

async function openKnowledgeChunk(chunkId) {
  showView('knowledge');
  if (state.knowledgeMode !== 'factory') await setKnowledgeMode('factory');
  await loadKnowledgeIndex();
  const payload = await api(`/api/knowledge/chunks/${chunkId}`);
  $('#knowledgeTitle').textContent = payload.document.title;
  $('#knowledgeSource').textContent = `${payload.document.source} · v${payload.document.version} · ${payload.document.status}`;
  $('#knowledgeMeta').innerHTML = '';
  $('#personalKnowledgeActions').hidden = true;
  $('#knowledgeContent').innerHTML = payload.chunks.map(chunk => `<section id="knowledge-chunk-${chunk.chunk_id}" class="knowledge-chunk ${chunk.chunk_id === Number(chunkId) ? 'target-chunk' : ''}"><h3>${escapeHtml(chunk.section)}</h3><div class="markdown-content">${renderMarkdown(chunk.content)}</div></section>`).join('');
  document.querySelectorAll('.knowledge-document').forEach(button => button.classList.toggle('active', Number(button.dataset.knowledgeChunk) === payload.chunks[0].chunk_id));
  window.setTimeout(() => document.querySelector(`#knowledge-chunk-${chunkId}`)?.scrollIntoView({behavior:'smooth', block:'start'}), 80);
}

function renderCaseList() {
  const query = $('#caseFilter').value.trim().toLowerCase();
  const step = $('#caseStepFilter').value;
  const cases = state.cases.filter(item => {
    const searchable = `${item.case_id} ${item.title} ${item.process_step} ${item.equipment_id || ''} ${item.problem} ${item.summary} ${item.tags}`.toLowerCase();
    return (!step || item.process_step === step) && (!query || searchable.includes(query));
  });
  $('#caseCount').textContent = `${cases.length} 个案例`;
  $('#caseList').innerHTML = cases.map(item => `<button class="case-list-item" data-case-id="${escapeHtml(item.case_id)}"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.case_id)} · ${escapeHtml(item.process_step)} · ${escapeHtml(item.occurred_date)}</span></button>`).join('') || '<p class="empty">没有匹配的历史案例</p>';
}

async function loadCaseIndex() {
  if (!state.cases.length) {
    state.casesPromise ||= api('/api/cases');
    state.cases = await state.casesPromise;
    const steps = [...new Set(state.cases.map(item => item.process_step))].sort();
    $('#caseStepFilter').insertAdjacentHTML('beforeend', steps.map(step => `<option value="${escapeHtml(step)}">${escapeHtml(step)}</option>`).join(''));
  }
  renderCaseList();
  return state.cases;
}

async function openHistoricalCase(caseId) {
  showView('cases');
  await loadCaseIndex();
  const item = await api(`/api/cases/${encodeURIComponent(caseId)}`);
  $('#caseReference').textContent = item.case_id;
  $('#caseTitle').textContent = item.title;
  $('#caseMeta').innerHTML = `<span>${escapeHtml(item.process_step)}</span>${item.equipment_id ? `<span>${escapeHtml(item.equipment_id)}</span>` : ''}<span>${escapeHtml(item.defect_type)}</span><span>${escapeHtml(item.occurred_date)}</span><span class="severity-${item.severity.toLowerCase()}">${escapeHtml(item.severity)}</span><span>${escapeHtml(item.case_status)}</span><span>RCA ${(Number(item.root_cause_confidence) * 100).toFixed(0)}%</span>`;
  const sections = [['问题', item.problem], ['解决方案', item.solution], ['解决结果', item.result], ['案例总结', item.summary]];
  $('#caseContent').innerHTML = `<div class="case-governance"><strong>已验证根因</strong><span>${escapeHtml(item.root_cause)}</span><small>${escapeHtml(item.validation_method)} · ${escapeHtml(item.recurrence_status)} · ${escapeHtml(item.approved_by)}</small></div>${sections.map(([title, content]) => `<section class="case-section"><h3>${title}</h3><p>${escapeHtml(content)}</p></section>`).join('')}`;
  document.querySelectorAll('.case-list-item').forEach(button => button.classList.toggle('active', button.dataset.caseId === caseId));
  document.querySelector('.case-reader')?.scrollIntoView({behavior:'smooth', block:'start'});
}

function renderModelConfig(config) {
  state.modelConfig = config;
  const activeLabel = config.display_name || config.model;
  $('#activeModelLabel').textContent = activeLabel;
  $('#agentMode').textContent = `${activeLabel} · 工具分析`;
  const select = $('#modelSelect');
  const options = config.model_options?.length ? config.model_options : config.allowed_models.map(model => ({model_id:model, display_name:model, provider_model:model}));
  select.innerHTML = options.map(model => `<option value="${escapeHtml(model.model_id)}" ${model.model_id === config.model ? 'selected' : ''}>${escapeHtml(model.display_name)} · ${escapeHtml(model.provider_model)}</option>`).join('');
}

async function loadModelConfig() {
  const config = await api('/api/settings/model');
  renderModelConfig(config);
  return config;
}

async function openModelSettings() {
  const message = $('#modelSettingsMessage'); message.hidden = true; message.classList.remove('error');
  try { await loadModelConfig(); $('#modelDialog').showModal(); }
  catch (error) { alert(`无法加载模型配置：${error.message}`); }
}

async function saveModelSettings(event) {
  event.preventDefault();
  const button = $('#saveModelSettings'), message = $('#modelSettingsMessage');
  const body = {model: $('#modelSelect').value};
  button.disabled = true; message.hidden = true;
  try {
    const config = await api('/api/settings/model', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    renderModelConfig(config);
    message.textContent = `已切换到 ${config.display_name || config.model}`; message.classList.remove('error'); message.hidden = false;
    updateSystemStatus(config.display_name || config.model);
    window.setTimeout(() => $('#modelDialog').open && $('#modelDialog').close(), 700);
  } catch (error) {
    message.textContent = error.message; message.classList.add('error'); message.hidden = false;
  } finally { button.disabled = false; }
}

function renderKpis(data) {
  const items = [
    ['综合良率', data.yield_pct, '%', `${formatNumber(data.good_wafers)} 片良品`],
    ['完成批次', data.lots, '', `${formatNumber(data.wafers)} 片投产`],
    ['平均周期', data.avg_cycle_hours, 'h', `平均 Hold ${data.avg_hold_hours}h`],
    ['制程异常', data.excursions, '次', '控制计划规则触发'],
    ['Hold 批次', data.held_lots, '批', '当前查询窗口'],
  ];
  $('#kpiGrid').innerHTML = items.map(([label, value, unit, meta]) => `<div class="kpi"><span class="kpi-label">${label}</span><span class="kpi-value">${formatNumber(value)}<span class="kpi-unit">${unit}</span></span><span class="kpi-meta">${meta}</span></div>`).join('');
}

function renderEquipment(rows) {
  $('#equipmentCount').textContent = `${rows.length} 台设备`;
  $('#equipmentBody').innerHTML = rows.map(row => `<tr><td><strong>${escapeHtml(row.equipment_id)}</strong></td><td><span class="status-pill status-${row.health.toLowerCase()}">${row.health}</span></td><td>${formatNumber(row.runs)}</td><td class="${row.excursions >= 3 ? 'metric-alert' : ''}">${row.excursions}</td><td>${row.pass_pct}%</td><td>${formatNumber(row.downtime_minutes)}</td></tr>`).join('');
}

function renderDefects(rows) {
  const max = Math.max(...rows.map(row => row.defect_count), 1);
  $('#defectBars').innerHTML = rows.length ? rows.map(row => `<div class="bar-row"><span class="bar-label" title="${escapeHtml(row.defect_type)} · ${escapeHtml(row.process_steps)}">${escapeHtml(row.defect_type)}</span><span class="bar-track"><span class="bar-fill" style="width:${Math.max(3, row.defect_count / max * 100)}%"></span></span><span class="bar-value">${row.defect_count}</span></div>`).join('') : '<p class="empty">范围内没有缺陷记录</p>';
}

function renderExcursions(rows) {
  $('#excursionBody').innerHTML = rows.map(row => {
    const metric = row.measurement_value == null
      ? `缺陷密度 ${row.defect_density}`
      : `${row.measurement_name} ${row.measurement_value} ${row.measurement_unit}`;
    return `<tr><td>${escapeHtml(row.run_time.slice(0, 10))}</td><td>${escapeHtml(row.lot_id)}</td><td><strong>${escapeHtml(row.equipment_id)}</strong></td><td><span class="status-pill status-critical">${escapeHtml(row.excursion_code)}</span></td><td>${metric}</td></tr>`;
  }).join('') || '<tr><td colspan="5">范围内没有制程异常</td></tr>';
}

function drawYieldChart(rows) {
  const canvas = $('#yieldChart');
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, rect.width * dpr); canvas.height = Math.max(1, rect.height * dpr);
  const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
  const w = rect.width, h = rect.height, pad = {l: 42, r: 16, t: 12, b: 28};
  ctx.clearRect(0, 0, w, h); ctx.font = '9px Segoe UI'; ctx.lineWidth = 1;
  if (!rows.length) return;
  const values = rows.map(r => Number(r.yield_pct));
  const minY = Math.min(88, Math.floor(Math.min(...values) - 1));
  const maxY = Math.max(98, Math.ceil(Math.max(...values) + 1));
  const x = i => pad.l + (rows.length === 1 ? 0 : i * (w-pad.l-pad.r)/(rows.length-1));
  const y = v => pad.t + (maxY-v)*(h-pad.t-pad.b)/(maxY-minY);
  ctx.strokeStyle = '#e5eae8'; ctx.fillStyle = '#7b8784';
  for (let tick=minY; tick<=maxY; tick+=2) { ctx.beginPath(); ctx.moveTo(pad.l,y(tick)); ctx.lineTo(w-pad.r,y(tick)); ctx.stroke(); ctx.fillText(`${tick}%`,4,y(tick)+3); }
  ctx.setLineDash([4,4]); ctx.strokeStyle='#c4944d'; ctx.beginPath(); ctx.moveTo(pad.l,y(90)); ctx.lineTo(w-pad.r,y(90)); ctx.stroke(); ctx.setLineDash([]);
  ctx.beginPath(); rows.forEach((r,i) => i ? ctx.lineTo(x(i),y(Number(r.yield_pct))) : ctx.moveTo(x(i),y(Number(r.yield_pct)))); ctx.strokeStyle='#087f70'; ctx.lineWidth=2; ctx.stroke();
  ctx.fillStyle='#087f70'; rows.forEach((r,i) => { ctx.beginPath(); ctx.arc(x(i),y(Number(r.yield_pct)),2.5,0,Math.PI*2); ctx.fill(); });
  const labelEvery = Math.max(1, Math.ceil(rows.length / 7)); ctx.fillStyle='#7b8784';
  rows.forEach((r,i) => { if (i % labelEvery === 0 || i === rows.length-1) ctx.fillText(r.week_start.slice(5), x(i)-12, h-7); });
  state.chartPoints = rows.map((r,i) => ({x:x(i), y:y(Number(r.yield_pct)), row:r}));
}

async function loadDashboard() {
  const start = $('#startDate').value, end = $('#endDate').value;
  $('#errorBanner').hidden = true;
  try {
    const data = await api(`/api/reports/dashboard?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
    state.dashboard = data;
    renderKpis(data.overview); renderEquipment(data.equipment); renderDefects(data.defects); renderExcursions(data.excursions); drawYieldChart(data.yield_trend);
    $('#rangeSummary').textContent = `${start} 至 ${end} · ${formatNumber(data.overview.lots)} 个批次`;
  } catch (error) { $('#errorBanner').textContent = error.message; $('#errorBanner').hidden = false; }
}

function capabilityRating(cpk) {
  if (cpk == null) return ['无数据', ''];
  if (cpk < 1.33) return ['能力不足', 'metric-alert'];
  if (cpk < 1.67) return ['观察', ''];
  return ['稳定', 'metric-good'];
}

async function loadCapability(step = state.activeStep) {
  state.activeStep = step;
  const start = $('#startDate').value, end = $('#endDate').value;
  const cacheKey = `${step}:${start}:${end}`;
  const table = $('#capabilityBody').closest('table');
  state.capabilityController?.abort();
  state.capabilityController = null;
  const requestId = ++state.capabilityRequestId;
  table.removeAttribute('aria-busy');
  table.classList.remove('table-loading');
  const cachedRows = state.capabilityCache.get(cacheKey);
  if (cachedRows) { renderCapability(step, cachedRows); return; }

  const controller = new AbortController();
  state.capabilityController = controller;
  table.setAttribute('aria-busy', 'true');
  table.classList.add('table-loading');
  $('#capabilityMetric').textContent = '正在计算制程能力…';
  try {
    const rows = await api(`/api/reports/capability?process_step=${encodeURIComponent(step)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`, {signal: controller.signal});
    if (requestId !== state.capabilityRequestId) return;
    state.capabilityCache.set(cacheKey, rows);
    renderCapability(step, rows);
  } catch (error) {
    if (error.name === 'AbortError') return;
    if (requestId === state.capabilityRequestId) $('#capabilityMetric').textContent = `读取失败：${error.message}`;
  } finally {
    if (requestId === state.capabilityRequestId) {
      table.removeAttribute('aria-busy');
      table.classList.remove('table-loading');
      state.capabilityController = null;
    }
  }
}

function renderCapability(step, rows) {
  const metric = rows[0];
  $('#capabilityTitle').textContent = `${processLabels[step] || step} · ${metric?.metric_name || '关键量测'}能力`;
  const lower = metric?.spec_lsl == null ? null : `LSL ${metric.spec_lsl}`;
  const upper = metric?.spec_usl == null ? null : `USL ${metric.spec_usl}`;
  const specification = [lower, upper].filter(Boolean).join(' / ');
  $('#capabilityMetric').textContent = metric ? `${specification} ${metric.metric_unit}；Cpk < 1.33 需关注` : '当前范围没有可用量测';
  $('#capabilityBody').innerHTML = rows.map(row => { const [rating, cls] = capabilityRating(row.cpk); return `<tr><td><strong>${row.equipment_id}</strong></td><td>${row.samples}</td><td>${row.mean_value}</td><td>${row.sigma}</td><td>${row.min_value}</td><td>${row.max_value}</td><td class="${cls}">${row.cpk ?? '—'}</td><td class="${cls}">${rating}</td></tr>`; }).join('') || '<tr><td colspan="8" class="empty">当前范围没有可用量测</td></tr>';
}

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
    const sourceReferences = new Map();
    for (const source of (item.metadata?.sources || [])) {
      if (source.reference_id) sourceReferences.set(source.reference_id, source);
      if (source.chunk_id) sourceReferences.set(String(source.chunk_id), source);
    }
    const content = assistant ? renderMarkdown(item.content, sourceReferences) : escapeHtml(item.content).replace(/\n/g, '<br>');
    const timestamp = new Date(item.created_at).toLocaleString('zh-CN', {hour12:false});
    const sources = assistant && item.metadata?.sources?.length
      ? `<div class="source-list"><strong>知识来源</strong>${item.metadata.sources.map(source => sourceLink(source, `[来源 ${source.reference_id || `KB-${source.chunk_id}`}] ${source.source || ''} · ${source.section || ''}`)).join('')}</div>`
      : '';
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
  return {el, steps: [], runId: null, buffer: new FabSmoothTextBuffer(), renderTimer: null, drainResolvers: [], firstToken: false, cancelled: false};
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
  answer.innerHTML = renderMarkdown(live.buffer.takeNext());
  if (follow) container.scrollTop = container.scrollHeight;
  if (live.buffer.pendingLength) {
    live.renderTimer = window.setTimeout(() => renderLiveAnswerFrame(live), live.buffer.pendingLength > 240 ? 24 : 32);
  } else {
    resolveLiveAnswerDrain(live);
  }
}

function scheduleLiveAnswerFrame(live) {
  if (live.cancelled || live.renderTimer || !live.buffer.pendingLength) return;
  live.renderTimer = window.setTimeout(() => renderLiveAnswerFrame(live), 24);
}

function appendLiveAnswer(live, delta) {
  if (!delta || live.cancelled) return;
  live.buffer.append(delta);
  if (!live.firstToken) {
    startLiveAnswer(live);
  }
  scheduleLiveAnswerFrame(live);
}

async function finishLiveAnswer(live, finalAnswer) {
  live.buffer.finish(finalAnswer);
  if (live.buffer.received && !live.firstToken) startLiveAnswer(live);
  live.el.querySelector('.live-indicator').textContent = live.buffer.done ? '完成' : '输出中';
  scheduleLiveAnswerFrame(live);
  if (!live.buffer.done) await new Promise(resolve => live.drainResolvers.push(resolve));
}

function cancelLiveAnswer(live) {
  live.cancelled = true;
  if (live.renderTimer) window.clearTimeout(live.renderTimer);
  live.renderTimer = null;
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

async function streamAgent(message, clientMessageId, onProgress) {
  let response;
  try {
    response = await fetch('/api/chat/stream', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message, session_id:state.sessionId, client_message_id:clientMessageId})});
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
    buffer += decoder.decode(value || new Uint8Array(), {stream:!done});
    const lines = buffer.split('\n'); buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === 'session') {
        state.sessionId = event.session_id; localStorage.setItem('fabInsightSessionId', state.sessionId);
      } else if (event.type === 'progress') onProgress(event);
      else if (event.type === 'result') finalResult = event.result;
      else if (event.type === 'error') throw apiError(event.error || {detail:event.detail || '分析失败'}, response);
    }
    if (done) break;
  }
  if (!finalResult) throw new FabApiError('分析结束但未收到结果', {code:'STREAM_INCOMPLETE', requestId:response.headers.get('x-request-id') || '', retryable:true});
  return finalResult;
}

function renderAssistantInto(el, content, extra = {}) {
  const sourceReferences = new Map();
  for (const source of (extra.sources || [])) {
    if (source.reference_id) sourceReferences.set(source.reference_id, source);
    if (source.chunk_id) sourceReferences.set(String(source.chunk_id), source);
  }
  const renderedContent = renderMarkdown(content, sourceReferences);
  const copyButton = '<button type="button" class="copy-answer" title="复制回答" aria-label="复制回答"><span aria-hidden="true">⧉</span><span>复制</span></button>';
  el.className = 'message assistant';
  el.innerHTML = `<div class="message-meta"><div class="message-label">FAB COPILOT</div></div>${renderToolTrace(extra.tool_trace, extra.run_id)}<div class="message-content markdown-content">${renderedContent}</div><div class="message-actions">${copyButton}</div>`;
  const copyAnswer = el.querySelector('.copy-answer');
  copyAnswer.addEventListener('click', async () => {
    try {
      await copyText(content);
      copyAnswer.innerHTML = '<span aria-hidden="true">✓</span><span>已复制</span>'; copyAnswer.classList.add('copied'); copyAnswer.title = '已复制';
      window.setTimeout(() => { copyAnswer.innerHTML = '<span aria-hidden="true">⧉</span><span>复制</span>'; copyAnswer.classList.remove('copied'); copyAnswer.title = '复制回答'; }, 1600);
    } catch (error) {
      copyAnswer.title = error.message; copyAnswer.classList.add('copy-error');
      window.setTimeout(() => copyAnswer.classList.remove('copy-error'), 1600);
    }
  });
  if (extra.sources?.length) {
    const sourceHtml = extra.sources.map(source => {
      const referenceId = source.reference_id || `KB-${source.chunk_id}`;
      const attribute = source.source_type === 'case'
        ? `data-case-id="${escapeHtml(source.case_id)}"`
        : source.source_type === 'personal'
          ? `data-personal-chunk="${escapeHtml(source.chunk_id)}"`
          : `data-knowledge-chunk="${Number(source.chunk_id)}"`;
      const retrieval = source.retrieval || {};
      const scoreTitle = retrieval.final_score != null ? `${retrieval.confidence} · score ${retrieval.final_score} · ${(retrieval.selection_reason || []).join(' · ')}` : '';
      return `<button type="button" class="source-link" ${attribute} title="${escapeHtml(scoreTitle)}">[来源 ${escapeHtml(referenceId)}] ${escapeHtml(source.source)} · ${escapeHtml(source.section)}</button>`;
    }).join('');
    el.querySelector('.message-content').insertAdjacentHTML('beforeend', `<div class="source-list"><strong>知识来源</strong>${sourceHtml}</div>`);
  }
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

async function sendChat(message, {clientMessageId = newClientMessageId(), isRetry = false} = {}) {
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
    const result = await streamAgent(text, clientMessageId, event => updateLiveAnalysis(live, event));
    await finishLiveAnswer(live, result.answer);
    renderAssistantInto(live.el, result.answer, result);
    state.history.push({role:'assistant', content:result.answer});
    $('#agentMode').textContent = result.mode === 'deepseek' ? `${state.modelConfig?.model || 'DeepSeek'} · 工具分析` : '本地规则分析';
  } catch (error) {
    cancelLiveAnswer(live);
    updateLiveAnalysis(live, {event:'run_failed', message:error.message});
    renderAgentRequestError(live, error, () => {
      live.el.remove();
      sendChat(text, {clientMessageId, isRetry:true});
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
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(v => v.classList.remove('active'));
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
  $('#openKnowledgeUpload').addEventListener('click', openKnowledgeUploadDialog);
  $('#knowledgeUploadForm').addEventListener('submit', uploadPersonalKnowledge);
  $('#knowledgeUploadFile').addEventListener('change', updateKnowledgeUploadFileState);
  $('#knowledgeUploadDrop').addEventListener('dragover', event => { event.preventDefault(); event.currentTarget.classList.add('dragging'); });
  $('#knowledgeUploadDrop').addEventListener('dragleave', event => event.currentTarget.classList.remove('dragging'));
  $('#knowledgeUploadDrop').addEventListener('drop', event => {
    event.preventDefault();
    event.currentTarget.classList.remove('dragging');
    const files = event.dataTransfer?.files;
    if (files?.length) { $('#knowledgeUploadFile').files = files; updateKnowledgeUploadFileState(); }
  });
  $('#closeKnowledgeUploadDialog').addEventListener('click', () => $('#knowledgeUploadDialog').close());
  $('#cancelKnowledgeUpload').addEventListener('click', () => $('#knowledgeUploadDialog').close());
  $('#knowledgeUploadDialog').addEventListener('close', resetKnowledgeUploadForm);
  $('#downloadPersonalKnowledge').addEventListener('click', downloadSelectedPersonalKnowledge);
  $('#retryPersonalKnowledge').addEventListener('click', retrySelectedPersonalKnowledge);
  $('#deletePersonalKnowledge').addEventListener('click', openPersonalKnowledgeDeleteDialog);
  $('#personalKnowledgeDeleteForm').addEventListener('submit', deleteSelectedPersonalKnowledge);
  $('#closePersonalKnowledgeDeleteDialog').addEventListener('click', () => $('#personalKnowledgeDeleteDialog').close());
  $('#cancelPersonalKnowledgeDelete').addEventListener('click', () => $('#personalKnowledgeDeleteDialog').close());
  $('#personalKnowledgeDeleteDialog').addEventListener('close', () => { state.pendingPersonalDeleteId = null; });
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
}

document.addEventListener('DOMContentLoaded', init);
