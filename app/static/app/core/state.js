(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabAppState = api;
})(globalThis, () => {
  function createState() {
    return {
      dashboard: null, history: [], sessionId: null, sessionLibrary: [], sessionLibraryFilter: 'active', selectedLibrarySessionId: null,
      selectedSessionIds: new Set(), sessionBatchMode: false, sessionLibraryRequestId: 0, sessionLibraryPreviewRequestId: 0,
      pendingRenameSessionId: null, pendingDeleteSessionIds: [], toastTimer: null, activeView: 'dashboard', previousView: 'dashboard',
      streaming: false, chartPoints: [], activeStep: 'CVD', modelConfig: null, enterpriseContext: null, knowledgeMode: 'factory',
      knowledgeDocuments: [], knowledgeIndexPromise: null, personalKnowledgeDocuments: [], selectedPersonalDocumentId: null,
      selectedPersonalDocument: null, personalKnowledgeRequestId: 0, personalKnowledgePollTimer: null, personalJobEventsController: null,
      personalJobEventsRetryTimer: null, personalJobEventsRefreshTimer: null, personalJobEventsProbeTimer: null,
      personalJobEventsStableTimer: null, personalJobEventsLastId: '', personalJobEventsFallback: false, personalJobEventsPolicy: null,
      personalUploadQueue: [], personalUploadInProgress: false, pendingPersonalMetadataId: null, pendingPersonalDeleteId: null,
      cases: [], casesPromise: null, capabilityCache: new Map(), capabilityController: null, capabilityRequestId: 0,
    };
  }

  return { createState };
});
