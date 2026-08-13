(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabPersonalJobEvents = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const ACTIVE = new Set(['uploaded', 'parsing', 'chunking', 'indexing', 'deleting']);
  const TERMINAL = new Set(['ready', 'failed', 'deleted']);

  function isActive(status) { return ACTIVE.has(status); }
  function isTerminal(status) { return TERMINAL.has(status); }

  function createParser(onEvent) {
    let buffer = '', event = {};
    function dispatch() {
      if (event.data !== undefined) onEvent({event: event.event || 'message', data: event.data, id: event.id || '', retry: event.retry});
      event = {};
    }
    function line(raw) {
      if (!raw) return dispatch();
      if (raw.startsWith(':')) return;
      const colon = raw.indexOf(':');
      const field = colon < 0 ? raw : raw.slice(0, colon);
      const value = (colon < 0 ? '' : raw.slice(colon + 1)).replace(/^ /, '');
      if (field === 'data') event.data = event.data === undefined ? value : `${event.data}\n${value}`;
      else if (field === 'event' || field === 'id') event[field] = value;
      else if (field === 'retry' && /^\d+$/.test(value)) event.retry = Number(value);
    }
    return {
      push(chunk) {
        buffer += String(chunk || '');
        const separator = /\r\n|\r|\n/;
        let match;
        while ((match = separator.exec(buffer))) {
          if (match[0] === '\r' && match.index + 1 === buffer.length) return;
          line(buffer.slice(0, match.index)); buffer = buffer.slice(match.index + match[0].length);
        }
      },
      finish() { if (buffer) line(buffer); buffer = ''; dispatch(); },
    };
  }

  function createReconnectPolicy({maxAttempts = 3, baseDelay = 300, maxDelay = 1200} = {}) {
    let attempts = 0;
    return {
      reset() { attempts = 0; },
      nextDelay(serverRetry) {
        attempts += 1;
        if (attempts > maxAttempts) return null;
        return Math.min(maxDelay, Math.max(0, Number(serverRetry) || baseDelay * (2 ** (attempts - 1))));
      },
      attempts: () => attempts,
    };
  }

  return {createParser, createReconnectPolicy, isActive, isTerminal};
});
