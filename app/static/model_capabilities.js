(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabModelCapabilities = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  const definitions = [
    ['streaming', '流式输出'], ['tool_calls', '工具调用'],
    ['thinking', 'Thinking'], ['native_multimodal', '原生多模态'],
  ];
  function publishPayload(values = {}) {
    return Object.fromEntries(definitions.map(([key]) => [key, values[key] === true]));
  }
  function labels(capabilities = {}) {
    return definitions.filter(([key]) => capabilities[key] === true).map(([, label]) => label);
  }
  return {publishPayload, labels};
});
