const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');

const html = fs.readFileSync('app/static/admin.html', 'utf8');
const script = fs.readFileSync('app/static/admin.js', 'utf8');
const css = fs.readFileSync('app/static/admin.css', 'utf8');

test('admin catalog exposes separate declaration and explicit compatibility actions', () => {
  assert.match(html, /editCapabilitiesDialog/);
  assert.match(script, /data-action="capabilities"/);
  assert.match(script, /data-action="compatibility"/);
  assert.match(script, /\/compatibility-check/);
  assert.match(script, /\/capabilities/);
  assert.doesNotMatch(script, /正在执行兼容性检查/);
});

test('compatibility success toast is centered without changing normal toast placement', () => {
  assert.match(script, /function showToast\(message, \{ centered = false \} = \{\}\)/);
  assert.match(script, /classList\.toggle\('admin-toast-centered', centered\)/);
  assert.match(script, /showToast\('能力探针通过', \{centered:true\}\)/);
  assert.match(script, /能力探针通过 · \$\{formatDate\(model\.compatibility_checked_at\)\}/);
  assert.match(script, /button\.textContent = '探针中…'/);
  assert.match(script, /能力探针失败：\$\{error\.message\}/);
  assert.match(script, /showToast\(`模型 \$\{payload\.display_name\} 已发布（尚未验证）`\)/);
  assert.match(css, /\.admin-toast \{[^}]*right: 18px;[^}]*bottom: 18px;/);
  assert.match(css, /\.admin-toast\.admin-toast-centered \{[^}]*top: 50%;[^}]*right: auto;[^}]*bottom: auto;[^}]*left: 50%;[^}]*max-width: min\(360px, calc\(100vw - 28px\)\);[^}]*transform: translate\(-50%, -50%\);/);
});

test('model catalog uses a responsive fixed layout and capability chips', () => {
  assert.match(html, /class="admin-table-wrap model-catalog-wrap"/);
  assert.match(html, /<table class="model-catalog-table"><colgroup>/);
  assert.match(html, /model-catalog-actions/);
  assert.match(script, /FabModelCapabilities\.enabledEntries\(model\.capabilities\)/);
  assert.match(script, /capability-chip capability-chip-\$\{key\}/);
  assert.match(script, /capability-chip capability-chip-empty">无/);
  assert.match(script, /data-label="兼容性"/);
  assert.match(script, /data-label="提供方模型"/);
  assert.match(script, /compatibility-details/);
  assert.match(script, /structured_context:'结构化上下文'/);
  assert.match(script, /data-label="健康"/);
  assert.match(script, /health-chip health-/);
  assert.match(script, /\$\{escapeHtml\(label\)\}/);
  assert.match(css, /\.model-catalog-wrap \{ overflow-x: hidden; \}/);
  assert.match(css, /\.model-catalog-table \{ width: 100%; table-layout: fixed; white-space: normal; \}/);
  assert.match(css, /\.catalog-actions \{ display: flex; flex-wrap: wrap;/);
  assert.match(css, /\.capability-chip-streaming \{[^}]*color: #08665f;[^}]*background: #e7f5f2;/);
  assert.match(css, /\.capability-chip-tool_calls \{[^}]*color: #365b70;[^}]*background: #edf4f7;/);
  assert.match(css, /\.capability-chip-thinking \{[^}]*color: #62507e;[^}]*background: #f3eff8;/);
  assert.match(css, /\.capability-chip-native_multimodal \{[^}]*color: #765c37;[^}]*background: #faf3e7;/);
  assert.match(css, /@media \(max-width: 1180px\) \{[^}]*\.model-catalog-table colgroup, .model-catalog-table thead \{ display: none; \}/);
  assert.match(css, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /\.model-catalog-table tr \{ grid-template-columns: 1fr; \}/);
});

test('model catalog header is semantic, Chinese, and visually distinct', () => {
  assert.equal((html.match(/<th scope="col">/g) || []).length, 11);
  assert.match(html, /<th scope="col">提供方模型<\/th>/);
  assert.doesNotMatch(html, />Provider Model</);
  assert.match(css, /\.model-catalog-table th \{[^}]*height: 44px;[^}]*color: #465957;[^}]*background: #f1f5f4;[^}]*font-size: 10px;[^}]*font-weight: 700;[^}]*text-transform: none;/);
  assert.match(css, /\.model-catalog-table th \{[^}]*border-bottom: 2px solid #c5d3d0;/);
  assert.match(css, /\.model-catalog-table th:nth-child\(8\), .model-catalog-table td:nth-child\(8\), .model-catalog-table th:nth-child\(9\), .model-catalog-table td:nth-child\(9\) \{ text-align: center; \}/);
  assert.match(css, /\.model-catalog-table th:nth-child\(11\), .model-catalog-table td:nth-child\(11\) \{ text-align: left; \}/);
  assert.match(css, /\.model-catalog-table \.catalog-actions \{ justify-content: flex-start; \}/);
  assert.match(css, /\.model-catalog-wrap \{ overflow-x: hidden; \}/);
  assert.match(css, /@media \(max-width: 1180px\) \{[^}]*\.model-catalog-table colgroup, .model-catalog-table thead \{ display: none; \}/);
});
