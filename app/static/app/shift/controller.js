(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabShiftController = api;
})(globalThis, (root) => {
  function safeLink(value) {
    if (typeof value !== 'string' || !value || /[\s\\]/.test(value)) return null;
    if (value.startsWith('/') && !value.startsWith('//')) return value;
    try {
      const url = new URL(value);
      return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }

  function filterItems(items, query, role = '', process = '') {
    const text = String(query || '').trim().toLowerCase();
    return items.filter(item => (!role || item.roles.includes(role))
      && (!process || item.process === process)
      && (!text || JSON.stringify(item).toLowerCase().includes(text)));
  }

  function createShiftController(deps) {
    const { $, escapeHtml: esc, showToast, setAgentOpen, fetchImpl = root.fetch.bind(root), windowImpl = root } = deps;
    let catalog = null, pending = null, role = '', kind = 'case', selected = null;
    const recent = [];
    const link = item => safeLink(item.url);

    async function loadCatalog() {
      if (catalog) return catalog;
      if (!pending) pending = (async () => {
        const response = await fetchImpl('/display_mock_data/catalog.json', {cache: 'no-store'});
        if (!response.ok) throw new Error('资料暂不可用，请检查展示资料目录');
        const data = await response.json();
        if (!Array.isArray(data.reports) || !Array.isArray(data.documents)) throw new Error('资料格式不正确');
        catalog = data;
        return data;
      })().finally(() => { pending = null; });
      return pending;
    }

    function reportAction(item) {
      const url = link(item);
      return url ? `<a class="shift-report-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer" data-open-report="${esc(item.id)}" aria-label="打开${esc(item.title)}">打开报表 ↗</a>` : '<span class="shift-unavailable">链接未配置</span>';
    }

    function renderReports() {
      if (!catalog) return;
      const items = filterItems(catalog.reports, $('#shiftReportSearch').value, role);
      $('#shiftReportCards').innerHTML = items.map(item => `<article class="panel shift-report-card"><div class="shift-report-heading"><h2>${esc(item.title)}</h2><span class="shift-tag">${esc(item.roles.join(' / '))}</span></div><p>${esc(item.description)}</p><div class="shift-report-object">${esc(item.object)}</div><div class="shift-report-footer"><small>更新时间：${esc(item.updated_at)}</small>${reportAction(item)}</div></article>`).join('') || '<p class="empty">没有符合条件的报表</p>';
      $('#shiftRecentReports').innerHTML = recent.map(id => catalog.reports.find(item => item.id === id)).filter(Boolean).map(item => `<tr><td>${esc(item.title)}</td><td>${esc(item.object)}</td><td>${esc(item.updated_at)}</td><td>${reportAction(item)}</td></tr>`).join('') || '<tr><td colspan="4" class="empty">尚未查看报表</td></tr>';
    }

    function renderDocuments() {
      if (!catalog) return;
      const items = filterItems(catalog.documents.filter(item => item.kind === kind), $('#shiftDocumentSearch').value, $('#shiftDocumentRole').value, $('#shiftDocumentProcess').value);
      if (!items.some(item => item.id === selected)) selected = items[0]?.id || null;
      $('#shiftDocumentCount').textContent = `共 ${items.length} 份${kind === 'sop' ? ' SOP' : '历史case'}`;
      $('#shiftDocumentList').innerHTML = items.map(item => `<button type="button" class="shift-document-item${item.id === selected ? ' selected' : ''}" data-shift-document="${esc(item.id)}" aria-pressed="${item.id === selected}"><strong>${esc(item.title)}</strong><span><span class="shift-tag">${esc(item.process)}</span> <span class="shift-tag">${esc(item.roles.join(' / '))}</span></span><small>${esc(item.summary)}</small><time>${esc(item.updated_at)}</time></button>`).join('');
      const item = items.find(value => value.id === selected);
      if (!item) {
        $('#shiftDocumentReader').innerHTML = '<p class="empty">没有符合条件的资料</p>';
        return;
      }
      const related = catalog.documents.find(value => value.id === item.related_sop);
      $('#shiftDocumentReader').innerHTML = `<header><h2>${esc(item.title)}</h2><p class="shift-document-meta">${esc(item.id)} · ${esc(item.version || item.updated_at)}</p></header>${item.sections.map(section => `<section><h3>${esc(section.title)}</h3>${section.steps ? `<ol>${section.steps.map(step => `<li>${esc(step)}</li>`).join('')}</ol>` : `<p>${esc(section.text)}</p>`}</section>`).join('')}${related ? `<section><h3>关联 SOP</h3><button type="button" class="shift-related" data-related-sop="${esc(related.id)}">${esc(related.title)} · ${esc(related.version)} ↗</button></section>` : ''}<div class="shift-reader-actions"><button type="button" class="secondary-btn" id="askShiftAssistant">向值班智能助手提问</button></div>`;
    }

    async function loadShiftView(name) {
      const status = name === 'reports' ? $('#shiftReportsStatus') : $('#shiftDocumentsStatus');
      status.textContent = '正在读取资料…';
      try {
        await loadCatalog();
        status.textContent = '';
        if (name === 'reports') renderReports();
        else {
          const control = $('#shiftDocumentProcess');
          if (control.options.length === 1) control.insertAdjacentHTML('beforeend', [...new Set(catalog.documents.map(item => item.process))].sort().map(process => `<option value="${esc(process)}">${esc(process)}</option>`).join(''));
          renderDocuments();
        }
      } catch (error) { status.textContent = error.message || '资料读取失败'; }
    }

    function switchKind(value) {
      kind = value;
      $('#shiftDocumentTabs').querySelectorAll('[data-document-kind]').forEach(button => {
        button.classList.toggle('active', button.dataset.documentKind === kind);
        button.setAttribute('aria-pressed', String(button.dataset.documentKind === kind));
      });
    }

    function bindShiftEvents() {
      $('#shiftReportSearch').addEventListener('input', renderReports);
      $('#shiftReportRoles').addEventListener('click', event => {
        const button = event.target.closest('[data-report-role]');
        if (!button) return;
        role = button.dataset.reportRole;
        $('#shiftReportRoles').querySelectorAll('button').forEach(item => {
          item.classList.toggle('active', item === button);
          item.setAttribute('aria-pressed', String(item === button));
        });
        renderReports();
      });
      $('#reportsView').addEventListener('click', event => {
        const anchor = event.target.closest('[data-open-report]');
        if (!anchor) return;
        const id = anchor.dataset.openReport;
        const previous = recent.indexOf(id);
        if (previous !== -1) recent.splice(previous, 1);
        recent.unshift(id);
        recent.splice(6);
        // Keep the clicked link alive until the browser performs navigation.
        windowImpl.setTimeout(renderReports, 0);
      });
      $('#shiftDocumentSearch').addEventListener('input', renderDocuments);
      $('#shiftDocumentProcess').addEventListener('change', renderDocuments);
      $('#shiftDocumentRole').addEventListener('change', renderDocuments);
      $('#shiftDocumentTabs').addEventListener('click', event => {
        const button = event.target.closest('[data-document-kind]');
        if (!button) return;
        switchKind(button.dataset.documentKind);
        renderDocuments();
      });
      $('#shiftDocumentList').addEventListener('click', event => {
        const button = event.target.closest('[data-shift-document]');
        if (!button) return;
        selected = button.dataset.shiftDocument;
        renderDocuments();
      });
      $('#shiftDocumentReader').addEventListener('click', event => {
        const related = event.target.closest('[data-related-sop]');
        if (related) {
          selected = related.dataset.relatedSop;
          switchKind('sop');
          $('#shiftDocumentSearch').value = '';
          $('#shiftDocumentProcess').value = '';
          $('#shiftDocumentRole').value = '';
          renderDocuments();
        } else if (event.target.closest('#askShiftAssistant')) {
          const item = catalog.documents.find(value => value.id === selected);
          const context = item.sections.map(section => `${section.title}：${section.text || section.steps.join('；')}`).join('\n');
          const input = $('#chatInput');
          input.value = `请协助复核以下资料，并指出还需确认的信息。\n${item.title}（${item.id}，${item.updated_at}）\n${context}`.slice(0, input.maxLength > 0 ? input.maxLength : 4000);
          input.dispatchEvent(new root.Event('input', {bubbles: true}));
          setAgentOpen(true);
        }
      });
      $('#autosystemLink').addEventListener('click', async () => {
        try {
          const data = await loadCatalog();
          const url = safeLink(data.autosystem_url);
          if (url) windowImpl.open(url, '_blank', 'noopener,noreferrer');
          else showToast('Autosystem 地址尚未配置');
        } catch { showToast('Autosystem 配置读取失败'); }
      });
    }
    return {loadShiftView, bindShiftEvents};
  }
  return {safeLink, filterItems, createShiftController};
});
