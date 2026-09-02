(function (root, factory) { const api = factory(root); if (typeof module === "object" && module.exports) module.exports = api; root.FabKnowledgeController = api; })(globalThis, (root) => {
  function createKnowledgeController(deps = {}) {
    const { state, $, escapeHtml, formatFileSize, api, identityHeaders, showToast, processLabels, renderMarkdown, showView, newClientMessageId, personalKnowledgeMetadata, personalJobEvents, personalUploadQueue, windowImpl = root, documentImpl = root.document, fetchImpl = root.fetch, AbortControllerImpl = root.AbortController, TextDecoderImpl = root.TextDecoder, FormDataImpl = root.FormData, requestAnimationFrameImpl = root.requestAnimationFrame } = deps;
    const window = windowImpl, document = documentImpl, fetch = fetchImpl, AbortController = AbortControllerImpl, TextDecoder = TextDecoderImpl, FormData = FormDataImpl, requestAnimationFrame = requestAnimationFrameImpl;
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
  const documentItems = documents.map(doc => {
    const [label, tone] = personalKnowledgeStatusLabel(doc.status);
    const details = [doc.filename, formatFileSize(doc.size_bytes), doc.chunk_count ? `${doc.chunk_count} 段` : ''].filter(Boolean).join(' · ');
    const tags = (doc.tags || []).slice(0, 3).map(tag => `#${escapeHtml(tag)}`).join(' · ');
    const source = doc.tags_source === 'auto' ? '自动标记' : '手动标记';
    return `<button class="knowledge-document personal-document ${doc.document_id === state.selectedPersonalDocumentId ? 'active' : ''}" data-personal-document-id="${escapeHtml(doc.document_id)}"><span class="personal-document-title"><strong>${escapeHtml(doc.title)}</strong><em class="personal-status ${tone}">${escapeHtml(label)}</em></span><span>${escapeHtml(details)}</span><small class="personal-document-tags"><i class="tag-source-badge ${doc.tags_source === 'auto' ? 'auto' : 'user'}">${source}</i>${tags || '无标签'}</small></button>`;
  }).join('');
  $('#knowledgeDocuments').innerHTML = documentItems ? `${documentItems}<div class="personal-knowledge-upload-more"><button type="button" class="secondary-btn" data-open-knowledge-upload>＋ 上传文档</button></div>` : '<div class="personal-knowledge-empty"><strong>还没有个人文档</strong><span>上传 SOP、分析记录或设备资料后，可在此预览和检索。</span><button type="button" class="secondary-btn" data-open-knowledge-upload>上传文档</button></div>';
}

function schedulePersonalKnowledgeRefresh() {
  window.clearTimeout(state.personalKnowledgePollTimer);
  state.personalKnowledgePollTimer = null;
  const processing = state.personalKnowledgeDocuments.some(doc => ['uploaded', 'parsing', 'chunking', 'indexing', 'deleting'].includes(doc.status));
  if (state.activeView !== 'knowledge' || state.knowledgeMode !== 'personal' || !processing || !state.personalJobEventsFallback) return;
  state.personalKnowledgePollTimer = window.setTimeout(async () => {
    try {
      await loadPersonalKnowledgeDocuments({selectFirst:false});
      if (state.selectedPersonalDocumentId && state.personalKnowledgeDocuments.some(doc => doc.document_id === state.selectedPersonalDocumentId)) {
        await openPersonalKnowledgeDocument(state.selectedPersonalDocumentId, {scroll:false});
      }
    } catch { /* A later user action can retry the refresh. */ }
  }, 1200);
}

function personalKnowledgeProcessing() {
  return state.personalKnowledgeDocuments.some(doc => personalJobEvents.isActive(doc.status));
}

function stopPersonalJobEvents({keepFallback = false, complete = false} = {}) {
  state.personalJobEventsController?.abort();
  state.personalJobEventsController = null;
  window.clearTimeout(state.personalJobEventsRetryTimer);
  state.personalJobEventsRetryTimer = null;
  window.clearTimeout(state.personalJobEventsRefreshTimer);
  state.personalJobEventsRefreshTimer = null;
  window.clearTimeout(state.personalJobEventsProbeTimer);
  state.personalJobEventsProbeTimer = null;
  window.clearTimeout(state.personalJobEventsStableTimer);
  state.personalJobEventsStableTimer = null;
  window.clearTimeout(state.personalKnowledgePollTimer);
  state.personalKnowledgePollTimer = null;
  if (!keepFallback) state.personalJobEventsFallback = false;
  if (complete) { state.personalJobEventsLastId = ''; state.personalJobEventsPolicy = null; }
}

function debouncePersonalKnowledgeEventRefresh() {
  window.clearTimeout(state.personalJobEventsRefreshTimer);
  state.personalJobEventsRefreshTimer = window.setTimeout(async () => {
    try {
      await loadPersonalKnowledgeDocuments({selectFirst:false});
      if (state.selectedPersonalDocumentId) await openPersonalKnowledgeDocument(state.selectedPersonalDocumentId, {scroll:false});
    } catch { /* Existing screen remains usable; retry/fallback handles transport failures. */ }
  }, 120);
}

function personalJobEventHeaders() {
  const headers = identityHeaders({'Accept':'text/event-stream'});
  if (state.personalJobEventsLastId) headers.set('Last-Event-ID', state.personalJobEventsLastId);
  return headers;
}

function enablePersonalJobEventsFallback() {
  state.personalJobEventsFallback = true;
  schedulePersonalKnowledgeRefresh();
  window.clearTimeout(state.personalJobEventsProbeTimer);
  state.personalJobEventsProbeTimer = window.setTimeout(() => {
    state.personalJobEventsProbeTimer = null;
    if (state.activeView !== 'knowledge' || state.knowledgeMode !== 'personal' || !personalKnowledgeProcessing()) return;
    state.personalJobEventsFallback = false;
    state.personalJobEventsPolicy = null;
    startPersonalJobEvents();
  }, 30000);
}

function startPersonalJobEvents() {
  if (!personalJobEvents || state.activeView !== 'knowledge' || state.knowledgeMode !== 'personal' || !personalKnowledgeProcessing() || state.personalJobEventsController || state.personalJobEventsFallback) return;
  state.personalJobEventsFallback = false;
  window.clearTimeout(state.personalKnowledgePollTimer); state.personalKnowledgePollTimer = null;
  state.personalJobEventsPolicy ||= personalJobEvents.createReconnectPolicy();
  const controller = new AbortController();
  state.personalJobEventsController = controller;
  (async () => {
    let sawEvent = false, serverRetry = 1200;
    try {
      const response = await fetch('/api/knowledge/personal/jobs/events', {headers: personalJobEventHeaders(), credentials:'same-origin', signal:controller.signal});
      if (!response.ok || !/^text\/event-stream(?:;|$)/i.test(response.headers.get('content-type') || '') || !response.body) throw new Error('SSE unavailable');
      state.personalJobEventsStableTimer = window.setTimeout(() => state.personalJobEventsPolicy?.reset(), 15000);
      const parser = personalJobEvents.createParser(event => {
        if (event.event !== 'job') return;
        serverRetry = event.retry || serverRetry;
        let job; try { job = JSON.parse(event.data); } catch { return; }
        if (!job || typeof job !== 'object') return;
        sawEvent = true;
        if (event.id) state.personalJobEventsLastId = event.id;
        state.personalKnowledgeDocuments = state.personalKnowledgeDocuments.map(doc => doc.document_id === job.document_id ? {...doc, status:job.status, latest_job:job} : doc);
        debouncePersonalKnowledgeEventRefresh();
      });
      const reader = response.body.getReader(), decoder = new TextDecoder();
      while (!controller.signal.aborted) {
        const {value, done} = await reader.read();
        if (done) break;
        parser.push(decoder.decode(value, {stream:true}));
      }
      parser.push(decoder.decode()); parser.finish();
      if (!controller.signal.aborted && personalKnowledgeProcessing() && !sawEvent) throw new Error('SSE ended without snapshot');
    } catch (error) {
      if (controller.signal.aborted) return;
      const delay = state.personalJobEventsPolicy.nextDelay(serverRetry);
      if (delay === null) { enablePersonalJobEventsFallback(); return; }
      state.personalJobEventsRetryTimer = window.setTimeout(() => { state.personalJobEventsController = null; startPersonalJobEvents(); }, delay);
      return;
    } finally {
      window.clearTimeout(state.personalJobEventsStableTimer);
      state.personalJobEventsStableTimer = null;
      if (state.personalJobEventsController === controller) state.personalJobEventsController = null;
    }
    if (!controller.signal.aborted && !personalKnowledgeProcessing()) {
      state.personalJobEventsLastId = '';
      state.personalJobEventsPolicy = null;
    } else if (!controller.signal.aborted && personalKnowledgeProcessing()) {
      const delay = state.personalJobEventsPolicy.nextDelay(serverRetry);
      if (delay === null) enablePersonalJobEventsFallback();
      else state.personalJobEventsRetryTimer = window.setTimeout(startPersonalJobEvents, delay);
    }
  })();
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
  if (personalKnowledgeProcessing()) {
    if (!state.personalJobEventsFallback) startPersonalJobEvents();
  } else stopPersonalJobEvents({complete:true});
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
  items.push(`<span class="tag-source-badge ${document.tags_source === 'auto' ? 'auto' : 'user'}">${document.tags_source === 'auto' ? '自动标记' : '手动标记'}</span>`);
  for (const tag of document.tags || []) items.push(`<span>#${escapeHtml(tag)}</span>`);
  return items.join('');
}

function renderPersonalKnowledgeContent(document) {
  const job = document.latest_job;
  const error = job?.error || (document.error_code ? {error_code:document.error_code, detail:document.error_message} : null);
  if (document.status === 'failed') {
    const ocrNote = error?.error_code === 'OCR_UNAVAILABLE' ? '<p>离线 OCR 引擎当前不可用，请稍后重试。</p>' : error?.error_code === 'OCR_FAILED' ? '<p>离线 OCR 未能识别该文件，请确认图片清晰后重试。</p>' : error?.error_code === 'OCR_QUALITY_LOW' ? '<p>文件识别质量不足，未写入知识库；请提供更清晰的原件。</p>' : '';
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
    $('#editPersonalKnowledge').disabled = personalDocument.status === 'deleting';
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
  stopPersonalJobEvents({complete:true});
  window.clearTimeout(state.personalKnowledgePollTimer);
  state.personalKnowledgePollTimer = null;
  document.querySelectorAll('[data-knowledge-mode]').forEach(button => {
    const active = button.dataset.knowledgeMode === mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  $('#knowledgeIndexTitle').textContent = mode === 'personal' ? '我的文档' : '文档目录';
  $('#knowledgeIndexHint').textContent = mode === 'personal' ? '仅当前用户可见' : '按文档浏览章节';
  $('#knowledgeFilter').placeholder = mode === 'personal' ? '搜索我的文档' : '筛选文档或章节';
  resetKnowledgeReader(mode);
  if (mode === 'personal') await loadPersonalKnowledgeDocuments();
  else await loadKnowledgeIndex();
}

const KNOWLEDGE_UPLOAD_FILE_HINT = '可多次添加并自动去重；支持 PDF、DOCX、Markdown、TXT、CSV、XLSX，单文件最大 50 MB';

function renderKnowledgeUploadQueue() {
  const queue = state.personalUploadQueue;
  const uploading = state.personalUploadInProgress;
  const statusLabels = {queued:'待上传', uploading:'上传中', success:'已上传', failed:'失败', invalid:'不支持'};
  $('#knowledgeUploadDrop').classList.toggle('has-file', queue.length > 0);
  $('#knowledgeUploadDrop').classList.toggle('is-disabled', uploading);
  $('#knowledgeUploadFile').disabled = uploading;
  $('#knowledgeUploadFileState').textContent = queue.length ? `队列中 ${queue.length} 个文件；可继续添加，重复文件会自动忽略。` : KNOWLEDGE_UPLOAD_FILE_HINT;
  $('#knowledgeUploadQueue').innerHTML = queue.map(item => `<div class="knowledge-upload-item ${item.status}"><div><strong>${escapeHtml(item.file.name)}</strong><span>${formatFileSize(item.file.size)} · ${statusLabels[item.status] || item.status}${item.error ? `：${escapeHtml(item.error)}` : ''}</span></div>${!uploading && item.status !== 'success' ? `<button type="button" class="icon-btn knowledge-upload-remove" data-upload-key="${escapeHtml(item.key)}" aria-label="移除 ${escapeHtml(item.file.name)}">×</button>` : ''}</div>`).join('') || '<p class="knowledge-upload-empty">尚未添加文件。可分多次选择或拖入文件。</p>';
  const pending = queue.filter(item => item.status === 'queued' || item.status === 'failed').length;
  const hasInvalid = personalUploadQueue.hasInvalid(queue);
  $('#confirmKnowledgeUpload').disabled = uploading || !personalUploadQueue.canUpload(queue);
  if (hasInvalid && !uploading) $('#knowledgeUploadFileState').textContent = '请先移除不支持或超限的文件，才能上传其余文件。';
  $('#confirmKnowledgeUpload').textContent = uploading ? '正在上传…' : queue.some(item => item.status === 'failed') && !queue.some(item => item.status === 'queued') ? `重试失败项（${pending}）` : `上传并处理（${pending}）`;
}

function mergeKnowledgeUploadFiles(files) {
  if (state.personalUploadInProgress) return;
  const {items, added} = personalUploadQueue.merge(state.personalUploadQueue, files);
  state.personalUploadQueue = items;
  const invalid = added.filter(item => item.status === 'invalid');
  if (invalid.length) showKnowledgeUploadMessage(`有 ${invalid.length} 个文件无法上传，请移除后继续。`, true);
  renderKnowledgeUploadQueue();
}

function showKnowledgeUploadMessage(text, error = false) {
  const message = $('#knowledgeUploadMessage');
  message.textContent = text; message.hidden = false; message.classList.toggle('error', error);
}

function resetKnowledgeUploadForm() {
  $('#knowledgeUploadForm').reset();
  state.personalUploadQueue = [];
  state.personalUploadInProgress = false;
  $('#knowledgeUploadMessage').hidden = true;
  $('#knowledgeUploadMessage').classList.remove('error');
  renderKnowledgeUploadQueue();
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
  const message = $('#knowledgeUploadMessage');
  if (state.personalUploadInProgress) return;
  if (personalUploadQueue.hasInvalid(state.personalUploadQueue)) {
    showKnowledgeUploadMessage('请先移除不支持或超限的文件，再上传其余文件。', true);
    return;
  }
  const files = state.personalUploadQueue.filter(item => item.status === 'queued' || item.status === 'failed');
  if (!files.length) return;
  const metadata = {
    process_steps: $('#knowledgeUploadStep').value ? [$('#knowledgeUploadStep').value] : [],
    equipment_ids: splitMetadataValues($('#knowledgeUploadEquipment').value),
  };
  const tags = splitMetadataValues($('#knowledgeUploadTags').value);
  if (tags.length) metadata.tags = tags;
  const effectiveDate = $('#knowledgeUploadEffectiveDate').value;
  if (effectiveDate) metadata.effective_date = effectiveDate;
  const button = $('#confirmKnowledgeUpload');
  state.personalUploadInProgress = true;
  message.hidden = true;
  message.classList.remove('error');
  renderKnowledgeUploadQueue();
  const {successes, failures} = await personalUploadQueue.uploadSequential(state.personalUploadQueue, async file => {
    const form = new FormData(); form.append('file', file); form.append('metadata', JSON.stringify(metadata));
    return api('/api/knowledge/personal/documents', {method:'POST', headers:{'Idempotency-Key':newClientMessageId()}, body:form});
  }, ({index, total}) => { renderKnowledgeUploadQueue(); button.textContent = `正在上传 ${Math.min(total, index + 1)}/${total}…`; });
  const failureDetails = failures.slice(0, 3).map(item => `${item.file.name}：${item.error || '上传失败'}`).join('；');
  const suffix = failures.length > 3 ? `；另有 ${failures.length - 3} 个文件失败` : '';
  const uploadSummary = `已成功上传 ${successes.length} 个，失败 ${failures.length} 个。${failureDetails}${suffix}`;
  let dialogClosedAfterFullSuccess = false;
  try {
    const lastSuccess = successes.at(-1);
    if (!failures.length) {
      $('#knowledgeUploadDialog').close();
      dialogClosedAfterFullSuccess = true;
      $('#knowledgeFilter').value = '';
      state.selectedPersonalDocumentId = lastSuccess.result.document_id;
      await setKnowledgeMode('personal');
      await openPersonalKnowledgeDocument(lastSuccess.result.document_id, {scroll:false});
      showToast(`已上传 ${successes.length} 个文档，正在建立个人检索索引`);
      return;
    }
    state.personalUploadQueue = state.personalUploadQueue.filter(item => item.status === 'failed' || item.status === 'invalid');
    if (successes.length) {
      $('#knowledgeFilter').value = '';
      state.selectedPersonalDocumentId = lastSuccess.result.document_id;
      await setKnowledgeMode('personal');
      await openPersonalKnowledgeDocument(lastSuccess.result.document_id, {scroll:false});
    }
    message.textContent = uploadSummary;
    message.classList.add('error');
    message.hidden = false;
  } catch (error) {
    if (dialogClosedAfterFullSuccess) {
      showToast(`已上传 ${successes.length} 个文档，但列表刷新失败：${error.message}`, {tone:'error'});
      return;
    }
    message.textContent = `${uploadSummary} 列表刷新失败：${error.message}`;
    message.classList.add('error');
    message.hidden = false;
  } finally {
    state.personalUploadInProgress = false;
    renderKnowledgeUploadQueue();
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

function openPersonalKnowledgeMetadataDialog() {
  const document = state.selectedPersonalDocument;
  if (!state.selectedPersonalDocumentId || !document) return;
  state.pendingPersonalMetadataId = state.selectedPersonalDocumentId;
  $('#personalKnowledgeMetadataTitle').value = document.title || '';
  $('#personalKnowledgeMetadataStep').value = document.process_steps?.[0] || '';
  $('#personalKnowledgeMetadataEquipment').value = (document.equipment_ids || []).join(', ');
  $('#personalKnowledgeMetadataEffectiveDate').value = document.effective_date || '';
  $('#personalKnowledgeMetadataTags').value = (document.tags || []).join(', ');
  $('#personalKnowledgeMetadataTagSource').textContent = document.tags_source === 'auto' ? '系统自动标记，可编辑确认' : '手动标记';
  $('#personalKnowledgeMetadataMessage').hidden = true;
  $('#personalKnowledgeMetadataDialog').showModal();
  requestAnimationFrame(() => $('#personalKnowledgeMetadataTitle').select());
}

function refreshRenderedPersonalSourceName(documentId, title) {
  document.querySelectorAll('.source-document-name[data-source-document-id]').forEach(element => {
    if (element.dataset.sourceDocumentId === documentId) element.textContent = title;
  });
}

async function savePersonalKnowledgeMetadata(event) {
  event.preventDefault();
  const documentId = state.pendingPersonalMetadataId;
  const message = $('#personalKnowledgeMetadataMessage');
  if (!documentId || !state.selectedPersonalDocument) return;
  const {error, patch} = personalKnowledgeMetadata.buildPatch(state.selectedPersonalDocument, {
    title: $('#personalKnowledgeMetadataTitle').value,
    process_step: $('#personalKnowledgeMetadataStep').value,
    equipment_ids: $('#personalKnowledgeMetadataEquipment').value,
    effective_date: $('#personalKnowledgeMetadataEffectiveDate').value,
    tags: $('#personalKnowledgeMetadataTags').value,
  });
  if (error) {
    message.textContent = error;
    message.hidden = false;
    return;
  }
  if (!Object.keys(patch).length) { $('#personalKnowledgeMetadataDialog').close(); showToast('未修改文档信息'); return; }
  const button = $('#confirmPersonalKnowledgeMetadata');
  button.disabled = true;
  try {
    const updated = await api(`/api/knowledge/personal/documents/${encodeURIComponent(documentId)}`, {
      method: 'PATCH',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(patch),
    });
    state.personalKnowledgeDocuments = state.personalKnowledgeDocuments.map(document => document.document_id === documentId ? {...document, ...updated} : document);
    if (state.selectedPersonalDocumentId === documentId) {
      state.selectedPersonalDocument = {...state.selectedPersonalDocument, ...updated};
      $('#knowledgeTitle').textContent = updated.title;
      $('#knowledgeMeta').innerHTML = personalKnowledgeMeta(state.selectedPersonalDocument);
    }
    renderPersonalKnowledgeDocuments();
    refreshRenderedPersonalSourceName(documentId, updated.title);
    $('#personalKnowledgeMetadataDialog').close();
    showToast('个人知识信息已更新');
    if ($('#knowledgeFilter').value.trim()) {
      try { await loadPersonalKnowledgeDocuments({selectFirst:false}); }
      catch (refreshError) { showToast(`信息已保存，但列表刷新失败：${refreshError.message}`, {tone:'error'}); }
    }
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
  } finally {
    button.disabled = false;
  }
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

    return { renderKnowledgeDocuments, personalKnowledgeStatusLabel, resetKnowledgeReader, renderPersonalKnowledgeDocuments, schedulePersonalKnowledgeRefresh, personalKnowledgeProcessing, stopPersonalJobEvents, debouncePersonalKnowledgeEventRefresh, personalJobEventHeaders, enablePersonalJobEventsFallback, startPersonalJobEvents, loadPersonalKnowledgeDocuments, personalKnowledgeMeta, renderPersonalKnowledgeContent, openPersonalKnowledgeDocument, openPersonalKnowledgeChunk, setKnowledgeMode, renderKnowledgeUploadQueue, mergeKnowledgeUploadFiles, showKnowledgeUploadMessage, resetKnowledgeUploadForm, openKnowledgeUploadDialog, uploadPersonalKnowledge, retrySelectedPersonalKnowledge, openPersonalKnowledgeMetadataDialog, refreshRenderedPersonalSourceName, savePersonalKnowledgeMetadata, openPersonalKnowledgeDeleteDialog, deleteSelectedPersonalKnowledge, downloadSelectedPersonalKnowledge, loadKnowledgeIndex, openKnowledgeChunk, renderCaseList, loadCaseIndex, openHistoricalCase };
  }
  return { createKnowledgeController };
});
