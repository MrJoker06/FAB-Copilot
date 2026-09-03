(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FabChatPresenter = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  function createChatPresenter(deps = {}) {
    const {
      $, escapeHtml, sourcePresenter, toolLabels,
      windowImpl = root, documentImpl = root.document, navigatorImpl = root.navigator,
    } = deps;
    const window = windowImpl;
    const document = documentImpl;
    const navigator = navigatorImpl;
  function sourceNavigationAttributes(source) {
    const documentAttribute = source.document_id ? ` data-source-document-id="${escapeHtml(source.document_id)}"` : '';
    if (source.source_type === 'case' || source.case_id) return `data-case-id="${escapeHtml(source.case_id)}"${documentAttribute}`;
    if (source.source_type === 'personal') return `data-personal-chunk="${escapeHtml(source.chunk_id)}"${documentAttribute}`;
    return `data-knowledge-chunk="${Number(source.chunk_id)}"${documentAttribute}`;
  }

  function sourceLink(source, label = '') {
    const attributes = sourceNavigationAttributes(source);
    if (label) return `<button type="button" class="source-link" ${attributes}>${escapeHtml(label)}</button>`;
    const name = sourcePresenter.displayName(source);
    const location = sourcePresenter.locationLabel(source);
    const documentAttribute = source.document_id ? ` data-source-document-id="${escapeHtml(source.document_id)}"` : '';
    return `<button type="button" class="citation-link" ${attributes}>[来源：<span class="source-document-name"${documentAttribute}>${escapeHtml(name)}</span>${location ? ` · ${escapeHtml(location)}` : ''}]</button>`;
  }

  function sourceReferenceMap(sources = []) {
    return sourcePresenter.referenceMap(sources);
  }

  function renderSourcePanel(sources = []) {
    const groups = sourcePresenter.groupSources(sources);
    if (!groups.length) return '';
    const body = groups.map(group => {
      const documentAttribute = group.documentId ? ` data-source-document-id="${escapeHtml(group.documentId)}"` : '';
      const links = group.items.map(source => sourceLink(source, sourcePresenter.locationLabel(source) || '打开来源')).join('');
      return `<section class="source-group"><div class="source-group-heading"><strong class="source-document-name"${documentAttribute}>${escapeHtml(group.name)}</strong><span>${escapeHtml(group.type)}</span></div><div class="source-locations">${links}</div></section>`;
    }).join('');
    return `<details class="source-list"><summary><span>知识来源</span><small>${groups.length} 份资料 · ${sources.length} 处引用</small></summary><div class="source-list-body">${body}</div></details>`;
  }

  function inlineMarkdown(value, sourceReferences = new Map()) {
    let text = escapeHtml(value);
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    text = text.replace(/\[来源(?:\s+chunk_id\s*:)?\s*([A-Za-z0-9,，、\-\s]+)\]/gi, (match, ids) => {
      const references = ids.split(/[,，、\s]+/).filter(Boolean).map(id => sourceReferences.get(id) || sourceReferences.get(`KB-${id}`)).filter(Boolean);
      return references.length ? references.map(source => sourceLink(source)).join(' ') : match;
    });
    return text;
  }

  function markdownCells(line) {
    return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(cell => cell.trim());
  }

  function renderMarkdown(markdown, sourceReferences = new Map()) {
    const lines = String(markdown || '').replace(/\r/g, '').split('\n');
    const output = [];
    let index = 0;
    const isBlockStart = line => /^(#{1,4})\s+/.test(line) || /^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line) || /^>\s?/.test(line) || /^```/.test(line) || /^\s*---+\s*$/.test(line);
    while (index < lines.length) {
      const line = lines[index];
      if (!line.trim()) { index += 1; continue; }
      if (/^```/.test(line)) {
        const code = []; index += 1;
        while (index < lines.length && !/^```/.test(lines[index])) { code.push(lines[index]); index += 1; }
        index += index < lines.length ? 1 : 0;
        output.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`); continue;
      }
      const heading = line.match(/^(#{1,4})\s+(.+)$/);
      if (heading) { const level = Math.min(4, heading[1].length + 1); output.push(`<h${level}>${inlineMarkdown(heading[2], sourceReferences)}</h${level}>`); index += 1; continue; }
      if (/^\s*---+\s*$/.test(line)) { output.push('<hr>'); index += 1; continue; }
      if (line.includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) {
        const headers = markdownCells(line); index += 2; const rows = [];
        while (index < lines.length && lines[index].includes('|') && lines[index].trim()) { rows.push(markdownCells(lines[index])); index += 1; }
        output.push(`<div class="markdown-table-wrap"><table><thead><tr>${headers.map(cell => `<th>${inlineMarkdown(cell, sourceReferences)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${headers.map((_, i) => `<td>${inlineMarkdown(row[i] || '', sourceReferences)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`); continue;
      }
      if (/^\s*[-*]\s+/.test(line) || /^\s*\d+\.\s+/.test(line)) {
        const ordered = /^\s*\d+\./.test(line), tag = ordered ? 'ol' : 'ul', items = [];
        const pattern = ordered ? /^\s*\d+\.\s+(.+)$/ : /^\s*[-*]\s+(.+)$/;
        while (index < lines.length) { const match = lines[index].match(pattern); if (!match) break; items.push(match[1]); index += 1; }
        output.push(`<${tag}>${items.map(item => `<li>${inlineMarkdown(item, sourceReferences)}</li>`).join('')}</${tag}>`); continue;
      }
      if (/^>\s?/.test(line)) {
        const quote = [];
        while (index < lines.length && /^>\s?/.test(lines[index])) { quote.push(lines[index].replace(/^>\s?/, '')); index += 1; }
        output.push(`<blockquote>${quote.map(item => inlineMarkdown(item, sourceReferences)).join('<br>')}</blockquote>`); continue;
      }
      const paragraph = [line.trim()]; index += 1;
      while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index]) && !(lines[index].includes('|') && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1]))) { paragraph.push(lines[index].trim()); index += 1; }
      output.push(`<p>${inlineMarkdown(paragraph.join(' '), sourceReferences)}</p>`);
    }
    return output.join('');
  }


  function formatDuration(milliseconds) {
    if (milliseconds == null) return '—';
    if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
    return `${(milliseconds / 1000).toFixed(2)} s`;
  }

  async function copyText(text) {
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return;
      } catch {
        // Fall through when Clipboard API exists but the browser denies permission.
      }
    }
    const textarea = document.createElement('textarea');
    textarea.value = text; textarea.setAttribute('readonly', ''); textarea.style.position = 'fixed'; textarea.style.opacity = '0';
    document.body.appendChild(textarea); textarea.select();
    const copied = document.execCommand('copy'); textarea.remove();
    if (!copied) throw new Error('浏览器未允许复制');
  }

  function renderToolTrace(trace, runId) {
    if (!trace?.length) return '';
    const items = trace.map((item, index) => {
      const status = item.status === 'error' ? '失败' : (item.status === 'blocked' ? '已拦截' : (item.status === 'local' ? '本地' : (item.status === 'running' ? '进行中' : '成功')));
      const result = item.rows == null ? status : `${status} · ${item.rows} 条结果`;
      const error = item.error ? `<p class="trace-error">${escapeHtml(item.error)}</p>` : '';
      const statusClass = item.status === 'error' ? 'error' : (item.status === 'blocked' ? 'blocked' : (item.status === 'running' ? 'running' : 'ok'));
      return `<li><div class="trace-step-heading"><span>${index + 1}. ${escapeHtml(item.label || toolLabels[item.tool] || item.tool || '未知工具')}</span><small class="trace-status-${statusClass}">${result}</small></div>${error}</li>`;
    }).join('');
    const failed = trace.some(item => item.status === 'error');
    const blocked = trace.some(item => item.status === 'blocked');
    const duration = trace.reduce((sum, item) => sum + Number(item.duration_ms || 0), 0);
    const summary = failed ? `执行路径异常 · ${trace.length} 个工具` : (blocked ? `执行路径受限 · ${trace.length} 个工具` : `执行路径已完成 · ${trace.length} 个工具${duration ? ` · ${formatDuration(duration)}` : ''}`);
    const runLabel = runId ? `<span title="${escapeHtml(runId)}">运行 ${escapeHtml(runId.slice(0, 8))}</span>` : '';
    return `<details class="analysis-trace" ${failed ? 'open' : ''}><summary><span>${summary}</span><small>可展开</small></summary><ol>${items}</ol><div class="trace-footer"><span>可审计工具路径，不包含模型内部草稿</span>${runLabel}</div></details>`;
  }

  function welcomeMarkup(message = '我可以查询制造报表、定位设备异常，并结合厂内 SOP 给出分析建议。') {
    return `<div class="message assistant"><div class="message-meta"><div class="message-label">FAB COPILOT</div></div><div class="message-content">${escapeHtml(message)}</div></div><div class="suggestions"><button>最近三个月哪些设备风险最高？</button><button>CVD-02 的膜厚是否发生漂移？</button><button>分析刻蚀设备 CD 偏移的潜在原因</button></div>`;
  }


  function renderAssistantInto(el, content, extra = {}) {
    const sources = extra.sources || [];
    const renderedContent = renderMarkdown(sourcePresenter.stripSourceAppendix(content), sourceReferenceMap(sources));
    const sourcePanel = renderSourcePanel(sources);
    const copyButton = '<button type="button" class="copy-answer" title="复制回答" aria-label="复制回答"><span aria-hidden="true">⧉</span><span>复制</span></button>';
    el.className = 'message assistant';
    el.innerHTML = `<div class="message-meta"><div class="message-label">FAB COPILOT</div></div>${renderToolTrace(extra.tool_trace, extra.run_id)}<div class="message-content markdown-content">${renderedContent}</div><div class="message-actions">${copyButton}</div>${sourcePanel}`;
    const copyAnswer = el.querySelector('.copy-answer');
    copyAnswer.addEventListener('click', async () => {
      try {
        await copyText(sourcePresenter.replaceReferenceIds(content, sources));
        copyAnswer.innerHTML = '<span aria-hidden="true">✓</span><span>已复制</span>'; copyAnswer.classList.add('copied'); copyAnswer.title = '已复制';
        window.setTimeout(() => { copyAnswer.innerHTML = '<span aria-hidden="true">⧉</span><span>复制</span>'; copyAnswer.classList.remove('copied'); copyAnswer.title = '复制回答'; }, 1600);
      } catch (error) {
        copyAnswer.title = error.message; copyAnswer.classList.add('copy-error');
        window.setTimeout(() => copyAnswer.classList.remove('copy-error'), 1600);
      }
    });
  }

  function addMessage(role, content, extra = {}) {
    const el = document.createElement('div');
    if (role === 'assistant') {
      renderAssistantInto(el, content, extra);
    } else {
      el.className = 'message user';
      el.innerHTML = `<div class="message-meta"><div class="message-label">YOU</div></div><div class="message-content">${escapeHtml(content).replace(/\n/g,'<br>')}</div>`;
    }
    $('#chatMessages').appendChild(el);
    $('#chatMessages').scrollTop = $('#chatMessages').scrollHeight;
    return el;
  }


    return {
      formatDuration, copyText, renderToolTrace, welcomeMarkup, sourceNavigationAttributes, sourceLink,
      sourceReferenceMap, renderSourcePanel, inlineMarkdown, markdownCells, renderMarkdown,
      renderAssistantInto, addMessage,
    };
  }

  return { createChatPresenter };
});
