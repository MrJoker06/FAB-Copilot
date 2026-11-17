(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabShiftController = api;
})(globalThis, (root) => {
  function safeLink(value) {
    if (typeof value !== 'string' || !value || /[\s\\]/.test(value)) return null;
    if (value.startsWith('/') && !value.startsWith('//')) return value;
    try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
    catch { return null; }
  }
  function filterItems(items, query, role = '', process = '') {
    const text = String(query || '').trim().toLowerCase();
    return items.filter(item => (!role || item.roles?.includes(role)) && (!process || item.process === process)
      && (!text || JSON.stringify(item).toLowerCase().includes(text)));
  }
  function createShiftController(deps) {
    const { $, escapeHtml: esc, showToast, setAgentOpen, showView, api, identityHeaders, processLabels,
      fetchImpl = root.fetch.bind(root), windowImpl = root } = deps;
    let reports = [], documents = [], kind = 'case', selected = null, renderVersion = 0, refreshTimer = null;
    const recent = [];
    const statuses = {processing:'正在处理', ready:'可阅读', failed:'处理失败'};
    const reportAction = item => safeLink(item.url) ? `<a class="shift-report-link" href="${esc(safeLink(item.url))}" target="_blank" rel="noopener noreferrer" data-open-report="${esc(item.id)}" aria-label="打开${esc(item.title)}">打开报表 ↗</a>` : '<span class="shift-unavailable">链接未配置</span>';

    function renderReports() {
      const items = filterItems(reports, $('#shiftReportSearch').value);
      $('#shiftReportCards').innerHTML = items.map(item => `<article class="panel shift-report-card"><div class="shift-report-heading"><h2>${esc(item.title)}</h2></div><p>${esc(item.description)}</p><div class="shift-report-object">${esc(item.object)}</div><div class="shift-report-footer"><small>更新时间：${esc(item.updated_at)}</small>${reportAction(item)}</div></article>`).join('') || '<p class="empty">没有符合条件的报表</p>';
      $('#shiftRecentReports').innerHTML = recent.map(id => reports.find(item => item.id === id)).filter(Boolean).map(item => `<tr><td>${esc(item.title)}</td><td>${esc(item.object)}</td><td>${esc(item.updated_at)}</td><td>${reportAction(item)}</td></tr>`).join('') || '<tr><td colspan="4" class="empty">尚未查看报表</td></tr>';
    }

    function historicalItem(item) {
      const sections = [['问题',item.problem],['解决方案',item.solution],['解决结果',item.result],['案例总结',item.summary]];
      if (item.root_cause) sections.unshift(['已验证根因', [item.root_cause,item.validation_method,item.recurrence_status,item.approved_by].filter(Boolean).join(' · ')]);
      return {key:`case:${item.case_id}`, id:item.case_id, title:item.title, kind:'case', process:item.process_step,
        roles:['PE','EE'], summary:item.summary || item.problem, updated_at:item.occurred_date,
        sections:sections.filter(([,text]) => text).map(([title,text]) => ({title,text})), source:'案例库'};
    }

    function updateProcessOptions() {
      const control = $('#shiftDocumentProcess'), previous = control.value;
      control.innerHTML = '<option value="">全部制程</option>' + [...new Set(documents.map(item => item.process).filter(Boolean))].sort().map(process => `<option value="${esc(process)}">${esc(process)}</option>`).join('');
      if ([...control.options].some(option => option.value === previous)) control.value = previous;
    }

    async function renderDocuments() {
      const version = ++renderVersion;
      const items = filterItems(documents.filter(item => item.kind === kind), $('#shiftDocumentSearch').value, $('#shiftDocumentRole').value, $('#shiftDocumentProcess').value);
      if (!items.some(item => item.key === selected)) selected = items[0]?.key || null;
      $('#shiftDocumentCount').textContent = `共 ${items.length} 份${kind === 'sop' ? ' SOP' : '历史case'}`;
      $('#shiftDocumentList').innerHTML = items.map(item => `<button type="button" class="shift-document-item${item.key === selected ? ' selected' : ''}" data-shift-document="${esc(item.key)}" aria-pressed="${item.key === selected}"><strong>${esc(item.title)}</strong><span>${item.process ? `<span class="shift-tag">${esc(item.process)}</span> ` : ''}<span class="shift-tag">${esc(item.source)}</span></span><small>${esc(item.summary || '')}</small><time>${esc(item.updated_at)}</time></button>`).join('');
      const item = items.find(value => value.key === selected);
      if (!item) { $('#shiftDocumentReader').innerHTML = '<p class="empty">没有符合条件的资料</p>'; return; }
      if (item.shared && (!item.enabled || item.status !== 'ready')) {
        $('#shiftDocumentReader').innerHTML = `<h2>${esc(item.title)}</h2><p>${esc(!item.enabled ? '资料已被管理员停用' : statuses[item.status] || item.status)}</p><p>${esc(item.error_message || '')}</p>`;
        return;
      }
      if (item.shared) {
        $('#shiftDocumentReader').innerHTML = '<p class="empty">正在读取资料…</p>';
        try {
          const detail = await api(`/api/knowledge/shared/documents/${encodeURIComponent(item.id)}`);
          if (version !== renderVersion) return;
          item.sections = detail.sections;
        } catch (error) { if (version === renderVersion) $('#shiftDocumentReader').textContent = error.message; return; }
      } else if (item.key.startsWith('case:')) {
        try {
          const detail = await api(`/api/cases/${encodeURIComponent(item.id)}`);
          if (version !== renderVersion) return;
          item.sections = historicalItem(detail).sections;
        } catch (error) { if (version === renderVersion) $('#shiftDocumentReader').textContent = error.message; return; }
      }
      const related = documents.find(value => value.id === item.related_sop && value.source === item.source);
      $('#shiftDocumentReader').innerHTML = `<header><h2>${esc(item.title)}</h2><p class="shift-document-meta">${esc(item.id)} · ${esc(item.version || item.updated_at)}</p></header>${(item.sections || []).map(section => `<section><h3>${esc(section.title)}</h3>${section.steps ? `<ol>${section.steps.map(step => `<li>${esc(step)}</li>`).join('')}</ol>` : `<p class="shift-section-text">${esc(section.text)}</p>`}</section>`).join('')}${related ? `<section><h3>关联 SOP</h3><button type="button" class="shift-related" data-related-sop="${esc(related.key)}">${esc(related.title)} · ${esc(related.version)} ↗</button></section>` : ''}<div class="shift-reader-actions"><button type="button" class="secondary-btn" id="askShiftAssistant">向值班智能助手提问</button>${item.shared ? '<button type="button" class="secondary-btn" id="downloadSharedDocument">下载原文</button>' : ''}</div>`;
    }

    async function loadShiftView(name) {
      if (name === 'reports') {
        $('#shiftReportsStatus').textContent = '正在读取目录…';
        try {
          const payload = await api('/api/reports/directory');
          reports = payload.reports;
          renderReports(); $('#shiftReportsStatus').textContent = '';
        } catch (error) {
          reports = []; renderReports(); $('#shiftReportsStatus').textContent = error.message;
        }
        return;
      }
      windowImpl.clearTimeout(refreshTimer);
      $('#shiftDocumentsStatus').textContent = '正在读取资料…';
      const results = await Promise.allSettled([
        fetchImpl('/display_mock_data/catalog.json', {cache:'no-store'}).then(async response => {
          if (!response.ok) throw new Error('展示资料暂不可用');
          const data = await response.json();
          if (!Array.isArray(data.documents)) throw new Error('展示资料格式不正确');
          return data.documents.map(item => ({...item,key:`sample:${item.id}`,source:'值班资料'}));
        }),
        api('/api/cases').then(items => items.map(historicalItem)),
        api('/api/knowledge/shared/documents').then(data => data.items.map(item => ({...item,key:`shared:${item.document_id}`,id:item.document_id,shared:true,roles:['PE','EE'],source:item.own ? '我的共享上传' : '共享上传',summary:!item.enabled ? '已停用' : statuses[item.status]}))),
      ]);
      documents = results.flatMap(result => result.status === 'fulfilled' ? result.value : []);
      const errors = results.map((result,index) => result.status === 'rejected' ? `${['值班资料','案例库','共享资料'][index]}：${result.reason.message}` : '').filter(Boolean);
      $('#shiftDocumentsStatus').textContent = errors.join('；');
      updateProcessOptions(); await renderDocuments();
      if (documents.some(item => item.shared && item.status === 'processing') && $('#proceduresView').classList.contains('active')) {
        refreshTimer = windowImpl.setTimeout(() => { if ($('#proceduresView').classList.contains('active')) loadShiftView('procedures'); }, 1500);
      }
    }

    function switchKind(value) {
      kind = value;
      $('#shiftDocumentTabs').querySelectorAll('[data-document-kind]').forEach(button => {
        button.classList.toggle('active', button.dataset.documentKind === kind);
        button.setAttribute('aria-pressed', String(button.dataset.documentKind === kind));
      });
    }
    function resetDocumentFilters() { $('#shiftDocumentSearch').value = ''; $('#shiftDocumentRole').value = ''; $('#shiftDocumentProcess').value = ''; }
    async function openHistoricalCase(id) {
      switchKind('case'); resetDocumentFilters(); selected = `case:${id}`;
      showView('procedures');
      await loadShiftView('procedures');
      if (!documents.some(item => item.key === `case:${id}`)) { showToast('案例不存在或暂不可用'); return; }
      selected = `case:${id}`; await renderDocuments();
    }

    async function uploadSharedDocument(event) {
      event.preventDefault();
      const file = $('#sharedUploadFile').files[0]; if (!file) return;
      $('#confirmSharedUpload').disabled = true; $('#sharedUploadMessage').textContent = '正在上传…';
      const form = new root.FormData(); form.append('file',file); form.append('kind',$('#sharedUploadKind').value);
      form.append('title',$('#sharedUploadTitle').value); form.append('process',$('#sharedUploadProcess').value);
      try {
        const uploaded = await api('/api/knowledge/shared/documents',{method:'POST',body:form});
        switchKind($('#sharedUploadKind').value); resetDocumentFilters(); selected = `shared:${uploaded.document_id}`;
        $('#sharedUploadDialog').close(); $('#sharedUploadForm').reset();
        showToast('上传已接收，处理完成后将对所有用户共享。');
        await loadShiftView('procedures');
      } catch (error) { $('#sharedUploadMessage').textContent = error.message; }
      finally { $('#confirmSharedUpload').disabled = false; }
    }

    async function downloadSharedDocument(item) {
      try {
        const response = await fetchImpl(`/api/knowledge/shared/documents/${encodeURIComponent(item.id)}/file`,{headers:identityHeaders()});
        if (!response.ok) throw new Error('原文不可用或已停用');
        const url = root.URL.createObjectURL(await response.blob()), anchor = root.document.createElement('a');
        anchor.href = url; anchor.download = item.filename; anchor.click(); windowImpl.setTimeout(() => root.URL.revokeObjectURL(url),1000);
      } catch (error) { showToast(error.message,{tone:'error'}); }
    }

    function bindShiftEvents() {
      $('#shiftReportSearch').addEventListener('input', renderReports);
      $('#reportsView').addEventListener('click', event => {
        const anchor = event.target.closest('[data-open-report]'); if (!anchor) return;
        const id = anchor.dataset.openReport, previous = recent.indexOf(id);
        if (previous !== -1) recent.splice(previous,1); recent.unshift(id); recent.splice(6);
        windowImpl.setTimeout(renderReports,0);
      });
      $('#shiftDocumentSearch').addEventListener('input', renderDocuments);
      $('#shiftDocumentProcess').addEventListener('change', renderDocuments);
      $('#shiftDocumentRole').addEventListener('change', renderDocuments);
      $('#shiftDocumentTabs').addEventListener('click', event => { const button = event.target.closest('[data-document-kind]'); if (button) { switchKind(button.dataset.documentKind); renderDocuments(); } });
      $('#shiftDocumentList').addEventListener('click', event => { const button = event.target.closest('[data-shift-document]'); if (button) { selected = button.dataset.shiftDocument; renderDocuments(); } });
      $('#shiftDocumentReader').addEventListener('click', event => {
        const related = event.target.closest('[data-related-sop]');
        if (related) { selected = related.dataset.relatedSop; switchKind('sop'); resetDocumentFilters(); renderDocuments(); return; }
        const item = documents.find(value => value.key === selected); if (!item) return;
        if (event.target.closest('#downloadSharedDocument')) { downloadSharedDocument(item); return; }
        if (event.target.closest('#askShiftAssistant')) {
          const context = (item.sections || []).map(section => `${section.title}：${section.text || section.steps.join('；')}`).join('\n');
          const input = $('#chatInput'); input.value = `请协助复核以下资料，并指出还需确认的信息。\n${item.title}（${item.id}，${item.updated_at}）\n${context}`.slice(0,input.maxLength > 0 ? input.maxLength : 4000);
          input.dispatchEvent(new root.Event('input',{bubbles:true})); setAgentOpen(true);
        }
      });
      $('#openSharedUpload').addEventListener('click', () => { $('#sharedUploadKind').value = kind; $('#sharedUploadMessage').textContent = ''; $('#sharedUploadDialog').showModal(); $('#sharedUploadFile').focus(); });
      $('#closeSharedUpload').addEventListener('click', () => $('#sharedUploadDialog').close());
      $('#sharedUploadForm').addEventListener('submit', uploadSharedDocument);
      $('#refreshShiftDocuments').addEventListener('click', () => loadShiftView('procedures'));
      $('#sharedUploadProcess').insertAdjacentHTML('beforeend',Object.entries(processLabels).map(([code,name]) => `<option value="${esc(code)}">${esc(name)}</option>`).join(''));
      $('#autosystemLink').addEventListener('click', async () => {
        try {
          const response = await fetchImpl('/display_mock_data/catalog.json',{cache:'no-store'});
          if (!response.ok) throw new Error();
          const data = await response.json(), url = safeLink(data.autosystem_url);
          if (url) windowImpl.open(url,'_blank','noopener,noreferrer'); else showToast('Autosystem 地址尚未配置');
        } catch { showToast('Autosystem 配置读取失败'); }
      });
    }
    return {loadShiftView,bindShiftEvents,openHistoricalCase};
  }
  return {safeLink,filterItems,createShiftController};
});
