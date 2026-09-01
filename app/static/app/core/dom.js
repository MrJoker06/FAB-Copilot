(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabAppDom = api;
})(globalThis, () => {
  const $ = (selector) => document.querySelector(selector);
  const isoDate = (date) => date.toISOString().slice(0, 10);
  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
  const formatNumber = (value) => {
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString('zh-CN') : String(value ?? '—');
  };
  const formatFileSize = (value) => {
    const bytes = Number(value) || 0;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  };
  const setInitialDates = () => {
    const end = new Date();
    const start = new Date();
    start.setDate(end.getDate() - 89);
    $('#startDate').value = isoDate(start);
    $('#endDate').value = isoDate(end);
  };

  return { $, escapeHtml, formatFileSize, formatNumber, isoDate, setInitialDates };
});
