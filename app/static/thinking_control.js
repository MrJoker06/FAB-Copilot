(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabThinkingControl = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  const EFFORTS = ['low', 'medium', 'high', 'xhigh'];
  const LABELS = {off: '关闭', low: '低', medium: '中', high: '高', xhigh: '极高'};
  function normalizeCapabilities(capabilities = {}) {
    const thinking = capabilities?.thinking === true;
    const declared = Array.isArray(capabilities?.thinking_effort_options)
      ? capabilities.thinking_effort_options.filter(value => EFFORTS.includes(value))
      : [];
    const options = thinking ? (declared.length ? declared : ['low', 'medium', 'high']) : [];
    return {thinking, effort: capabilities?.thinking_effort || (thinking ? 'high' : 'off'), options};
  }
  function modelCapabilities(modelConfig = {}) {
    const capabilities = modelConfig.capabilities || {};
    const thinking = modelConfig.thinking || {};
    return {
      ...capabilities,
      thinking: thinking.thinking ?? capabilities.thinking,
      thinking_effort: thinking.effort ?? capabilities.thinking_effort,
      thinking_effort_options: thinking.options ?? capabilities.thinking_effort_options,
      reasoning_dialect: thinking.dialect ?? capabilities.reasoning_dialect,
    };
  }
  function supportsThinking(modelConfig = {}) {
    return normalizeCapabilities(modelCapabilities(modelConfig)).thinking;
  }
  function availableEfforts(modelConfig = {}) {
    const settings = normalizeCapabilities(modelCapabilities(modelConfig));
    return settings.thinking ? ['off', ...settings.options] : ['off'];
  }
  function defaultEffort(modelConfig = {}) {
    const settings = normalizeCapabilities(modelCapabilities(modelConfig));
    const available = availableEfforts(modelConfig);
    return available.includes(settings.effort) ? settings.effort : (available[1] || 'off');
  }
  function reconcile(modelConfig = {}, effort = 'off') {
    const supported = supportsThinking(modelConfig);
    const available = availableEfforts(modelConfig);
    const selected = supported && available.includes(effort) ? effort : (supported ? defaultEffort(modelConfig) : 'off');
    return {supported, enabled: selected !== 'off', effort: selected, options: available};
  }
  function requestPayload(payload = {}, modelConfig = {}, effort = 'off') {
    const next = {...payload};
    const state = reconcile(modelConfig, effort);
    next.thinking = state.enabled;
    next.thinking_effort = state.effort;
    return next;
  }
  function options(modelConfig = {}) {
    return availableEfforts(modelConfig).map(value => ({value, label: LABELS[value] || value}));
  }
  return {normalizeCapabilities, supportsThinking, availableEfforts, defaultEffort, reconcile, requestPayload, options, LABELS};
});
