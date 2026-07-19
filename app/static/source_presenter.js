(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabSourcePresenter = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  function displayName(source = {}) {
    return String(source.title || source.source || source.filename || '未命名来源').trim();
  }

  function locationLabel(source = {}) {
    if (source.section) return String(source.section).trim();
    if (source.page_number) return `第 ${source.page_number} 页`;
    return '';
  }

  function typeLabel(source = {}) {
    if (source.source_type === 'personal') return '个人知识';
    if (source.source_type === 'case' || source.case_id) return '历史案例';
    return '工厂知识';
  }

  function documentKey(source = {}) {
    const locator = source.document_id || source.case_id || source.source || source.title || source.filename;
    return `${source.source_type || 'knowledge'}:${locator || source.chunk_id || source.reference_id || ''}`;
  }

  function citationLabel(source = {}) {
    const location = locationLabel(source);
    return `[来源：${displayName(source)}${location ? ` · ${location}` : ''}]`;
  }

  function groupSources(sources = []) {
    const groups = new Map();
    for (const source of sources) {
      const key = documentKey(source);
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          name: displayName(source),
          type: typeLabel(source),
          documentId: source.document_id || '',
          items: [],
          itemKeys: new Set(),
        });
      }
      const group = groups.get(key);
      const itemKey = String(source.chunk_id || source.case_id || locationLabel(source) || source.reference_id || 'source');
      if (group.itemKeys.has(itemKey)) continue;
      group.itemKeys.add(itemKey);
      group.items.push(source);
    }
    return [...groups.values()].map(({itemKeys, ...group}) => group);
  }

  function referenceMap(sources = []) {
    const references = new Map();
    for (const source of sources) {
      if (source.reference_id) references.set(String(source.reference_id), source);
      if (source.chunk_id) references.set(String(source.chunk_id), source);
    }
    return references;
  }

  function stripSourceAppendix(markdown = '') {
    return String(markdown).replace(/\n+#{1,4}\s+来源\s*\n[\s\S]*$/i, '').trim();
  }

  function replaceReferenceIds(markdown = '', sources = []) {
    const references = referenceMap(sources);
    return stripSourceAppendix(markdown).replace(
      /\[来源(?:\s+chunk_id\s*:)?\s*([A-Za-z0-9,，、\-\s]+)\]/gi,
      (match, ids) => {
        const matched = ids.split(/[,，、\s]+/).filter(Boolean)
          .map(id => references.get(id) || references.get(`KB-${id}`))
          .filter(Boolean);
        return matched.length ? matched.map(citationLabel).join(' ') : match;
      },
    );
  }

  return {
    citationLabel,
    displayName,
    groupSources,
    locationLabel,
    referenceMap,
    replaceReferenceIds,
    stripSourceAppendix,
    typeLabel,
  };
}));
