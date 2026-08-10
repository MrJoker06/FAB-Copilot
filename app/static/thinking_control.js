(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabThinkingControl = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  function normalizeCapabilities(capabilities = {}) {
    return {thinking: capabilities?.thinking === true};
  }
  function supportsThinking(modelConfig = {}) {
    return normalizeCapabilities(modelConfig.capabilities).thinking;
  }
  function reconcile(modelConfig = {}, enabled = false) {
    const supported = supportsThinking(modelConfig);
    return {supported, enabled: supported && enabled === true};
  }
  function requestPayload(payload = {}, modelConfig = {}, enabled = false) {
    const next = {...payload};
    if (reconcile(modelConfig, enabled).enabled) next.thinking = true;
    else delete next.thinking;
    return next;
  }
  return {normalizeCapabilities, supportsThinking, reconcile, requestPayload};
});
