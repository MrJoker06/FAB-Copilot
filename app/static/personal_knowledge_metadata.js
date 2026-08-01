(function(root, factory) { const api = factory(); if (typeof module === 'object' && module.exports) module.exports = api; root.FabPersonalKnowledgeMetadata = api; })(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  function split(value) { return [...new Set(String(value || '').split(/[,，、;；\n]+/).map(item => item.trim()).filter(Boolean))]; }
  function same(left, right) { return JSON.stringify(left || []) === JSON.stringify(right || []); }
  function buildPatch(document, values) {
    const title = String(values.title || '').trim();
    if (!title) return {error: '知识名称不能为空。', patch: {}};
    const patch = {}, processSteps = values.process_step ? [values.process_step] : [], equipmentIds = split(values.equipment_ids), tags = split(values.tags), effectiveDate = values.effective_date || null;
    if (title !== (document.title || '')) patch.title = title;
    if (!same(processSteps, document.process_steps)) patch.process_steps = processSteps;
    if (!same(equipmentIds, document.equipment_ids)) patch.equipment_ids = equipmentIds;
    if (effectiveDate !== (document.effective_date || null)) patch.effective_date = effectiveDate;
    if (!same(tags, document.tags)) patch.tags = tags;
    return {error: '', patch};
  }
  return {split, same, buildPatch};
});
