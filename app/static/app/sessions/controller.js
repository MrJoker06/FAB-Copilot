(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabSessionController = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  function createSessionController(deps = {}) {
    const {
      state, $, escapeHtml, api, showToast, sourcePresenter, presenter,
      windowImpl = root, localStorageImpl = root.localStorage,
      requestAnimationFrameImpl = root.requestAnimationFrame,
      getShowView = () => () => {}, getSetAgentOpen = () => () => {},
    } = deps;
    const window = windowImpl;
    const localStorage = localStorageImpl;
    const requestAnimationFrame = requestAnimationFrameImpl;
    const { welcomeMarkup, addMessage, sourceReferenceMap, renderMarkdown, renderSourcePanel } = presenter;
    const showView = (...args) => getShowView()(...args);
    const setAgentOpen = (...args) => getSetAgentOpen()(...args);
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


    return {
      renderConversation, createConversation, restoreConversation, sessionGroup, openSession,
      filteredSessionLibrary, updateSessionBatchToolbar, setSessionBatchMode, clearSessionBatchSelection,
      renderSessionLibrary, renderSessionLibraryPreview, openSessionLibraryPreview, loadSessionLibrary,
      updateSessionRenameCount, openSessionRenameDialog, renameSelectedLibrarySession, resetConversationDraft,
      archiveLibrarySession, restoreLibrarySession, openSessionDeleteDialog, permanentlyDeleteSelectedSession,
      runSessionLibraryAction, toggleSelectedLibrarySessionArchive, continueSelectedLibrarySession,
      openSessionLibraryWorkspace, closeSessionLibraryWorkspace,
    };
  }

  return { createSessionController };
});
