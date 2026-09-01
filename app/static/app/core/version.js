(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabAppVersion = api;
})(globalThis, (root) => {
  const DISMISSED_VERSION_KEY = 'fabInsightDismissedVersion';
  function createVersion({ api, $, documentImpl = root.document, storage = root.sessionStorage } = {}) {
    const APP_VERSION = documentImpl.querySelector('meta[name="app-version"]')?.content || 'unknown';
    function handleBuildVersion(build) {
      if (!build?.version || build.version === APP_VERSION) return;
      if (storage.getItem(DISMISSED_VERSION_KEY) === build.version) return;
      const banner = $('#versionBanner');
      banner.dataset.version = build.version;
      banner.hidden = false;
    }
    async function checkAppVersion() {
      try { handleBuildVersion(await api('/api/version')); }
      catch { /* Keep version checks silent; normal API requests expose connectivity failures. */ }
    }
    return { APP_VERSION, checkAppVersion, handleBuildVersion };
  }

  return { DISMISSED_VERSION_KEY, createVersion };
});
