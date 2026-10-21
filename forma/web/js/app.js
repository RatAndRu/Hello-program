import { Viewer } from './viewer.js';

const $ = (id) => document.getElementById(id);
const TOKEN = new URLSearchParams(location.search).get('token') || '';

const state = {
  script: '',
  payload: null,
  viewer: null,
  building: false,
  pending: false,
  examples: [],
  projects: [],
  help: null,
  projectName: 'проект',
  autobuildTimer: null,
  lastBuildAt: 0,
};

function toast(message, kind = '') {
  const el = $('toast');
  el.textContent = message;
  el.className = 'toast ' + kind;
  el.hidden = false;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.hidden = true; }, 3200);
}

async function api(path, body) {
  const sep = path.includes('?') ? '&' : '?';
  const url = path + sep + 'token=' + encodeURIComponent(TOKEN);
  const opts = body === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({ error: { message: 'Некорректный ответ сервера' } }));
  if (data.error) throw data.error;
  return data;
}

/* ------------------------------------------------------------------ */
/*  Редактор                                                          */
/* ------------------------------------------------------------------ */
function currentScript() {
  return $('code').value;
}

function setScript(text, { build = true } = {}) {
  $('code').value = text;
  updateGutter();
  updateCursor();
  if (build) buildNow();
}

function updateGutter(errorLine) {
  const lines = currentScript().split('\n');
  const gutter = $('gutter');
  gutter.innerHTML = lines
    .map((_, i) => `<div class="${errorLine === i + 1 ? 'err' : ''}">${i + 1}</div>`)
    .join('');
  gutter.scrollTop = $('code').scrollTop;
  $('script-stats').textContent = `${lines.length} стр. · ${currentScript().length} симв.`;
}

function updateCursor() {
  const ta = $('code');
  const pos = ta.selectionStart;
  const before = ta.value.slice(0, pos);
  const line = before.split('\n').length;
  const col = pos - before.lastIndexOf('\n');
  $('cursor-pos').textContent = `стр. ${line}, кол. ${col}`;
}

function lineAt(index) {
  const ta = $('code');
  const before = ta.value.slice(0, index);
  return before.split('\n').length;
}

$('code').addEventListener('scroll', () => { $('gutter').scrollTop = $('code').scrollTop; });
$('code').addEventListener('input', () => {
  updateGutter();
  updateCursor();
  hideError();
  if ($('autobuild').checked) {
    clearTimeout(state.autobuildTimer);
    state.autobuildTimer = setTimeout(() => buildNow(true), 750);
  }
});
$('code').addEventListener('click', updateCursor);
$('code').addEventListener('keyup', updateCursor);

$('code').addEventListener('keydown', (e) => {
  if (e.key === 'Tab') {
    e.preventDefault();
    const ta = e.target;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    ta.value = ta.value.slice(0, start) + '  ' + ta.value.slice(end);
    ta.selectionStart = ta.selectionEnd = start + 2;
    updateGutter();
    return;
  }
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    buildNow();
  }
});

document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault();
    saveProject();
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    buildNow();
  }
  if (e.key === 'Escape') {
    document.querySelectorAll('.menu.open').forEach((m) => m.classList.remove('open'));
    $('help-modal').hidden = true;
  }
});

/* ------------------------------------------------------------------ */
/*  Построение                                                        */
/* ------------------------------------------------------------------ */
async function buildNow(silent = false) {
  if (state.building) { state.pending = true; return; }
  state.building = true;
  $('loader').hidden = false;
  $('btn-build').disabled = true;
  const t0 = performance.now();
  try {
    const payload = await api('/api/build', { script: currentScript() });
    state.payload = payload;
    applyBuild(payload, Math.round(performance.now() - t0));
    if (payload.ok) {
      await loadModel(payload.glb_url);
      if (!silent) toast(`Готово за ${Math.round(performance.now() - t0)} мс`);
    }
  } catch (err) {
    showError(err);
  } finally {
    state.building = false;
    $('loader').hidden = true;
    $('btn-build').disabled = false;
    if (state.pending) { state.pending = false; buildNow(true); }
  }
}

function applyBuild(payload, elapsed) {
  const a = payload.analysis || {};
  const metrics = a.metrics || {};
  $('status-time').textContent = `${payload.timings?.total ?? elapsed} мс`;
  $('status-tris').textContent = metrics.tris ? `${fmtInt(metrics.tris)} трис` : '';
  $('status-size').textContent = metrics.size
    ? `${fmt(metrics.size[0])} × ${fmt(metrics.size[1])} × ${fmt(metrics.size[2])} мм` : '';
  $('status-parts').textContent = metrics.parts ? `частей: ${metrics.parts}` : '';
  $('status-version').textContent = `v${payload.version || ''}`;

  if (!payload.ok) {
    showError(payload.error || { message: 'Неизвестная ошибка' });
    $('report-text').textContent = 'Модель не построена. Исправьте ошибку в сценарии — и нажмите «Собрать».';
    $('checks-list').innerHTML = '';
    $('checks-summary').textContent = '—';
    $('verdict').hidden = true;
    return;
  }

  hideError();
  const stateEl = $('status-state');
  stateEl.textContent = 'модель построена';
  stateEl.className = 'status-item ok';

  renderReport(payload);
  renderChecks(payload);
  renderObjects(payload);
  renderDimensions(metrics);
}

function fmt(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1000) return v.toFixed(0);
  if (Math.abs(v - Math.round(v)) < 1e-6) return String(Math.round(v));
  return v.toFixed(digits).replace(/\.?0+$/, '');
}
function fmtInt(v) { return String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ' '); }

function renderReport(payload) {
  const a = payload.analysis || {};
  $('report-text').textContent = a.text || '';
  const checks = a.checks || [];
  const failed = checks.filter((c) => !c.ok).length;
  const warnings = a.warnings || [];
  const verdict = $('verdict');
  verdict.hidden = false;
  if (failed > 0) {
    verdict.className = 'verdict bad';
    verdict.textContent = `✗ ${failed} из ${checks.length} проверок не пройдено — посмотрите вкладку «Проверки».`;
  } else if (warnings.length) {
    verdict.className = 'verdict warn';
    verdict.textContent = `✓ Проверки пройдены (${checks.length}), есть замечания: ${warnings.length}.`;
  } else if (checks.length) {
    verdict.className = 'verdict good';
    verdict.textContent = `✓ Все проверки пройдены (${checks.length}) и замечаний нет.`;
  } else {
    verdict.className = 'verdict warn';
    verdict.textContent = 'Проверки не заданы. Добавьте строки check, чтобы приложение само оценивало результат.';
  }
}

function renderChecks(payload) {
  const a = payload.analysis || {};
  const checks = a.checks || [];
  const list = $('checks-list');
  const failed = checks.filter((c) => !c.ok).length;
  $('checks-summary').textContent = checks.length
    ? `${checks.length - failed} из ${checks.length} пройдено`
    : 'Проверки не заданы';
  $('checks-summary').style.color = failed ? 'var(--bad)' : (checks.length ? 'var(--good)' : '');
  list.innerHTML = '';
  checks.forEach((c) => {
    const el = document.createElement('div');
    el.className = 'check-item ' + (c.ok ? 'ok' : 'bad');
    el.innerHTML = `
      <div class="mark">${c.ok ? '✓' : '✗'}</div>
      <div class="check-body">
        <div class="check-label">${escapeHtml(c.label || c.rule)} · стр. ${c.line}</div>
        <div class="check-text">${escapeHtml(c.text)}</div>
      </div>`;
    el.addEventListener('click', () => focusLine(c.line));
    list.appendChild(el);
  });
  if (!checks.length) {
    list.innerHTML = '<div class="hint-box">Нет ни одной проверки. Пример: ' +
      '<code>check кружка height 90..110</code></div>';
  }
}

function renderObjects(payload) {
  const list = $('objects-list');
  list.innerHTML = '';
  const objs = payload.objects || [];
  objs.forEach((o) => {
    const el = document.createElement('div');
    el.className = 'obj-item' + (o.visible ? '' : ' hidden-obj');
    el.innerHTML = `
      <span class="swatch" style="background:${o.color}"></span>
      <div class="obj-main">
        <div class="obj-name">${escapeHtml(o.name)}</div>
        <div class="obj-meta">${fmt(o.size[0])}×${fmt(o.size[1])}×${fmt(o.size[2])} мм ·
          ${fmt(o.volume_cm3)} см³ · ${fmtInt(o.tris)} трис</div>
      </div>
      <span class="eye">${o.visible ? '●' : '○'}</span>`;
    el.addEventListener('click', () => {
      const ta = $('code');
      const lines = ta.value.split('\n');
      const lineIndex = Math.max(0, (o.line || 1) - 1);
      const pos = lines.slice(0, lineIndex).join('\n').length + (lineIndex ? 1 : 0);
      ta.focus();
      ta.setSelectionRange(pos, pos + (lines[lineIndex] || '').length);
      updateCursor();
    });
    list.appendChild(el);
  });
  const m = (payload.analysis || {}).metrics || {};
  $('objects-summary').innerHTML = objs.length
    ? `Всего объектов: ${objs.length} (видимых ${m.visible_count ?? '—'}).<br>
       Материал: ${fmt(m.volume_cm3)} см³, масса ${fmt(m.mass_g, 0)} г.`
    : 'Пока нет объектов.';
}

function renderDimensions(metrics) {
  const box = $('dim-overlay');
  if (!metrics.size) { box.hidden = true; return; }
  box.hidden = false;
  const wall = metrics.wall
    ? `стенка ${fmt(metrics.wall.median)} мм`
    : 'сплошное тело';
  box.innerHTML = `Ш ${fmt(metrics.size[0])} · Г ${fmt(metrics.size[1])} · В ${fmt(metrics.size[2])} мм<br>
    ${fmt(metrics.volume_cm3)} см³ · ${fmt(metrics.mass_g, 0)} г · ${wall}`;
  const badge = $('viewer-badge');
  badge.hidden = false;
  badge.textContent = `${fmtInt(metrics.tris)} треугольников`;
}

function showError(err) {
  const bar = $('error-bar');
  bar.hidden = false;
  $('error-msg').textContent = (err.line ? `Строка ${err.line}: ` : '') + (err.message || 'Ошибка');
  $('error-hint').textContent = err.hint || '';
  $('status-state').textContent = 'ошибка';
  $('status-state').className = 'status-item err';
  if (err.line) {
    updateGutter(err.line);
    focusLine(err.line);
  }
}

function hideError() {
  $('error-bar').hidden = true;
  $('status-state').textContent = 'готово';
  $('status-state').className = 'status-item';
}

function focusLine(line) {
  const ta = $('code');
  const lines = ta.value.split('\n');
  const idx = Math.min(Math.max(line, 1), lines.length) - 1;
  const start = lines.slice(0, idx).join('\n').length + (idx ? 1 : 0);
  ta.focus();
  ta.setSelectionRange(start, start + (lines[idx] || '').length);
  const lineHeight = 1.65 * 12.5;
  ta.scrollTop = Math.max(0, idx * lineHeight - ta.clientHeight / 2);
  updateCursor();
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/* ------------------------------------------------------------------ */
/*  Просмотр                                                          */
/* ------------------------------------------------------------------ */
async function loadModel(url) {
  if (!url) return;
  $('viewer-empty').hidden = true;
  try {
    await state.viewer.load(url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN));
  } catch (e) {
    toast('Не удалось показать модель: ' + (e?.message || e), 'bad');
  }
}

function initViewer() {
  try {
    state.viewer = new Viewer($('viewer'));
  } catch (e) {
    $('viewer-empty').innerHTML = '<p>WebGL недоступен в этом окне.<br>Модель можно посмотреть через PNG-снимки кнопкой «Снимки».</p>';
    console.error(e);
  }
}

document.querySelectorAll('.view-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.view-btn').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    state.viewer?.setView(btn.dataset.view);
  });
});

$('btn-grid').addEventListener('click', (e) => {
  const on = !e.currentTarget.classList.contains('active');
  e.currentTarget.classList.toggle('active', on);
  state.viewer?.setGrid(on);
});
$('btn-wire').addEventListener('click', (e) => {
  const on = !e.currentTarget.classList.contains('active');
  e.currentTarget.classList.toggle('active', on);
  state.viewer?.setWireframe(on);
});
$('btn-spin').addEventListener('click', (e) => {
  const on = !e.currentTarget.classList.contains('active');
  e.currentTarget.classList.toggle('active', on);
  state.viewer?.setSpin(on);
});
$('btn-shot').addEventListener('click', () => {
  if (!state.viewer) return;
  const link = document.createElement('a');
  link.href = state.viewer.screenshot();
  link.download = 'форма_3d_' + Date.now() + '.png';
  link.click();
});

/* ------------------------------------------------------------------ */
/*  Снимки, экспорт                                                   */
/* ------------------------------------------------------------------ */
$('btn-render').addEventListener('click', async () => {
  if (!state.payload?.ok) { toast('Сначала соберите модель', 'bad'); return; }
  const btn = $('btn-render');
  btn.disabled = true;
  toast('Готовим снимки четырёх видов…');
  try {
    const res = await api('/api/render', {});
    const strip = $('render-strip');
    strip.hidden = false;
    strip.innerHTML = '';
    res.files.forEach((f) => {
      const a = document.createElement('a');
      a.href = f.url + '&token=' + encodeURIComponent(TOKEN);
      a.target = '_blank';
      a.innerHTML = `<img src="${f.url}&token=${encodeURIComponent(TOKEN)}" alt="${escapeHtml(f.label)}">
        <div class="cap">${escapeHtml(f.label)}</div>`;
      strip.appendChild(a);
    });
    toast('Снимки готовы — они лежат в папке renders');
  } catch (e) {
    toast(e.message || 'Ошибка рендера', 'bad');
  } finally {
    btn.disabled = false;
  }
});

$('btn-export').parentElement.querySelector('.menu').addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-format]');
  if (!btn) return;
  const fmt = btn.dataset.format;
  document.querySelectorAll('.menu.open').forEach((m) => m.classList.remove('open'));
  if (!state.payload?.ok) { toast('Сначала соберите модель', 'bad'); return; }
  toast('Экспорт…');
  try {
    const res = await api('/api/export', { format: fmt });
    const url = res.url + '&token=' + encodeURIComponent(TOKEN) + '&download=1';
    const link = document.createElement('a');
    link.href = url;
    link.download = res.name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    toast(`Сохранено: ${res.path}`);
  } catch (err) {
    toast(err.message || 'Ошибка экспорта', 'bad');
  }
});

/* ------------------------------------------------------------------ */
/*  Меню, проекты, примеры                                            */
/* ------------------------------------------------------------------ */
document.querySelectorAll('.menu-wrap > button').forEach((btn) => {
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const menu = btn.parentElement.querySelector('.menu');
    const open = menu.classList.contains('open');
    document.querySelectorAll('.menu.open').forEach((m) => m.classList.remove('open'));
    if (!open) menu.classList.add('open');
  });
});
document.addEventListener('click', () => {
  document.querySelectorAll('.menu.open').forEach((m) => m.classList.remove('open'));
});

function renderProjects() {
  const examples = $('example-list');
  examples.innerHTML = '';
  state.examples.forEach((ex) => {
    const b = document.createElement('button');
    b.textContent = ex.name;
    b.addEventListener('click', async () => {
      try {
        const res = await api('/api/example?key=' + encodeURIComponent(ex.key));
        state.projectName = ex.name;
        setScript(res.script);
        closeMenus();
        toast('Пример загружен: ' + ex.name);
      } catch (e) { toast(e.message, 'bad'); }
    });
    examples.appendChild(b);
  });
  const projects = $('project-list');
  projects.innerHTML = '';
  if (!state.projects.length) {
    projects.innerHTML = '<div class="empty-note">Пока пусто — сохраните проект кнопкой «Сохранить».</div>';
  }
  state.projects.forEach((p) => {
    const b = document.createElement('button');
    const when = new Date(p.modified * 1000).toLocaleString('ru-RU', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    });
    b.innerHTML = `<span>${escapeHtml(p.name)}</span><small>${when}</small>`;
    b.addEventListener('click', async () => {
      try {
        const res = await api('/api/project?name=' + encodeURIComponent(p.key || p.name));
        state.projectName = res.name;
        setScript(res.script);
        closeMenus();
        toast('Открыт проект: ' + res.name);
      } catch (e) { toast(e.message, 'bad'); }
    });
    projects.appendChild(b);
  });
}

function closeMenus() {
  document.querySelectorAll('.menu.open').forEach((m) => m.classList.remove('open'));
}

async function askName(defaultName) {
  return new Promise((resolve) => {
    const wrap = document.createElement('div');
    wrap.className = 'modal';
    wrap.innerHTML = `
      <div class="modal-card" style="width:min(420px,90vw)">
        <div class="modal-head"><strong>Название проекта</strong></div>
        <div style="padding:14px 16px">
          <input id="name-input" type="text" style="width:100%;padding:9px 11px;border-radius:8px;
            background:#10151c;border:1px solid #232d3a;color:#e7ecf3;font-family:inherit;font-size:13px;outline:none" />
          <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:14px">
            <button data-act="cancel" class="small">Отмена</button>
            <button data-act="ok" class="primary small">Сохранить</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(wrap);
    const input = wrap.querySelector('#name-input');
    input.value = defaultName;
    input.focus();
    input.select();
    const finish = (value) => { wrap.remove(); resolve(value); };
    wrap.querySelector('[data-act="ok"]').addEventListener('click', () => finish(input.value.trim() || defaultName));
    wrap.querySelector('[data-act="cancel"]').addEventListener('click', () => finish(null));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') finish(input.value.trim() || defaultName);
      if (e.key === 'Escape') finish(null);
    });
  });
}

async function saveProject() {
  const name = await askName(state.projectName || 'проект');
  if (!name) return;
  try {
    const res = await api('/api/save', { name, script: currentScript() });
    state.projectName = res.name;
    await refreshProjects();
    toast('Проект сохранён: ' + res.path);
  } catch (e) { toast(e.message || 'Ошибка сохранения', 'bad'); }
}

$('btn-save').addEventListener('click', saveProject);
$('btn-build').addEventListener('click', () => buildNow());

async function refreshProjects() {
  try {
    const res = await api('/api/projects');
    state.projects = res.projects || [];
    renderProjects();
  } catch (e) { /* тихо */ }
}

/* ------------------------------------------------------------------ */
/*  Вкладки, справка, помощник                                        */
/* ------------------------------------------------------------------ */
document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.tab-page').forEach((p) => p.classList.remove('active'));
    tab.classList.add('active');
    $('page-' + tab.dataset.tab).classList.add('active');
  });
});

function openHelp() {
  $('help-modal').hidden = false;
  $('help-search').focus();
}
$('btn-help').addEventListener('click', openHelp);
$('help-close').addEventListener('click', () => { $('help-modal').hidden = true; });
$('help-modal').addEventListener('click', (e) => {
  if (e.target === $('help-modal')) $('help-modal').hidden = true;
});

function renderHelp(filter = '') {
  const body = $('help-body');
  const commands = state.help || [];
  const q = filter.trim().toLowerCase();
  const groups = {};
  commands.forEach((c) => {
    const hay = (c.name + ' ' + (c.aliases || []).join(' ') + ' ' + c.summary + ' ' +
      (c.params || []).map((p) => p.name + ' ' + p.desc).join(' ')).toLowerCase();
    if (q && !hay.includes(q)) return;
    (groups[c.category] = groups[c.category] || []).push(c);
  });
  body.innerHTML = '';
  const cats = Object.keys(groups);
  if (!cats.length) {
    body.innerHTML = '<div class="hint-box">Ничего не найдено.</div>';
    return;
  }
  cats.forEach((cat) => {
    const g = document.createElement('div');
    g.className = 'cmd-group';
    g.innerHTML = `<h4>${escapeHtml(cat)}</h4>`;
    groups[cat].forEach((c) => {
      const card = document.createElement('div');
      card.className = 'cmd-card';
      const params = (c.params || [])
        .map((p) => `<span class="cmd-param"><b>${escapeHtml(p.name)}</b> — ${escapeHtml(p.desc)}</span>`)
        .join('');
      card.innerHTML = `
        <div><span class="cmd-name">${escapeHtml(c.name)}</span>
          <span class="cmd-aliases">${(c.aliases || []).map(escapeHtml).join(', ')}</span></div>
        <div class="cmd-summary">${escapeHtml(c.summary)}</div>
        ${params ? `<div class="cmd-params">${params}</div>` : ''}
        ${c.example ? `<pre>${escapeHtml(c.example)}</pre>` : ''}`;
      g.appendChild(card);
    });
    body.appendChild(g);
  });
}

$('help-search').addEventListener('input', (e) => renderHelp(e.target.value));

$('btn-prompt').addEventListener('click', async () => {
  try {
    const res = await api('/api/prompt', { script: currentScript(), goal: $('goal').value });
    $('prompt-out').value = res.text;
    toast('Запрос готов и сохранён: ' + res.path);
  } catch (e) { toast(e.message || 'Ошибка', 'bad'); }
});

$('btn-copy').addEventListener('click', async () => {
  const text = $('prompt-out').value;
  if (!text) { toast('Сначала сформируйте запрос', 'bad'); return; }
  try {
    await navigator.clipboard.writeText(text);
    toast('Скопировано в буфер обмена');
  } catch {
    $('prompt-out').select();
    document.execCommand('copy');
    toast('Скопировано');
  }
});

$('btn-prompt-save').addEventListener('click', async () => {
  if (!$('prompt-out').value) { toast('Сначала сформируйте запрос', 'bad'); return; }
  try {
    const res = await api('/api/export', { format: 'prompt' });
    const link = document.createElement('a');
    link.href = res.url + '&token=' + encodeURIComponent(TOKEN) + '&download=1';
    link.download = res.name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    toast('Сохранено: ' + res.path);
  } catch (e) { toast(e.message || 'Ошибка', 'bad'); }
});

/* ------------------------------------------------------------------ */
/*  Старт                                                             */
/* ------------------------------------------------------------------ */
async function init() {
  initViewer();
  try {
    const st = await api('/api/state');
    state.examples = st.examples || [];
    state.projects = st.projects || [];
    state.projectName = st.project || 'проект';
    state.help = (await api('/api/commands')).commands || [];
    renderProjects();
    renderHelp();
    setScript(st.script, { build: false });
    $('status-version').textContent = 'v' + (st.version || '');
    if (st.has_build) {
      buildNow(true);
    } else {
      buildNow(true);
    }
  } catch (e) {
    toast(e.message || 'Не удалось запустить приложение', 'bad');
  }
}

init();
