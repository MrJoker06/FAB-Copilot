(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabAppBootstrap = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  const CHAT_DRAFT_KEY = 'fabInsightChatDraft';

  function createBootstrap(deps = {}) {
    const {
      state, $, api, setInitialDates, initializeAgentResize, restoreAgentPanelWidth,
      loadModelConfig, updateSystemStatus, handleBuildVersion, loadDashboard,
      restoreConversation, setAgentOpen, showView, loadCapability,
      renderKnowledgeDocuments, loadPersonalKnowledgeDocuments, setKnowledgeMode,
      openKnowledgeChunk, openPersonalKnowledgeDocument, openKnowledgeUploadDialog,
      uploadPersonalKnowledge, mergeKnowledgeUploadFiles, renderKnowledgeUploadQueue,
      resetKnowledgeUploadForm, downloadSelectedPersonalKnowledge,
      openPersonalKnowledgeMetadataDialog, retrySelectedPersonalKnowledge,
      openPersonalKnowledgeDeleteDialog, deleteSelectedPersonalKnowledge,
      savePersonalKnowledgeMetadata, renderCaseList, openHistoricalCase,
      clearSessionBatchSelection, loadSessionLibrary, filteredSessionLibrary,
      renderSessionLibrary, setSessionBatchMode, openSessionDeleteDialog,
      runSessionLibraryAction, openSessionLibraryPreview, openSessionRenameDialog,
      toggleSelectedLibrarySessionArchive, continueSelectedLibrarySession,
      updateSessionRenameCount, renameSelectedLibrarySession,
      permanentlyDeleteSelectedSession, createConversation, closeSessionLibraryWorkspace,
      openSessionLibraryWorkspace, toggleAgentPanel, sendChat, toggleThinking,
      openModelSettings, saveModelSettings, checkAppVersion, drawYieldChart,
      showToast, personalUploadQueue, openPersonalKnowledgeChunk,
      windowImpl = root, documentImpl = root.document,
      localStorageImpl = root.localStorage, sessionStorageImpl = root.sessionStorage,
    } = deps;
    const window = windowImpl;
    const document = documentImpl;
    const localStorage = localStorageImpl;
    const sessionStorage = sessionStorageImpl;

    function showSourceTarget(event) {
      const knowledgeTarget = event.target.closest('[data-knowledge-chunk]');
      const personalTarget = event.target.closest('[data-personal-chunk]');
      const caseTarget = event.target.closest('[data-case-id]');
      if (knowledgeTarget) {
        openKnowledgeChunk(Number(knowledgeTarget.dataset.knowledgeChunk));
        return true;
      }
      else if (personalTarget) {
        openPersonalKnowledgeChunk(personalTarget.dataset.personalChunk)
          .catch(error => showToast(`个人来源加载失败：${error.message}`, { tone: 'error' }));
        return true;
      } else if (caseTarget) {
        openHistoricalCase(caseTarget.dataset.caseId);
        return true;
      }
      return false;
    }

    function bindEvents() {
      $('#dateForm').addEventListener('submit', event => {
        event.preventDefault();
        state.capabilityCache.clear();
        loadDashboard();
        if ($('#capabilityView').classList.contains('active')) loadCapability();
      });
      document.querySelectorAll('[data-view]').forEach(button => {
        button.addEventListener('click', () => showView(button.dataset.view));
      });
      $('#focusAgent').addEventListener('click', toggleAgentPanel);
      $('#mobileAgentToggle').addEventListener('click', toggleAgentPanel);
      $('#collapseAgent').addEventListener('click', () => setAgentOpen(false));
      $('#sessionHistoryButton').addEventListener('click', () => {
        if (state.activeView === 'sessions') closeSessionLibraryWorkspace();
        else openSessionLibraryWorkspace();
      });
      $('#closeSessionLibrary').addEventListener('click', closeSessionLibraryWorkspace);
      $('#stepSelector').addEventListener('click', event => {
        if (!event.target.dataset.step) return;
        document.querySelectorAll('#stepSelector button').forEach(button => button.classList.remove('active'));
        event.target.classList.add('active');
        loadCapability(event.target.dataset.step);
      });

      let knowledgeSearchTimer = null;
      $('#knowledgeFilter').addEventListener('input', event => {
        window.clearTimeout(knowledgeSearchTimer);
        if (state.knowledgeMode === 'factory') renderKnowledgeDocuments(event.target.value);
        else {
          knowledgeSearchTimer = window.setTimeout(() => {
            loadPersonalKnowledgeDocuments({ selectFirst: true })
              .catch(error => showToast(`搜索失败：${error.message}`, { tone: 'error' }));
          }, 180);
        }
      });
      $('#knowledgeSourceTabs').addEventListener('click', event => {
        const button = event.target.closest('[data-knowledge-mode]');
        if (button) {
          setKnowledgeMode(button.dataset.knowledgeMode)
            .catch(error => showToast(`知识库加载失败：${error.message}`, { tone: 'error' }));
        }
      });
      $('#knowledgeDocuments').addEventListener('click', event => {
        const factoryTarget = event.target.closest('[data-knowledge-chunk]');
        const personalTarget = event.target.closest('[data-personal-document-id]');
        if (factoryTarget) openKnowledgeChunk(Number(factoryTarget.dataset.knowledgeChunk));
        else if (personalTarget) {
          openPersonalKnowledgeDocument(personalTarget.dataset.personalDocumentId)
            .catch(error => showToast(`文档加载失败：${error.message}`, { tone: 'error' }));
        } else if (event.target.closest('[data-open-knowledge-upload]')) openKnowledgeUploadDialog();
      });
      $('#knowledgeUploadForm').addEventListener('submit', uploadPersonalKnowledge);
      $('#knowledgeUploadFile').addEventListener('change', event => {
        mergeKnowledgeUploadFiles(event.target.files);
        event.target.value = '';
      });
      $('#knowledgeUploadDrop').addEventListener('keydown', event => {
        if (!['Enter', ' '].includes(event.key) || state.personalUploadInProgress) return;
        event.preventDefault();
        $('#knowledgeUploadFile').click();
      });
      $('#knowledgeUploadDrop').addEventListener('dragover', event => {
        event.preventDefault();
        event.currentTarget.classList.add('dragging');
      });
      $('#knowledgeUploadDrop').addEventListener('dragleave', event => {
        event.currentTarget.classList.remove('dragging');
      });
      $('#knowledgeUploadDrop').addEventListener('drop', event => {
        event.preventDefault();
        event.currentTarget.classList.remove('dragging');
        const files = event.dataTransfer?.files;
        if (files?.length) mergeKnowledgeUploadFiles(files);
      });
      $('#knowledgeUploadQueue').addEventListener('click', event => {
        const button = event.target.closest('[data-upload-key]');
        if (!button || state.personalUploadInProgress) return;
        state.personalUploadQueue = personalUploadQueue.remove(
          state.personalUploadQueue,
          button.dataset.uploadKey,
        );
        renderKnowledgeUploadQueue();
      });
      const closeKnowledgeUploadDialog = () => {
        if (!state.personalUploadInProgress) $('#knowledgeUploadDialog').close();
      };
      $('#closeKnowledgeUploadDialog').addEventListener('click', closeKnowledgeUploadDialog);
      $('#cancelKnowledgeUpload').addEventListener('click', closeKnowledgeUploadDialog);
      $('#knowledgeUploadDialog').addEventListener('cancel', event => {
        if (state.personalUploadInProgress) event.preventDefault();
      });
      $('#knowledgeUploadDialog').addEventListener('close', resetKnowledgeUploadForm);
      $('#downloadPersonalKnowledge').addEventListener('click', downloadSelectedPersonalKnowledge);
      $('#editPersonalKnowledge').addEventListener('click', openPersonalKnowledgeMetadataDialog);
      $('#retryPersonalKnowledge').addEventListener('click', retrySelectedPersonalKnowledge);
      $('#deletePersonalKnowledge').addEventListener('click', openPersonalKnowledgeDeleteDialog);
      $('#personalKnowledgeDeleteForm').addEventListener('submit', deleteSelectedPersonalKnowledge);
      $('#closePersonalKnowledgeDeleteDialog').addEventListener('click', () => {
        $('#personalKnowledgeDeleteDialog').close();
      });
      $('#cancelPersonalKnowledgeDelete').addEventListener('click', () => {
        $('#personalKnowledgeDeleteDialog').close();
      });
      $('#personalKnowledgeDeleteDialog').addEventListener('close', () => {
        state.pendingPersonalDeleteId = null;
      });
      $('#personalKnowledgeMetadataForm').addEventListener('submit', savePersonalKnowledgeMetadata);
      $('#closePersonalKnowledgeMetadataDialog').addEventListener('click', () => {
        $('#personalKnowledgeMetadataDialog').close();
      });
      $('#cancelPersonalKnowledgeMetadata').addEventListener('click', () => {
        $('#personalKnowledgeMetadataDialog').close();
      });
      $('#personalKnowledgeMetadataDialog').addEventListener('close', () => {
        state.pendingPersonalMetadataId = null;
        $('#personalKnowledgeMetadataMessage').hidden = true;
      });

      $('#caseFilter').addEventListener('input', renderCaseList);
      $('#caseStepFilter').addEventListener('change', renderCaseList);
      $('#caseList').addEventListener('click', event => {
        const target = event.target.closest('[data-case-id]');
        if (target) openHistoricalCase(target.dataset.caseId);
      });

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
        document.querySelectorAll('[data-session-filter]').forEach(item => {
          item.classList.toggle('active', item === button);
        });
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
        } else if (!event.target.closest('summary')) openSessionLibraryPreview(sessionId);
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
      $('#deleteSelectedSessions').addEventListener('click', () => {
        openSessionDeleteDialog([...state.selectedSessionIds]);
      });
      $('#sessionLibraryMessages').addEventListener('click', showSourceTarget);
      $('#renameLibrarySession').addEventListener('click', () => openSessionRenameDialog());
      $('#archiveLibrarySession').addEventListener('click', toggleSelectedLibrarySessionArchive);
      $('#deleteLibrarySession').addEventListener('click', () => {
        openSessionDeleteDialog(state.selectedLibrarySessionId);
      });
      $('#continueLibrarySession').addEventListener('click', continueSelectedLibrarySession);
      $('#sessionRenameForm').addEventListener('submit', event => {
        event.preventDefault();
        renameSelectedLibrarySession();
      });
      $('#sessionRenameInput').addEventListener('input', () => {
        updateSessionRenameCount();
        $('#sessionRenameMessage').hidden = true;
      });
      $('#closeSessionRenameDialog').addEventListener('click', () => $('#sessionRenameDialog').close());
      $('#cancelSessionRename').addEventListener('click', () => $('#sessionRenameDialog').close());
      $('#sessionRenameDialog').addEventListener('close', () => {
        state.pendingRenameSessionId = null;
        $('#sessionRenameMessage').hidden = true;
      });
      $('#sessionDeleteForm').addEventListener('submit', event => {
        event.preventDefault();
        permanentlyDeleteSelectedSession()
          .catch(error => showToast(`删除失败：${error.message}`, { tone: 'error' }));
      });
      $('#closeSessionDeleteDialog').addEventListener('click', () => $('#sessionDeleteDialog').close());
      $('#cancelSessionDelete').addEventListener('click', () => $('#sessionDeleteDialog').close());
      $('#sessionDeleteDialog').addEventListener('close', () => {
        state.pendingDeleteSessionIds = [];
      });
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
        const sourceHandled = showSourceTarget(event);
        const suggestion = event.target.closest('.suggestions button');
        if (!sourceHandled && suggestion) sendChat(suggestion.textContent);
      });
      $('#chatForm').addEventListener('submit', event => {
        event.preventDefault();
        sendChat($('#chatInput').value);
      });
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
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden) checkAppVersion();
      });
      $('#clearChat').addEventListener('click', async () => {
        if (!state.streaming) await createConversation('已创建新会话。');
      });
      $('#modelSettingsButton').addEventListener('click', openModelSettings);
      $('#modelSettingsForm').addEventListener('submit', saveModelSettings);
      $('#closeModelDialog').addEventListener('click', () => $('#modelDialog').close());
      $('#cancelModelSettings').addEventListener('click', () => $('#modelDialog').close());
      $('#yieldChart').addEventListener('mousemove', event => {
        const rect = event.currentTarget.getBoundingClientRect();
        const mouseX = event.clientX - rect.left;
        const point = state.chartPoints.reduce(
          (closest, candidate) => Math.abs(candidate.x - mouseX) < Math.abs(closest.x - mouseX)
            ? candidate
            : closest,
          state.chartPoints[0],
        );
        const tooltip = $('#chartTooltip');
        if (!point || Math.abs(point.x - mouseX) > 18) {
          tooltip.hidden = true;
          return;
        }
        tooltip.hidden = false;
        tooltip.style.left = `${point.x}px`;
        tooltip.style.top = `${point.y}px`;
        tooltip.textContent = `${point.row.week_start} · ${point.row.yield_pct}% · ${point.row.lots}批`;
      });
      $('#yieldChart').addEventListener('mouseleave', () => { $('#chartTooltip').hidden = true; });
      window.addEventListener('resize', () => {
        restoreAgentPanelWidth();
        if (state.dashboard) drawYieldChart(state.dashboard.yield_trend);
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
      } catch {
        $('#systemStatus').textContent = '数据源不可用';
      }
      await loadDashboard();
      await restoreConversation();
      setAgentOpen(true, false);
      const requestedView = new URLSearchParams(window.location.search).get('view');
      if (['dashboard', 'capability', 'knowledge', 'cases', 'sessions'].includes(requestedView)) {
        showView(requestedView);
      }
      bindEvents();
      document.documentElement.dataset.appReady = 'true';
    }

    return { init, bindEvents };
  }

  return { createBootstrap };
});
