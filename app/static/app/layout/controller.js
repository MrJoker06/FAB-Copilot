(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabLayoutController = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  const AGENT_WIDTH_KEY = 'fabInsightAgentWidth';
  const AGENT_MIN_WIDTH = 300;
  const AGENT_MAX_WIDTH = 620;

  function createLayoutController(deps = {}) {
    const {
      state, $, loadCapability = () => {}, loadPersonalKnowledgeDocuments = () => {},
      loadKnowledgeIndex = () => {}, loadCaseIndex = () => {}, loadSessionLibrary = () => {},
      stopPersonalJobEvents = () => {}, drawYieldChart = () => {}, windowImpl = root,
      documentImpl = root.document, localStorageImpl = root.localStorage,
      requestAnimationFrameImpl = root.requestAnimationFrame,
    } = deps;
    const window = windowImpl;
    const document = documentImpl;
    const localStorage = localStorageImpl;
    const requestAnimationFrame = requestAnimationFrameImpl;

    function showView(name) {
      if (name !== 'sessions') state.previousView = name;
      state.activeView = name;
      if (name !== 'knowledge') stopPersonalJobEvents({ complete: true });
      document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
      document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
      document.querySelectorAll('.nav-item[data-view]').forEach(item => item.removeAttribute('aria-current'));
      document.querySelector(`[data-view="${name}"]`)?.setAttribute('aria-current', 'page');
      $(`#${name}View`).classList.add('active');
      document.querySelector(`[data-view="${name}"]`)?.classList.add('active');

      const historyActive = name === 'sessions';
      const historyButton = $('#sessionHistoryButton');
      historyButton.classList.toggle('active', historyActive);
      historyButton.setAttribute('aria-expanded', String(historyActive));
      historyButton.setAttribute('aria-label', historyActive ? '关闭历史会话' : '打开历史会话');
      historyButton.title = historyActive ? '关闭历史会话' : '打开历史会话';
      if (!document.querySelector('.app-shell').classList.contains('agent-collapsed')) {
        $('#focusAgent').classList.add('active');
      }
      if (name === 'capability') loadCapability();
      else if (name === 'knowledge') {
        if (state.knowledgeMode === 'personal') loadPersonalKnowledgeDocuments();
        else loadKnowledgeIndex();
      } else if (name === 'cases') loadCaseIndex();
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
        panel.scrollIntoView({ behavior: 'smooth', block: window.innerWidth <= 980 ? 'start' : 'nearest' });
        window.setTimeout(() => $('#chatInput').focus({ preventScroll: true }), 350);
      }
    }

    function toggleAgentPanel() {
      const collapsed = document.querySelector('.app-shell').classList.contains('agent-collapsed');
      setAgentOpen(collapsed);
    }

    function getAgentWidthBounds() {
      const sidebarWidth = $('.sidebar').getBoundingClientRect().width;
      const minimumMainWidth = window.innerWidth <= 1280 ? 600 : 660;
      return {
        min: AGENT_MIN_WIDTH,
        max: Math.max(AGENT_MIN_WIDTH, Math.min(
          AGENT_MAX_WIDTH,
          window.innerWidth - sidebarWidth - minimumMainWidth,
        )),
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
        if (state.dashboard) drawYieldChart(state.dashboard.yield_trend);
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

    return { showView, setAgentOpen, toggleAgentPanel, getAgentWidthBounds, updateAgentResizeAria, setAgentPanelWidth, restoreAgentPanelWidth, resetAgentPanelWidth, initializeAgentResize };
  }

  return { createLayoutController };
});
