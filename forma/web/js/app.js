import { Viewer } from './viewer.js';
import { encodeGif, downloadBlob } from './gif.js';

const $ = (id) => document.getElementById(id);
// Токен берём из адреса, а если его нет (обновили страницу, открыли голый
// адрес) — из мета-тега, который сервер подставляет в index.html.
const TOKEN = (() => {
  const meta = document.querySelector('meta[name="forma-token"]')?.content || '';
  if (meta && meta !== '__FORMA_TOKEN__') return meta;
  return new URLSearchParams(location.search).get('token') || '';
})();

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
  selection: null,
  selectMode: false,
  spaceMode: false,
  space: null,
  loopMode: 'auto',
  orbitSelection: false,
  occluders: false,
  runLine: 0,
  runSoft: [],
  notes: [],
  actions: [],
  cmdHistory: [],
  cmdIndex: -1,
  history: [],
  historyInfo: [],
  future: [],
  futureInfo: [],
  hidden: new Set(),
  userHidden: new Set(),
  editBaseline: null,
  lastSaved: '', 
  material: { color: '#c9d1e3', metal: 0, rough: 0.5 },
  anim: {
    mode: 'clips', time: 0, duration: 0, playing: false,
    frames: [], frameIndex: 0, frameTimer: 0, hold: 0.8, fps: 24,
    cache: new Map(), pending: null, timer: null, busy: false, preview: null,
    seqKey: null, morphPending: null,
  },
};

function readLoopMode() {
  try { return localStorage.getItem('forma_loop_mode') || 'auto'; } catch (e) { return 'auto'; }
}
state.loopMode = readLoopMode();

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

function updateUndoButtons() {
  const undo = $('btn-undo');
  const redo = $('btn-redo');
  if (undo) { undo.disabled = !state.history.length; undo.title = state.history.length ? 'Отменить последнее действие (Ctrl+Z)' : 'Отменять нечего'; }
  if (redo) redo.disabled = !state.future.length;
}

function pushHistory(previous, label = 'правка', next = null) {
  if (previous === undefined || previous === null) return;
  const target = next === null ? currentScript() : next;
  if (previous === target) return;          // действие ничего не меняет
  state.history.push(previous);
  state.historyInfo.push({ label, at: Date.now() });
  if (state.history.length > 200) {
    state.history.shift();
    state.historyInfo.shift();
  }
  state.future.length = 0;
  state.futureInfo.length = 0;
  updateUndoButtons();
  renderHistory();
}

function setScript(text, { build = true, record = true, label = 'правка' } = {}) {
  if (record) pushHistory(currentScript(), label, text);
  $('code').value = text;
  state.editBaseline = text;
  updateGutter();
  updateCursor();
  if (build) buildNow();
}

/** Правки в самом редакторе: одна запись истории на «сеанс» набора. */
let editTimer = 0;
function scheduleEditSnapshot() {
  clearTimeout(editTimer);
  editTimer = setTimeout(() => {
    const now = currentScript();
    if (state.editBaseline === null || now === state.editBaseline) return;
    pushHistory(state.editBaseline, 'правка в редакторе', now);
    state.editBaseline = now;
  }, 650);
}

function undo() {
  if (!state.history.length) { toast('Отменять нечего'); return; }
  state.future.push(currentScript());
  state.futureInfo.push(state.historyInfo.pop() || { label: 'правка', at: Date.now() });
  const prev = state.history.pop();
  setScript(prev, { record: false });
  updateUndoButtons();
  renderHistory();
  toast('Шаг отменён (' + state.history.length + ' в истории)');
}

function redo() {
  if (!state.future.length) { toast('Возвращать нечего'); return; }
  state.history.push(currentScript());
  state.historyInfo.push(state.futureInfo.pop() || { label: 'возврат', at: Date.now() });
  const next = state.future.pop();
  setScript(next, { record: false });
  updateUndoButtons();
  renderHistory();
  toast('Шаг возвращён');
}

/** Список всех шагов: текущий и предыдущие состояния сценария. */
function renderHistory() {
  const list = $('history-list');
  if (!list) return;
  list.innerHTML = '';
  const row = (title, subtitle, onClick, active = false) => {
    const el = document.createElement('button');
    el.className = 'history-item' + (active ? ' active' : '');
    el.innerHTML = `<span class="history-title">${escapeHtml(title)}</span>
      <span class="history-sub">${escapeHtml(subtitle)}</span>`;
    if (onClick) el.addEventListener('click', onClick);
    else el.disabled = true;
    list.appendChild(el);
  };
  row('Сейчас', state.history.length ? `${state.history.length + 1}-е состояние` : 'начальное состояние', null, true);
  for (let i = state.history.length - 1; i >= 0; i--) {
    const info = state.historyInfo[i] || { label: 'правка', at: 0 };
    const time = info.at ? new Date(info.at).toLocaleTimeString('ru-RU') : '';
    const stepsBack = state.history.length - i;
    row(`${stepsBack} шаг(ов) назад: ${info.label}`, time,
      () => rollbackTo(i));
  }
}

/** Откат к состоянию из истории (от последнего к первому). */
function rollbackTo(index) {
  const target = state.history[index];
  if (target === undefined) return;
  state.future = [currentScript(), ...state.history.slice(index + 1)];
  state.futureInfo = [{ label: 'сейчас', at: Date.now() },
    ...state.historyInfo.slice(index + 1)];
  state.history = state.history.slice(0, index);
  state.historyInfo = state.historyInfo.slice(0, index);
  setScript(target, { record: false });
  updateUndoButtons();
  renderHistory();
  toast(`Откат к шагу ${state.history.length + 1} — сделано`);
}

function updateGutter(errorLine) {
  const lines = currentScript().split('\n');
  const gutter = $('gutter');
  const soft = new Set(state.runSoft || []);
  gutter.innerHTML = lines
    .map((_, i) => {
      const cls = [errorLine === i + 1 ? 'err' : '', state.runLine === i + 1 ? 'run' : '',
        soft.has(i + 1) ? 'run-soft' : ''].filter(Boolean).join(' ');
      return `<div class="${cls}">${i + 1}</div>`;
    })
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

$('code').addEventListener('scroll', () => {
  $('gutter').scrollTop = $('code').scrollTop;
  placeRunHighlight(false);
});
$('code').addEventListener('input', () => {
  clearScriptHighlight();
  updateGutter();
  updateCursor();
  scheduleEditSnapshot();
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
  // Ctrl+Enter обрабатывает глобальный обработчик: иначе сборка
  // запускалась дважды (в поле и ещё раз после всплытия события)
});

document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault();
    saveProject();
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault();
    buildNow();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'z' || e.key === 'Z' || e.key === 'я' || e.key === 'Я')) {
    e.preventDefault();
    if (e.shiftKey) redo(); else undo();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || e.key === 'Y' || e.key === 'н' || e.key === 'Н')) {
    e.preventDefault();
    redo();
    return;
  }
  if (e.key === 'Escape') {
    document.querySelectorAll('.menu.open').forEach((m) => m.classList.remove('open'));
    $('help-modal').hidden = true;
    const studio = $('studio-panel');
    if (studio && !studio.hidden) toggleStudio(false);
    const mat = $('material-panel');
    if (mat && !mat.hidden) selectObject('');
    if (state.selectMode) setSelectMode(false);
    if (state.spaceMode) setSpaceMode(false);
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
    const payload = await api('/api/build', { script: currentScript(), auto: silent });
    state.payload = payload;
    applyBuild(payload, Math.round(performance.now() - t0));
    if (payload.ok) {
      if (payload.empty || !payload.glb_url) {
        // Пустой сценарий = чистая сцена: снимаем и модель, и подсветку,
        // и всё, что было применено раньше. Никакой ошибки — просто ничего.
        clearSceneView();
      } else {
        await loadModel(payload.glb_url, payload.timeline || payload.animation);
      }
      if (!silent) toast(payload.empty ? 'Сцена пуста — всё снято'
        : `Готово за ${Math.round(performance.now() - t0)} мс`);
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

/** Чистая сцена: убираем модель, подсветку, кисть и надпись «пусто». */
function clearSceneView() {
  const v = state.viewer;
  if (!v) return;
  v.setPaintMode(false, null, '', false);
  v.disposeModel();
  state.hidden.clear();
  state.userHidden.clear();
  state.selected = null;
  state.paintCount = 0;
  state.anim.frames = [];
  state.anim.playing = false;
  const empty = $('viewer-empty');
  if (empty) {
    empty.hidden = false;
    empty.innerHTML = '<p>Сцена пуста. Напишите команды в сценарии слева — '
      + 'например, <code>куб = box size=[100,100,100]</code>.</p>';
  }
  syncPaintMode();
  updateAnimState();
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
    renderSections(null);
    state.anim.frames = [];
    state.anim.playing = false;
    updateAnimState();
    return;
  }

  hideError();
  const stateEl = $('status-state');
  stateEl.textContent = payload.empty ? 'сцена пуста' : 'модель построена';
  stateEl.className = 'status-item ok';

  // Скрытые детали (например, вошедшие в union/weld) должны оставаться
  // скрытыми, но открываться одним кликом по глазку. Держим единое состояние.
  const names = new Set((payload.objects || []).map((o) => o.name));
  // Скрытое состояние собираем заново на каждой сборке: иначе деталь,
  // спрятанная в прошлом примере, оставалась невидимой в новом, хотя глазок
  // показывал «видим». Скрытие глазком храним отдельно и переносим.
  state.hidden.clear();
  (payload.objects || []).forEach((o) => { if (!o.visible) state.hidden.add(o.name); });
  [...state.userHidden].forEach((n) => {
    if (names.has(n)) state.hidden.add(n); else state.userHidden.delete(n);
  });

  renderReport(payload);
  renderSections(payload);
  renderChecks(payload);
  if ($('page-links')?.classList.contains('active')) renderLinks();
  renderObjects(payload);
  renderDimensions(metrics);
  if (state.selected?.name) {
    const fresh = (payload.objects || []).find((o) => o.name === state.selected.name);
    if (fresh) renderObjectStats(fresh);
    else selectObject('');
  }
  if (payload.notes) { state.notes = payload.notes; renderNotes(); }
  if (payload.actions) { state.actions = payload.actions; renderActions(); }
  const checks = (payload.analysis?.checks || []);
  const failed = checks.filter((c) => !c.ok).length;
  setCmdResult(`✓ собрано · ${fmtInt(metrics.tris || 0)} трис`
    + (checks.length ? ` · проверки ${checks.length - failed}/${checks.length}` : ''),
    failed ? 'bad' : 'ok');
  applyViewSettings(payload);
  updatePolyBadge();
  // Сразу показываем, что за клипы придут с моделью, не дожидаясь загрузки GLB.
  state.anim.frames = payload.frames || [];
  if (state.anim.mode === 'frames' && !state.anim.frames.length) state.anim.mode = 'clips';
  refreshAnimSelectors();
  updateAnimState();
}

function fmt(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1000) return v.toFixed(0);
  if (Math.abs(v - Math.round(v)) < 1e-6) return String(Math.round(v));
  return v.toFixed(digits).replace(/\.?0+$/, '');
}
function fmtInt(v) { return String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ' '); }

function renderSections(payload) {
  const panel = $('section-panel');
  const view = $('section-view');
  if (!panel || !view) return;
  // в сценарии может быть несколько строк section: показываем последнюю
  const sections = (payload?.sections || []).filter((s) => (s.contours || []).length);
  if (!sections.length) {
    panel.hidden = true;
    view.innerHTML = '';
    return;
  }
  const sec = sections[sections.length - 1];
  const bb = sec.bbox || [0, 0, 1, 1];
  const w = Math.max(1e-3, bb[2] - bb[0]);
  const h = Math.max(1e-3, bb[3] - bb[1]);
  const path = sec.contours.map((c) => 'M ' + c.map((pt) => `${pt[0].toFixed(2)} ${pt[1].toFixed(2)}`).join(' L ') + ' Z').join(' ');
  const stroke = Math.max(w, h) / 300;
  view.innerHTML = `<svg viewBox="${bb[0]} ${bb[1]} ${w} ${h}" preserveAspectRatio="xMidYMid meet">`
    + `<g transform="translate(0 ${bb[1] + bb[3]}) scale(1 -1)">`
    + `<path d="${path}" fill="#79a9e0" fill-opacity="0.35" fill-rule="evenodd" `
    + `stroke="#bcd9ff" stroke-width="${stroke}" stroke-linejoin="round" />`
    + '</g></svg>'
    + `<div class="section-caption">${escapeHtml(sec.object || '')} · ${escapeHtml(sec.plane || 'z')}=${fmt(sec.at)} мм`
    + ` · площадь ${fmt((sec.area || 0) / 100)} см²`
    + (sec.holes ? ` · отверстий ${sec.holes}` : '')
    + '</div>';
  panel.hidden = false;
}

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

function renderNotes() {
  const box = $('notes-list');
  if (!box) return;
  const notes = state.notes || [];
  box.innerHTML = '';
  if (!notes.length) {
    box.innerHTML = '<div class="notes-empty">Пока пусто. Включите «выбор», кликните по области модели и напишите, что не так.</div>';
    return;
  }
  notes.slice().reverse().forEach((n) => {
    const el = document.createElement('div');
    el.className = 'note-item';
    const c = (n.center || []).map((v) => fmt(v)).join(', ');
    if (n.kind === 'пространство') {
      el.classList.add('note-space');
      el.innerHTML = `<div class="note-meta">${escapeHtml(n.time || '')} · кубы: `
        + `<b>${n.cells || 0}</b> × ${fmt(n.cell || 0)} мм · ${escapeHtml(n.indices || '')} · `
        + `центр (${escapeHtml(c)}) мм · ${fmt(n.volume_cm3 || 0)} см³</div>`
        + `<div class="note-text">${escapeHtml(n.text || '')}</div>`;
    } else {
      el.innerHTML = `<div class="note-meta">${escapeHtml(n.time || '')} · ${escapeHtml(n.object || '')} · `
        + `${n.tris || 0} трис · центр (${escapeHtml(c)})</div>`
        + `<div class="note-text">${escapeHtml(n.text || '')}</div>`;
    }
    box.appendChild(el);
  });
}

function renderActions() {
  const box = $('actions-list');
  if (!box) return;
  const actions = (state.actions || []).slice(-10).reverse();
  box.innerHTML = '';
  if (!actions.length) {
    box.innerHTML = '<div class="actions-empty">Здесь появятся выполненные шаги: сборка, снимки, экспорт, правки.</div>';
    return;
  }
  actions.forEach((a) => {
    const el = document.createElement('div');
    el.className = 'action-item ' + (a.ok ? 'ok' : 'bad');
    el.innerHTML = `<span class="t">${escapeHtml(a.time || '')}</span>`
      + `<span class="k">${a.ok ? '✓' : '✗'}</span>`
      + `<span class="d">${escapeHtml(a.kind || '')}: ${escapeHtml(a.text || '')}</span>`;
    box.appendChild(el);
  });
}

function fullReportText() {
  const a = state.payload?.analysis || {};
  const parts = [(a.text || '').trim()];
  if (state.notes.length) {
    parts.push('', 'ЗАМЕЧАНИЯ К ОБЛАСТЯМ');
    state.notes.forEach((n) => {
      const c = (n.center || []).map((v) => fmt(v)).join(', ');
      if (n.kind === 'пространство') {
        parts.push(`• ${n.time || ''} ${n.cells || 0} куб. по ${fmt(n.cell || 0)} мм `
          + `[${n.indices || ''}], центр (${c}) мм, объём ${fmt(n.volume_cm3 || 0)} см³: `
          + `${n.text || ''}`);
      } else {
        parts.push(`• ${n.time || ''} «${n.object || ''}» (${n.tris || 0} трис, `
          + `${n.area_mm2 || 0} мм², центр (${c})): ${n.text || ''}`);
      }
    });
  }
  if (state.actions.length) {
    parts.push('', 'ХОД РАБОТЫ');
    state.actions.slice(-20).forEach((x) => {
      parts.push(`${x.ok ? '✓' : '✗'} ${x.time || ''} ${x.kind || ''}: ${x.text || ''}`);
    });
  }
  return parts.join('\n');
}

async function copyReport() {
  const text = fullReportText();
  if (!text.trim()) { toast('Отчёт пока пуст — соберите модель', 'bad'); return; }
  try {
    await navigator.clipboard.writeText(text);
    toast('Отчёт скопирован');
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
    toast('Отчёт скопирован');
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

/* ------------------------------------------------------------------ */
/*  0.19: мастер зазоров — что с чем соединено                        */
/* ------------------------------------------------------------------ */
function linkRow(name, note, status, mateLine) {
  const row = document.createElement('div');
  row.className = 'links-row';
  const badge = document.createElement('span');
  badge.className = 'links-badge ' + (status.kind || '');
  badge.textContent = status.text;
  const nm = document.createElement('span');
  nm.className = 'links-name';
  nm.textContent = name;
  const nt = document.createElement('span');
  nt.className = 'links-note';
  nt.textContent = note;
  row.append(badge, nm, nt);
  if (mateLine) {
    const btn = document.createElement('button');
    btn.className = 'small';
    btn.textContent = 'связать';
    btn.title = 'Дописать в сценарий: ' + mateLine;
    btn.addEventListener('click', () => insertTool(mateLine, 'сопряжение'));
    row.appendChild(btn);
  }
  return row;
}

function addLinksTitle(body, text) {
  const t = document.createElement('div');
  t.className = 'links-group-title';
  t.textContent = text;
  body.appendChild(t);
}

async function renderLinks() {
  const body = $('links-body');
  if (!body) return;
  if (!state.payload) {
    body.innerHTML = '<div class="hint-box">Соберите модель — тогда будет видно, ' +
      'какие детали касаются друг друга, а какие висят отдельно.</div>';
    return;
  }
  let data;
  try {
    data = await api('/api/links');
  } catch (e) {
    $('links-summary').textContent = e.message || 'не удалось посчитать связи';
    return;
  }
  body.innerHTML = '';
  const total = data.objects || 0;
  const loose = data.loose || [];
  const mates = data.mates || [];
  $('links-summary').textContent = total
    ? `деталей ${total} · сборок ${data.groups || 0} · в главной ${data.main || 0}` +
      ` · касаний ${data.touches || 0}`
    : 'в сцене нет видимых деталей';

  if (loose.length) {
    addLinksTitle(body, `Висят отдельно — ${loose.length}`);
    loose.forEach((item) => {
      const near = item.nearest ? `ближайшая «${item.nearest}», зазор ${item.gap} мм`
        : 'рядом ничего нет';
      const status = item.gap !== null && item.gap <= 2
        ? { text: 'зазор', kind: 'warn' } : { text: 'висит', kind: 'bad' };
      const line = item.nearest
        ? `сопряжение ${item.name} ${item.nearest} type=зазор offset=0`
        : null;
      body.appendChild(linkRow(item.name, near, status, line));
    });
  } else if (total) {
    addLinksTitle(body, 'Все детали соединены');
    body.appendChild(linkRow('сборка', `${total} деталей образуют одну сборку`,
      { text: 'ok', kind: 'ok' }, null));
  }

  if (mates.length) {
    addLinksTitle(body, `Сопряжения — ${mates.length}`);
    mates.forEach((m) => {
      const hinge = m.kind === 'hinge';
      const tol = hinge ? 1 : 0.05;
      const res = Number(m.residual || 0);
      const ok = res <= tol;
      const off = m.offset ? `, зазор ${m.offset} мм` : '';
      const ang = m.angle ? `, поворот ${m.angle}°` : '';
      body.appendChild(linkRow(
        `${m.moving} → ${m.base}`,
        `${m.kind_ru || m.kind}${off}${ang} · остаток ${res.toFixed(3)} мм · стр. ${m.line}`,
        { text: ok ? 'держится' : 'разъехалась', kind: ok ? 'ok' : 'bad' }, null));
    });
  } else if (total) {
    addLinksTitle(body, 'Сопряжений нет');
    body.appendChild(linkRow('как добавить',
      'сопряжение колесо рейка type=паз axis=y · дверь корпус type=петля point=[x,y,z] angle=30',
      { text: 'подсказка', kind: '' }, null));
  }

  const pairs = (data.pairs || []).filter((pr) => pr.gap > 0.05).slice(0, 24);
  if (pairs.length) {
    addLinksTitle(body, 'Зазоры между деталями');
    pairs.forEach((pr) => {
      body.appendChild(linkRow(`${pr.a} ↔ ${pr.b}`,
        `зазор ${pr.gap} мм`,
        { text: pr.gap <= 2 ? 'стык' : 'щель', kind: pr.gap <= 2 ? 'warn' : '' }, null));
    });
  }
}

$('links-refresh')?.addEventListener('click', renderLinks);

function renderObjects(payload) {
  const list = $('objects-list');
  list.innerHTML = '';
  const objs = payload.objects || [];
  objs.forEach((o) => {
    const el = document.createElement('div');
    el.className = 'obj-item' + (o.visible && !state.hidden.has(o.name) ? '' : ' hidden-obj');
    el.innerHTML = `
      <span class="swatch" style="background:${o.color}"></span>
      <div class="obj-main">
        <div class="obj-name">${escapeHtml(o.name)}</div>
        <div class="obj-meta">${fmt(o.size[0])}×${fmt(o.size[1])}×${fmt(o.size[2])} мм ·
          ${fmt(o.volume_cm3)} см³ · ${fmtInt(o.tris)} трис
          ${o.tex ? ' · <span class="obj-tex">текстура: ' + escapeHtml(o.tex.label || o.tex.kind) + '</span>' : ''}</div>
      </div>
      <span class="eye" title="Скрыть или показать">${state.hidden.has(o.name) ? '○' : '●'}</span>
      <span class="trash" title="Удалить объект из модели">🗑</span>`;
    el.dataset.name = o.name;
    const eye = el.querySelector('.eye');
    if (eye) {
      eye.title = o.visible ? 'Скрыть объект' : 'Показать объект';
      eye.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const name = o.name;
        const willHide = !state.hidden.has(name);
        if (willHide) { state.hidden.add(name); state.userHidden.add(name); }
        else { state.hidden.delete(name); state.userHidden.delete(name); }
        state.viewer?.setObjectVisible(name, !willHide);
        eye.textContent = willHide ? '○' : '●';
        el.classList.toggle('hidden-obj', willHide);
        toast(willHide ? `Скрыто: ${name}` : `Показано: ${name}`);
      });
    }
    const trash = el.querySelector('.trash');
    if (trash) {
      trash.addEventListener('click', (ev) => {
        ev.stopPropagation();
        deleteObject(o.name);
      });
    }
    el.addEventListener('click', () => {
      selectObject(o.name);
    });
    el.addEventListener('dblclick', () => {
      // двойной клик — навести камеру на деталь
      if (state.viewer?.focusObject(o.name)) {
        toast(`Камера наведена: ${o.name}`);
        return;
      }
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
  if ($('obj-badge-count')) $('obj-badge-count').textContent = objs.length;
  // если предмет выбран, карточка справа должна остаться его, а не сцены:
  // список перерисовывается после каждого скрытия/показа и пересборки
  if (state.selected?.name) {
    const sel = objs.find((o) => o.name === state.selected.name);
    if (sel) {
      Object.assign(state.selected, sel);
      renderObjectStats(sel);
      return;
    }
  }
  $('objects-summary').innerHTML = objs.length
    ? `Всего объектов: ${objs.length} (видимых ${m.visible_count ?? '—'}).<br>
       Материал: ${fmt(m.volume_cm3)} см³, масса ${fmt(m.mass_g, 0)} г.`
    : 'Пока нет объектов.';
}

/** Удаление объекта: дописывает команду «удалить» и чистит его строки материала. */
function deleteObject(name) {
  if (!name) return;
  const esc = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const keep = (line) => {
    const t = line.trim();
    if (new RegExp(`^(удалить|delete|remove|убрать)\\s+${esc}$`, 'i').test(t)) return false;
    if (new RegExp(`^(color|цвет|texture|текстура|hide|скрыть|show|показать)\\s+${esc}(\\s|$)`, 'i').test(t)) return false;
    return true;
  };
  const lines = currentScript().split('\n').filter(keep);
  lines.push(`удалить ${name}`);
  if (state.selected?.name === name) selectObject('');
  setScript(lines.join('\n').trimEnd(), { label: `удаление «${name}»` });
  toast(`Объект «${name}» удалён — Ctrl+Z вернёт`);
}

function setAllObjectsVisible(visible) {
  const objs = state.payload?.objects || [];
  objs.forEach((o) => {
    if (visible) { state.hidden.delete(o.name); state.userHidden.delete(o.name); }
    else { state.hidden.add(o.name); state.userHidden.add(o.name); }
    state.viewer?.setObjectVisible(o.name, visible);
  });
  renderObjects(state.payload || {});
  toast(visible ? 'Показаны все объекты' : 'Скрыты все объекты');
}

$('objects-optimize')?.addEventListener('click', () => {
  const lines = currentScript().split('\n').filter((l) => !l.trim().toLowerCase().startsWith('optimize '));
  lines.push('optimize all tolerance=0.15');
  setScript(lines.join('\n').trimEnd());
  setCmdResult('✓ добавлена оптимизация сетки: ровные участки теряют лишние грани', 'ok');
});

$('objects-hide-all')?.addEventListener('click', () => setAllObjectsVisible(false));
$('objects-show-all')?.addEventListener('click', () => setAllObjectsVisible(true));

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

/** Статистика только выбранного предмета — в подписи, статусе и списке. */
function renderObjectStats(obj) {
  if (!obj) { renderSceneStats(); return; }
  state.selected = obj;
  const size = obj.size || [0, 0, 0];
  const box = $('dim-overlay');
  if (box) {
    box.hidden = false;
    box.innerHTML = `<b>${escapeHtml(obj.name)}</b> · ${fmt(size[0])} × ${fmt(size[1])} × ${fmt(size[2])} мм<br>`
      + `${fmt(obj.volume_cm3)} см³ · ${fmt(obj.mass_g, 0)} г · ${fmtInt(obj.tris)} трис`
      + (obj.parts !== undefined ? ` · частей ${obj.parts}` : '')
      + `<br><span class="dim">строка ${obj.line || '—'}${obj.op ? ' · ' + escapeHtml(obj.op) : ''}</span>`;
  }
  const badge = $('viewer-badge');
  if (badge) {
    badge.hidden = false;
    badge.textContent = `${escapeHtml(obj.name)} · ${fmtInt(obj.tris)} трис · ${fmt(obj.volume_cm3)} см³`;
  }
  $('status-tris').textContent = `${fmtInt(obj.tris)} трис`;
  $('status-size').textContent = `${fmt(size[0])} × ${fmt(size[1])} × ${fmt(size[2])} мм`;
  $('status-parts').textContent = 'объект: ' + obj.name;
  const sum = $('objects-summary');
  if (sum) {
    const ghosts = (state.occludersNow || []).length;
    sum.innerHTML = `Выбран: <b>${escapeHtml(obj.name)}</b><br>`
      + `${fmt(size[0])} × ${fmt(size[1])} × ${fmt(size[2])} мм · ${fmt(obj.volume_cm3)} см³ · ${fmt(obj.mass_g, 0)} г<br>`
      + `${fmtInt(obj.tris)} трис · ${fmtInt(obj.verts)} верш.`
      + (obj.genus !== undefined ? ` · род ${obj.genus}` : '')
      + (obj.areas_mm2 || obj.area_mm2 ? ` · площадь ${fmt(obj.area_mm2)} мм²` : '')
      + (obj.tex ? ` · текстура: ${escapeHtml(obj.tex.label || obj.tex.kind)}` : '')
      + (ghosts ? `<br><span class="dim">заслонок прозрачных: ${ghosts}</span>` : '')
      + '<br><span class="dim">двойной клик в списке — камера; Delete — удалить; ⌖ — приблизить</span>';
  }
}

/** Возврат к статистике всей сцены. */
function renderSceneStats() {
  const m = state.payload?.analysis?.metrics || {};
  renderDimensions(m);
  if (m.tris) $('status-tris').textContent = `${fmtInt(m.tris)} трис`;
  if (m.size) $('status-size').textContent = `${fmt(m.size[0])} × ${fmt(m.size[1])} × ${fmt(m.size[2])} мм`;
  if (m.parts) $('status-parts').textContent = `частей: ${m.parts}`;
  if (state.payload) renderObjects(state.payload);
}

function setCmdResult(text, kind = '') {
  const el = $('cmd-result');
  if (!el) return;
  el.textContent = text || '';
  el.className = 'cmd-result ' + kind;
}

function showError(err) {
  setCmdResult('✗ ' + (err.message || 'ошибка'), 'bad');
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

/** Плавная прокрутка текстового поля к нужной высоте (без рывков). */
let scrollTween = null;
function smoothScrollTo(el, target) {
  const from = el.scrollTop;
  const to = Math.max(0, target);
  if (Math.abs(to - from) < 2) { el.scrollTop = to; return; }
  if (scrollTween) cancelAnimationFrame(scrollTween.raf);
  const t0 = performance.now();
  const dur = 240;
  const step = (now) => {
    const k = Math.min(1, (now - t0) / dur);
    const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
    el.scrollTop = from + (to - from) * e;
    if (k < 1) scrollTween.raf = requestAnimationFrame(step);
    else scrollTween = null;
  };
  scrollTween = { raf: requestAnimationFrame(step) };
}

/** Подсветка строки сценария, которая сейчас играет. */
function placeRunHighlight(follow = false) {
  const el = $('code-run');
  const ta = $('code');
  if (!el || !ta) return;
  const cs = getComputedStyle(ta);
  const lh = parseFloat(cs.lineHeight) || 20.6;
  const pad = parseFloat(cs.paddingTop) || 12;
  if (!state.runLine) { el.hidden = true; return; }
  const lineTop = (state.runLine - 1) * lh;
  const viewTop = ta.scrollTop;
  const viewBottom = viewTop + (ta.clientHeight || 0) - lh;
  if (follow) {
    // Держим играющую строку на виду, но подкручиваем плавно: мгновенный
    // скачок на каждом кадре и был той самой «телепортацией».
    const target = Math.max(0, lineTop - Math.max(0, (ta.clientHeight || 0)) * 0.35);
    smoothScrollTo(ta, target);
    const gutter = $('gutter');
    if (gutter) smoothScrollTo(gutter, target);
  }
  const offset = pad + lineTop - ta.scrollTop;
  el.style.top = offset + 'px';
  el.style.height = lh + 'px';
  // если пользователь сам прокрутил текст, полосу не навязываем
  el.hidden = offset < -lh || offset > ta.clientHeight;
}

/** Подсветить одну строку (основную) и необязательно ещё несколько бледных. */
function highlightScriptLine(line, { scroll = false, follow = true, soft = [] } = {}) {
  const n = Number(line) || 0;
  state.runLine = n;
  state.runSoft = n ? (soft || []).map(Number).filter((x) => x && x !== n) : [];
  const gutter = $('gutter');
  if (gutter) {
    const softSet = new Set(state.runSoft);
    [...gutter.children].forEach((el, i) => {
      el.classList.toggle('run', i + 1 === n);
      el.classList.toggle('run-soft', softSet.has(i + 1));
    });
  }
  placeRunHighlight(follow);
  if (state.runSoft.length) {
    // вторая полоса — на самом раннем из параллельных клипов
    const lines = [...state.runSoft, n].sort((x, y) => x - y);
    const el = $('code-run-soft');
    const ta = $('code');
    if (el && ta) {
      const cs = getComputedStyle(ta);
      const lh = parseFloat(cs.lineHeight) || 20.6;
      const pad = parseFloat(cs.paddingTop) || 12;
      const top = pad + (lines[0] - 1) * lh - ta.scrollTop;
      el.style.top = top + 'px';
      el.style.height = (lines[lines.length - 1] - lines[0] + 1) * lh + 'px';
      el.hidden = top + parseFloat(el.style.height) < 0 || top > ta.clientHeight;
    }
  } else if ($('code-run-soft')) {
    $('code-run-soft').hidden = true;
  }
}

function clearScriptHighlight() {
  state.runLine = 0;
  state.runSoft = [];
  const gutter = $('gutter');
  if (gutter) [...gutter.children].forEach((el) => el.classList.remove('run', 'run-soft'));
  ['code-run', 'code-run-soft'].forEach((id) => { const el = $(id); if (el) el.hidden = true; });
}

/** Клипы, звучащие в момент t. */
function activeClipsAt(time) {
  const eps = 1e-6;
  return animClips().filter((c) => {
    if (!c.line) return false;
    const s0 = Number(c.start) || 0;
    const s1 = s0 + (Number(c.length) || 0);
    return time >= s0 - eps && time <= s1 + eps;
  });
}

/** Самый «подробный» клип: короткий, а при равенстве — начавшийся позже. */
function pickClosest(list) {
  return list.reduce((best, c) => {
    if (!best) return c;
    const a = Number(c.length) || 0;
    const b = Number(best.length) || 0;
    if (a < b - 1e-6) return c;
    if (Math.abs(a - b) <= 1e-6 && (Number(c.start) || 0) >= (Number(best.start) || 0)) return c;
    return best;
  }, null);
}

/** Какая строка сценария соответствует моменту t: клипы или кадр сборки. */
function highlightFromTime(t, { scroll = false } = {}) {
  const a = state.anim;
  if (a.mode === 'frames') {
    const frame = animFrames()[a.frameIndex];
    if (frame) highlightScriptLine(frame.line, { scroll });
    return;
  }
  const clips = animClips();
  if (!clips.length) return;
  const time = Number(t) || 0;
  const active = activeClipsAt(time);
  const focus = state.viewer?._focusName || '';
  const focused = focus ? active.filter((c) => c.object === focus) : [];
  let pick = pickClosest(focused) || pickClosest(active);
  if (!pick) {
    // пауза между движениями: показываем последнюю прошедшую строку
    const past = clips.filter((c) => (Number(c.start) || 0) + (Number(c.length) || 0) <= time + 1e-6);
    pick = past.sort((x, y) => (Number(x.start) + Number(x.length)) - (Number(y.start) + Number(y.length))).pop();
  }
  if (!pick) return;
  const soft = active.filter((c) => c.line !== pick.line).map((c) => c.line);
  highlightScriptLine(pick.line, { scroll, soft });
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/* ------------------------------------------------------------------ */
/*  Просмотр                                                          */
/* ------------------------------------------------------------------ */
async function loadModel(url, animation = null) {
  state.anim.preview = null;
  state.anim.cache.clear();
  state.anim.pending = null;
  state.anim.frameTimer = 0;
  if (!url) return;
  $('viewer-empty').hidden = true;
  try {
    await state.viewer.load(url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN), animation);
    // мгновенная проверка видимости и текстур (не зависит от того, что попало в GLB)
    applyLoopMode();
    state.viewer.setAxes($('opt-axes')?.checked !== false);
    // Сбрасываем прежние скрытия: набор объектов мог смениться целиком.
    if (state.viewer.hidden) state.viewer.hidden.clear();
    state.hidden.forEach((name) => state.viewer.setObjectVisible(name, false));
    (state.payload?.objects || []).forEach((o) => {
      if (o.tex && o.tex.kind) applyTextureToViewer(o.name, o.tex.kind, o.tex.scale);
    });
    // Диагностика: если GLB загрузился, но деталей нет, честно говорим об этом,
    // а не оставляем пустое окно после «сборка готова».
    const shown = state.viewer.getStats?.();
    if (shown && typeof shown.meshes === 'number' && !shown.meshes) {
      const bar = $('error-bar');
      if (bar) {
        bar.hidden = false;
        $('error-msg').textContent = 'Модель построена, но в окне нет ни одной детали. '
          + 'Нажмите «Снимки» — отчёт покажет, что получилось.';
        $('error-hint').textContent = 'Если детали должны быть видимы, проверьте команды hide и глазки в списке объектов.';
      }
    } else if (shown) {
      $('viewer-badge').textContent = `${fmtInt(shown.tris)} треугольников`;
    }
    if (state.selected?.name && !state.hidden.has(state.selected.name)) {
      state.viewer?.setHighlight(state.selected.name);
    }
    state.anim.frames = state.payload?.frames || [];
    state.anim.frameIndex = 0;
    state.anim.time = 0;
    if (!state.anim.userMode) {
      const clips = animClips();
      const onlyAssembly = clips.length && clips.every((c) => c.kind === 'assembly');
      state.anim.mode = onlyAssembly && state.anim.frames.length ? 'frames' : 'clips';
    }
    renderSceneSelect();
    refreshAnimSelectors();
    if (state.anim.mode === 'frames' && !state.anim.frames.length) state.anim.mode = 'clips';
    if ($('anim-mode')) $('anim-mode').value = state.anim.mode;
    updateAnimState();
    if (state.anim.mode === 'frames') {
      if (state.anim.frames.length) showFrame(0);
    } else if (animClips().length || animKeys().length) {
      // Не запускаем анимацию сами: сначала показываем готовую модель.
      // Пользователь нажмёт «играть», когда захочет смотреть движение.
      state.viewer.playAnimation(false);
      state.anim.playing = false;
      state.viewer.setTime(0);
      state.anim.time = 0;
      highlightScriptLine(0);
      syncAnimUI();
      // подпись ставим последней: syncAnimUI её не перетирает, но порядок надёжнее
      if ($('anim-focus')) {
        $('anim-focus').textContent = `анимация готова (${animClips().length} движений) — нажмите ▶`;
      }
    }
  } catch (e) {
    toast('Не удалось показать модель: ' + (e?.message || e), 'bad');
  }
}

function sandboxParams() {
  return {
    pattern: $('tex-pattern')?.value || 'полосы',
    color1: $('tex-color1')?.value || '#3a6ea5',
    color2: $('tex-color2')?.value || '#e8dfcf',
    scale: $('tex-scale')?.value || '1',
    relief: $('tex-relief')?.value || '0',
    seed: $('tex-seed')?.value || '1',
  };
}

function sandboxCommand(name = 'объект') {
  const p = sandboxParams();
  return `texture ${name} kind=своя pattern=${p.pattern} color1=${p.color1} `
    + `color2=${p.color2} scale=${p.scale} seed=${p.seed} relief=${p.relief}`;
}

function textureUrl(kind, scale = 1) {
  let url = '/api/texture?kind=' + encodeURIComponent(kind)
    + '&scale=' + encodeURIComponent(scale);
  if (kind === 'своя') {
    const p = sandboxParams();
    url += '&pattern=' + encodeURIComponent(p.pattern)
      + '&color1=' + encodeURIComponent(p.color1) + '&color2=' + encodeURIComponent(p.color2)
      + '&seed=' + encodeURIComponent(p.seed) + '&relief=' + encodeURIComponent(p.relief);
  }
  return url + '&token=' + encodeURIComponent(TOKEN);
}

function textureNormalUrl() {
  const p = sandboxParams();
  return '/api/texture?kind=своя&normal=1'
    + '&pattern=' + encodeURIComponent(p.pattern)
    + '&color1=' + encodeURIComponent(p.color1) + '&color2=' + encodeURIComponent(p.color2)
    + '&scale=' + encodeURIComponent(p.scale) + '&seed=' + encodeURIComponent(p.seed)
    + '&relief=' + encodeURIComponent(p.relief) + '&token=' + encodeURIComponent(TOKEN);
}

function applyTextureToViewer(name, kind, scale = 1) {
  if (!name) return;
  if (!kind) { state.viewer?.clearTexture(name); return; }
  if (kind === 'custom' || kind === 'своя') {
    // свою текстуру показываем сразу, не дожидаясь пересборки
    state.viewer?.setTexture(name, textureUrl('своя'), textureNormalUrl());
    return;
  }
  state.viewer?.setTexture(name, textureUrl(kind, scale));
}

function showTexturePreview(kind) {
  const img = $('mat-tex-preview');
  if (!img) return;
  if (!kind) { img.hidden = true; img.removeAttribute('src'); return; }
  img.hidden = false;
  img.src = textureUrl(kind);
  img.title = 'Так выглядит рисунок «' + kind + '»';
}

const ANIM_KINDS = { spin: 'вращение', formation: 'формирование', explode: 'разлёт',
  assembly: 'сборка по шагам', move: 'перемещение', scale: 'масштаб', turn: 'доворот',
  wait: 'пауза', morph: 'изменение формы', roll: 'качение', jump: 'прыжок',
  fall: 'падение', fan: 'вентилятор' };
const ANIM_COLORS = { spin: '#2f4f8a', formation: '#2f7a5f', explode: '#8a5a2f',
  assembly: '#6b4f9e', move: '#2f7a8a', scale: '#8a7a2f', turn: '#8a2f6b',
  wait: '#4a4f57', morph: '#2f5f8a', roll: '#8a5f2f', jump: '#3f7a4f',
  fall: '#7a4f3f', fan: '#4f7a8a' };

function animPlan() {
  const p = state.payload?.timeline;
  if (p && Array.isArray(p.clips)) return p;
  const one = state.payload?.animation;
  return one && one.kind ? { clips: [one], duration: one.seconds || 4, count: 1 } : null;
}

/** Заготовленная сцена, выбранная в просмотре ('' — все сцены). */
function activeScene() { return state.viewer?.currentScene?.() || ''; }

/** Клип относится к выбранной сцене? Клипы без scene — общие. */
function inScene(clip) {
  const scene = activeScene();
  return !clip?.scene || !scene || clip.scene === scene;
}

function animClips() {
  const plan = animPlan();
  if (plan?.clips?.length) return plan.clips.filter(inScene);
  return (state.anim.preview?.clips || []).filter(inScene);
}

/** Длительность с учётом выбранной сцены: у «прыжка» она короче, чем у всех. */
function animDuration() {
  const own = Number(state.viewer?.duration) || 0;
  const all = Number(animPlan()?.duration) || Number(state.anim.preview?.duration) || 0;
  return Math.max(own, all);
}
function animKeys() { return animPlan()?.keys || []; }
function animFrames() { return state.anim.frames || []; }
function animFps() { return Number(animClips()[0]?.fps) || 24; }
function animTrackList() {
  const tracks = new Set(animClips().map((c) => Number(c.track) || 1));
  return [...tracks].sort((a, b) => a - b);
}

function animHasContent() {
  if (state.anim.mode === 'frames') return animFrames().length > 0;
  if (state.anim.preview) return true;
  return animClips().length > 0 || animKeys().length > 0
    || Boolean(state.viewer?.hasAnimation());
}

/** Нет animate в сценарии — всё равно показываем вращение, но не пишем его в сценарий. */
function startPreviewAnimation() {
  const v = state.viewer;
  if (!v || !v.hasModel?.()) return false;
  const clip = { kind: 'spin', axis: 'z', start: 0, length: 6, end: 6, loop: true,
                 seconds: 6, fps: 24, preview: true, track: 1 };
  const plan = { clips: [clip], duration: 6, count: 1, has: true, kinds: ['spin'],
                 assembly: null, tracks: [1], keys: [] };
  if (!v.setTimeline) return false;
  v.setTimeline(plan);
  v.playAnimation(true);
  state.anim.preview = plan;
  state.anim.mode = 'clips';
  state.anim.duration = 6;
  state.anim.time = 0;
  state.anim.playing = v.playing !== false;
  if ($('anim-mode')) $('anim-mode').value = 'clips';
  syncAnimUI();
  toast('Включён предпросмотр вращения. Чтобы сохранить его в модель, добавьте строку animate');
  return true;
}

/** Понятное объяснение вместо ложного «в сценарии нет анимации». */
function explainNoAnimation() {
  if (state.building) { toast('Модель ещё строится — анимация появится сразу после сборки'); return; }
  if (!state.payload?.ok) { toast('Сценарий не построен — сначала исправьте ошибку', 'bad'); return; }
  if (state.anim.mode === 'frames') {
    toast('В сценарии нет шагов сборки: добавьте объекты и операции', 'bad');
    return;
  }
  const lines = currentScript().split('\n').filter((l) => /^\s*animate\b/i.test(l)).length;
  if (lines) {
    toast('Строка animate есть, но клип пока не построен — нажмите «Собрать»', 'bad');
  } else {
    toast('Анимация не задана. Добавьте клип в редакторе или строкой animate kind=spin', 'bad');
    $('anim-editor').hidden = false;
  }
}

function syncAnimUI() {
  const a = state.anim;
  const has = animHasContent();
  const btn = $('anim-play');
  if (btn) {
    btn.textContent = a.playing ? '❚❚ пауза' : '▶ играть';
    btn.classList.toggle('active', a.playing);
    btn.disabled = false;   // всегда можно нажать: приложение объяснит, чего не хватает
    btn.title = has ? 'Играть / пауза' : 'Анимация не задана — открою редактор';
  }
  const label = $('anim-status');
  if (label) {
    if (a.mode === 'frames') {
      const totalSteps = (state.payload?.steps || []).length;
      label.textContent = animFrames().length
        ? `кадры сборки: ${animFrames().length} шаг(ов)` + (totalSteps > animFrames().length
          ? ` из ${totalSteps} команд` : '')
        : 'кадров сборки нет';
      label.title = 'Шагами считаются только команды, меняющие форму или видимость; '
        + 'проверки, цвет и служебные строки пропускаются';
      label.className = 'anim-status ' + (animFrames().length ? 'ok' : '');
    } else {
      const clips = animClips();
      const keys = animKeys();
      const total = animDuration() || 0;
      const preview = Boolean(a.preview);
      const shownTotal = preview ? a.preview.duration : total;
      const tracks = animTrackList().length;
      const bits = [];
      const kinds = [...new Set(clips.map((c) => ANIM_KINDS[c.kind] || c.kind))];
      if (kinds.length) bits.push(kinds.slice(0, 3).join(', '));
      if (clips.length) bits.push(`клипов ${clips.length}`);
      if (keys.length) bits.push(`ключей ${keys.length}`);
      if (tracks > 1) bits.push(`дорожек ${tracks}`);
      label.textContent = bits.length
        ? `${bits.join(' · ')} · ${shownTotal.toFixed(1)} с` + (preview ? ' · предпросмотр' : '')
        : 'анимация не задана (animate)';
      label.className = 'anim-status ' + ((clips.length || keys.length) ? 'ok' : '');
    }
  }
  const scrub = $('anim-scrub');
  if (scrub) {
    if (a.mode === 'frames') {
      scrub.max = String(Math.max(0, animFrames().length - 1));
      scrub.value = String(a.frameIndex || 0);
    } else {
      scrub.max = '1000';
    }
  }
  if ($('anim-frame-label') && a.mode === 'frames') {
    $('anim-frame-label').textContent =
      `шаг ${animFrames().length ? a.frameIndex + 1 : 0}/${animFrames().length}`;
  }
  syncAnimClock();
  renderAnimTracks();
  renderAnimClipsEditor();
  renderAnimKeys();
}

/** Быстрое обновление только часов (вызывается каждый кадр во время игры). */
function syncAnimClock() {
  const a = state.anim;
  const total = a.duration || animPlan()?.duration || 0;
  const scrub = $('anim-scrub');
  if (scrub && a.mode !== 'frames') scrub.value = String(total ? Math.round((a.time / total) * 1000) : 0);
  if ($('anim-time')) $('anim-time').textContent = `${a.time.toFixed(2)} / ${total.toFixed(2)} с`;
  if ($('anim-frame-label') && a.mode !== 'frames') {
    const fps = animFps();
    $('anim-frame-label').textContent = `кадр ${Math.round((a.time || 0) * fps)}/${Math.round(total * fps)}`;
  }
  const btn = $('anim-play');
  if (btn) {
    btn.textContent = a.playing ? '❚❚ пауза' : '▶ играть';
    btn.classList.toggle('active', a.playing);
  }
}

function updateAnimState() {
  const a = state.anim;
  a.duration = animDuration();
  if (a.mode === 'frames') a.duration = 0;
  syncAnimUI();
}

/* --- дорожки клипов и шагов ------------------------------------------ */
function renderAnimTracks() {
  const box = $('anim-tracks');
  if (!box) return;
  const a = state.anim;
  box.innerHTML = '';
  if (a.mode === 'frames') {
    const frames = animFrames();
    if (!frames.length) {
      box.innerHTML = '<span class="anim-empty">шагов сборки нет — добавьте объекты в сценарий</span>';
      return;
    }
    // шаги в отдельной прокручиваемой строке: их может быть сотня
    const row = document.createElement('div');
    row.className = 'anim-steps';
    frames.forEach((f, i) => {
      const b = document.createElement('button');
      b.className = 'anim-step' + (i === a.frameIndex ? ' cur' : '');
      b.textContent = String(f.frame || i + 1);
      b.title = `строка ${f.line}: ${f.text}`;
      b.onclick = () => { pauseAnim(); seekFrame(i); };
      row.appendChild(b);
    });
    box.appendChild(row);
    return;
  }
  const clips = animClips();
  const keys = animKeys();
  const total = animDuration() || Number(a.preview?.duration) || 0;
  if (!clips.length && !keys.length) {
    box.innerHTML = '<span class="anim-empty">клипов нет: animate kind=spin seconds=6</span>';
    return;
  }
  const laneFor = (track, object) => {
    const row = document.createElement('div');
    row.className = 'anim-track-row';
    if (animTrackList().length > 1 || object) {
      const name = document.createElement('span');
      name.className = 'anim-track-name';
      name.textContent = 'дорожка ' + track + (object ? ` · ${object}` : '');
      row.appendChild(name);
    }
    const lane = document.createElement('div');
    lane.className = 'anim-lane';
    clips.filter((c) => (Number(c.track) || 1) === track
      && (c.object || '') === object).forEach((c) => {
      const seg = document.createElement('div');
      seg.className = 'anim-seg seg-' + (c.kind || 'spin');
      const st = Number(c.start) || 0;
      const len = Number(c.length) || Number(c.seconds) || 1;
      seg.style.left = total ? `${(st / total) * 100}%` : '0%';
      seg.style.width = total ? `${Math.max(2, (len / total) * 100)}%` : '100%';
      if (ANIM_COLORS[c.kind]) seg.style.background = ANIM_COLORS[c.kind];
      seg.title = `${ANIM_KINDS[c.kind] || c.kind} · ${st.toFixed(1)}–${(st + len).toFixed(1)} с`
        + (c.object ? ` · ${c.object}` : '') + (c.line ? ` · строка ${c.line}` : '');
      seg.innerHTML = `<span>${(st === 0 || len / Math.max(total, 0.001) > 0.12)
        ? (ANIM_KINDS[c.kind] || c.kind) : ''}</span>`;
      seg.onclick = () => { pauseAnim(); seekTime(st); };
      lane.appendChild(seg);
    });
    row.appendChild(lane);
    return row;
  };
  const lanes = [];
  clips.forEach((c) => {
    const track = Number(c.track) || 1;
    const object = c.object || '';
    if (!lanes.some((l) => l.track === track && l.object === object)) {
      lanes.push({ track, object });
    }
  });
  lanes.sort((a, b) => (a.track - b.track) || a.object.localeCompare(b.object, 'ru'));
  lanes.forEach((l) => box.appendChild(laneFor(l.track, l.object)));

  if (keys.length) {
    const row = document.createElement('div');
    row.className = 'anim-track-row';
    if (animTrackList().length > 1) {
      const name = document.createElement('span');
      name.className = 'anim-track-name';
      name.textContent = 'ключи';
      row.appendChild(name);
    }
    const lane = document.createElement('div');
    lane.className = 'anim-lane anim-lane-keys';
    keys.forEach((k) => {
      const d = document.createElement('div');
      d.className = 'anim-key';
      d.style.left = total ? `${Math.min(100, ((Number(k.t) || 0) / total) * 100)}%` : '0%';
      d.title = `ключ ${k.object} @ ${(Number(k.t) || 0).toFixed(1)} с`
        + (k.pos ? ` · Δ(${k.pos.join(', ')})` : '')
        + (k.rot ? ` · ∠(${k.rot.join(', ')})` : '')
        + (k.scale !== undefined ? ` · ×${k.scale}` : '');
      d.onclick = () => { pauseAnim(); seekTime(Number(k.t) || 0); };
      lane.appendChild(d);
    });
    row.appendChild(lane);
    box.appendChild(row);
  }
}

/* --- редактор клипов ------------------------------------------------ */
function renderAnimClipsEditor() {
  const box = $('anim-clips');
  if (!box) return;
  const clips = animClips();
  box.innerHTML = '';
  if (!clips.length) {
    box.innerHTML = '<span class="anim-empty">пока ни одного клипа</span>';
    return;
  }
  clips.forEach((c) => {
    const row = document.createElement('div');
    row.className = 'anim-clip-row';
    const title = `${ANIM_KINDS[c.kind] || c.kind}`
      + ` · дорожка ${Number(c.track) || 1}`
      + (c.object ? ` · ${c.object}` : '')
      + (c.kind === 'assembly' ? ` · ${(c.hold || 0.8).toFixed(1)} с/шаг`
        : ` · ${(Number(c.length) || Number(c.seconds) || 0).toFixed(1)} с`)
      + ` · с ${(Number(c.start) || 0).toFixed(1)} с`;
    row.innerHTML = `<span class="anim-clip-name">${escapeHtml(title)}</span>`
      + `<code>${escapeHtml(c.text || '')}</code>`;
    const edit = document.createElement('button');
    edit.className = 'mini';
    edit.textContent = '✎';
    edit.title = 'Загрузить значения в редактор';
    edit.onclick = () => loadClipIntoEditor(c);
    const del = document.createElement('button');
    del.className = 'mini';
    del.textContent = '✕';
    del.title = 'Удалить клип из сценария';
    del.onclick = () => removeScriptLine(c.line, /^\s*(animate|анимация|движение|animation)\b/i,
                                         'клип');
    row.appendChild(edit);
    row.appendChild(del);
    box.appendChild(row);
  });
}

function loadClipIntoEditor(c) {
  $('anim-editor').hidden = false;
  $('ae-kind').value = c.kind || 'spin';
  $('ae-axis').value = c.axis ? ((Number(c.axis_sign) < 0 ? '-' : '') + c.axis) : 'z';
  $('ae-seconds').value = String(Number(c.seconds) || 4);
  $('ae-start').value = c.start === null || c.start === undefined ? '' : String(c.start);
  $('ae-track').value = String(Number(c.track) || 1);
  $('ae-object').value = c.object || '';
  $('ae-hold').value = String(Number(c.hold) || 0.8);
  $('ae-amount').value = String(Number(c.amount) || 30);
  if (c.delta) {
    $('ae-dx').value = String(c.delta[0]); $('ae-dy').value = String(c.delta[1]);
    $('ae-dz').value = String(c.delta[2]);
  }
  const num = (v, fallback) => (v === undefined || v === null || Number.isNaN(Number(v))
    ? fallback : Number(v));
  if (c.kind === 'scale') {
    $('ae-from').value = String(num(c.from, 1));
    $('ae-to').value = String(num(c.to, 1.5));
  }
  if (c.kind === 'turn') $('ae-angle').value = String(Number(c.angle) || 90);
  if (c.kind === 'spin') $('ae-turns').value = String(Number(c.turns ?? 1));
  if (c.kind === 'roll') {
    $('ae-distance').value = String(Number(c.distance ?? 250));
    $('ae-radius').value = String(Number(c.radius ?? 10));
  }
  if ($('ae-pivot')) {
    $('ae-pivot').value = Array.isArray(c.pivot) ? c.pivot.join(', ') : '';
  }
  if (c.kind === 'morph') {
    $('ae-param').value = c.param || '';
    $('ae-from').value = String(num(c.from, 0));
    $('ae-to').value = String(num(c.to, 1));
    $('ae-samples').value = String(Number(c.samples) || 12);
  }
  if ($('ae-scene')) $('ae-scene').value = c.scene || '';
  $('ae-loop').checked = c.loop !== false;
  updateEditorVisibility();
}

function updateEditorVisibility() {
  const kind = $('ae-kind')?.value || 'spin';
  const show = (id, on) => { if ($(id)) $(id).style.display = on ? '' : 'none'; };
  show('ae-hold-wrap', kind === 'assembly');
  show('ae-amount-wrap', kind === 'explode');
  show('ae-dx-wrap', kind === 'move');
  show('ae-dy-wrap', kind === 'move');
  show('ae-dz-wrap', kind === 'move');
  show('ae-from-wrap', kind === 'scale' || kind === 'morph');
  show('ae-to-wrap', kind === 'scale' || kind === 'morph');
  show('ae-angle-wrap', kind === 'turn');
  show('ae-pivot-wrap', ['turn', 'spin', 'roll'].includes(kind));
  show('ae-turns-wrap', kind === 'spin');
  show('ae-distance-wrap', kind === 'roll');
  show('ae-radius-wrap', kind === 'roll');
  show('ae-height-wrap', kind === 'jump' || kind === 'fall');
  show('ae-elastic-wrap', kind === 'jump' || kind === 'fall');
  show('ae-rpm-wrap', kind === 'fan');
  show('ae-scene-wrap', true);
  show('ae-param-wrap', kind === 'morph');
  show('ae-samples-wrap', kind === 'morph');
  show('ae-object-wrap', ['move', 'scale', 'turn', 'spin', 'explode', 'roll', 'formation',
    'jump', 'fall', 'fan'].includes(kind));
  if ($('ae-seconds')) $('ae-seconds').disabled = kind === 'assembly' || kind === 'wait';
  if ($('ae-loop')) $('ae-loop').parentElement.style.display = ['spin', 'formation'].includes(kind) ? '' : 'none';
}

function animLineFromEditor() {
  const kind = $('ae-kind').value;
  const axis = $('ae-axis').value || 'z';
  const seconds = Number($('ae-seconds').value) || 4;
  const start = $('ae-start').value.trim();
  const track = Math.max(1, Math.min(8, Number($('ae-track').value) || 1));
  const object = $('ae-object')?.value || '';
  const hold = Number($('ae-hold').value) || 0.8;
  const loop = $('ae-loop').checked;
  const parts = [`animate kind=${kind}`];
  if (['spin', 'turn', 'formation', 'explode'].includes(kind)) parts.push(`axis=${axis}`);
  if (kind === 'assembly') parts.push(`hold=${hold}`);
  else parts.push(`seconds=${seconds}`);
  if (kind === 'explode') parts.push(`amount=${Number($('ae-amount').value) || 30}`);
  if (kind === 'move') {
    parts.push(`dx=${Number($('ae-dx').value) || 0}`);
    parts.push(`dy=${Number($('ae-dy').value) || 0}`);
    parts.push(`dz=${Number($('ae-dz').value) || 0}`);
  }
  if (kind === 'scale') {
    parts.push(`from=${Number($('ae-from').value) || 1}`);
    parts.push(`to=${Number($('ae-to').value) || 1.5}`);
  }
  if (kind === 'morph') {
    const param = $('ae-param').value;
    if (!param) { toast('Для изменения формы нужен параметр сценария (R = 40…)', 'bad'); return null; }
    parts.push(`param=${param}`);
    parts.push(`from=${Number($('ae-from').value) || 0}`);
    parts.push(`to=${Number($('ae-to').value) || 1}`);
    parts.push(`samples=${Math.max(2, Number($('ae-samples').value) || 12)}`);
  }
  if (kind === 'turn') parts.push(`angle=${Number($('ae-angle').value) || 90}`);
  if (kind === 'spin') parts.push(`turns=${Number($('ae-turns')?.value) || 1}`);
  if (kind === 'roll') {
    parts.push(`distance=${Number($('ae-distance')?.value) || 250}`);
    parts.push(`radius=${Number($('ae-radius')?.value) || 10}`);
  }
  if (kind === 'jump' || kind === 'fall') {
    parts.push(`height=${Number($('ae-height')?.value) || 80}`);
    if ($('ae-elastic') && !$('ae-elastic').checked) parts.push('elastic=нет');
  }
  if (kind === 'fan') parts.push(`rpm=${Number($('ae-rpm')?.value) || 900}`);
  const sceneName = ($('ae-scene')?.value || '').trim();
  if (sceneName) parts.push(`scene=${sceneName.replace(/\s+/g, '_')}`);
  if (['turn', 'spin', 'roll'].includes(kind)) {
    const piv = ($('ae-pivot')?.value || '').split(/[,\s]+/).filter(Boolean).map(Number);
    if (piv.length === 3 && piv.every((v) => Number.isFinite(v))) {
      parts.push(`pivot=[${piv.join(', ')}]`);
    }
  }
  if (object) parts.push(`object=${object}`);
  if (track !== 1) parts.push(`track=${track}`);
  if (start !== '' && Number(start) > 0) parts.push(`start=${start}`);
  if (!loop && ['spin', 'formation'].includes(kind)) parts.push('loop=нет');
  return parts.join(' ');
}

function addAnimationClip() {
  const line = animLineFromEditor();
  if (!line) return;
  const script = currentScript().replace(/\s+$/, '');
  setScript((script ? script + '\n' : '') + line, { label: 'анимация: ' + line });
  toast('Клип добавлен: ' + line);
}

function renderAnimKeys() {
  const box = $('anim-keys');
  if (!box) return;
  const keys = animKeys();
  box.innerHTML = '';
  if (!keys.length) {
    box.innerHTML = '<span class="anim-empty">ключей нет — добавьте их ниже</span>';
    return;
  }
  keys.forEach((k) => {
    const row = document.createElement('div');
    row.className = 'anim-clip-row';
    const bits = [`${k.object} @ ${(Number(k.t) || 0).toFixed(2)} с`];
    if (k.pos) bits.push(`Δ(${k.pos.map((v) => Number(v).toFixed(0)).join(', ')})`);
    if (k.rot) bits.push(`∠(${k.rot.map((v) => Number(v).toFixed(0)).join(', ')})`);
    if (k.scale !== undefined && k.scale !== null) bits.push(`×${Number(k.scale)}`);
    row.innerHTML = `<span class="anim-clip-name">${escapeHtml(bits.join(' · '))}</span>`
      + `<code>${escapeHtml(k.text || '')}</code>`;
    const del = document.createElement('button');
    del.className = 'mini';
    del.textContent = '✕';
    del.title = 'Удалить ключ из сценария';
    del.onclick = () => removeScriptLine(k.line,
      /^\s*(keyframe|key|ключ|кадр|ключ_кадр|keys)\b/i, 'ключ');
    row.appendChild(del);
    box.appendChild(row);
  });
}

function parseVecField(value) {
  return String(value || '').split(/[,;\s]+/).map((v) => Number(v)).filter((v) => !Number.isNaN(v));
}

function addKeyframe() {
  const object = $('ak-object')?.value;
  if (!object) { toast('Выберите объект для ключа', 'bad'); return; }
  const at = Math.max(0, Number($('ak-at').value) || 0);
  const pos = parseVecField($('ak-pos').value);
  const rot = parseVecField($('ak-rot').value);
  const scaleRaw = $('ak-scale').value.trim();
  if (pos.length && pos.length !== 3) { toast('Смещение: три числа через запятую', 'bad'); return; }
  if (rot.length && rot.length !== 3) { toast('Поворот: три угла через запятую', 'bad'); return; }
  const parts = [`keyframe ${object}`, `at=${at}`];
  if (pos.length === 3 && pos.some((v) => v !== 0)) parts.push(`pos=[${pos.join(', ')}]`);
  if (rot.length === 3 && rot.some((v) => v !== 0)) parts.push(`rot=[${rot.join(', ')}]`);
  if (scaleRaw !== '') parts.push(`scale=${Number(scaleRaw)}`);
  if (parts.length === 2) { toast('Ключ пустой: задайте смещение, поворот или масштаб', 'bad'); return; }
  const line = parts.join(' ');
  const script = currentScript().replace(/\s+$/, '');
  setScript((script ? script + '\n' : '') + line, { label: 'ключ: ' + line });
  toast('Ключ добавлен: ' + line);
}

/** Удаление строки сценария по номеру (клип или ключ). */
function removeScriptLine(line, pattern, what = 'строку') {
  if (!line) { toast('Эта строка добавлена не командой — уберите её в тексте сценария', 'bad'); return; }
  const lines = currentScript().split('\n');
  const idx = line - 1;
  if (idx < 0 || idx >= lines.length) { toast('Строка не найдена', 'bad'); return; }
  if (!pattern.test(lines[idx])) {
    toast('Строка изменилась — удалите её в тексте сценария', 'bad');
    return;
  }
  lines.splice(idx, 1);
  setScript(lines.join('\n'), { label: `удаление: ${what}` });
  toast('Удалено из сценария');
}

/** Обновляет списки объектов и параметров в редакторе анимации. */
function refreshAnimSelectors() {
  const objs = (state.payload?.objects || []).map((o) => o.name)
    .concat(Object.keys(state.payload?.groups || {}));
  ['ae-object', 'ak-object'].forEach((id) => {
    const sel = $(id);
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = (id === 'ae-object' ? '<option value="">вся модель</option>' : '')
      + objs.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
    if (objs.includes(cur)) sel.value = cur;
    else if (id === 'ak-object' && objs.length) sel.value = objs[0];
  });
  const params = Object.keys(state.payload?.params || {});
  const ps = $('ae-param');
  if (ps) {
    const cur = ps.value;
    ps.innerHTML = '<option value="">—</option>'
      + params.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
    if (params.includes(cur)) ps.value = cur;
  }
}

/* --- последовательность: сборка и морфинг внутри клипов --------------- */
function updateSequence(t) {
  const a = state.anim;
  const clips = animClips();
  const active = clips.filter((c) => t >= (Number(c.start) || 0) - 1e-6
    && t < (Number(c.start) || 0) + (Number(c.length) || 0) + 1e-6);
  const assembly = active.find((c) => c.kind === 'assembly');
  const morph = active.find((c) => c.kind === 'morph');
  if (assembly && animFrames().length) {
    const hold = Math.max(0.1, Number(assembly.hold) || 0.8);
    const idx = Math.max(0, Math.min(animFrames().length - 1,
      Math.floor((t - (Number(assembly.start) || 0)) / hold)));
    if (a.seqKey !== 'a' + idx) {
      a.seqKey = 'a' + idx;
      a.frameIndex = idx;
      showFrame(idx);
      prefetchFrame(idx + 1);
    }
    return;
  }
  if (morph) {
    const length = Math.max(0.001, Number(morph.length) || 1);
    const p = Math.max(0, Math.min(1, (t - (Number(morph.start) || 0)) / length));
    const n = Math.max(2, Number(morph.samples) || 12);
    const idx = Math.min(n - 1, Math.round(p * (n - 1)));
    const value = Number(morph.from) + (Number(morph.to) - Number(morph.from)) * (idx / (n - 1));
    if (a.seqKey !== 'm' + idx) {
      a.seqKey = 'm' + idx;
      showMorph(morph, value);
      prefetchMorph(morph, idx + 1);
      // видно, что именно меняется: подсвечиваем деталь и подписываем её
      const target = morph.object && !state.hidden.has(morph.object) ? morph.object : '';
      if (target) {
        state.viewer?.setHighlight(target);
        if ($('anim-focus')) $('anim-focus').textContent = 'меняется: ' + target;
      }
    }
    return;
  }
  if (a.seqKey) {
    a.seqKey = null;
    state.viewer?.showFinalModel();
    if (state.selected?.name && !state.hidden.has(state.selected.name)) {
      state.viewer?.setHighlight(state.selected.name);
    }
    if ($('anim-focus')) $('anim-focus').textContent = '';
  }
}

function showMorph(clip, value) {
  const target = clip.object || state.payload?.analysis?.metrics?.main || '';
  if (target && !state.hidden.has(target)) {
    state.viewer?.setHighlight(target);
    if ($('anim-focus')) $('anim-focus').textContent = 'меняется: ' + target;
  }
  const script = currentScript();
  const pending = 'm' + value.toFixed(3) + clip.param;
  state.anim.morphPending = pending;
  api('/api/morph', { script, param: clip.param, value })
    .then((res) => {
      if (!res.glb || state.anim.morphPending !== pending) return;
      state.viewer?.loadFrame(res.key, '/api/frame.glb?key=' + encodeURIComponent(res.key)
        + '&token=' + encodeURIComponent(TOKEN)).catch(() => {});
    })
    .catch(() => {});
}

function morphValueAt(clip, index) {
  const n = Math.max(2, Number(clip.samples) || 12);
  const i = Math.max(0, Math.min(n - 1, index));
  return Number(clip.from) + (Number(clip.to) - Number(clip.from)) * (i / (n - 1));
}

function prefetchMorph(clip, index) {
  const n = Math.max(2, Number(clip.samples) || 12);
  if (index >= n) return;
  const value = morphValueAt(clip, index);
  const script = currentScript();
  const key = `pf_m_${clip.param}_${value}`;
  if (state.anim.cache.has(key)) return;
  state.anim.cache.set(key, true);
  api('/api/morph', { script, param: clip.param, value })
    .then((res) => {
      if (res.glb) state.viewer?.preloadFrame(res.key,
        '/api/frame.glb?key=' + encodeURIComponent(res.key) + '&token=' + encodeURIComponent(TOKEN));
    })
    .catch(() => { state.anim.cache.delete(key); });
}

function prefetchFrame(index) {
  const frames = animFrames();
  const frame = frames[index];
  if (!frame) return;
  const key = `pf_${state.payload?.script_hash || ''}_${frame.n}`;
  if (state.anim.cache.has(key)) return;
  state.anim.cache.set(key, true);
  api('/api/frame', { script: currentScript(), upto: frame.n })
    .then((res) => {
      if (res.glb) state.viewer?.preloadFrame(res.key,
        '/api/frame.glb?key=' + encodeURIComponent(res.key) + '&token=' + encodeURIComponent(TOKEN));
    })
    .catch(() => { state.anim.cache.delete(key); });
}

/* --- транспорт и прокрутка ------------------------------------------ */
function pauseAnim() {
  const a = state.anim;
  a.playing = false;
  if (state.viewer) state.viewer.playAnimation(false);
  syncAnimUI();
}

function seekTime(t) {
  const a = state.anim;
  a.time = Math.max(0, Math.min(Number(t) || 0, a.duration || 0));
  state.viewer?.setTime(a.time);
  if (a.mode === 'frames') highlightFromTime(a.time);
  syncAnimUI();
}

function stepByFrames(dir) {
  const a = state.anim;
  if (a.mode === 'frames') {
    pauseAnim();
    seekFrame(a.frameIndex + dir);
    return;
  }
  const fps = animFps();
  pauseAnim();
  seekTime((a.time || 0) + dir / fps);
}

function seekFrame(index) {
  const a = state.anim;
  const frames = animFrames();
  if (!frames.length) return;
  a.frameIndex = Math.max(0, Math.min(index, frames.length - 1));
  syncAnimUI();
  highlightScriptLine(frames[a.frameIndex].line);
  showFrame(a.frameIndex);
}

async function showFrame(index) {
  const a = state.anim;
  const frame = animFrames()[index];
  if (!frame || !state.viewer) return;
  const script = currentScript();
  const key = `${state.payload?.script_hash || 'x'}_${frame.n}`;
  const cached = a.cache.get(key);
  if (cached) {
    await state.viewer.loadFrame(cached.key, cached.url).catch(() => {});
    focusFrameObject(frame);
    return;
  }
  if (a.busy) { a.next = index; return; }
  a.busy = true;
  try {
    const res = await api('/api/frame', { script, upto: frame.n });
    if (!res.glb) { toast('Этот шаг не даёт геометрии — выберите другой', 'bad'); return; }
    const url = '/api/frame.glb?key=' + encodeURIComponent(res.key)
      + '&token=' + encodeURIComponent(TOKEN);
    a.cache.set(key, { key: res.key, url });
    while (a.cache.size > 24) a.cache.delete(a.cache.keys().next().value);
    await state.viewer.loadFrame(res.key, url);
    focusFrameObject(frame);
  } catch (e) {
    toast('Не удалось показать кадр: ' + (e.message || e), 'bad');
  } finally {
    a.busy = false;
    if (a.next !== undefined && a.next !== index) {
      const next = a.next;
      a.next = undefined;
      showFrame(next);
    }
  }
}

/** Во время сборки подсвечиваем деталь, которая появилась на этом шаге. */
function focusFrameObject(frame) {
  const objects = new Set((state.payload?.objects || []).map((o) => o.name));
  const added = (frame?.added || []).filter((n) => !state.hidden.has(n));
  const changed = frame?.target && objects.has(frame.target)
    && !state.hidden.has(frame.target) ? frame.target : '';
  const name = added[0] || changed;
  const label = $('anim-focus');
  if (name) {
    state.viewer?.setHighlight(name);
    if (label) label.textContent = (added.length ? 'появился: ' : 'меняется: ') + name;
  } else if (state.selected?.name && !state.hidden.has(state.selected.name)) {
    state.viewer?.setHighlight(state.selected.name);
    if (label) label.textContent = '';
  } else {
    if (label) label.textContent = '';
  }
}

function setAnimMode(mode) {
  const a = state.anim;
  a.mode = mode;
  a.seqKey = null;
  a.playing = false;
  a.time = 0;
  a.frameTimer = 0;
  state.viewer?.playAnimation(false);
  if (mode === 'frames') {
    if (state.viewer) state.viewer.manualAdvance = true;
    a.frameIndex = 0;
    if (animFrames().length) showFrame(0);
  } else {
    if (state.viewer) { state.viewer.manualAdvance = false; state.viewer.showFinalModel(); state.viewer.setTime(0); }
  }
  updateAnimState();
}

function togglePlayAnim() {
  const a = state.anim;
  if (!animHasContent()) {
    if (!startPreviewAnimation()) explainNoAnimation();
    return;
  }
  a.playing = !a.playing;
  if (a.mode === 'frames') {
    if (state.viewer) { state.viewer.manualAdvance = true; state.viewer.playing = a.playing; }
    a.frameTimer = 0;
    if (a.playing) seekFrame(a.frameIndex);
  } else if (state.viewer) {
    state.viewer.manualAdvance = false;
    state.viewer.playAnimation(a.playing);
    a.playing = state.viewer.playing;
  }
  syncAnimUI();
}

/* ------------------------------------------------------------------ */
/*  0.15: конец анимации — повтор или остановка                       */
/* ------------------------------------------------------------------ */
function applyLoopMode() {
  const loop = state.viewer?.setLoopMode(state.loopMode);
  const el = $('anim-loop');
  if (el) {
    el.value = state.loopMode;
    el.classList.toggle('loop-off', state.loopMode === 'off');
  }
  return loop;
}

$('anim-loop')?.addEventListener('change', (e) => {
  state.loopMode = e.target.value;
  try { localStorage.setItem('forma_loop_mode', state.loopMode); } catch (err) { /* ок */ }
  const loop = applyLoopMode();
  const msg = state.loopMode === 'off'
    ? 'Анимация остановится на последнем кадре'
    : state.loopMode === 'on'
      ? 'Анимация будет повторяться'
      : (loop ? 'Повтор: как в сценарии (включён)' : 'Повтор: как в сценарии (выключен)');
  toast(msg);
});

/** Список заготовленных сцен анимации: у шкафа — дверь, ящик, колёса… */
function renderSceneSelect() {
  const sel = $('anim-scene');
  if (!sel) return;
  const scenes = state.viewer?.scenes?.() || [];
  sel.innerHTML = '';
  if (scenes.length < 2) {
    sel.hidden = true;
    return;
  }
  sel.hidden = false;
  const all = document.createElement('option');
  all.value = '';
  all.textContent = 'все сцены';
  sel.appendChild(all);
  scenes.forEach((name) => {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  });
  sel.value = state.viewer?.currentScene?.() || '';
}

$('anim-scene')?.addEventListener('change', (e) => {
  const name = state.viewer?.setScene(e.target.value) || '';
  state.anim.time = 0;
  renderAnimTracks();
  renderAnimKeys();
  updateAnimState();
  applyLoopMode();
  const scenes = state.viewer?.scenes?.() || [];
  const total = name ? (animPlan()?.scene_durations?.[name] || state.viewer?.duration || 0) : 0;
  toast(name ? `Сцена «${name}» · ${Number(total).toFixed(1)} с` : 'Показаны все сцены сразу');
  state.viewer?.playAnimation(true);
  state.anim.playing = state.viewer?.playing || false;
  syncAnimUI();
});

/** Скрыть/показать объект так же, как глаз в списке. */
function toggleObjectHidden(name) {
  if (!name) return;
  const willHide = !state.hidden.has(name);
  if (willHide) { state.hidden.add(name); state.userHidden.add(name); }
  else { state.hidden.delete(name); state.userHidden.delete(name); }
  state.viewer?.setObjectVisible(name, !willHide);
  if (state.payload) renderObjects(state.payload);
  toast(willHide ? `Скрыто: ${name}` : `Показано: ${name}`);
}

/** Контекстное меню по правой кнопке на предмете. */
function openContextMenu(x, y, name) {
  const menu = $('ctx-menu');
  if (!menu) return;
  if (!name) { menu.hidden = true; return; }
  // Правая кнопка ничего не выделяет: в меню только действия над предметом
  // под курсором, а выделение — левой кнопкой (или пунктом «выделить»).
  const isHidden = state.hidden.has(name);
  const poly = Boolean(state.viewer?.objectPolygons(name));
  const spacer = () => { const d = document.createElement('div'); d.className = 'ctx-sep'; return d; };
  const item = (label, fn, cls = '') => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    if (cls) b.className = cls;
    b.addEventListener('click', () => {
      menu.hidden = true;
      fn();
    });
    return b;
  };
  menu.innerHTML = '';
  const title = document.createElement('div');
  title.className = 'ctx-title';
  title.textContent = name;
  if (state.selected?.name !== name) {
    title.textContent = name + '  (не выделен)';
  }
  menu.appendChild(title);
  menu.appendChild(item('выделить предмет', () => {
    selectObject(name);
    toast(`Выделено: ${name}`);
  }));
  menu.appendChild(item(isHidden ? 'показать предмет' : 'скрыть предмет',
    () => toggleObjectHidden(name)));
  menu.appendChild(item(poly ? 'вернуть сплошной вид' : 'показать полигонами', () => {
    const on = !state.viewer?.objectPolygons(name);
    const n = state.viewer?.setObjectPolygons(name, on) || 0;
    toast(on ? `Полигонами: ${name} (${n} меш.)` : `Сплошной вид: ${name}`);
  }));
  menu.appendChild(item('приблизить и вращать вокруг', () => {
    selectObject(name);
    state.orbitSelection = true;
    $('btn-orbit-sel')?.classList.add('active');
    state.viewer?.setOrbitTarget(name);
    state.viewer?.focusObject(name);
    setTimeout(() => state.viewer?.refreshOccluders?.(), 420);
  }));
  menu.appendChild(item('выделить кубы этого предмета', () => {
    const sel = state.viewer?.selectSpaceForObject(name);
    if (!sel) { toast('Не удалось определить секторы предмета', 'bad'); return; }
    if (state.selected?.name) state.hidden.delete(name);
    updateSpaceUI(sel);
    toast(`Секторы «${name}»: ${sel.cells} шт. · ${sel.indices}`);
  }));
  menu.appendChild(spacer());
  menu.appendChild(item('удалить предмет', () => deleteObject(name), 'danger'));
  menu.style.left = Math.max(8, Math.min(x, window.innerWidth - 250)) + 'px';
  menu.style.top = Math.max(8, Math.min(y, window.innerHeight - 240)) + 'px';
  menu.hidden = false;
}

document.addEventListener('pointerdown', (e) => {
  const menu = $('ctx-menu');
  if (menu && !menu.hidden && !menu.contains(e.target)) menu.hidden = true;
});
window.addEventListener('blur', () => { const m = $('ctx-menu'); if (m) m.hidden = true; });

function initViewer() {
  try {
    state.viewer = new Viewer($('viewer'));
    state.viewer.onSelect = (name) => selectObject(name);
    state.viewer.onSelection = (stats) => showSelection(stats);
    state.viewer.onTextureError = () => toast('Не удалось загрузить текстуру: проверьте соединение с окном приложения', 'bad');
    let lastClock = 0;
    let lastLine = 0;
    state.viewer.onTime = (t) => {
      if (state.anim.mode !== 'clips') return;
      state.anim.time = t;
      updateSequence(t);
      const now = performance.now();
      if (now - lastClock > 60) {
        lastClock = now;
        syncAnimClock();
        // Подсветка строки нужна только сборке по шагам. Во время обычной
        // анимации сценарий не дёргается и не подкручивается.
        if (state.anim.mode === 'frames' && now - lastLine > 90) {
          lastLine = now;
          highlightFromTime(t, { scroll: false });
        }
      }
    };
    state.viewer.onFocus = (name, names) => {
      if (state.anim.mode !== 'clips') return;
      // В обычной анимации ничего не выделяем: подсветка и слежение за
      // сценарием — только у сборки по шагам.
      const all = (names && names.length ? names : (name ? [name] : []))
        .filter((n) => !state.hidden.has(n));
      if ($('anim-focus') && all.length) $('anim-focus').textContent = 'движется: ' + all.join(', ');
    };
    state.viewer.onEnd = () => { state.anim.playing = false; syncAnimUI(); };
    state.viewer.onSpace = (sel) => updateSpaceUI(sel);
    state.viewer.onSpaceCell = (mm, asked) => {
      // ползунок остаётся там, куда его поставил пользователь, а в подписи
      // честно пишем, какой шаг получился на самом деле
      const real = Math.round(mm * 10) / 10;
      const want = Math.round((Number(asked) || real) * 10) / 10;
      const num = (v) => String(v).replace('.', ',');
      if ($('space-size-val')) {
        $('space-size-val').textContent = Math.abs(real - want) < 0.05
          ? `${num(real)} мм`
          : `${num(want)} мм → клетки по ${num(real)} мм (мельче не влезает)`;
      }
    };
    state.viewer.onOccluders = (names) => {
      state.occludersNow = names || [];
    };
    state.viewer.onContextMenu = (event, hit) => {
      const name = hit?.name || state.selected?.name || '';
      openContextMenu(event.clientX, event.clientY, name);
    };
    state.viewer.onPaintNeedsTarget = () => {
      toast('Сначала выделите предмет: кисть красит только выбранное', 'bad');
    };
    state.viewer.onPaintStroke = (stroke) => addStroke(stroke);
    state.viewer.onPaint = (info) => {
      state.paintCount = (state.paintCount || 0) + 1;
      if (state.paintCount === 1 || state.paintCount % 12 === 0) {
        toast(`Покрашено граней: ${state.paintCount} · ${info.name}`);
      }
    };
    applyLoopMode();
    state.viewer.onFrame = (dt) => {
      const a = state.anim;
      if (a.mode !== 'frames' || !a.playing) return;
      a.frameTimer += dt * (state.viewer.speed || 1);
      const hold = Math.max(0.15, Number(animPlan()?.assembly?.hold) || 0.8);
      if (a.frameTimer < hold) return;
      a.frameTimer = 0;
      const last = animFrames().length - 1;
      if (a.frameIndex >= last) {
        if (state.viewer.loop) seekFrame(0);
        else { a.playing = false; state.viewer.playing = false; syncAnimUI(); }
      } else {
        seekFrame(a.frameIndex + 1);
      }
    };
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
$('btn-focus-sel')?.addEventListener('click', () => {
  const name = state.selected?.name;
  if (!name) { toast('Сначала выделите предмет в списке или кликом', 'bad'); return; }
  if (state.viewer?.focusObject(name)) {
    toast(`Камера наведена: ${name}`);
    setTimeout(() => state.viewer?.refreshOccluders?.(), 420);
  }
});
$('btn-orbit-sel')?.addEventListener('click', (e) => {
  state.orbitSelection = !state.orbitSelection;
  e.currentTarget.classList.toggle('active', state.orbitSelection);
  state.viewer?.setOrbitTarget(state.orbitSelection ? (state.selected?.name || '') : '');
  toast(state.orbitSelection
    ? 'Вращение и приближение — вокруг выделенного предмета'
    : 'Вращение — вокруг центра сцены');
});
$('btn-occl')?.classList.toggle('active', Boolean(state.occluders));
$('btn-occl')?.addEventListener('click', (e) => {
  state.occluders = !state.occluders;
  e.currentTarget.classList.toggle('active', state.occluders);
  state.viewer?.setOccluders(state.occluders);
  toast(state.occluders
    ? 'Предметы перед выделенным показываются прозрачным каркасом'
    : 'Заслоняющие предметы снова сплошные');
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
  updateStatsOverlay();
}

function updateStatsOverlay() {
  const box = $('viewer-stats');
  if (!box) return;
  const v = state.viewer;
  if (!v || !state.payload?.ok) { box.hidden = true; return; }
  const st = v.getStats();
  const sel = state.selected;
  const dims = sel?.size || state.payload?.analysis?.metrics?.size;
  box.hidden = false;
  // пока предмет выделен, счётчики показывают его, а не всю сцену:
  // иначе таймер раз в 0,7 с затирал бы статистику выбора
  box.innerHTML = sel
    ? `<b>${escapeHtml(sel.name)}</b><br>
      <b>${fmtInt(sel.tris)}</b> треугольников · <b>${fmtInt(sel.verts || 0)}</b> верш.<br>
      ${fmt(sel.volume_cm3)} см³ · ${fmt(sel.mass_g, 0)} г<br>
      ${dims ? `<b>${fmt(dims[0])}×${fmt(dims[1])}×${fmt(dims[2])}</b> мм<br>` : ''}
      <span class="dim">вся сцена: ${fmtInt(st.tris)} трис</span>
      ${st.fps ? `<br><b>${st.fps}</b> кадр/с` : ''}`
    : `<b>${fmtInt(st.tris)}</b> треугольников<br>
      <b>${fmtInt(st.verts)}</b> вершин · <b>${st.meshes}</b> объектов<br>
      ${dims ? `<b>${fmt(dims[0])}×${fmt(dims[1])}×${fmt(dims[2])}</b> мм<br>` : ''}
      ${st.fps ? `<b>${st.fps}</b> кадр/с` : ''}`;
  const badge = $('viewer-badge');
  if (badge) {
    badge.textContent = sel
      ? `${sel.name} · ${fmtInt(sel.tris)} трис`
      : `${fmtInt(st.tris)} треугольников`;
  }
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
$('anim-play')?.addEventListener('click', () => togglePlayAnim());
$('anim-restart')?.addEventListener('click', () => {
  const a = state.anim;
  a.playing = false;
  if (a.mode === 'frames') { seekFrame(0); return; }
  seekTime(0);
});
$('anim-first')?.addEventListener('click', () => {
  pauseAnim();
  if (state.anim.mode === 'frames') seekFrame(0); else seekTime(0);
});
$('anim-back')?.addEventListener('click', () => stepByFrames(-1));
$('anim-fwd')?.addEventListener('click', () => stepByFrames(1));
$('anim-speed')?.addEventListener('input', (e) => {
  const v = Number(e.target.value);
  $('anim-speed-val').textContent = v.toFixed(1) + '×';
  state.viewer?.setSpeed(v);
});
$('anim-scrub')?.addEventListener('input', (e) => {
  const a = state.anim;
  const value = Number(e.target.value);   // читаем до паузы: она перерисовывает ползунок
  pauseAnim();
  if (a.mode === 'frames') {
    seekFrame(value);
  } else {
    const total = a.duration || animPlan()?.duration || 0;
    seekTime((value / 1000) * total);
  }
});
$('anim-mode')?.addEventListener('change', (e) => {
  state.anim.userMode = true;
  setAnimMode(e.target.value);
});
$('anim-editor-toggle')?.addEventListener('click', () => {
  const box = $('anim-editor');
  box.hidden = !box.hidden;
  updateEditorVisibility();
});
$('ae-kind')?.addEventListener('change', updateEditorVisibility);
$('ae-add')?.addEventListener('click', addAnimationClip);
$('ak-add')?.addEventListener('click', addKeyframe);
refreshAnimSelectors();

document.addEventListener('keydown', (e) => {
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')) return;
  if ((e.key === 'Delete' || e.key === 'Backspace') && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (state.selected?.name) {
      e.preventDefault();
      const name = state.selected.name;
      deleteObject(name);
      toast(`Удалено: ${name}`);
      return;
    }
    const space = state.space || state.viewer?.spaceSelection?.();
    if (state.spaceMode && space?.cells) {
      e.preventDefault();
      state.viewer?.clearSpaceSelection?.();
      updateSpaceUI(null);
      toast(`Удалено секторов: ${space.cells}`);
      return;
    }
  }
  if (e.code === 'Space' && !e.ctrlKey && !e.metaKey) {
    if ($('anim-panel') && !$('anim-panel').hidden) { e.preventDefault(); togglePlayAnim(); }
  } else if (e.key === 'ArrowLeft' && e.altKey) {
    e.preventDefault(); stepByFrames(-1);
  } else if (e.key === 'ArrowRight' && e.altKey) {
    e.preventDefault(); stepByFrames(1);
  }
});

$('btn-wire')?.addEventListener('dblclick', () => {
  $('opt-poly').checked = !$('opt-poly').checked;
  state.viewer?.setPolygons($('opt-poly').checked);
});

/* ------------------------------------------------------------------ */
/*  Кисть по граням                                                   */
/* ------------------------------------------------------------------ */
function paintTargetName() {
  return state.selected?.name || '';
}

function syncPaintMode() {
  const on = Boolean(state.viewer?.paintMode);
  const erase = Boolean(state.viewer?.eraseMode);
  $('paint-toggle')?.classList.toggle('active', on && !erase);
  $('paint-erase')?.classList.toggle('active', on && erase);
  const count = brushLines(paintTargetName()).length;
  if ($('brush-count')) $('brush-count').textContent = String(count);
}

/** Строки кисти/ластика этого предмета в сценарии. */
function brushLines(name) {
  if (!name) return [];
  const re = new RegExp(`^(кисть|brush|ластик|eraser)\\s+${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`);
  return currentScript().split('\n').filter((line) => re.test(line.trim()));
}

/** Одна команда на мазок: точка или цепочка точек. */
function strokeCommand(stroke) {
  const op = stroke.erase ? 'ластик' : 'кисть';
  const head = stroke.erase ? `${op} ${stroke.name} radius=${stroke.radius}`
    : `${op} ${stroke.name} ${stroke.color} radius=${stroke.radius}`;
  const pts = stroke.points.map((p) => `[${p[0]}, ${p[1]}, ${p[2]}]`);
  return pts.length > 1 ? `${head} path=[${pts.join(', ')}]` : `${head} point=${pts[0]}`;
}

/** Дописать мазок в сценарий (и пересобрать модель). */
function addStroke(stroke) {
  if (!stroke || !stroke.points.length) return;
  const script = currentScript().replace(/\s+$/, '');
  const line = strokeCommand(stroke);
  setScript(`${script}\n${line}\n`, { label: stroke.erase ? 'ластик' : 'кисть' });
  syncPaintMode();
  toast(stroke.erase ? 'Стёрто нарисованное' : `Мазок: ${stroke.points.length} точ.`);
}

function toggleBrush(erase) {
  const name = paintTargetName();
  if (!name) {
    toast('Сначала выделите предмет: кисть красит только выбранное', 'bad');
    return;
  }
  if (state.hidden.has(name)) {
    toast('Предмет скрыт — покажите его, чтобы рисовать', 'bad');
    return;
  }
  const v = state.viewer;
  const want = !(v?.paintMode) || Boolean(v?.eraseMode) !== erase;
  if (!want) {
    v?.setPaintMode(false, null, name, false);
    syncPaintMode();
    toast('Рисование выключено — обычное вращение и выделение');
    return;
  }
  v?.setPaintMode(true, $('paint-color')?.value || '#ff8a3d', name, erase);
  if (v) v.paintRadiusPx = Number($('paint-size')?.value) || 10;
  syncPaintMode();
  state.paintCount = 0;
  toast(erase
    ? 'Ластик: стирает нарисованное кистью, материал не трогает'
    : 'Кисть включена: зажмите кнопку и ведите по предмету');
  return undefined;
}

$('paint-toggle')?.addEventListener('click', () => toggleBrush(false));
$('paint-erase')?.addEventListener('click', () => toggleBrush(true));
$('paint-color')?.addEventListener('input', (e) => {
  if (state.viewer?.paintMode && !state.viewer?.eraseMode) {
    state.viewer.setPaintMode(true, e.target.value, paintTargetName(), false);
  }
});
$('paint-size')?.addEventListener('input', (e) => {
  if (state.viewer) state.viewer.paintRadiusPx = Number(e.target.value) || 10;
});
$('paint-clear')?.addEventListener('click', () => {
  const name = paintTargetName();
  if (!name) { toast('Сначала выделите предмет', 'bad'); return; }
  const lines = brushLines(name);
  if (!lines.length) { toast('У этого предмета нет мазков'); return; }
  const keep = currentScript().split('\n').filter((line) => !lines.includes(line));
  setScript(keep.join('\n') + '\n', { label: 'снять роспись' });
  syncPaintMode();
  toast(`Снято мазков: ${lines.length}`);
});
$('brush-undo')?.addEventListener('click', () => {
  const name = paintTargetName();
  if (!name) { toast('Сначала выделите предмет', 'bad'); return; }
  const lines = brushLines(name);
  if (!lines.length) { toast('Мазков нет'); return; }
  const last = lines[lines.length - 1];
  const all = currentScript().split('\n');
  const idx = all.lastIndexOf(last);
  if (idx >= 0) all.splice(idx, 1);
  setScript(all.join('\n') + '\n', { label: 'убрать мазок' });
  syncPaintMode();
  toast('Последний мазок убран');
});

/* ------------------------------------------------------------------ */
/*  Материал выбранного объекта                                       */
/* ------------------------------------------------------------------ */
function selectObject(name) {
  updateCustomTexVisibility();
  if (!name) {
    state.selected = null;
    state.occludersNow = [];
    document.querySelectorAll('.obj-item').forEach((el) => el.classList.remove('selected'));
    $('material-panel').hidden = true;
    state.viewer?.clearHighlight();
    // без выделения кисть не должна срабатывать: выключаем её вместе с выбором
    state.viewer?.setPaintMode(false, null, '', false);
    syncPaintMode();
    if (state.orbitSelection) state.viewer?.setOrbitTarget('');
    if (state.spaceMode) state.viewer?.rebuildSpace?.();
    renderSceneStats();
    return;
  }
  const obj = (state.payload?.objects || []).find((o) => o.name === name);
  if (!obj) return;
  state.selected = obj;
  document.querySelectorAll('.obj-item').forEach((el) => {
    el.classList.toggle('selected', el.dataset.name === name);
  });
  // Подсветка прямо в окне: выбранный в списке объект видно на модели.
  // Заодно прозрачным каркасом показываются детали, которые его закрывают.
  state.occludersNow = [];
  if (!state.hidden.has(name)) state.viewer?.setHighlight(name);
  if (state.viewer?.paintMode) {
    state.viewer.setPaintMode(true, null, name, state.viewer.eraseMode);
  }
  syncPaintMode();
  if (state.orbitSelection) state.viewer?.setOrbitTarget(name);
  renderObjectStats(obj);
  if (state.spaceMode) state.viewer?.rebuildSpace?.();
  $('material-panel').hidden = false;
  $('mat-name').textContent = obj.name;
  state.material = { color: obj.color || '#c9d1e3', metal: obj.metal || 0,
                     rough: obj.rough ?? 0.5, emissive: obj.emissive || '',
                     glow: obj.emissive_strength ?? 1,
                     transmission: obj.transmission ?? 0 };
  $('mat-color').value = state.material.color;
  $('mat-hex').textContent = state.material.color;
  $('mat-metal').value = state.material.metal;
  $('mat-metal-val').textContent = state.material.metal;
  $('mat-rough').value = state.material.rough;
  $('mat-rough-val').textContent = state.material.rough;
  if ($('mat-emissive')) {
    $('mat-emissive').value = state.material.emissive || '#000000';
    $('mat-emissive-val').textContent = state.material.emissive || 'нет';
    $('mat-glow').value = state.material.glow;
    $('mat-glow-val').textContent = state.material.glow;
    $('mat-trans').value = state.material.transmission;
    $('mat-trans-val').textContent = state.material.transmission;
  }
  const KIND_RU = { wood: 'дерево', marble: 'мрамор', metal: 'металл', fabric: 'ткань',
    leather: 'кожа', checker: 'клетка', noise: 'шум', brick: 'кирпич', ceramic: 'керамика' };
  $('mat-tex').value = !obj.tex ? ''
    : (obj.tex.kind === 'custom' ? 'своя' : (KIND_RU[obj.tex.kind] || ''));
  updateCustomTexVisibility();
  showTexturePreview(!obj.tex ? ''
    : (obj.tex.kind === 'custom' ? 'своя' : (KIND_RU[obj.tex.kind] || '')));
  // открываем вкладку объектов
  const tab = document.querySelector('.tab[data-tab="objects"]');
  if (tab && !tab.classList.contains('active')) tab.click();
}

/** Держим значения в самих объектах сцены: при переключении они не откатятся. */
function rememberMaterial(patch) {
  if (!state.selected) return;
  Object.assign(state.selected, patch);
  const obj = (state.payload?.objects || []).find((o) => o.name === state.selected.name);
  if (obj) Object.assign(obj, patch);
}
$('mat-color')?.addEventListener('input', (e) => {
  state.material.color = e.target.value;
  $('mat-hex').textContent = e.target.value;
  rememberMaterial({ color: e.target.value });
  state.viewer?.applyMaterial(state.selected?.name, { color: e.target.value });
});
$('mat-metal')?.addEventListener('input', (e) => {
  state.material.metal = Number(e.target.value);
  $('mat-metal-val').textContent = e.target.value;
  rememberMaterial({ metal: Number(e.target.value) });
  state.viewer?.applyMaterial(state.selected?.name, { metal: Number(e.target.value) });
});
$('mat-rough')?.addEventListener('input', (e) => {
  state.material.rough = Number(e.target.value);
  $('mat-rough-val').textContent = e.target.value;
  rememberMaterial({ rough: Number(e.target.value) });
  state.viewer?.applyMaterial(state.selected?.name, { rough: Number(e.target.value) });
});
$('mat-emissive')?.addEventListener('input', (e) => {
  const v = e.target.value === '#000000' ? '' : e.target.value;
  state.material.emissive = v;
  $('mat-emissive-val').textContent = v || 'нет';
  rememberMaterial({ emissive: v });
  state.viewer?.applyMaterial(state.selected?.name,
    { emissive: v, emissiveStrength: Number($('mat-glow')?.value || 1) });
});
$('mat-glow')?.addEventListener('input', (e) => {
  state.material.glow = Number(e.target.value);
  $('mat-glow-val').textContent = e.target.value;
  rememberMaterial({ emissive_strength: Number(e.target.value) });
  state.viewer?.applyMaterial(state.selected?.name,
    { emissive: state.material.emissive, emissiveStrength: Number(e.target.value) });
});
$('mat-trans')?.addEventListener('input', (e) => {
  state.material.transmission = Number(e.target.value);
  $('mat-trans-val').textContent = e.target.value;
  rememberMaterial({ transmission: Number(e.target.value) });
  state.viewer?.applyMaterial(state.selected?.name, { transmission: Number(e.target.value) });
});
// по отпусканию ползунка записываем значение в сценарий, чтобы оно жило после пересборки
['mat-color', 'mat-metal', 'mat-rough', 'mat-emissive', 'mat-glow', 'mat-trans'].forEach((id) => {
  $(id)?.addEventListener('change', () => {
    if (!state.selected) return;
    writeMaterialScript({ rebuild: true });
  });
});
$('mat-close')?.addEventListener('click', () => selectObject(''));

function writeMaterialScript({ rebuild = true } = {}) {
  if (!state.selected) return;
  const { color, metal, rough, emissive, glow, transmission } = state.material;
  const tex = $('mat-tex')?.value || '';
  const m = state.selected.name;
  const lines = currentScript().split('\n').filter((l) => {
    const t = l.trim();
    return !(t.startsWith(`color ${m} `) || t.startsWith(`texture ${m} `) || t.startsWith(`материал ${m} `));
  });
  let line = `color ${m} ${color} metal=${metal} rough=${rough}`;
  if (emissive) line += ` emissive=${emissive} emissive_strength=${glow}`;
  if (transmission > 0) line += ` transmission=${transmission}`;
  lines.push(line);
  if (tex === 'своя') lines.push(sandboxCommand(m));
  else if (tex) lines.push(`texture ${m} kind=${tex}`);
  setScript(lines.join('\n').trimEnd());
  if (!rebuild) toast(`Материал «${m}» записан в сценарий`);
}

$('mat-apply')?.addEventListener('click', () => {
  if (!state.selected) return;
  writeMaterialScript({ rebuild: true });
  toast(`Материал «${state.selected.name}» записан в сценарий`);
});

function updateCustomTexVisibility() {
  const block = $('custom-tex');
  if (!block) return;
  block.hidden = ($('mat-tex')?.value || '') !== 'своя';
}

/* ---------------- песочница генеративных текстур ---------------- */
let texPreviewTimer = 0;

function updateSandboxPreview() {
  const img = $('tex-big');
  if (!img) return;
  img.src = textureUrl('своя') + '&_=' + Date.now();
  const cmd = $('tex-command');
  if (cmd) cmd.textContent = sandboxCommand(state.selected?.name || 'объект');
  if ($('tex-scale-val')) $('tex-scale-val').textContent = $('tex-scale').value;
  if ($('tex-relief-val')) $('tex-relief-val').textContent = $('tex-relief').value;
}

function scheduleSandboxPreview() {
  clearTimeout(texPreviewTimer);
  texPreviewTimer = setTimeout(updateSandboxPreview, 180);
}

function openTexSandbox() {
  const modal = $('tex-modal');
  if (!modal) return;
  modal.hidden = false;
  updateSandboxPreview();
}

function closeTexSandbox() {
  const modal = $('tex-modal');
  if (modal) modal.hidden = true;
}

function applySandboxTexture() {
  const name = state.selected?.name;
  if (!name) { toast('Сначала выберите объект в списке справа', 'bad'); return; }
  const cmd = sandboxCommand(name);
  const lines = currentScript().split('\n').filter((l) => !l.trim().startsWith(`texture ${name} `));
  lines.push(cmd);
  $('mat-tex').value = 'своя';
  applyTextureToViewer(name, 'своя');
  showTexturePreview('своя');
  setScript(lines.join('\n').trimEnd());
  buildNow(true);
  toast(`Текстура применена к «${name}»`);
}

$('tex-sandbox')?.addEventListener('click', openTexSandbox);
$('tex-close')?.addEventListener('click', closeTexSandbox);
$('tex-modal')?.addEventListener('click', (e) => { if (e.target === $('tex-modal')) closeTexSandbox(); });
['tex-pattern', 'tex-color1', 'tex-color2', 'tex-scale', 'tex-relief', 'tex-seed']
  .forEach((id) => $(id)?.addEventListener('input', scheduleSandboxPreview));
['tex-pattern', 'tex-color1', 'tex-color2', 'tex-seed']
  .forEach((id) => $(id)?.addEventListener('change', updateSandboxPreview));
$('tex-dice')?.addEventListener('click', () => {
  $('tex-seed').value = String(1 + Math.floor(Math.random() * 999));
  updateSandboxPreview();
});
$('tex-apply')?.addEventListener('click', applySandboxTexture);
$('tex-download')?.addEventListener('click', () => {
  const a = document.createElement('a');
  a.href = textureUrl('своя') + '&download=1';
  a.download = 'forma-texture.png';
  document.body.appendChild(a);
  a.click();
  a.remove();
});

$('mat-tex')?.addEventListener('change', (e) => {
  updateCustomTexVisibility();
  if (!state.selected) return;
  const name = state.selected.name;
  const kind = e.target.value || '';
  if (!kind) {
    applyTextureToViewer(name, '');
    showTexturePreview('');
    const lines = currentScript().split('\n').filter((l) => !l.trim().startsWith(`texture ${name} `));
    setScript(lines.join('\n').trimEnd());
    toast('Текстура снята');
    return;
  }
  // 1) мгновенный предпросмотр на модели и в панели, 2) запись в сценарий и пересборка
  applyTextureToViewer(name, kind);
  showTexturePreview(kind);
  writeMaterialScript({ rebuild: true });
  toast(`Текстура «${kind}» применена к «${name}»`);
});

/* ------------------------------------------------------------------ */
/*  Выделение области и замечания                                     */
/* ------------------------------------------------------------------ */
function setSelectMode(on) {
  state.selectMode = on;
  $('btn-select')?.classList.toggle('active', on);
  state.viewer?.setSelectMode(on);
  if (!on) {
    $('sel-card').hidden = true;
    state.selection = null;
  } else {
    toast('Кликните по модели — выделится область. Затем опишите, что не так.');
  }
  updateViewerHint();
}

function updateViewerHint() {
  const hint = $('viewer-hint');
  if (!hint) return;
  if (state.spaceMode) {
    hint.textContent = 'кубы: ЛКМ — выбрать сектор · Shift — добавить · Ctrl — убрать · рамка — много · СКМ — вращать';
    return;
  }
  hint.textContent = state.selectMode
    ? 'выбор: ЛКМ — выделить область · ползунок — размер · «Вырезать» — убрать'
    : 'ЛКМ — вращать · колесо — масштаб · ПКМ — сдвинуть · двойной клик — вернуть вид';
}


/* ------------------------------------------------------------------ */
/*  0.15: выделение пустого пространства кубическими секторами         */
/* ------------------------------------------------------------------ */
function setSpaceMode(on) {
  state.spaceMode = Boolean(on);
  if (state.spaceMode) setSelectMode(false);
  state.viewer?.setSpaceMode(state.spaceMode);
  $('btn-space')?.classList.toggle('active', state.spaceMode);
  const card = $('space-card');
  if (card) card.hidden = !state.spaceMode;
  if (state.spaceMode) {
    let cell = Number($('space-size')?.value) || 50;
    // размер куба подгоняется под модель: примерно 10 секторов по большей стороне
    const size = state.viewer?.bbox?.size;
    if (size) {
      const span = Math.max(Number(size.x) || 0, Number(size.y) || 0, Number(size.z) || 0);
      if (span > 0) cell = Math.max(10, Math.min(200, Math.round(span / 10 / 5) * 5));
    }
    if ($('space-size')) $('space-size').value = String(cell);
    state.viewer?.setSpaceCell(cell);
    if ($('space-size-val')) $('space-size-val').textContent = cell + ' мм';
    updateSpaceUI(state.viewer?.spaceSelection() || null);
    toast('Кубы: щёлкните рядом с моделью; Shift — добавить, Ctrl — убрать, рамка — много');
  } else {
    state.space = null;
  }
  updateViewerHint();
}

function updateSpaceUI(sel) {
  state.space = sel || null;
  const info = $('space-info');
  if (!info) return;
  if (!sel || !sel.cells) {
    info.innerHTML = 'Включён режим кубов: щёлкните по пустому месту рядом с моделью.<br>'
      + '<span class="dim">Shift — добавить сектор · Ctrl — убрать · рамка — выбрать сразу много</span>';
    return;
  }
  const c = sel.script_center.map((v) => fmt(v)).join(', ');
  const sz = sel.script_size.map((v) => fmt(v)).join(' × ');
  info.innerHTML = `секторов: <b>${sel.cells}</b> · куб <b>${fmt(sel.cell)}</b> мм<br>`
    + `индексы: <b>${escapeHtml(sel.indices || '')}</b><br>`
    + `центр сцены: <b>(${escapeHtml(c)})</b> мм · размер <b>${escapeHtml(sz)}</b> мм<br>`
    + `<span class="dim">${fmt(sel.volume_cm3)} см³ · Shift — добавить, Ctrl — убрать</span>`;
}

async function saveSpaceNote() {
  const sel = state.space || state.viewer?.spaceSelection();
  if (!sel || !sel.cells) { toast('Сначала выделите кубы', 'bad'); return; }
  const text = ($('space-note')?.value || '').trim();
  if (!text) { toast('Напишите, что добавить в этом месте', 'bad'); return; }
  const c = sel.script_center.map((v) => fmt(v)).join(', ');
  try {
    const res = await api('/api/note', {
      kind: 'пространство',
      object: `секторы: ${sel.cells}`,
      text,
      cells: sel.cells,
      cell: sel.cell,
      indices: sel.indices || '',
      center: sel.script_center,
      size: sel.script_size,
      volume_cm3: sel.volume_cm3,
      tris: 0,
      area_mm2: 0,
    });
    state.notes = res.notes || state.notes;
    renderNotes();
    // Приписка остаётся и в сценарии — вместе с индексами и координатами.
    const comment = `# приписка [${sel.cells} куб., ${fmt(sel.cell)} мм, ${sel.indices || ''}, `
      + `центр (${c})]: ${text}`;
    const script = currentScript().replace(/\s+$/, '');
    setScript(script ? `${script}\n${comment}\n` : `${comment}\n`,
      { build: false, label: 'приписка к пространству' });
    state.actions = [...(state.actions || []), {
      time: new Date().toLocaleTimeString('ru-RU'),
      kind: 'приписка', text: `${sel.cells} сектор(ов): ${text}`, ok: true,
    }];
    renderActions();
    $('space-note').value = '';
    toast(`Приписка прикреплена к ${sel.cells} сектор(ам)`);
  } catch (e) {
    toast(e.message || 'Не удалось сохранить приписку', 'bad');
  }
}

$('btn-space')?.addEventListener('click', () => setSpaceMode(!state.spaceMode));
$('space-close')?.addEventListener('click', () => setSpaceMode(false));
$('space-size')?.addEventListener('input', (e) => {
  const mm = Number(e.target.value) || 50;
  if ($('space-size-val')) $('space-size-val').textContent = mm + ' мм';
  state.viewer?.setSpaceCell(mm);
  updateSpaceUI(state.viewer?.spaceSelection() || null);
});
$('space-clear')?.addEventListener('click', () => {
  state.viewer?.clearSpaceSelection();
  updateSpaceUI(null);
});
$('space-save')?.addEventListener('click', saveSpaceNote);

function showSelection(list) {
  const selections = Array.isArray(list) ? list : (list ? [list] : []);
  const card = $('sel-card');
  if (!selections.length) { card.hidden = true; return; }
  const summary = state.viewer?.selectionSummary();
  if (!summary) { card.hidden = true; return; }
  state.selection = summary;
  card.hidden = false;
  $('sel-title').textContent = summary.regions > 1
    ? `выделено областей: ${summary.regions}` : 'выделено: ' + (summary.object || 'деталь');
  const c = summary.center.map((v) => fmt(v)).join(', ');
  const sz = summary.size.map((v) => fmt(v)).join(' × ');
  $('sel-info').innerHTML =
    `треугольников: <b>${fmtInt(summary.tris)}</b> · площадь <b>${fmt(summary.area_mm2)}</b> мм²<br>`
    + `общий центр: <b>(${escapeHtml(c)})</b> мм · размер <b>${escapeHtml(sz)}</b> мм<br>`
    + `<span class="dim">Shift — добавить область, Ctrl+клик — убрать</span>`;
  const palette = ['#ff5a5a', '#ffb35a', '#7dff8f', '#5ac8ff', '#c78bff', '#ff6bd6'];
  const box = $('sel-list');
  box.innerHTML = '';
  selections.forEach((sel, i) => {
    const chip = document.createElement('div');
    chip.className = 'sel-chip';
    chip.innerHTML = `<span><span class="dot" style="background:${palette[i % palette.length]}"></span>`
      + `<b>${escapeHtml(sel.object || 'деталь')}</b> · ${fmtInt(sel.tris)} трис</span>`
      + `<span>${fmt(sel.area_mm2)} мм²</span>`;
    box.appendChild(chip);
  });
  $('sel-note').focus();
}

function clearSelection() {
  state.selection = null;
  $('sel-card').hidden = true;
  state.viewer?.clearSelection();
}

function selectionRegions() {
  return (state.viewer?.selections || []).map((s) => ({
    object: s.object, tris: s.tris, area_mm2: s.area_mm2, center: s.center,
    size: s.size, bbox: s.bbox, point: s.point, radius: s.radius,
  }));
}

$('btn-select')?.addEventListener('click', () => setSelectMode(!state.selectMode));
$('sel-close')?.addEventListener('click', () => clearSelection());
$('sel-radius')?.addEventListener('input', (e) => {
  $('sel-radius-val').textContent = e.target.value + ' мм';
  state.viewer?.setSelectRadius(Number(e.target.value));
});
$('sel-save')?.addEventListener('click', async () => {
  const regions = selectionRegions();
  if (!regions.length) { toast('Сначала выделите область на модели', 'bad'); return; }
  const text = $('sel-note').value.trim();
  if (!text) { toast('Напишите словами, что не так в этом месте', 'bad'); return; }
  try {
    let notes = state.notes || [];
    for (let i = 0; i < regions.length; i += 1) {
      const label = regions.length > 1 ? `${text} [область ${i + 1}/${regions.length}]` : text;
      const res = await api('/api/note', { ...regions[i], text: label });
      notes = res.notes || notes;
    }
    state.notes = notes;
    renderNotes();
    state.actions = [...(state.actions || []), { time: new Date().toLocaleTimeString('ru-RU'),
      kind: 'замечание', text: `${regions.length} обл.: ${text}`, ok: true }];
    renderActions();
    state.notes = (await api('/api/notes', {})).notes || notes;
    renderNotes();
    $('sel-note').value = '';
    toast(`Замечание добавлено (${regions.length} обл.)`);
  } catch (e) { toast(e.message || 'Не удалось сохранить замечание', 'bad'); }
});

$('sel-clear')?.addEventListener('click', () => clearSelection());

$('sel-cut')?.addEventListener('click', async () => {
  const regions = selectionRegions();
  if (!regions.length) { toast('Сначала выделите область', 'bad'); return; }
  let script = currentScript();
  let last = null;
  try {
    for (const region of regions) {
      const name = region.object;
      const defined = script.split('\n').some((l) => l.includes('=') && l.split('=')[0].trim() === name);
      if (!defined) {
        toast(`«${name}» — часть составного объекта, вырезание пропущено`, 'bad');
        continue;
      }
      const radius = Math.max(region.radius, Math.max(...region.size) / 2);
      last = await api('/api/edit/cut', { script, object: name, center: region.center, radius });
      script = last.script;
    }
    if (!last) return;
    clearSelection();
    setSelectMode(false);
    setScript(script);
    toast(`Вырезано областей: ${regions.length}`);
  } catch (e) { toast(e.message || 'Не удалось вырезать область', 'bad'); }
});

$('notes-clear')?.addEventListener('click', async () => {
  try {
    const res = await api('/api/notes', { clear: true });
    state.notes = res.notes || [];
    renderNotes();
    toast('Список замечаний очищен');
  } catch (e) { toast(e.message || 'Ошибка', 'bad'); }
});

/* ------------------------------------------------------------------ */
/*  Командная строка                                                   */
/* ------------------------------------------------------------------ */
async function captureViews() {
  if (!state.payload?.ok) { toast('Сначала соберите модель', 'bad'); return; }
  try {
    const res = await api('/api/render', {});
    renderStrip(res);
    toast('Снимки четырёх видов готовы');
    setCmdResult(`✓ снимки: ${(res.files || []).length} видов`, 'ok');
  } catch (e) { toast(e.message || 'Ошибка снимков', 'bad'); }
}

function scriptLines(text) {
  return String(text || '').replace(/\r\n?/g, '\n').split('\n')
    .map((l) => l.replace(/\s+$/, ''))
    .filter((l) => l.trim() && !l.trim().startsWith('#'));
}

/** Вставка нескольких строк: полный сценарий заменяем, одиночную команду дописываем. */
function insertScriptText(text, { replace = false } = {}) {
  const lines = scriptLines(text);
  if (!lines.length) return 0;
  if (replace || lines.length > 1) {
    setScript(lines.join('\n'), { label: `вставка ${lines.length} строк` });
  } else {
    const script = currentScript().replace(/\s+$/, '');
    setScript((script ? script + '\n' : '') + lines[0], { label: 'команда: ' + lines[0] });
  }
  return lines.length;
}

function runCommand() {
  const raw = $('cmd-input').value.trim();
  if (!raw) { buildNow(); return; }
  if (/[\n\r]/.test(raw)) {
    $('cmd-input').value = '';
    const n = insertScriptText(raw, { replace: true });
    if (n) {
      setCmdResult(`✓ вставлено строк: ${n} — сценарий заменён (откат: Ctrl+Z)`, 'ok');
      toast(`Сценарий из ${n} строк собран`);
    }
    return;
  }
  const low = raw.toLowerCase();
  if (low === '/снимки' || low === '/render') { $('cmd-input').value = ''; captureViews(); return; }
  if (low === '/отчёт' || low === '/report') {
    $('cmd-input').value = '';
    document.querySelector('.tab[data-tab="report"]')?.click();
    return;
  }
  if (low === '/справка' || low === '/help') { $('cmd-input').value = ''; openHelp(); return; }
  if (low === '/инструменты' || low === '/tools') {
    $('cmd-input').value = '';
    openTools();
    return;
  }
  const RECIPES = { '/кружка': 'mug', '/mug': 'mug', '/ваза': 'vase', '/vase': 'vase',
    '/шестерня': 'gear', '/gear': 'gear', '/кузов': 'car', '/car': 'car',
    '/бутылка': 'bottle', '/bottle': 'bottle', '/пришелец': 'alien', '/alien': 'alien',
    '/манекен': 'mannequin', '/mannequin': 'mannequin', '/яблоко': 'apple', '/apple': 'apple',
    '/шкаф': 'wardrobe', '/wardrobe': 'wardrobe',
    '/механика': 'mechanics', '/mechanics': 'mechanics',
    '/дорожки': 'animation_tracks', '/tracks': 'animation_tracks' };
  if (RECIPES[low] || low === '/рецепты' || low === '/recipes') {
    $('cmd-input').value = '';
    if (RECIPES[low]) { loadExample(RECIPES[low]); return; }
    if (low === '/инструменты' || low === '/tools') { openTools(); return; }
    toast('Рецепты: /кружка, /яблоко, /ваза, /бутылка, /шестерня, /кузов, /пришелец, /манекен, /шкаф, /механика, /дорожки, /инструменты');
    return;
  }
  if (low === '/очистить' || low === '/clear') {
    setScript('');
    $('cmd-input').value = '';
    return;
  }
  state.cmdHistory.push(raw);
  state.cmdIndex = state.cmdHistory.length;
  const script = currentScript().replace(/\s+$/, '');
  $('cmd-input').value = '';
  setCmdResult('выполняю: ' + raw);
  setScript((script ? script + '\n' : '') + raw, { label: 'команда: ' + raw });
}

function sendToAssistant() {
  const text = $('cmd-input').value.trim();
  $('cmd-input').value = '';
  document.querySelector('.tab[data-tab="assist"]')?.click();
  if (text) {
    $('goal').value = text;
    toast('Задача перенесена в «Помощник» — нажмите «Сформировать запрос»');
  }
  $('goal')?.focus();
}

$('cmd-run')?.addEventListener('click', runCommand);
$('cmd-input')?.addEventListener('paste', (e) => {
  const text = e.clipboardData?.getData('text') || '';
  if (!/[\n\r]/.test(text)) return;   // одна строка — обычная вставка
  e.preventDefault();
  $('cmd-input').value = '';
  const n = insertScriptText(text, { replace: true });
  if (n) {
    setCmdResult(`✓ вставлено строк: ${n} — сценарий заменён (откат: Ctrl+Z)`, 'ok');
    toast(`Многострочный сценарий: ${n} строк`);
  }
});

function fitCmdInput() {
  const el = $('cmd-input');
  if (!el) return;
  el.style.height = 'auto';
  el.style.height = Math.min(132, Math.max(28, el.scrollHeight)) + 'px';
}
$('cmd-input')?.addEventListener('input', fitCmdInput);

$('cmd-input')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    // здесь Ctrl+Enter — «вопрос нейросети», а не пересборка модели;
    // событие не должно всплыть до глобального обработчика
    e.preventDefault();
    e.stopPropagation();
    sendToAssistant();
    return;
  }
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runCommand(); return; }
  if (e.key === 'ArrowUp' && state.cmdHistory.length) {
    state.cmdIndex = Math.max(0, state.cmdIndex - 1);
    $('cmd-input').value = state.cmdHistory[state.cmdIndex] || '';
    e.preventDefault();
  }
  if (e.key === 'ArrowDown' && state.cmdHistory.length) {
    state.cmdIndex = Math.min(state.cmdHistory.length, state.cmdIndex + 1);
    $('cmd-input').value = state.cmdHistory[state.cmdIndex] || '';
    e.preventDefault();
  }
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
function renderStrip(res) {
  const strip = $('render-strip');
  if (!strip) return;
  strip.hidden = false;
  strip.innerHTML = '';
  (res.files || []).forEach((f) => {
    const a = document.createElement('a');
    a.href = f.url + (f.url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN);
    a.target = '_blank';
    a.innerHTML = `<img src="${f.url}${f.url.includes('?') ? '&' : '?'}token=${encodeURIComponent(TOKEN)}" alt="${escapeHtml(f.label)}">
      <div class="cap">${escapeHtml(f.label)}</div>`;
    strip.appendChild(a);
  });
}

$('btn-render').addEventListener('click', async () => {
  if (!state.payload?.ok) { toast('Сначала соберите модель', 'bad'); return; }
  const btn = $('btn-render');
  btn.disabled = true;
  toast('Готовим снимки четырёх видов…');
  try {
    const res = await api('/api/render', {});
    renderStrip(res);
    toast('Снимки готовы — они лежат в папке renders');
  } catch (e) {
    toast(e.message || 'Ошибка рендера', 'bad');
  } finally {
    btn.disabled = false;
  }
});

document.querySelectorAll('[data-section-export]').forEach((btn) => {
  btn.addEventListener('click', async () => {
    if (!state.payload?.ok) { toast('Сначала соберите модель', 'bad'); return; }
    const fmtName = btn.dataset.sectionExport;
    try {
      const res = await api('/api/export', { format: fmtName });
      const url = res.url + (res.url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN) + '&download=1';
      const link = document.createElement('a');
      link.href = url;
      link.download = res.name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      toast(`Сечение сохранено: ${res.name}`);
    } catch (err) {
      toast(err.message || 'Нет сечений: добавьте section z=40 в сценарий', 'bad');
    }
  });
});


/* ------------------------------------------------------------------ */
/*  Экспорт анимации: GIF и видео                                     */
/* ------------------------------------------------------------------ */
function animExportSeconds() {
  const total = Number(state.viewer?.duration) || animDuration() || 0;
  if (total < 0.2) return 0;
  return total;
}

function animExportName(ext) {
  const base = (state.payload?.project || state.projectName || 'анимация')
    .toString().replace(/[^\wа-яА-ЯёЁ-]+/g, '_').slice(0, 40) || 'анимация';
  return `${base}_${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')}.${ext}`;
}

function exportCanvas(viewer, maxWidth) {
  const src = viewer?.renderer?.domElement;
  if (!src || !src.width) return null;
  const scale = Math.min(1, maxWidth / src.width);
  const w = Math.max(2, Math.round(src.width * scale));
  const h = Math.max(2, Math.round(src.height * scale));
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(src, 0, 0, w, h);
  return { canvas, ctx, w, h };
}

function setAnimExportBusy(busy, label = '') {
  ['anim-gif', 'anim-webm'].forEach((id) => {
    const btn = $(id);
    if (btn) btn.disabled = busy;
  });
  if (label) toast(label);
}

async function exportAnimationGif() {
  const viewer = state.viewer;
  const seconds = animExportSeconds();
  if (!viewer || !viewer.hasAnimation?.() || !seconds) {
    toast('Сначала постройте модель с анимацией: animate … в сценарии', 'bad');
    return;
  }
  const fps = 12;
  const total = Math.min(240, Math.max(2, Math.round(seconds * fps)));
  const keep = viewer.time;
  setAnimExportBusy(true, `GIF: кадр 1/${total}…`);
  try {
    let frames = [];
    let size = null;
    for (let i = 0; i < total; i++) {
      viewer.applyTime(seconds * i / total);
      viewer.renderNow();
      const shot = exportCanvas(viewer, 560);
      if (!shot) throw new Error('Нет изображения для записи');
      size = { w: shot.w, h: shot.h };
      frames.push(new Uint8ClampedArray(shot.ctx.getImageData(0, 0, shot.w, shot.h).data));
      if (i % 3 === 0) {
        toast(`GIF: кадр ${i + 1} из ${total}…`);
        await new Promise((r) => setTimeout(r, 0));
      }
    }
    viewer.applyTime(keep);
    toast('GIF: сжимаю кадры…');
    await new Promise((r) => setTimeout(r, 30));
    const data = encodeGif(frames, size.w, size.h, { fps, maxColors: 256, loop: true });
    downloadBlob(new Blob([data], { type: 'image/gif' }), animExportName('gif'));
    toast(`GIF сохранён: ${size.w}×${size.h}, ${total} кадров`);
  } catch (err) {
    toast(err.message || 'Не удалось собрать GIF', 'bad');
  } finally {
    setAnimExportBusy(false);
  }
}

async function exportAnimationWebm() {
  const viewer = state.viewer;
  const seconds = animExportSeconds();
  if (!viewer || !viewer.hasAnimation?.() || !seconds) {
    toast('Сначала постройте модель с анимацией: animate … в сценарии', 'bad');
    return;
  }
  const canvas = viewer.renderer?.domElement;
  if (!canvas || !canvas.captureStream || typeof MediaRecorder === 'undefined') {
    toast('Браузер не поддерживает запись видео — сохраните GIF', 'bad');
    return;
  }
  const fps = 30;
  const total = Math.min(600, Math.max(2, Math.round(seconds * fps)));
  const keep = viewer.time;
  setAnimExportBusy(true, 'Видео: запись…');
  try {
    const stream = canvas.captureStream(0);
    const track = stream.getVideoTracks()[0];
    const types = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'];
    const mime = types.find((t) => MediaRecorder.isTypeSupported?.(t)) || 'video/webm';
    const rec = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 8_000_000 });
    const chunks = [];
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    const stopped = new Promise((resolve) => { rec.onstop = resolve; });
    rec.start();
    for (let i = 0; i < total; i++) {
      viewer.applyTime(seconds * i / total);
      viewer.renderNow();
      if (track?.requestFrame) track.requestFrame();
      await new Promise((r) => setTimeout(r, Math.max(8, 1000 / fps)));
      if (i % 15 === 0) toast(`Видео: кадр ${i + 1} из ${total}…`);
    }
    rec.stop();
    await stopped;
    track?.stop?.();
    const blob = new Blob(chunks, { type: mime.split(';')[0] || 'video/webm' });
    downloadBlob(blob, animExportName('webm'));
    toast(`Видео сохранено: ${(blob.size / 1024 / 1024).toFixed(1)} МБ`);
  } catch (err) {
    toast(err.message || 'Не удалось записать видео', 'bad');
  } finally {
    viewer.applyTime(keep);
    setAnimExportBusy(false);
  }
}

$('anim-gif')?.addEventListener('click', exportAnimationGif);
$('anim-webm')?.addEventListener('click', exportAnimationWebm);

$('btn-export').parentElement.querySelector('.menu').addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-format]');
  if (!btn) return;
  const fmt = btn.dataset.format;
  document.querySelectorAll('.menu.open').forEach((m) => m.classList.remove('open'));
  if (!state.payload?.ok) { toast('Сначала соберите модель', 'bad'); return; }
  if (fmt === 'gif') { exportAnimationGif(); return; }
  if (fmt === 'webm') { exportAnimationWebm(); return; }
  toast('Экспорт…');
  try {
    const res = await api('/api/export', { format: fmt });
    const url = res.url + (res.url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN) + '&download=1';
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
/*  0.15: «Инструменты» — готовые фигуры и приёмы с параметрами        */
/* ------------------------------------------------------------------ */
const TOOL_SHAPES = [
  {
    op: 'star', name: 'звезда', title: 'Звезда',
    desc: 'Лучи, глубина впадин, фаска и плавное скругление кромки.',
    params: [
      { k: 'points', label: 'лучи', v: 5, step: 1, min: 3 },
      { k: 'outer', label: 'радиус', v: 55, step: 1 },
      { k: 'inner', label: 'впадина', v: 22, step: 1 },
      { k: 'depth', label: 'толщина', v: 12, step: 1 },
      { k: 'bevel', label: 'фаска', v: 2, step: 0.5 },
      { k: 'smooth', label: 'сглаж.', v: 0.4, step: 0.1 },
      { k: 'twist', label: 'закрутка', v: 0, step: 5 },
    ],
  },
  {
    op: 'plate', name: 'тарелка', title: 'Тарелка',
    desc: 'Борт, плоское дно и стенка — глубокая или мелкая.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 220, step: 5 },
      { k: 'depth', label: 'высота', v: 26, step: 1 },
      { k: 'wall', label: 'стенка', v: 4, step: 0.5 },
      { k: 'well', label: 'дно', v: 0.62, step: 0.02 },
    ],
  },
  {
    op: 'spring', name: 'пружина', title: 'Пружина',
    desc: 'Винтовая пружина: средний диаметр, проволока, витки и шаг.',
    params: [
      { k: 'diameter', label: 'виток', v: 22, step: 1 },
      { k: 'wire', label: 'провол.', v: 3, step: 0.2 },
      { k: 'turns', label: 'витки', v: 8, step: 1 },
      { k: 'pitch', label: 'шаг', v: 6, step: 0.5 },
      { k: 'right', label: 'правая', v: true, kind: 'bool' },
    ],
  },
  {
    op: 'gear', name: 'шестерня', title: 'Шестерня',
    desc: 'Прямозубая: число зубьев, модуль, толщина, ступица и отверстие.',
    params: [
      { k: 'teeth', label: 'зубья', v: 20, step: 1, min: 6 },
      { k: 'module', label: 'модуль', v: 2, step: 0.25 },
      { k: 'thickness', label: 'толщина', v: 8, step: 1 },
      { k: 'bore', label: 'отверстие', v: 8, step: 1 },
      { k: 'hub', label: 'ступица', v: 0, step: 2 },
    ],
  },
  {
    op: 'washer', name: 'шайба', title: 'Шайба',
    desc: 'Плоское кольцо с фаской; размеры в миллиметрах.',
    params: [
      { k: 'outer', label: 'наружн.', v: 40, step: 1 },
      { k: 'inner', label: 'отверстие', v: 16, step: 1 },
      { k: 'thickness', label: 'толщина', v: 4, step: 0.5 },
    ],
  },
  {
    op: 'cube_hole', name: 'кубик', title: 'Кубик с отверстием',
    desc: 'Брусок с круглым отверстием; можно задать размеры и ось.',
    params: [
      { k: 'size', label: 'размер', v: '40,40,40', kind: 'vec' },
      { k: 'hole', label: 'отверстие', v: 16, step: 1 },
      { k: 'axis', label: 'ось', v: 'z' },
      { k: 'round', label: 'скругл.', v: 2, step: 0.5 },
    ],
  },
  {
    op: 'nut', name: 'гайка', title: 'Гайка',
    desc: 'Шестигранная гайка с настоящей внутренней резьбой.',
    params: [
      { k: 'd', label: 'резьба', v: 8, step: 1 },
      { k: 'pitch', label: 'шаг', v: 1.25, step: 0.25 },
      { k: 'h', label: 'высота', v: 6.4, step: 0.2 },
    ],
  },
  {
    op: 'bolt', name: 'болт', title: 'Болт',
    desc: 'Шестигранная головка и резьба на стержне.',
    params: [
      { k: 'd', label: 'резьба', v: 8, step: 1 },
      { k: 'length', label: 'длина', v: 30, step: 1 },
      { k: 'pitch', label: 'шаг', v: 1.25, step: 0.25 },
    ],
  },
  {
    op: 'screw', name: 'винт', title: 'Винт / саморез',
    desc: 'Потайная или полукруглая головка, частая резьба и остриё.',
    params: [
      { k: 'd', label: 'диаметр', v: 4, step: 0.5 },
      { k: 'length', label: 'длина', v: 25, step: 1 },
      { k: 'head', label: 'головка', v: 'потай' },
    ],
  },
  {
    op: 'hinge', name: 'петля', title: 'Петля',
    desc: 'Две пластины, шарнир и ось; отверстия под саморезы.',
    params: [
      { k: 'width', label: 'ширина', v: 45, step: 1 },
      { k: 'height', label: 'высота', v: 35, step: 1 },
      { k: 'thickness', label: 'толщина', v: 2, step: 0.5 },
    ],
  },
  {
    op: 'bracket', name: 'уголок', title: 'Уголок',
    desc: 'Две полки под 90° и отверстия под крепёж.',
    params: [
      { k: 'width', label: 'ширина', v: 60, step: 5 },
      { k: 'depth', label: 'глубина', v: 40, step: 5 },
      { k: 'height', label: 'высота', v: 40, step: 5 },
      { k: 'thickness', label: 'сталь', v: 3, step: 0.5 },
    ],
  },
  {
    op: 'bearing', name: 'подшипник', title: 'Подшипник',
    desc: 'Наружное и внутреннее кольца, шарики, посадка под вал.',
    params: [
      { k: 'outer', label: 'наружный', v: 40, step: 1 },
      { k: 'inner', label: 'вал', v: 17, step: 1 },
      { k: 'width', label: 'ширина', v: 12, step: 1 },
      { k: 'balls', label: 'шариков', v: 9, step: 1 },
    ],
  },
  {
    op: 'caster', name: 'ролик', title: 'Ролик',
    desc: 'Колесо, вилка, площадка и ось — готовое колёсико под шкаф.',
    params: [
      { k: 'wheel', label: 'колесо', v: 50, step: 5 },
      { k: 'width', label: 'ширина', v: 18, step: 1 },
      { k: 'plate', label: 'площадка', v: 45, step: 5 },
    ],
  },
  {
    op: 'pulley', name: 'шкив', title: 'Шкив',
    desc: 'Обод с канавкой под ремень и отверстием под вал.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 80, step: 5 },
      { k: 'width', label: 'ширина', v: 20, step: 1 },
      { k: 'bore', label: 'вал', v: 10, step: 1 },
      { k: 'groove', label: 'канавка', v: 6, step: 1 },
    ],
  },
  {
    op: 'egg', name: 'яйцо', title: 'Яйцо', group: 'Примитивы',
    desc: 'Настоящее яйцо: тупой конец шире, острый — уже; proportion 0..1, sharp=верх|низ.',
    params: [
      { k: 'height', label: 'высота', v: 60, step: 1 },
      { k: 'diameter', label: 'диаметр', v: 42, step: 1 },
      { k: 'proportion', label: 'яйцевидн.', v: 0.55, step: 0.05 },
      { k: 'sharp', label: 'острый', v: 'верх', kind: 'raw' },
    ],
  },
  {
    op: 'drop', name: 'капля', title: 'Капля', group: 'Примитивы',
    desc: 'Круглое дно и вытянутый хвост: вода, слеза, стекло. tip=0..1 — острота.',
    params: [
      { k: 'radius', label: 'радиус', v: 14, step: 1 },
      { k: 'height', label: 'высота', v: 36, step: 1 },
      { k: 'tip', label: 'острота', v: 0.5, step: 0.05 },
    ],
  },
  {
    op: 'heart', name: 'сердце', title: 'Сердце', group: 'Примитивы',
    desc: 'Настоящая форма сердца: два лепестка и остриё. Ширина, толщина, скругление.',
    params: [
      { k: 'width', label: 'ширина', v: 60, step: 2 },
      { k: 'depth', label: 'толщина', v: 18, step: 1 },
      { k: 'round', label: 'скругл.', v: 2, step: 0.5 },
    ],
  },
  {
    op: 'plus', name: 'плюс', title: 'Плюс', group: 'Примитивы',
    desc: 'Перекрестие из двух брусьев: аптечка, крест, перекладина.',
    params: [
      { k: 'arm', label: 'длина', v: 60, step: 2 },
      { k: 'thick', label: 'брус', v: 18, step: 1 },
      { k: 'depth', label: 'толщина', v: 14, step: 1 },
      { k: 'round', label: 'скругл.', v: 1.5, step: 0.5 },
    ],
  },
  {
    op: 'sector', name: 'сектор', title: 'Сектор шара', group: 'Примитивы',
    desc: 'Долька шара с любым углом: 90° — четвертинка, 180° — полусфера.',
    params: [
      { k: 'radius', label: 'радиус', v: 50, step: 2 },
      { k: 'angle', label: 'угол°', v: 90, step: 5 },
      { k: 'thickness', label: 'стенка', v: 0, step: 1 },
    ],
  },
  {
    op: 'spiral', name: 'спираль', title: 'Спираль', group: 'Примитивы',
    desc: 'Плоская улитка из центра наружу: пружинка, завиток, креманка.',
    params: [
      { k: 'radius', label: 'радиус', v: 60, step: 2 },
      { k: 'turns', label: 'витки', v: 3, step: 0.5 },
      { k: 'wire', label: 'нить', v: 6, step: 0.5 },
      { k: 'height', label: 'высота', v: 6, step: 1 },
    ],
  },
  {
    op: 'rope', name: 'верёвка', title: 'Верёвка', group: 'Примитивы',
    desc: 'Кручёные нити вокруг общей оси: канат, шнур, трос.',
    params: [
      { k: 'length', label: 'длина', v: 200, step: 10 },
      { k: 'diameter', label: '⌀', v: 20, step: 1 },
      { k: 'strands', label: 'нити', v: 3, step: 1 },
      { k: 'twist', label: 'свивка', v: 55, step: 5 },
    ],
  },
  {
    op: 'seven_seg', name: 'индикатор', title: 'Семисегментный', group: 'Примитивы',
    desc: 'Светодиодные цифры: «21:38». С материалом led сразу горит.',
    params: [
      { k: 'text', label: 'текст', v: '21:38', kind: 'raw' },
      { k: 'height', label: 'высота', v: 54, step: 2 },
      { k: 'depth', label: 'толщина', v: 2, step: 0.5 },
    ],
  },
  {
    op: 'arrow', name: 'стрелка', title: 'Стрелка', group: 'Знаки и фигуры',
    desc: 'Указатель остриём вправо: древко, наконечник, вырез в хвосте.',
    params: [
      { k: 'length', label: 'длина', v: 120, step: 5 },
      { k: 'width', label: 'древко', v: 26, step: 2 },
      { k: 'head', label: 'наконеч.', v: 42, step: 2 },
      { k: 'head_width', label: 'размах', v: 68, step: 2 },
      { k: 'tail', label: 'вырез', v: 0, step: 2 },
      { k: 'depth', label: 'толщина', v: 12, step: 1 },
      { k: 'round', label: 'скругл.', v: 2, step: 0.5 },
    ],
  },
  {
    op: 'tee', name: 'тавр', title: 'Форма Т', group: 'Знаки и фигуры',
    desc: 'Буква Т: перекладина и ножка одной деталью.',
    params: [
      { k: 'arm', label: 'переклад.', v: 90, step: 5 },
      { k: 'bar', label: 'толщина', v: 20, step: 2 },
      { k: 'stem', label: 'ножка', v: 22, step: 2 },
      { k: 'leg', label: 'длина нож.', v: 60, step: 5 },
      { k: 'depth', label: 'толщина Z', v: 14, step: 1 },
      { k: 'round', label: 'скругл.', v: 2, step: 0.5 },
    ],
  },
  {
    op: 'crescent', name: 'полумесяц', title: 'Полумесяц', group: 'Знаки и фигуры',
    desc: 'Серп: из круга выкушен второй круг, рога сходятся в острия.',
    params: [
      { k: 'radius', label: 'радиус', v: 50, step: 5 },
      { k: 'thickness', label: 'толщина', v: 18, step: 2 },
      { k: 'bite', label: 'выкус', v: 1, step: 0.05 },
      { k: 'depth', label: 'толщина Z', v: 12, step: 1 },
    ],
  },
  {
    op: 'swirl', name: 'завиток', title: 'Завиток', group: 'Знаки и фигуры',
    desc: 'Наплывы со спиральной канавкой: «мягкое мороженое», куча.',
    params: [
      { k: 'radius', label: 'радиус', v: 42, step: 2 },
      { k: 'height', label: 'высота', v: 70, step: 5 },
      { k: 'coils', label: 'наплывы', v: 3, step: 1, min: 1 },
      { k: 'groove', label: 'канавка', v: 4, step: 0.5 },
    ],
  },
  {
    op: 'lightning', name: 'молния', title: 'Молния', group: 'Знаки и фигуры',
    desc: 'Классический зигзаг с двумя остриями.',
    params: [
      { k: 'height', label: 'высота', v: 90, step: 5 },
      { k: 'width', label: 'ширина', v: 44, step: 2 },
      { k: 'depth', label: 'толщина Z', v: 10, step: 1 },
      { k: 'round', label: 'скругл.', v: 1.5, step: 0.5 },
    ],
  },
  {
    op: 'banana', name: 'банан', title: 'Банан / бровь', group: 'Знаки и фигуры',
    desc: 'Дуга с утолщением в середине: банан, бровь, стручок, скоба.',
    params: [
      { k: 'length', label: 'длина', v: 120, step: 5 },
      { k: 'bend', label: 'изгиб°', v: 110, step: 10 },
      { k: 'thick', label: 'толщина', v: 28, step: 2 },
      { k: 'flat', label: 'плоскость', v: 0.75, step: 0.05 },
      { k: 'taper', label: 'кончики', v: 0.32, step: 0.05 },
    ],
  },
  {
    op: 'yoke', name: 'рогатка', title: 'Форма Y', group: 'Знаки и фигуры',
    desc: 'Буква Y: ствол снизу, две ветви, круглые концы.',
    params: [
      { k: 'height', label: 'высота', v: 110, step: 5 },
      { k: 'spread', label: 'размах', v: 64, step: 4 },
      { k: 'arm', label: 'ветвь', v: 16, step: 1 },
      { k: 'fork', label: 'развилка', v: 0.38, step: 0.02 },
      { k: 'depth', label: 'толщина Z', v: 14, step: 1 },
    ],
  },
  {
    op: 'arch', name: 'арка', title: 'Арка', group: 'Примитивы',
    desc: 'Полукольцо с прямоугольным сечением: проём, свод, тоннель.',
    params: [
      { k: 'radius', label: 'радиус', v: 200, step: 10 },
      { k: 'width', label: 'сечение', v: 60, step: 5 },
      { k: 'thickness', label: 'толщина', v: 40, step: 5 },
      { k: 'angle', label: 'угол', v: 180, step: 15 },
    ],
  },
  {
    op: 'hemisphere', name: 'полусфера', title: 'Полусфера', group: 'Примитивы',
    desc: 'Купол или миска со стенкой — mode=купол|миска.',
    params: [
      { k: 'radius', label: 'радиус', v: 60, step: 1 },
      { k: 'mode', label: 'вид', v: 'купол' },
      { k: 'wall', label: 'стенка', v: 4, step: 0.5 },
    ],
  },
  {
    op: 'cloud', name: 'облако', title: 'Облако', group: 'Примитивы',
    desc: 'Пушистое тело из сплавленных сфер: габарит, число шаров, зерно.',
    params: [
      { k: 'size', label: 'размер', v: '180,90,70', kind: 'vec' },
      { k: 'puffs', label: 'шаров', v: 9, step: 1, min: 3 },
      { k: 'seed', label: 'зерно', v: 3, step: 1 },
    ],
  },
  {
    op: 'box', name: 'куб', title: 'Куб', group: 'Примитивы',
    desc: 'Прямоугольный блок со скруглением рёбер.',
    params: [
      { k: 'size', label: 'размер', v: '120,80,60', kind: 'vec' },
      { k: 'round', label: 'скругл.', v: 3, step: 1 },
    ],
  },
  {
    op: 'sphere', name: 'сфера', title: 'Сфера', group: 'Примитивы',
    desc: 'Шар заданного радиуса.',
    params: [
      { k: 'radius', label: 'радиус', v: 50, step: 1 },
      { k: 'segments', label: 'сегм.', v: 64, step: 8 },
    ],
  },
  {
    op: 'cylinder', name: 'цилиндр', title: 'Цилиндр', group: 'Примитивы',
    desc: 'Круглый столбик: радиус, высота, сегменты.',
    params: [
      { k: 'radius', label: 'радиус', v: 40, step: 1 },
      { k: 'height', label: 'высота', v: 100, step: 1 },
    ],
  },
  {
    op: 'cone', name: 'конус', title: 'Конус', group: 'Примитивы',
    desc: 'Конус с вершиной вверх — воронки, ножки, сопла.',
    params: [
      { k: 'radius', label: 'радиус', v: 45, step: 1 },
      { k: 'height', label: 'высота', v: 90, step: 1 },
    ],
  },
  {
    op: 'torus', name: 'тор', title: 'Тор', group: 'Примитивы',
    desc: 'Кольцо-бублик: радиус кольца и радиус трубки.',
    params: [
      { k: 'major', label: 'радиус', v: 55, step: 1 },
      { k: 'minor', label: 'трубка', v: 12, step: 1 },
    ],
  },
  {
    op: 'prism', name: 'призма', title: 'Призма', group: 'Примитивы',
    desc: 'Правильный многоугольник: гайки, колонны, соты.',
    params: [
      { k: 'sides', label: 'сторон', v: 6, step: 1 },
      { k: 'radius', label: 'радиус', v: 40, step: 1 },
      { k: 'height', label: 'высота', v: 60, step: 1 },
    ],
  },
  {
    op: 'pyramid', name: 'пирамида', title: 'Пирамида', group: 'Примитивы',
    desc: 'Правильная n-угольная пирамида: плоские грани, острая вершина, можно наклонить.',
    params: [
      { k: 'sides', label: 'сторон', v: 4, step: 1 },
      { k: 'radius', label: 'радиус', v: 60, step: 2 },
      { k: 'height', label: 'высота', v: 90, step: 5 },
    ],
  },
  {
    op: 'icosphere', name: 'икосфера', title: 'Икосфера', group: 'Примитивы',
    desc: 'Сфера из одинаковых треугольников, как в Blender: ровный полигонаж без полюсов.',
    params: [
      { k: 'radius', label: 'радиус', v: 40, step: 2 },
      { k: 'divisions', label: 'уровень', v: 2, step: 1, min: 1, max: 4 },
    ],
  },
  {
    op: 'diamond', name: 'алмаз', title: 'Алмаз', group: 'Примитивы',
    desc: 'Нижний конус и верхняя огранка с площадкой; sharp — острая трапецевидная призма.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 40, step: 2 },
      { k: 'crown', label: 'верх', v: 14, step: 1 },
      { k: 'pavilion', label: 'низ', v: 26, step: 1 },
      { k: 'sides', label: 'граней', v: 8, step: 1 },
      { k: 'sharp', label: 'острый', v: false, kind: 'bool' },
    ],
  },
  {
    op: 'capsule', name: 'капсула', title: 'Капсула', group: 'Примитивы',
    desc: 'Цилиндр с полусферическими концами.',
    params: [
      { k: 'radius', label: 'радиус', v: 18, step: 1 },
      { k: 'height', label: 'длина', v: 90, step: 5 },
    ],
  },
  {
    op: 'box_body', name: 'ящик', title: 'Коробка с полостью', group: 'Готовые фигуры',
    desc: 'Открытый сверху корпус с дном и стенками — ящик, лоток, кожух.',
    params: [
      { k: 'size', label: 'размер', v: '200,150,80', kind: 'vec' },
      { k: 'wall', label: 'стенка', v: 4, step: 0.5 },
      { k: 'bottom', label: 'дно', v: 6, step: 0.5 },
      { k: 'round', label: 'скругл.', v: 8, step: 1 },
    ],
  },
  {
    op: 'pipe', name: 'трубка', title: 'Труба со стенкой', group: 'Готовые фигуры',
    desc: 'Труба по ломаной: митры на поворотах, настоящая стенка.',
    params: [
      { k: 'path', label: 'путь', v: '[[0,0,0],[0,0,150],[90,0,150]]', kind: 'raw' },
      { k: 'diameter', label: 'диаметр', v: 32, step: 1 },
      { k: 'wall', label: 'стенка', v: 2, step: 0.5 },
    ],
  },
  {
    op: 'shaft', name: 'вал', title: 'Вал с буртиком', group: 'Готовые фигуры',
    desc: 'Ступенчатый вал: буртик задаётся шириной и диаметром, фаски и осевое отверстие.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 20, step: 1 },
      { k: 'length', label: 'длина', v: 120, step: 5 },
      { k: 'flange', label: 'буртик', v: 6, step: 1 },
      { k: 'flange_d', label: 'Ø буртика', v: 46, step: 1 },
      { k: 'bore', label: 'осевое', v: 6, step: 1 },
    ],
  },
  {
    op: 'wheel', name: 'колесо', title: 'Колесо', group: 'Готовые фигуры',
    desc: 'Шина, обод, спицы и ступица. Ось по Y; 1 спица — сплошной диск.',
    params: [
      { k: 'diameter', label: 'Ø по шине', v: 300, step: 10 },
      { k: 'width', label: 'ширина', v: 90, step: 5 },
      { k: 'tire', label: 'шина', v: 21, step: 1 },
      { k: 'rim', label: 'обод', v: 18, step: 1 },
      { k: 'spokes', label: 'спиц', v: 5, step: 1 },
      { k: 'hub', label: 'ступица', v: 40, step: 2 },
    ],
  },
  {
    op: 'handle', name: 'ручка', title: 'Ручка-скоба', group: 'Готовые фигуры',
    desc: 'П-образная ручка: перекладина, стойки и круглые площадки под винты.',
    params: [
      { k: 'length', label: 'длина', v: 160, step: 10 },
      { k: 'height', label: 'вынос', v: 34, step: 2 },
      { k: 'diameter', label: 'толщина', v: 10, step: 1 },
      { k: 'plate_d', label: 'Ø площадки', v: 24, step: 1 },
    ],
  },
  {
    op: 'rack', name: 'рейка', title: 'Зубчатая рейка', group: 'Готовые фигуры',
    desc: 'Рейка того же модуля, что шестерня, — реечная передача.',
    params: [
      { k: 'length', label: 'длина', v: 200, step: 10 },
      { k: 'teeth', label: 'зубьев', v: 20, step: 1 },
      { k: 'module', label: 'модуль', v: 2, step: 0.25 },
    ],
  },
  {
    op: 'coupling', name: 'муфта', title: 'Муфта', group: 'Готовые фигуры',
    desc: 'Соединительная муфта двух валов с буртиком.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 40, step: 2 },
      { k: 'length', label: 'длина', v: 60, step: 5 },
      { k: 'bore', label: 'вал', v: 12, step: 1 },
    ],
  },
  {
    op: 'heatsink', name: 'радиатор', title: 'Радиатор', group: 'Готовые фигуры',
    desc: 'Основание и рёбра с заданным шагом.',
    params: [
      { k: 'size', label: 'размер', v: '80,60,30', kind: 'vec' },
      { k: 'fins', label: 'рёбер', v: 9, step: 1 },
      { k: 'base', label: 'основание', v: 5, step: 1 },
    ],
  },
  {
    op: 'rock', name: 'камень', title: 'Камень', group: 'Готовые фигуры',
    desc: 'Выпуклая оболочка: всегда замкнутый, seed повторяет форму.',
    params: [
      { k: 'size', label: 'размер', v: '120,90,55', kind: 'vec' },
      { k: 'seed', label: 'зерно', v: 3, step: 1 },
      { k: 'rough', label: 'грубость', v: 0.35, step: 0.05 },
    ],
  },
  {
    op: 'leaf', name: 'лист', title: 'Лист', group: 'Готовые фигуры',
    desc: 'Лист с изгибом — для растений и декора.',
    params: [
      { k: 'length', label: 'длина', v: 90, step: 5 },
      { k: 'width', label: 'ширина', v: 45, step: 5 },
      { k: 'curl', label: 'изгиб', v: 0.25, step: 0.05 },
    ],
  },
  {
    op: 'ring', name: 'кольцо', title: 'Кольцо', group: 'Готовые фигуры',
    desc: 'Обод с плоскими сторонами и скруглёнными краями.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 20, step: 1 },
      { k: 'width', label: 'ширина', v: 6, step: 0.5 },
      { k: 'thickness', label: 'толщина', v: 2.2, step: 0.2 },
      { k: 'round', label: 'скругл.', v: 0.6, step: 0.1 },
    ],
  },
  {
    op: 'rail', name: 'направляющая', title: 'Направляющая', group: 'Механика',
    desc: 'П-образный профиль постоянного сечения для ящиков и станков.',
    params: [
      { k: 'length', label: 'длина', v: 400, step: 10 },
      { k: 'width', label: 'ширина', v: 30, step: 2 },
      { k: 'height', label: 'высота', v: 14, step: 1 },
      { k: 'wall', label: 'стенка', v: 2, step: 0.5 },
    ],
  },
  {
    op: 'profile2020', name: 'профиль', title: 'Конструкционный профиль', group: 'Механика',
    desc: 'Квадрат с четырьмя T-пазами и набором столбиков внутри (без круглого канала).',
    params: [
      { k: 'length', label: 'длина', v: 300, step: 10 },
      { k: 'size', label: 'сторона', v: 20, step: 1 },
      { k: 'slot', label: 'паз', v: 6, step: 0.5 },
      { k: 'columns', label: 'столбиков', v: 5, step: 1 },
      { k: 'smooth', label: 'сглаж.', v: 0.6, step: 0.1 },
    ],
  },
  {
    op: 'gusset', name: 'косынка', title: 'Косынка', group: 'Механика',
    desc: 'Треугольный лист жёсткости в прямой угол рамы; впадина на гипотенузе настраивается.',
    params: [
      { k: 'leg', label: 'катет', v: 70, step: 5 },
      { k: 'height', label: 'высота', v: 55, step: 5 },
      { k: 'thickness', label: 'толщина', v: 6, step: 1 },
      { k: 'notch', label: 'впадина', v: 16, step: 2 },
      { k: 'notch_shape', label: 'форма', v: 'ступени' },
    ],
  },
  {
    op: 'leg', name: 'ножка', title: 'Ножка мебели', group: 'Механика',
    desc: 'Опора под корпус: пятка на полу, площадка под саморезы сверху, сужение и регулировка.',
    params: [
      { k: 'height', label: 'высота', v: 90, step: 5 },
      { k: 'top', label: 'сверху', v: 34, step: 2 },
      { k: 'bottom', label: 'снизу', v: 22, step: 2 },
      { k: 'flange', label: 'площадка', v: 8, step: 1 },
      { k: 'shape', label: 'форма', v: 'круглая' },
      { k: 'adjust', label: 'пятка', v: 0, step: 1 },
    ],
  },
  {
    op: 'grommet', name: 'люверс', title: 'Люверс', group: 'Механика',
    desc: 'Втулка с бортиком под шнур или провод — блочка.',
    params: [
      { k: 'diameter', label: 'внутри', v: 12, step: 1 },
      { k: 'height', label: 'высота', v: 8, step: 1 },
      { k: 'wall', label: 'стенка', v: 1.6, step: 0.2 },
      { k: 'flange', label: 'борт', v: 3, step: 0.5 },
    ],
  },
  {
    op: 'worm_shaft', name: 'червяк', title: 'Червячный вал', group: 'Механика',
    desc: 'Цилиндр с настоящим винтовым витком: шаг, глубина, заходы.',
    params: [
      { k: 'length', label: 'длина', v: 90, step: 5 },
      { k: 'diameter', label: 'диаметр', v: 30, step: 2 },
      { k: 'pitch', label: 'шаг', v: 8, step: 1 },
      { k: 'depth', label: 'виток', v: 4, step: 0.5 },
    ],
  },
  {
    op: 'horn', name: 'рог', title: 'Рог', group: 'Природа',
    desc: 'Изогнутый сужающийся рог — природа, трофей, декор.',
    params: [
      { k: 'length', label: 'длина', v: 160, step: 10 },
      { k: 'radius', label: 'основание', v: 22, step: 2 },
      { k: 'tip', label: 'кончик', v: 3, step: 0.5 },
      { k: 'bend', label: 'изгиб', v: 55, step: 5 },
    ],
  },
];

const TOOL_RECIPES = [
  {
    title: 'Наполнение',
    desc: 'Сыплет зёрна в открытую посуду: тарелка, миска, ящик. Уровень, плотность и seed '
      + 'задают раскладку — одна и та же строка всегда даёт одну и ту же кашу.',
    fields: [
      { k: 'd', label: '⌀ посуды', v: 180 },
      { k: 'depth', label: 'глубина', v: 55 },
      { k: 'grain', label: 'зерно', v: 'зерно', kind: 'raw' },
      { k: 'size', label: 'размер', v: 7 },
      { k: 'level', label: 'уровень', v: 0.75 },
      { k: 'dome', label: 'горб', v: 0 },
      { k: 'seed', label: 'seed', v: 3 },
    ],
    build: (v) => {
      const d = rnum(v.d, 180);
      const dep = rnum(v.depth, 55);
      const g = String(v.grain || 'зерно').trim() || 'зерно';
      const dome = rnum(v.dome, 0);
      const hump = dome > 0 ? ` dome=${fnum(dome)}` : '';
      return `посуда = plate diameter=${fnum(d)} depth=${fnum(dep)} wall=4\n`
        + `наполнение = fill [посуда] grain=${g} size=${fnum(v.size, 7)} `
        + `level=${fnum(v.level, 0.75)} density=0.7${hump} seed=${fnum(v.seed, 3)}`;
    },
  },
  {
    title: 'Горка',
    desc: 'Насыпь из мелких деталей на плоскости: галька, песок, конфеты. '
      + 'Профиль — округлый конус; можно дать готовый предмет — горка сложится из его копий.',
    fields: [
      { k: 'r', label: 'радиус', v: 110 },
      { k: 'h', label: 'высота', v: 48 },
      { k: 'grain', label: 'зерно', v: 'галька', kind: 'raw' },
      { k: 'size', label: 'размер', v: 15 },
      { k: 'seed', label: 'seed', v: 5 },
      { k: 'base', label: 'подложка', v: 0 },
    ],
    build: (v) => {
      const g = String(v.grain || 'галька').trim() || 'галька';
      const base = rnum(v.base, 0);
      const pad = base > 0 ? ` base=${fnum(base)}` : '';
      return `горка = pile radius=${fnum(v.r, 110)} height=${fnum(v.h, 48)} `
        + `grain=${g} size=${fnum(v.size, 15)}${pad} seed=${fnum(v.seed, 5)}`;
    },
  },
  {
    title: 'Массив по кругу',
    desc: 'Копии предмета на окружности: полный круг или сектор. spin=да поворачивает '
      + 'каждую копию вокруг своей оси — детали смотрят наружу.',
    fields: [
      { k: 'obj', label: 'объект', v: '', kind: 'raw' },
      { k: 'count', label: 'копий', v: 8 },
      { k: 'radius', label: 'радиус', v: 60 },
      { k: 'angle', label: 'угол', v: 360 },
      { k: 'spin', label: 'поворот', v: true, kind: 'bool' },
    ],
    build: (v) => {
      let obj = String(v.obj || '').trim();
      let head = '';
      if (!obj) {                      // пусто — соберём показательную стойку
        obj = 'стойка';
        head = 'стойка = cylinder radius=6 height=60\n';
      }
      const count = Math.max(1, Math.round(rnum(v.count, 8)));
      const rad = Math.max(0, rnum(v.radius, 60));
      const ang = rnum(v.angle, 360);
      const spin = v.spin ? 'да' : 'нет';
      return head + `кольцо = array [${obj}] count=${count} mode=radial radius=${fnum(rad)} `
        + `angle=${fnum(ang)} around=z spin=${spin}`;
    },
  },
  {
    title: 'Кружка',
    desc: 'Корпус, полость и ручка: ручка врезается в стенку, полость вычитается повторно — внутри сухо.',
    fields: [
      { k: 'd', label: '⌀', v: 68 },
      { k: 'h', label: 'высота', v: 95 },
      { k: 'wall', label: 'стенка', v: 4 },
      { k: 'handle', label: 'ручка', v: true, kind: 'bool' },
    ],
    build: (v) => {
      const r = rnum(v.d, 68) / 2;
      const h = rnum(v.h, 95);
      const w = Math.max(1.5, rnum(v.wall, 4));
      const ri = Math.max(2, r - w);
      const hi = Math.max(6, h - w * 1.5);
      const out = `корпус = cylinder radius=${fnum(r)} height=${fnum(h)} r2=${fnum(r * 1.18)} segments=128\n`
        + `полость = cylinder radius=${fnum(ri)} height=${fnum(hi)} r2=${fnum(ri * 1.2)} segments=128\n`
        + `полость = translate [полость] offset=[0,0,${fnum(w * 1.5)}]\n`
        + `кружка = difference [корпус, полость]\n`;
      if (!v.handle) return out + 'color кружка #ece7df rough=0.35';
      const dx = r - 1;
      return out
        + `ручка = sweep path=[[${fnum(dx)},0,${fnum(h * 0.25)}],[${fnum(dx + 14)},0,${fnum(h * 0.28)}],`
        + `[${fnum(dx + 22)},0,${fnum(h * 0.52)}],[${fnum(dx + 14)},0,${fnum(h * 0.77)}],`
        + `[${fnum(dx + 3)},0,${fnum(h * 0.81)}]] radius=4.6 smooth=10\n`
        + 'кружка = union [кружка, ручка]\n'
        + `полость = cylinder radius=${fnum(ri)} height=${fnum(hi)} r2=${fnum(ri * 1.2)} segments=128\n`
        + `полость = translate [полость] offset=[0,0,${fnum(w * 1.5)}]\n`
        + 'кружка = difference [кружка, полость]\n'
        + 'color кружка #ece7df rough=0.35';
    },
  },
  {
    title: 'Накатка',
    desc: 'Рифление по окружности: число канавок и глубина. Ручки, винты, крышки.',
    fields: [
      { k: 'd', label: '⌀', v: 32 },
      { k: 'h', label: 'высота', v: 70 },
      { k: 'count', label: 'канавок', v: 24 },
      { k: 'depth', label: 'глубина', v: 1 },
    ],
    build: (v) => `заготовка = cylinder radius=${fnum(rnum(v.d, 32) / 2)} height=${fnum(rnum(v.h, 70))} segments=96\n`
      + `заготовка = knurl [заготовка] count=${Math.max(6, Math.round(rnum(v.count, 24)))} depth=${fnum(rnum(v.depth, 1))}\n`
      + 'color заготовка #b9bec6 metal=0.6 rough=0.35',
  },
  {
    title: 'Скрутка',
    desc: 'Брусок превращается в витую колонну: twist закручивает верх на заданный угол.',
    fields: [
      { k: 'w', label: 'ширина', v: 40 },
      { k: 'h', label: 'высота', v: 200 },
      { k: 'angle', label: 'угол', v: 180 },
    ],
    build: (v) => `скрутка = box size=[${fnum(rnum(v.w, 40))},${fnum(rnum(v.w, 40))},${fnum(rnum(v.h, 200))}] round=3\n`
      + `скрутка = twist [скрутка] angle=${fnum(rnum(v.angle, 180))} axis=z`,
  },
  {
    title: 'Изгиб',
    desc: 'bend гнёт деталь по дуге — поручни, дуги, скобы. Угол и сечение свои.',
    fields: [
      { k: 'w', label: 'ширина', v: 24 },
      { k: 'l', label: 'длина', v: 160 },
      { k: 'h', label: 'размах', v: 240 },
      { k: 'angle', label: 'угол', v: 90 },
    ],
    build: (v) => `дуга = box size=[${fnum(rnum(v.w, 24))},${fnum(rnum(v.l, 160))},${fnum(rnum(v.h, 240))}] round=5\n`
      + `дуга = bend [дуга] angle=${fnum(rnum(v.angle, 90))}`,
  },
  {
    title: 'Надпись',
    desc: 'Объёмный текст своим шрифтом — без сторонних файлов и шрифтов в системе.',
    fields: [
      { k: 'word', label: 'текст', v: 'ПРИВЕТ', kind: 'raw' },
      { k: 'size', label: 'высота', v: 10 },
      { k: 'depth', label: 'толщина', v: 2 },
    ],
    build: (v) => `надпись = text "${String(v.word || 'ПРИВЕТ').replace(/"/g, '')}" `
      + `size=${fnum(rnum(v.size, 10))} depth=${fnum(rnum(v.depth, 2))}\n`
      + 'color надпись #e8c27a',
  },
  {
    title: 'Резьба: гайка',
    desc: 'Внутренняя резьба: гайка накручивается на болт того же шага.',
    fields: [
      { k: 'd', label: '⌀', v: 17 },
      { k: 'h', label: 'высота', v: 7 },
      { k: 'pitch', label: 'шаг', v: 1.5 },
    ],
    build: (v) => `гайка_резьба = thread diameter=${fnum(rnum(v.d, 17))} length=${fnum(rnum(v.h, 7))} `
      + `pitch=${fnum(rnum(v.pitch, 1.5))} internal=true`,
  },
  {
    title: 'Фаска',
    desc: 'Снимает наружные рёбра: на простых деталях — радиусом, на сложных — фаской 45°.',
    fields: [
      { k: 'size', label: 'размер', v: '60,40,20', kind: 'vec' },
      { k: 'radius', label: 'фаска', v: 3 },
      { k: 'mode', label: 'режим', v: 'авто', kind: 'raw' },
    ],
    build: (v) => `плита_фаска = box size=[${rvec(v.size, [60, 40, 20]).join(', ')}]\n`
      + `плита_фаска = bevel [плита_фаска] radius=${fnum(rnum(v.radius, 3))} mode=${v.mode || 'авто'}`,
  },
  {
    title: 'Облегчение',
    desc: 'Упрощение сетки с контролем отклонения — деталь легче для печати и рендера.',
    fields: [
      { k: 'size', label: 'размер', v: '60,40,20', kind: 'vec' },
      { k: 'deviation', label: 'допуск', v: 0.2 },
    ],
    build: (v) => `плита_лёгкая = box size=[${rvec(v.size, [60, 40, 20]).join(', ')}]\n`
      + `плита_лёгкая = simplify [плита_лёгкая] deviation=${fnum(rnum(v.deviation, 0.2))}`,
  },
  {
    title: 'Уклон',
    desc: 'Технологический уклон стенок — деталь вынимается из формы без поднутрений.',
    fields: [
      { k: 'size', label: 'размер', v: '80,50,10', kind: 'vec' },
      { k: 'angle', label: 'угол', v: 2 },
    ],
    build: (v) => `плита_уклон = box size=[${rvec(v.size, [80, 50, 10]).join(', ')}]\n`
      + `плита_уклон = draft [плита_уклон] angle=${fnum(rnum(v.angle, 2))}`,
  },
  {
    title: 'Отверстия сеткой',
    desc: 'Один вызов holes вместо десятка difference: сетка, шаг, сдвиг сетки по детали.',
    fields: [
      { k: 'size', label: 'размер', v: '200,120,8', kind: 'vec' },
      { k: 'grid', label: 'сетка', v: '4,3', kind: 'vec' },
      { k: 'diameter', label: '⌀', v: 8 },
      { k: 'pitch', label: 'шаг', v: '40,30', kind: 'vec' },
      { k: 'offset', label: 'сдвиг', v: '0,0', kind: 'vec' },
    ],
    build: (v) => {
      const grid = rvec(v.grid, [4, 3]);
      const pitch = rvec(v.pitch, [40, 30]);
      const offset = rvec(v.offset, [0, 0]);
      let line = `панель_дыр = holes [панель_дыр] grid=[${grid.join(', ')}] `
        + `diameter=${fnum(rnum(v.diameter, 8))} pitch=[${pitch.join(', ')}]`;
      if (Math.abs(offset[0]) > 1e-9 || Math.abs(offset[1] || 0) > 1e-9) {
        line += ` offset=[${offset.join(', ')}]`;
      }
      return `панель_дыр = box size=[${rvec(v.size, [200, 120, 8]).join(', ')}] round=3\n` + line;
    },
  },
  {
    title: 'Разброс деталей',
    desc: 'scatter раскладывает копии по площади; seed повторяет раскладку.',
    fields: [
      { k: 'count', label: 'штук', v: 24 },
      { k: 'area', label: 'площадь', v: '500,400', kind: 'vec' },
      { k: 'scale', label: 'масштаб', v: '0.7,1.3', kind: 'vec' },
      { k: 'seed', label: 'seed', v: 7 },
    ],
    build: (v) => `камень_разброс = rock size=[120,90,55] seed=3\n`
      + `камни = scatter [камень_разброс] count=${Math.max(2, Math.round(rnum(v.count, 24)))} `
      + `area=[${rvec(v.area, [500, 400]).join(', ')}] seed=${Math.round(rnum(v.seed, 7))} `
      + `scale=[${rvec(v.scale, [0.7, 1.3]).join(', ')}]`,
  },
  {
    title: 'Выпуклая оболочка',
    desc: 'hull обтягивает детали оболочкой — кузова, скульптуры, капсулы.',
    fields: [
      { k: 'r', label: 'радиус', v: 60 },
      { k: 'h', label: 'высота', v: 50 },
      { k: 'top', label: 'верх', v: 90 },
    ],
    build: (v) => `низ_оболочки = prism sides=6 radius=${fnum(rnum(v.r, 60))} height=${fnum(rnum(v.h, 50))}\n`
      + `верх_оболочки = sphere radius=${fnum(rnum(v.r, 60) * 0.92)} at=[0,0,${fnum(rnum(v.top, 90))}]\n`
      + 'оболочка = hull objects=[низ_оболочки, верх_оболочки]',
  },
  {
    title: 'Корпус с полостью',
    desc: 'shell выдалбливает деталь с заданной стенкой и открытым верхом — корпус, ящик, лоток.',
    fields: [
      { k: 'size', label: 'размер', v: '120,80,50', kind: 'vec' },
      { k: 'thickness', label: 'стенка', v: 3 },
      { k: 'open', label: 'открыт', v: 'top', kind: 'raw' },
    ],
    build: (v) => `корпус_полый = box size=[${rvec(v.size, [120, 80, 50]).join(', ')}] round=4\n`
      + `корпус_полый = shell [корпус_полый] thickness=${fnum(rnum(v.thickness, 3))} open=${v.open || 'top'}`,
  },
  {
    title: 'Зеркальная пара',
    desc: 'mirror_copy оставляет деталь и добавляет её отражение — парные кронштейны, ручки.',
    fields: [
      { k: 'size', label: 'размер', v: '30,20,60', kind: 'vec' },
      { k: 'plane', label: 'плоскость', v: 'x', kind: 'raw' },
      { k: 'gap', label: 'зазор', v: 0 },
    ],
    build: (v) => {
      const size = rvec(v.size, [30, 20, 60]);
      const plane = (v.plane || 'x').toLowerCase();
      const gap = rnum(v.gap, 0);
      const at = [0, 0, 0];
      at[Math.max(0, 'xyz'.indexOf(plane))] = size[Math.max(0, 'xyz'.indexOf(plane))] / 2 + gap / 2;
      return `половина = box size=[${size.join(', ')}] round=3 at=[${at.map(fnum).join(',')}]\n`
        + `пара = mirror_copy [половина] plane=${plane} gap=${fnum(gap)}`;
    },
  },
  {
    title: 'Сечение',
    desc: 'section показывает контур разреза на заданной высоте — видно стенки и полости.',
    fields: [
      { k: 'z', label: 'высота Z', v: 10 },
    ],
    build: (v) => 'деталь_сечения = cube_hole size=[60,60,20] hole=16\n'
      + `section деталь_сечения z=${fnum(rnum(v.z, 10))}`,
  },
  {
    title: 'Проба материала',
    desc: 'probe отвечает, есть ли материал в точке — проверка стенки и полости.',
    fields: [
      { k: 'x', label: 'X', v: 0 },
      { k: 'y', label: 'Y', v: 0 },
      { k: 'z', label: 'Z', v: 10 },
    ],
    build: (v) => 'деталь_пробы = cube_hole size=[60,60,20] hole=16\n'
      + `probe деталь_пробы x=${fnum(rnum(v.x, 0))} y=${fnum(rnum(v.y, 0))} z=${fnum(rnum(v.z, 10))}`,
  },
  {
    title: 'Паспорт детали',
    desc: 'passport выводит габарит, объём, массу, число треугольников и герметичность.',
    fields: [],
    build: () => 'деталь_паспорта = cube_hole size=[60,60,20] hole=16\n'
      + 'passport деталь_паспорта',
  },
];

/** Число из поля рецепта: пустое или мусор — значение по умолчанию. */
function rnum(raw, fallback) {
  const n = Number(String(raw).replace(',', '.').replace(/\s+/g, ''));
  return Number.isFinite(n) ? n : fallback;
}

/** Вектор из поля рецепта: «40, 30» → [40, 30]. */
function rvec(raw, fallback) {
  const nums = String(raw).split(/[;,\s]+/).filter(Boolean).map(Number).filter(Number.isFinite);
  return nums.length ? nums : fallback;
}

/** Число в сценарии без хвоста нулей: 34.5, 70, 0.35. */
function fnum(x) {
  const n = Number(x);
  if (!Number.isFinite(n)) return '0';
  return String(Math.round(n * 1000) / 1000);
}

/** Поля рецепта — те же, что у фигур: подпись + поле ввода. */
function recipeFields(params) {
  const wrap = document.createElement('div');
  wrap.className = 'tool-fields';
  (params || []).forEach((p) => {
    const label = document.createElement('label');
    label.className = 'tool-field';
    const caption = document.createElement('span');
    caption.textContent = p.label;
    let input;
    if (p.kind === 'bool') {
      input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = p.v !== false;
    } else {
      input = document.createElement('input');
      input.type = 'text';
      input.value = String(p.v);
      if (p.kind !== 'vec' && p.kind !== 'raw') input.inputMode = 'decimal';
      input.style.width = p.kind === 'vec' || p.kind === 'raw' ? '124px' : '58px';
    }
    input.dataset.key = p.k;
    label.append(caption, input);
    wrap.appendChild(label);
  });
  return wrap;
}

/** Значения полей рецепта в виде объекта. */
function recipeValues(recipe, card) {
  const values = {};
  (recipe.fields || []).forEach((p) => {
    const input = card.querySelector(`[data-key="${p.k}"]`);
    if (!input) return;
    values[p.k] = p.kind === 'bool' ? input.checked : input.value.trim();
  });
  return values;
}

function addRecipeTool(recipe, card) {
  const lines = recipe.build(recipeValues(recipe, card));
  insertTool(uniqueExample(lines, currentScript()), recipe.title);
}

function uniqueObjectName(name, script) {
  const used = new Set(String(script).split('\n')
    .map((line) => (line.includes('=') ? line.split('=')[0].trim() : ''))
    .filter(Boolean));
  if (!used.has(name)) return name;
  let i = 2;
  while (used.has(`${name}_${i}`)) i += 1;
  return `${name}_${i}`;
}

function insertTool(lines, label) {
  const script = currentScript().replace(/\s+$/, '');
  const text = (script ? script + '\n' : '') + `# инструмент: ${label}\n` + lines + '\n';
  setScript(text, { label: 'инструмент: ' + label });
  toast(`Добавлено: ${label}`);
}

function addShapeTool(tool, card) {
  const parts = [];
  tool.params.forEach((p) => {
    const input = card.querySelector(`[data-key="${p.k}"]`);
    if (!input) return;
    if (p.kind === 'bool') {
      parts.push(`${p.k}=${input.checked ? 'да' : 'нет'}`);
      return;
    }
    const raw = input.value.trim();
    if (!raw) return;
    if (p.kind === 'vec') {
      const nums = raw.split(/[,\s]+/).filter(Boolean);
      parts.push(`${p.k}=[${nums.join(', ')}]`);
    } else if (p.kind === 'raw') {
      parts.push(`${p.k}=${raw}`);
    } else {
      parts.push(`${p.k}=${raw}`);
    }
  });
  const name = uniqueObjectName(tool.name, currentScript());
  insertTool(`${name} = ${tool.op} ${parts.join(' ')}`, tool.title);
}

/** Переименовывает объекты примера, чтобы вставка не ломала имена. */
function uniqueExample(text, script) {
  const names = [...text.matchAll(/^([\wА-Яа-яЁё]+)\s*=/gm)].map((m) => m[1]);
  let out = text;
  names.forEach((name) => {
    const fresh = uniqueObjectName(name, script + '\n' + out);
    if (fresh === name) return;
    const esc = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    out = out.replace(new RegExp(`(?<![\\wА-Яа-яЁё])${esc}(?![\\wА-Яа-яЁё])`, 'g'), fresh);
  });
  return out;
}

/** Карточка команды, собранная из справочника: описание, параметры, пример. */
function commandCard(c) {
  const card = document.createElement('div');
  card.className = 'tool-card tool-cmd';
  const head = document.createElement('div');
  head.className = 'tool-card-head';
  head.innerHTML = `<b>${escapeHtml(c.name)}</b><code>${escapeHtml((c.aliases || []).join(', ') || c.category)}</code>`;
  const desc = document.createElement('div');
  desc.className = 'tool-desc';
  desc.textContent = c.summary || '';
  card.append(head, desc);
  const params = document.createElement('div');
  params.className = 'tool-params';
  (c.params || []).forEach((p) => {
    const chip = document.createElement('span');
    chip.innerHTML = `<b>${escapeHtml(p.name)}</b> — ${escapeHtml(p.desc)}`;
    params.appendChild(chip);
  });
  if (params.children.length) card.appendChild(params);
  if (c.example) {
    const pre = document.createElement('pre');
    pre.textContent = c.example;
    card.appendChild(pre);
  }
  card.dataset.search = [c.name, (c.aliases || []).join(' '), c.category, c.summary,
    ...(c.params || []).map((p) => p.name + ' ' + p.desc)].join(' ').toLowerCase();
  if (c.example) {
    const btn = document.createElement('button');
    btn.className = 'small primary';
    btn.textContent = 'Вставить пример';
    btn.addEventListener('click', () => insertTool(
      `# ${c.name}: пример из справочника\n` + uniqueExample(c.example, currentScript()),
      c.name));
    card.appendChild(btn);
  }
  return card;
}

function renderTools() {
  const body = $('tools-body');
  if (!body) return;
  body.innerHTML = '';
  const groups = new Map();
  TOOL_SHAPES.forEach((tool) => {
    const key = tool.group || 'Готовые фигуры';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(tool);
  });
  groups.forEach((tools, title) => {
    const section = document.createElement('div');
    section.className = 'tool-group';
    const head = document.createElement('h4');
    head.textContent = title;
    const grid = document.createElement('div');
    grid.className = 'tool-grid';
    section.appendChild(head);
    section.appendChild(grid);
    tools.forEach((tool) => {
      const card = document.createElement('div');
      card.className = 'tool-card';
      const cardHead = document.createElement('div');
      cardHead.className = 'tool-card-head';
      cardHead.innerHTML = `<b>${escapeHtml(tool.title)}</b><code>${escapeHtml(tool.op)}</code>`;
      card.appendChild(cardHead);
      const desc = document.createElement('div');
      desc.className = 'tool-desc';
      desc.textContent = tool.desc;
      card.appendChild(desc);
      const fields = document.createElement('div');
      fields.className = 'tool-fields';
      tool.params.forEach((p) => {
        const label = document.createElement('label');
        label.className = 'tool-field';
        const caption = document.createElement('span');
        caption.textContent = p.label;
        let input;
        if (p.kind === 'bool') {
          input = document.createElement('input');
          input.type = 'checkbox';
          input.checked = p.v !== false;
        } else {
          input = document.createElement('input');
          input.type = 'text';
          input.value = String(p.v);
          if (p.kind !== 'vec' && p.kind !== 'raw') input.inputMode = 'decimal';
          input.style.width = p.kind === 'vec' || p.kind === 'raw' ? '124px' : '58px';
        }
        input.dataset.key = p.k;
        label.appendChild(caption);
        label.appendChild(input);
        fields.appendChild(label);
      });
      card.appendChild(fields);
      card.dataset.search = [tool.title, tool.op, tool.name, tool.desc, title,
        ...tool.params.map((p) => p.label)].join(' ').toLowerCase();
      const btn = document.createElement('button');
      btn.className = 'small primary';
      btn.textContent = 'Добавить';
      btn.addEventListener('click', () => addShapeTool(tool, card));
      card.appendChild(btn);
      grid.appendChild(card);
    });
    body.appendChild(section);
  });

  const recipes = document.createElement('div');
  recipes.className = 'tool-group';
  const recipesHead = document.createElement('h4');
  recipesHead.textContent = 'Приёмы';
  recipes.appendChild(recipesHead);
  const rgrid = document.createElement('div');
  rgrid.className = 'tool-grid';
  TOOL_RECIPES.forEach((recipe) => {
    const card = document.createElement('div');
    card.className = 'tool-card tool-recipe';
    const head = document.createElement('div');
    head.className = 'tool-card-head';
    head.innerHTML = `<b>${escapeHtml(recipe.title)}</b><code>приём</code>`;
    card.appendChild(head);
    const desc = document.createElement('div');
    desc.className = 'tool-desc';
    desc.textContent = recipe.desc;
    card.appendChild(desc);
    const fields = recipeFields(recipe.fields);
    if (fields.children.length) card.appendChild(fields);
    const pre = document.createElement('pre');
    card.appendChild(pre);
    const refresh = () => {
      pre.textContent = recipe.build(recipeValues(recipe, card));
    };
    fields.addEventListener('input', refresh);
    refresh();
    card.dataset.search = [recipe.title, recipe.desc,
      ...(recipe.fields || []).map((p) => p.label)].join(' ').toLowerCase();
    const btn = document.createElement('button');
    btn.className = 'small primary';
    btn.textContent = 'Вставить';
    btn.addEventListener('click', () => addRecipeTool(recipe, card));
    card.appendChild(btn);
    rgrid.appendChild(card);
  });
  recipes.appendChild(rgrid);
  body.appendChild(recipes);

  // Все команды из справочника — у каждой своя карточка с параметрами и примером.
  const commands = state.help || [];
  const order = [];
  const byCat = new Map();
  commands.forEach((c) => {
    const key = c.category || 'Прочее';
    if (!byCat.has(key)) { byCat.set(key, []); order.push(key); }
    byCat.get(key).push(c);
  });
  order.forEach((cat) => {
    const section = document.createElement('div');
    section.className = 'tool-group tool-group-cmd';
    const head = document.createElement('h4');
    head.textContent = `Все команды · ${cat} · ${byCat.get(cat).length}`;
    const grid = document.createElement('div');
    grid.className = 'tool-grid';
    section.append(head, grid);
    byCat.get(cat).forEach((c) => grid.appendChild(commandCard(c)));
    body.appendChild(section);
  });
  applyToolsFilter();
}

/** Поиск по инструментам: фильтрует карточки и прячет пустые группы. */
function applyToolsFilter() {
  const q = ($('tools-search')?.value || '').trim().toLowerCase();
  const body = $('tools-body');
  if (!body) return;
  let shown = 0;
  let total = 0;
  body.querySelectorAll('.tool-group').forEach((group) => {
    let visible = 0;
    group.querySelectorAll('.tool-card').forEach((card) => {
      total += 1;
      const hit = !q || (card.dataset.search || '').includes(q);
      card.hidden = !hit;
      if (hit) visible += 1;
    });
    group.hidden = visible === 0;
    shown += visible;
  });
  const label = $('tools-count');
  if (label) label.textContent = q ? `нашлось ${shown} из ${total}` : `всего ${total}`;
}
$('tools-search')?.addEventListener('input', applyToolsFilter);

function openTools() {
  $('tools-modal').hidden = false;
  renderTools();
}
$('btn-tools')?.addEventListener('click', openTools);
$('tools-close')?.addEventListener('click', () => { $('tools-modal').hidden = true; });
$('tools-modal')?.addEventListener('click', (e) => {
  if (e.target === $('tools-modal')) $('tools-modal').hidden = true;
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('tools-modal').hidden) $('tools-modal').hidden = true;
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
$('btn-undo')?.addEventListener('click', undo);
$('btn-redo')?.addEventListener('click', redo);
$('btn-history')?.addEventListener('click', () => {
  const panel = $('history-panel');
  if (!panel) return;
  panel.hidden = !panel.hidden;
  if (!panel.hidden) { renderHistory(); panel.scrollIntoView({ block: 'nearest' }); }
});
$('history-close')?.addEventListener('click', () => { $('history-panel').hidden = true; });
$('btn-format')?.addEventListener('click', () => {
  const lines = currentScript().split('\n').map((l) => l.replace(/[ \t]+$/, ''));
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
  setScript(lines.join('\n'));
  toast('Сценарий выровнен');
});

async function loadExample(key, name = '') {
  try {
    const res = await api('/api/example?key=' + encodeURIComponent(key));
    state.projectName = name || key;
    state.userHidden.clear();
    state.hidden.clear();
    if (state.viewer?.hidden) state.viewer.hidden.clear();
    setScript(res.script, { label: 'пример: ' + (name || key) });
    toast('Готовый сценарий загружен: ' + (name || key));
  } catch (e) { toast(e.message || 'Не удалось загрузить сценарий', 'bad'); }
}

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
    if (tab.dataset.tab === 'links') renderLinks();
  });
});

function openHelp() {
  $('help-modal').hidden = false;
  $('help-search').focus();
}
$('btn-help').addEventListener('click', openHelp);
$('help-close').addEventListener('click', () => { $('help-modal').hidden = true; });
// Закрываем только если и нажали, и отпустили на затемнении: иначе выделение
// текста мышью с «вылетом» за карточку закрывало справочник.
let helpBackdropDown = false;
$('help-modal').addEventListener('mousedown', (e) => {
  helpBackdropDown = (e.target === $('help-modal'));
});
$('help-modal').addEventListener('mouseup', (e) => {
  if (helpBackdropDown && e.target === $('help-modal')) $('help-modal').hidden = true;
  helpBackdropDown = false;
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('help-modal').hidden) $('help-modal').hidden = true;
});

async function copyText(text, okMsg = 'Скопировано') {
  try {
    await navigator.clipboard.writeText(text);
    toast(okMsg);
    return true;
  } catch (err) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand && document.execCommand('copy');
    ta.remove();
    toast(ok ? okMsg : 'Не удалось скопировать', ok ? '' : 'bad');
    return !!ok;
  }
}

$('help-modal').addEventListener('click', (e) => {
  const btn = e.target.closest && e.target.closest('.cmd-copy');
  if (!btn) return;
  const card = btn.closest('.cmd-card');
  const pre = card && card.querySelector('pre');
  copyText(pre ? pre.textContent : (card ? card.textContent.trim() : ''));
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
        ${c.example ? `<div class="cmd-example"><pre>${escapeHtml(c.example)}</pre>
          <button class="mini cmd-copy" title="Скопировать пример">⧉</button></div>` : ''}`;
      g.appendChild(card);
    });
    body.appendChild(g);
  });
}

$('help-search').addEventListener('input', (e) => renderHelp(e.target.value));

$('btn-copy-report')?.addEventListener('click', copyReport);
$('btn-to-prompt')?.addEventListener('click', () => {
  document.querySelector('.tab[data-tab="assist"]')?.click();
  $('goal')?.focus();
  toast('Опишите задачу и нажмите «Сформировать запрос»');
});

$('btn-prompt').addEventListener('click', async () => {
  try {
    const res = await api('/api/prompt', {
      script: currentScript(), goal: $('goal').value,
      reference: $('with-reference') ? $('with-reference').checked : true,
    });
    if ($('with-reference')?.checked) localStorage.setItem('forma_reference_shown', '1');
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
    state.notes = st.notes || [];
    state.actions = st.actions || [];
    renderNotes();
    renderActions();
    const ref = $('with-reference');
    if (ref) {
      const seen = localStorage.getItem('forma_reference_shown') === '1';
      ref.checked = !seen;
    }
    if (st.blender?.found) {
      $('status-blender').textContent = 'Blender найден';
      $('status-blender').title = st.blender.path;
    }
    renderProjects();
    renderHelp();
    setScript(st.script, { build: false, record: false });
    state.editBaseline = st.script;
    updateUndoButtons();
    renderHistory();
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
