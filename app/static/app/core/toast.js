(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabAppToast = api;
})(globalThis, () => {
  function createToast(state, { $, escapeHtml, documentImpl = document, windowImpl = window } = globalThis.FabAppDom) {
    function dismissToast() {
      windowImpl.clearTimeout(state.toastTimer);
      state.toastTimer = null;
      $('#toastRegion').innerHTML = '';
    }
    function showToast(message, { actionLabel = '', onAction = null, tone = 'default', duration = 5200 } = {}) {
      dismissToast();
      const toast = documentImpl.createElement('div');
      toast.className = `toast${tone === 'error' ? ' error' : ''}`;
      toast.innerHTML = `<span class="toast-message">${escapeHtml(message)}</span>${actionLabel ? `<button type="button" class="toast-action">${escapeHtml(actionLabel)}</button>` : ''}<button type="button" class="toast-close" aria-label="关闭提示">×</button>`;
      $('#toastRegion').appendChild(toast);
      toast.querySelector('.toast-close').addEventListener('click', dismissToast);
      toast.querySelector('.toast-action')?.addEventListener('click', async () => {
        dismissToast();
        try { await onAction?.(); }
        catch (error) { showToast(`操作失败：${error.message}`, { tone: 'error' }); }
      });
      state.toastTimer = windowImpl.setTimeout(dismissToast, duration);
    }
    return { dismissToast, showToast };
  }

  return { createToast };
});
