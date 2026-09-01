(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabAppApi = api;
})(globalThis, (root) => {
  const TENANT_ID_KEY = 'fabInsightTenantId';
  const USER_ID_KEY = 'fabInsightUserId';

  class FabApiError extends Error {
    constructor(message, { code = 'REQUEST_ERROR', requestId = '', retryable = false, status = 0 } = {}) {
      super(message);
      this.name = 'FabApiError'; this.code = code; this.requestId = requestId; this.retryable = retryable; this.status = status;
    }
  }

  const identityHeaders = (initial = {}, { HeadersImpl = root.Headers, storage = root.localStorage } = {}) => {
    const headers = new HeadersImpl(initial);
    const tenantId = storage.getItem(TENANT_ID_KEY), userId = storage.getItem(USER_ID_KEY);
    if (tenantId) headers.set('X-Tenant-ID', tenantId);
    if (userId) headers.set('X-User-ID', userId);
    return headers;
  };
  const apiError = (payload = {}, response = null) => new FabApiError(payload.detail || `请求失败 (${response?.status || '网络错误'})`, {
    code: payload.error_code || 'REQUEST_ERROR', requestId: payload.request_id || response?.headers?.get('x-request-id') || '', retryable: Boolean(payload.retryable), status: response?.status || 0,
  });
  async function api(url, options, { fetchImpl = root.fetch, headersOptions } = {}) {
    const headers = identityHeaders(options?.headers || {}, headersOptions);
    let response;
    try { response = await fetchImpl(url, { ...(options || {}), headers }); }
    catch (error) { throw new FabApiError('无法连接 Fab Insight 服务', { code: 'NETWORK_ERROR', retryable: true }); }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw apiError(payload, response);
    return payload;
  }

  return { FabApiError, TENANT_ID_KEY, USER_ID_KEY, api, apiError, identityHeaders };
});
