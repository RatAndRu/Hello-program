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
  selected: null,
  material: { color: '#c9d1e3', metal: 0, rough: 0.5 },
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
  applyViewSettings(payload);
  updatePolyBadge();
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
          ${fmt(o.volume_cm3)} см³ · ${fmtInt(o.tris)} трис
          ${o.tex ? ' · <span class="obj-tex">текстура: ' + escapeHtml(o.tex.label || o.tex.kind) + '</span>' : ''}</div>
      </div>
      <span class="eye">${o.visible ? '●' : '○'}</span>`;
    el.dataset.name = o.name;
    el.addEventListener('click', () => {
      selectObject(o.name);
    });
    el.addEventListener('dblclick', () => {
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
    state.viewer.onSelect = (name) => selectObject(name);
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
/*  Вид: свет, фон, полигонаж, статистика, анимация                   */
/* ------------------------------------------------------------------ */
function updatePolyBadge() {
  const badge = $('poly-badge');
  if (!badge) return;
  const objs = state.payload?.objects || [];
  const tris = objs.filter((o) => o.visible).reduce((sum, o) => sum + (o.tris || 0), 0);
  if (!tris) { badge.hidden = true; return; }
  badge.hidden = false;
  badge.textContent = `${fmtInt(tris)} трис`;
}

function applyViewSettings(payload) {
  const s = payload.settings || {};
  state.viewer?.applySettings(s);
  const chips = $('env-chips');
  if (chips) {
    chips.querySelectorAll('.chip').forEach((c) => {
      c.classList.toggle('active', c.dataset.env === (s.env || 'studio'));
    });
  }
  if ($('exposure')) {
    const v = Number(s.exposure ?? 1.05);
    $('exposure').value = v;
    $('exposure-val').textContent = v.toFixed(2);
  }
  ['shadows', 'grid', 'ground'].forEach((k) => {
    const el = $('opt-' + k);
    if (el) el.checked = s[k] !== false;
  });
  if ($('bg-color') && s.bg) $('bg-color').value = s.bg;
  document.querySelectorAll('#bg-swatches .swatch').forEach((sw) => {
    sw.classList.toggle('active', (sw.dataset.bg || '').toLowerCase() === (s.bg || '').toLowerCase());
  });
  const anim = payload.animation;
  if (anim && $('anim-kind')) $('anim-kind').value = anim.kind || '';
  if (state.viewer?.hasAnimation()) {
    state.viewer.setLoop(anim ? anim.loop !== false : true);
  }
  updateStatsOverlay();
}

function updateStatsOverlay() {
  const box = $('viewer-stats');
  if (!box) return;
  const v = state.viewer;
  if (!v || !state.payload?.ok) { box.hidden = true; return; }
  const st = v.getStats();
  const objs = state.payload?.objects || [];
  const dims = state.payload?.analysis?.metrics?.size;
  box.hidden = false;
  box.innerHTML = `<b>${fmtInt(st.tris)}</b> треугольников<br>
    <b>${fmtInt(st.verts)}</b> вершин · <b>${st.meshes}</b> объектов<br>
    ${dims ? `<b>${fmt(dims[0])}×${fmt(dims[1])}×${fmt(dims[2])}</b> мм<br>` : ''}
    ${st.fps ? `<b>${st.fps}</b> кадр/с` : ''}`;
  const badge = $('viewer-badge');
  if (badge) badge.textContent = `${fmtInt(st.tris)} треугольников`;
  if ($('obj-badge-count')) $('obj-badge-count').textContent = objs.length;
}
setInterval(updateStatsOverlay, 700);

function toggleStudio(force) {
  const panel = $('studio-panel');
  if (!panel) return;
  panel.hidden = force === undefined ? !panel.hidden : !force;
  $('btn-studio')?.classList.toggle('active', !panel.hidden);
}

$('btn-studio')?.addEventListener('click', (e) => {
  e.stopPropagation();
  toggleStudio();
});
document.addEventListener('click', (e) => {
  const panel = $('studio-panel');
  if (!panel || panel.hidden) return;
  if (panel.contains(e.target) || e.target.closest('#btn-studio')) return;
  toggleStudio(false);
});

$('env-chips')?.querySelectorAll('.chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    $('env-chips').querySelectorAll('.chip').forEach((c) => c.classList.remove('active'));
    chip.classList.add('active');
    state.viewer?.setEnv(chip.dataset.env);
  });
});
$('bg-swatches')?.querySelectorAll('.swatch').forEach((sw) => {
  sw.addEventListener('click', () => {
    $('bg-swatches').querySelectorAll('.swatch').forEach((c) => c.classList.remove('active'));
    sw.classList.add('active');
    $('bg-color').value = sw.dataset.bg;
    state.viewer?.setBackground(sw.dataset.bg);
  });
});
$('bg-color')?.addEventListener('input', (e) => {
  $('bg-swatches')?.querySelectorAll('.swatch').forEach((c) => c.classList.remove('active'));
  state.viewer?.setBackground(e.target.value);
});
$('exposure')?.addEventListener('input', (e) => {
  const v = Number(e.target.value);
  $('exposure-val').textContent = v.toFixed(2);
  state.viewer?.setExposure(v);
});
$('shading')?.addEventListener('change', (e) => state.viewer?.setShading(e.target.value));
$('opt-shadows')?.addEventListener('change', (e) => state.viewer?.applySettings({ shadows: e.target.checked }));
$('opt-grid')?.addEventListener('change', (e) => state.viewer?.setGrid(e.target.checked));
$('opt-ground')?.addEventListener('change', (e) => state.viewer?.setGround(e.target.checked));
$('opt-axes')?.addEventListener('change', (e) => state.viewer?.setAxes(e.target.checked));
$('opt-poly')?.addEventListener('change', (e) => {
  $('btn-wire')?.classList.toggle('active', e.target.checked);
  state.viewer?.setPolygons(e.target.checked);
});
$('anim-play')?.addEventListener('click', (e) => {
  if (!state.viewer) return;
  if (!state.viewer.hasAnimation()) { toast('В сценарии нет анимации. Выберите вид анимации.', 'bad'); return; }
  const playing = e.currentTarget.dataset.playing !== '1';
  e.currentTarget.dataset.playing = playing ? '1' : '';
  e.currentTarget.textContent = playing ? '❚❚ пауза' : '▶ играть';
  state.viewer.playAnimation(playing);
});
$('anim-restart')?.addEventListener('click', () => {
  state.viewer?.restartAnimation();
  const b = $('anim-play');
  if (b) { b.dataset.playing = '1'; b.textContent = '❚❚ пауза'; }
});
$('anim-speed')?.addEventListener('input', (e) => {
  const v = Number(e.target.value);
  $('anim-speed-val').textContent = v.toFixed(1) + '×';
  state.viewer?.setSpeed(v);
});
$('anim-kind')?.addEventListener('change', (e) => {
  const kind = e.target.value;
  if (!kind) return;
  setAnimationCommand(kind);
});
$('btn-wire')?.addEventListener('dblclick', () => {
  $('opt-poly').checked = !$('opt-poly').checked;
  state.viewer?.setPolygons($('opt-poly').checked);
});

function setAnimationCommand(kind) {
  const names = { spin: 'вращение', formation: 'формирование', explode: 'разлёт' };
  const lines = currentScript().split('\n').filter((l) => !/^\s*animate\b/i.test(l));
  const seconds = { spin: 6, formation: 4, explode: 3 }[kind] || 4;
  lines.push(`animate kind=${kind} seconds=${seconds}`);
  setScript(lines.join('\n'));
  toast(`Анимация сценария: ${names[kind] || kind}`);
}

/* ------------------------------------------------------------------ */
/*  Материал выбранного объекта                                       */
/* ------------------------------------------------------------------ */
function selectObject(name) {
  if (!name) {
    state.selected = null;
    document.querySelectorAll('.obj-item').forEach((el) => el.classList.remove('selected'));
    $('material-panel').hidden = true;
    return;
  }
  const obj = (state.payload?.objects || []).find((o) => o.name === name);
  if (!obj) return;
  state.selected = obj;
  document.querySelectorAll('.obj-item').forEach((el) => {
    el.classList.toggle('selected', el.dataset.name === name);
  });
  $('material-panel').hidden = false;
  $('mat-name').textContent = obj.name;
  state.material = { color: obj.color || '#c9d1e3', metal: obj.metal || 0, rough: obj.rough ?? 0.5 };
  $('mat-color').value = state.material.color;
  $('mat-hex').textContent = state.material.color;
  $('mat-metal').value = state.material.metal;
  $('mat-metal-val').textContent = state.material.metal;
  $('mat-rough').value = state.material.rough;
  $('mat-rough-val').textContent = state.material.rough;
  const KIND_RU = { wood: 'дерево', marble: 'мрамор', metal: 'металл', fabric: 'ткань',
    leather: 'кожа', checker: 'клетка', noise: 'шум', brick: 'кирпич', ceramic: 'керамика' };
  $('mat-tex').value = obj.tex ? (KIND_RU[obj.tex.kind] || '') : '';
  // открываем вкладку объектов
  const tab = document.querySelector('.tab[data-tab="objects"]');
  if (tab && !tab.classList.contains('active')) tab.click();
}

$('mat-color')?.addEventListener('input', (e) => {
  state.material.color = e.target.value;
  $('mat-hex').textContent = e.target.value;
  state.viewer?.applyMaterial(state.selected?.name, { color: e.target.value });
});
$('mat-metal')?.addEventListener('input', (e) => {
  state.material.metal = Number(e.target.value);
  $('mat-metal-val').textContent = e.target.value;
  state.viewer?.applyMaterial(state.selected?.name, { metal: Number(e.target.value) });
});
$('mat-rough')?.addEventListener('input', (e) => {
  state.material.rough = Number(e.target.value);
  $('mat-rough-val').textContent = e.target.value;
  state.viewer?.applyMaterial(state.selected?.name, { rough: Number(e.target.value) });
});
$('mat-close')?.addEventListener('click', () => selectObject(''));
$('mat-apply')?.addEventListener('click', () => {
  if (!state.selected) return;
  const { color, metal, rough } = state.material;
  const tex = $('mat-tex')?.value || '';
  const m = state.selected.name;
  let lines = currentScript().split('\n').filter((l) => {
    const t = l.trim();
    return !(t.startsWith(`color ${m} `) || t.startsWith(`texture ${m} `) || t.startsWith(`материал ${m} `));
  });
  lines.push(`color ${m} ${color} metal=${metal} rough=${rough}`);
  if (tex) lines.push(`texture ${m} kind=${tex}`);
  setScript(lines.join('\n').trimEnd());
  toast(`Материал «${m}» записан в сценарий`);
});

/* ------------------------------------------------------------------ */
/*  Открытие внешних файлов                                           */
/* ------------------------------------------------------------------ */
async function uploadFile(file) {
  if (!file) return;
  const name = file.name || 'модель.glb';
  toast(`Открываю ${name}…`);
  try {
    const url = '/api/upload?name=' + encodeURIComponent(name) + '&token=' + encodeURIComponent(TOKEN);
    const res = await fetch(url, { method: 'POST', body: file });
    const data = await res.json();
    if (data.error) throw data.error;
    if (data.note) toast(data.note, 'bad');
    const lines = currentScript().split('\n');
    lines.push(data.line);
    setScript(lines.join('\n'));
    toast(`Файл добавлен в сцену: ${data.file}`);
  } catch (err) {
    toast('Не удалось открыть файл: ' + (err.message || err), 'bad');
  }
}

$('btn-open-file')?.addEventListener('click', () => $('file-input').click());
$('file-input')?.addEventListener('change', (e) => {
  const f = e.target.files?.[0];
  e.target.value = '';
  uploadFile(f);
});

const dropZone = $('drop-zone');
const viewerEl = $('viewer');
if (viewerEl) {
  ['dragenter', 'dragover'].forEach((ev) => viewerEl.addEventListener(ev, (e) => {
    e.preventDefault(); e.stopPropagation();
    if (dropZone) dropZone.hidden = false;
  }));
  ['dragleave', 'drop'].forEach((ev) => viewerEl.addEventListener(ev, (e) => {
    e.preventDefault(); e.stopPropagation();
    if (dropZone && (ev === 'drop' || e.target === viewerEl)) dropZone.hidden = true;
  }));
  viewerEl.addEventListener('drop', (e) => {
    const file = e.dataTransfer?.files?.[0];
    if (file) uploadFile(file);
  });
}

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
$('btn-format')?.addEventListener('click', () => {
  const lines = currentScript().split('\n').map((l) => l.replace(/[ \t]+$/, ''));
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  setScript(lines.join('\n'));
  toast('Сценарий выровнен');
});

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
    if (st.blender?.found) {
      $('status-blender').textContent = 'Blender найден';
      $('status-blender').title = st.blender.path;
    }
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
