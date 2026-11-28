let abilityItems = [], abilityKind = 'tool';
const abilityLabel = () => abilityKind === 'tool' ? '工具' : '技能';
function renderAbilities() {
  const search = $('[data-ability-search]').value.trim().toLowerCase(), scope = $('[data-ability-filter]').value;
  const entries = abilityItems.filter(x => x.kind === abilityKind && x.registered &&
    (!scope || (x.access ? 'module' : 'common') === scope) &&
    [x.name, x.title, x.access?.owner, ...(x.access?.readers || []), ...x.groups].join(' ').toLowerCase().includes(search));
  $('[data-register-ability]').textContent = '＋ 注册' + abilityLabel();
  document.querySelectorAll('[data-ability-kind]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.abilityKind === abilityKind)));
  $('[data-ability-rows]').innerHTML = entries.map(x => {
    const visibility = x.access ? [x.access.owner, ...x.access.readers].join('、') : '通用';
    const state = x.availability_issue ? '包不可用' : !x.enabled ? '已停用' : x.missing.length ? '依赖未就绪' : x.kind === 'skill' && !x.workflow ? '可读说明' : '已启用';
    return `<tr><td><strong>${escapeHtml(x.title || x.name)}</strong><div>${escapeHtml(x.name)}</div></td><td>${escapeHtml(visibility)}</td><td>${escapeHtml(x.groups.join('、') || '—')}</td><td>${escapeHtml(x.version || '—')}</td><td>${state}</td><td><button class="quiet-button" data-config-ability="${escapeHtml(x.name)}">查看 / 配置</button></td></tr>`;
  }).join('') || '<tr><td colspan="6" class="empty-row">没有符合条件的能力</td></tr>';
}
async function loadAbilities() {
  try {
    abilityItems = (await adminApi('/api/admin/capabilities')).items;
    $('[data-ability-notice]').textContent = '';
  } catch (error) { abilityItems = []; $('[data-ability-notice]').textContent = error.message; }
  renderAbilities();
}
function bindAbilities() {
  const form = $('[data-ability-form]'), f = form.elements, dialog = $('[data-ability-dialog]');
  const syncScope = () => { f.owner.required = f.scope.value === 'module'; f.owner.disabled = f.readers.disabled = !f.owner.required; };
  const fill = () => {
    const x = abilityItems.find(a => a.kind === abilityKind && a.name === f.candidate.value);
    f.scope.value = x.registered ? (x.access ? 'module' : 'common') : '';
    f.owner.value = x.access?.owner || ''; f.readers.value = (x.access?.readers || []).join('，');
    f.groups.value = x.groups.join('，'); f.enabled.checked = x.enabled; syncScope();
    const users = abilityItems.filter(a => a.requires && Object.hasOwn(a.requires, x.name)).map(a => a.title || a.name);
    const detail = x.kind === 'tool' ? {输入:x.inputSchema,输出:x.outputSchema || '未声明',依赖此工具的技能:users} :
      {包状态:x.availability_issue || '可注册',所需工具:x.requires,缺少的依赖:x.missing,说明:x.instructions};
    $('[data-ability-details]').textContent = x.description + '\n\n' + JSON.stringify(detail, null, 2);
    $('[data-ability-error]').textContent = '';
  };
  function open(name) {
    const entries = abilityItems.filter(x => x.kind === abilityKind && (name ? x.name === name : !x.registered));
    if (!entries.length) { $('[data-ability-notice]').textContent = '没有待注册的能力，请先部署对应的业务包。'; return; }
    f.candidate.replaceChildren(...entries.map(x => new Option(x.title || x.name, x.name)));
    $('[data-ability-heading]').textContent = (name ? '配置' : '注册') + abilityLabel();
    fill(); dialog.showModal();
  }
  document.querySelectorAll('[data-ability-kind]').forEach(b => b.onclick = () => { abilityKind = b.dataset.abilityKind; renderAbilities(); });
  $('[data-ability-search]').oninput = renderAbilities; $('[data-ability-filter]').onchange = renderAbilities;
  $('[data-ability-rows]').onclick = e => { const b = e.target.closest('[data-config-ability]'); if (b) open(b.dataset.configAbility); };
  $('[data-register-ability]').onclick = () => open(); $('[data-close-ability]').onclick = () => dialog.close();
  f.scope.onchange = syncScope; f.candidate.onchange = fill;
  form.onsubmit = async event => {
    event.preventDefault();
    const access = f.scope.value === 'module' ? {owner:f.owner.value.trim(), readers:moduleList(f.readers.value)} : null;
    const groups = [...new Set(f.groups.value.split(/[,，、]/).map(s => s.trim()).filter(Boolean))];
    try {
      await adminApi('/api/admin/capabilities/'+abilityKind+'/'+encodeURIComponent(f.candidate.value),
        {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({access,groups,enabled:f.enabled.checked})});
      dialog.close(); await loadAbilities();
    } catch (error) { $('[data-ability-error]').textContent = error.message; }
  };
}
