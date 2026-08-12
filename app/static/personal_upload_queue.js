(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabPersonalUploadQueue = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  const MAX_BYTES = 50 * 1024 * 1024;
  const ALLOWED_EXTENSIONS = new Set(['pdf', 'docx', 'md', 'txt', 'csv', 'xlsx', 'png', 'jpg', 'jpeg', 'tif', 'tiff']);

  function fileKey(file) { return [file.name, file.size, file.lastModified, file.type].join('|'); }
  function extension(file) { return String(file.name || '').split('.').pop().toLowerCase(); }
  function validateFile(file) {
    if (!ALLOWED_EXTENSIONS.has(extension(file))) return `不支持 ${file.name} 的文件类型`;
    if (Number(file.size) > MAX_BYTES) return `${file.name} 超过 50 MB`;
    return '';
  }
  function createItem(file) {
    const error = validateFile(file);
    return {key: fileKey(file), file, status: error ? 'invalid' : 'queued', error};
  }
  function merge(items, files) {
    const seen = new Set(items.map(item => item.key));
    const added = [];
    for (const file of Array.from(files || [])) {
      const key = fileKey(file);
      if (seen.has(key)) continue;
      seen.add(key);
      added.push(createItem(file));
    }
    return {items: [...items, ...added], added};
  }
  function remove(items, key) { return items.filter(item => item.key !== key); }
  function hasInvalid(items) { return items.some(item => item.status === 'invalid'); }
  function canUpload(items) { return !hasInvalid(items) && items.some(item => item.status === 'queued' || item.status === 'failed'); }
  async function uploadSequential(items, upload, onProgress = () => {}) {
    const active = items.filter(item => item.status === 'queued' || item.status === 'failed');
    const successes = [], failures = [];
    for (let index = 0; index < active.length; index += 1) {
      const item = active[index];
      item.status = 'uploading'; item.error = '';
      onProgress({item, index, total: active.length});
      try { item.result = await upload(item.file, item); item.status = 'success'; successes.push(item); }
      catch (error) { item.status = 'failed'; item.error = error?.message || '上传失败'; failures.push(item); }
      onProgress({item, index: index + 1, total: active.length});
    }
    return {successes, failures};
  }
  function retryable(items) { return items.filter(item => item.status === 'failed'); }
  return {MAX_BYTES, ALLOWED_EXTENSIONS, fileKey, validateFile, merge, remove, hasInvalid, canUpload, uploadSequential, retryable};
});
