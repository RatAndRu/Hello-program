import { Viewer } from './viewer.js';
import { encodeGif, downloadBlob } from './gif.js';
import { Preview3D } from './preview3d.js';
import { installPanelLayout } from './panels.js';
import { ToolThumbs } from './toolpreview.js';

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
  panels: null,
  lastSaved: null,
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

/**
 * Отдаёт готовый файл серверу, чтобы тот положил его в «Загрузки».
 *
 * Обычная ссылка `<a download>` кладёт файл туда, куда решит браузер, и
 * приложение об этом не узнаёт — именно поэтому записи анимации «никуда не
 * сохранялись». Здесь байты уходят на `/api/save-file`, сервер пишет копию в
 * папку данных и в «Загрузки», а в ответ приходит точный путь.
 * Если сервер недоступен, остаётся прежнее скачивание — файл не теряется.
 */
async function saveBlob(blob, filename) {
  try {
    const url = `/api/save-file?name=${encodeURIComponent(filename)}&token=${encodeURIComponent(TOKEN)}`;
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: blob,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw data.error || new Error('Сервер не принял файл');
    return data;
  } catch (err) {
    downloadBlob(blob, filename);
    toast(`Сохранил через браузер: ${filename}`, 'warn');
    return { name: filename, browser: true, path: '', error: err?.message || String(err) };
  }
}

/**
 * Экспорт уже лёг в «Загрузки» на стороне сервера — второй раз через браузер
 * его не скачиваем, иначе рядом появляется копия «имя (1).ext».
 * Показываем точный путь и кнопку «открыть Загрузки».
 */
function exportSaved(res, what = 'Файл сохранён') {
  const path = res?.path || '';
  const dir = path ? path.slice(0, Math.max(path.lastIndexOf('/'), path.lastIndexOf(String.fromCharCode(92))) + 1) : (res?.downloads || '');
  toastSaved({ name: res?.name || '', path, downloads: dir }, what);
  return res;
}

/** Пишет в подсказку точный путь и предлагает открыть папку. */
function toastSaved(res, what = 'Сохранено') {
  const path = res?.path || res?.downloads || res?.name || '';
  toast(`${what}: ${path}`);
  if (res?.downloads || res?.path) {
    state.lastSaved = res;
    const btn = $('btn-open-downloads');
    if (btn) btn.hidden = false;
  }
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
    const sent = currentScript();
    const payload = await api('/api/build', { script: sent, auto: silent });
    state.payload = payload;
    state.builtScript = payload.ok ? sent : state.builtScript;
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
  // бюджет кубической сетки: после сборки подсвечиваем, вписались ли в него
  if (state.spaceMode && state.space) updateSpaceUI(state.space);
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
  if (state.viewer) {
    state.viewer.objectAxes = Object.fromEntries((state.payload?.objects || [])
      .map((o) => [o.name, o.axes || null]));
  }
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
  // Меню живёт прямо в body и позиционируется по экранным координатам курсора.
  // Раньше оно лежало внутри панели модели и отсчитывалось от её левого
  // верхнего угла — отсюда «далеко справа и снизу».
  menu.hidden = false;
  menu.style.visibility = 'hidden';
  menu.style.left = '0px';
  menu.style.top = '0px';
  const rect = menu.getBoundingClientRect();
  const gap = 6;
  let left = x + gap;
  let top = y + gap;
  if (left + rect.width > window.innerWidth - 8) left = Math.max(8, x - rect.width - gap);
  if (top + rect.height > window.innerHeight - 8) top = Math.max(8, y - rect.height - gap);
  menu.style.left = `${Math.round(left)}px`;
  menu.style.top = `${Math.round(top)}px`;
  menu.style.visibility = '';
}

document.addEventListener('pointerdown', (e) => {
  const menu = $('ctx-menu');
  if (menu && !menu.hidden && !menu.contains(e.target)) menu.hidden = true;
});
window.addEventListener('blur', () => { const m = $('ctx-menu'); if (m) m.hidden = true; });
window.addEventListener('resize', () => { const m = $('ctx-menu'); if (m) m.hidden = true; });
document.addEventListener('scroll', (e) => {
  const m = $('ctx-menu');
  if (m && !m.hidden) m.hidden = true;
  void e;
}, true);

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
$('btn-spin')?.addEventListener('click', (e) => {
  const on = !e.currentTarget.classList.contains('active');
  e.currentTarget.classList.toggle('active', on);
  state.viewer?.setSpin(on);
});
$('btn-shot').addEventListener('click', async () => {
  if (!state.viewer) return;
  const dataUrl = state.viewer.screenshot();
  if (!dataUrl) { toast('Не удалось снять картинку', 'bad'); return; }
  const name = 'форма_3d_' + Date.now() + '.png';
  try {
    const blob = await (await fetch(dataUrl)).blob();
    const saved = await saveBlob(blob, name);
    toastSaved(saved, 'Снимок');
  } catch (err) {
    const link = document.createElement('a');
    link.href = dataUrl;
    link.download = name;
    link.click();
  }
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

/** Текущий вид сцены — то, что живёт в строке scene. */
function currentViewSettings() {
  const s = state.viewSettings ? { ...state.viewSettings } : {};
  return {
    bg: $('bg-color')?.value || s.bg || '#0b0e13',
    env: document.querySelector('#env-chips .chip.active')?.dataset.env || s.env || 'studio',
    exposure: Number($('exposure')?.value ?? s.exposure ?? 1.05),
    shadows: $('opt-shadows') ? $('opt-shadows').checked : s.shadows !== false,
    grid: $('opt-grid') ? $('opt-grid').checked : s.grid !== false,
    ground: $('opt-ground') ? $('opt-ground').checked : s.ground !== false,
    axes: $('opt-axes') ? $('opt-axes').checked : s.axes !== false,
    poly: $('opt-poly') ? $('opt-poly').checked : s.poly === true,
    bloom: Number($('bloom')?.value ?? s.bloom ?? 0.6),
  };
}

/** Строка сценария для текущего вида: ползунки не должны слетать. */
function sceneCommand(v = currentViewSettings()) {
  const yn = (b) => (b ? 'да' : 'нет');
  const parts = [`bg=${v.bg}`, `env=${v.env}`, `exposure=${v.exposure.toFixed(2)}`,
    `shadows=${yn(v.shadows)}`, `grid=${yn(v.grid)}`, `ground=${yn(v.ground)}`,
    `axes=${yn(v.axes)}`, `poly=${yn(v.poly)}`];
  if (v.bloom > 0.001) parts.push(`bloom=${v.bloom.toFixed(2)}`);
  return 'scene ' + parts.join(' ');
}

/** Переписывает строку scene в сценарии — без пересборки: вид уже на экране. */
function writeViewScript() {
  const v = currentViewSettings();
  state.viewSettings = v;
  const lines = currentScript().split('\n').filter((l) => {
    const t = l.trim().toLowerCase();
    return !['scene', 'сцена', 'окружение', 'фон', 'view'].some(
      (cmd) => t === cmd || t.startsWith(cmd + ' '));
  });
  const body = lines.join('\n').replace(/\s+$/, '');
  const text = (body ? body + '\n' : '') + sceneCommand(v);
  if (text === currentScript()) return;
  // в историю эти правки не пишем: вид не должен забивать отмену
  setScript(text, { build: false, record: false, label: 'вид сцены' });
}

function clearScriptNow() {
  if (!currentScript().trim()) {
    toast('Сценарий уже пуст');
    return;
  }
  if (!confirm('Удалить весь сценарий? Шаг отменяется кнопкой ↶ или Ctrl+Z.')) return;
  setScript('', { label: 'очистка сценария' });
  toast('Сценарий очищен');
}

function clearSceneNow() {
  const objects = state.payload?.objects || [];
  if (!objects.length) {
    toast('Сцена уже пуста');
    return;
  }
  if (!confirm(`Убрать все предметы (${objects.length})? Свет, фон и стиль останутся.`)) return;
  const dropLines = new Set(objects.map((o) => Number(o.line) || 0).filter((n) => n > 0));
  const names = new Set(objects.map((o) => o.name));
  // номера строк относятся к тому сценарию, который реально собирался
  const source = (state.builtScript || currentScript());
  const lines = source.split('\n');
  const kept = lines.filter((line, i) => {
    if (dropLines.has(i + 1)) return false;
    const t = line.trim();
    const m = /^(color|цвет|texture|material|материал|кисть|brush|ластик|eraser|покраска|paint)\s+(\S+)/i
      .exec(t);
    if (!m) return true;
    const target = m[2].replace(/[,;]$/, '');
    return !(names.has(target) || names.has(target.split('.')[0]));
  });
  const text = kept.join('\n').replace(/\n{3,}/g, '\n\n').trim();
  if (!text) {
    setScript('', { label: 'очистка сцены' });
  } else {
    setScript(text, { label: 'очистка сцены' });
  }
  toast('Сцена очищена — свет и стиль на месте');
}

function applyViewSettings(payload) {
  const s = payload.settings || {};
  // Пустой объект = в сценарии стиля нет: выбор пользователя в окне не трогаем,
  // иначе стиль сбрасывался бы при каждой пересборке модели.
  if (s.anime !== undefined && s.anime && Object.keys(s.anime).length) {
    state.anime = (s.anime.mode && s.anime.mode !== 'выкл')
      ? Object.assign({}, s.anime) : { mode: 'выкл' };
    syncAnimeControls();
  }
  state.viewSettings = Object.assign({}, state.viewSettings, {
    bg: s.bg, env: s.env, exposure: s.exposure, shadows: s.shadows, grid: s.grid,
    ground: s.ground, axes: s.axes, poly: s.poly, bloom: s.bloom,
  });
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
  ['shadows', 'grid', 'ground', 'axes'].forEach((k) => {
    const el = $('opt-' + k);
    if (el) el.checked = s[k] !== false;
  });
  if ($('opt-poly')) $('opt-poly').checked = s.poly === true;
  if ($('bloom')) {
    const b = Number(s.bloom ?? 0.6);
    $('bloom').value = String(b);
    $('bloom-val').textContent = b.toFixed(2);
  }
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
    // фон окружения подставляем в поле цвета: иначе в строку scene попадёт
    // старый цвет и после пересборки фон «откатится»
    const envBg = state.viewer?.settings?.bg;
    if (envBg && $('bg-color')) {
      $('bg-color').value = envBg;
      $('bg-swatches')?.querySelectorAll('.swatch').forEach((sw) => {
        sw.classList.toggle('active', (sw.dataset.bg || '').toLowerCase() === envBg.toLowerCase());
      });
    }
    writeViewScript();
  });
});
$('bg-swatches')?.querySelectorAll('.swatch').forEach((sw) => {
  sw.addEventListener('click', () => {
    $('bg-swatches').querySelectorAll('.swatch').forEach((c) => c.classList.remove('active'));
    sw.classList.add('active');
    $('bg-color').value = sw.dataset.bg;
    state.viewer?.setBackground(sw.dataset.bg);
    writeViewScript();
  });
});
let viewScriptTimer = 0;
function scheduleViewScript() {
  clearTimeout(viewScriptTimer);
  viewScriptTimer = setTimeout(writeViewScript, 260);
}
$('bg-color')?.addEventListener('input', (e) => {
  $('bg-swatches')?.querySelectorAll('.swatch').forEach((c) => c.classList.remove('active'));
  state.viewer?.setBackground(e.target.value);
  scheduleViewScript();     // цвет тянется мышью — пишем с паузой
});
$('bg-color')?.addEventListener('change', writeViewScript);
/* ---------------- аниме/манга-стиль: живая настройка в окне ---------------- */
const ANIME_MODES = {
  'выкл': { mode: 'выкл' },
  'аниме': { mode: 'аниме', line: 1.6, crease: 32, toon: 3, tone: 0, paper: '#f4f6fa' },
  'манга': { mode: 'манга', line: 1.8, crease: 30, toon: 3, tone: 0.75, paper: '#fbfbf7' },
  'комикс': { mode: 'комикс', line: 2.6, crease: 38, toon: 2, tone: 0.6, paper: '#fdf4e3' },
  'скетч': { mode: 'скетч', line: 1.5, crease: 26, toon: 0, tone: 0, paper: '#f6f1e6',
             hatch: 0.85, 'hatch_angle': 52, 'hatch_step': 7, paper_tex: 0.6 },
  'линия': { mode: 'линия', line: 1.4, crease: 28, toon: 0, tone: 0, paper: '#ffffff', shade: false },
};
state.anime = state.anime || { mode: 'выкл' };

function animeUiValues() {
  const a = state.anime || {};
  return {
    line: Number(a.line ?? 1.6),
    crease: Number(a.crease ?? 32),
    toon: Number(a.toon ?? 3),
    tone: Number(a.tone ?? 0),
    inner: a.inner !== false,
    seams: a.seams !== false,
    paper: a.paper === null ? '#ffffff' : (a.paper || '#f4f6fa'),
    paperScene: a.paper === null,
    hatch: Number(a.hatch ?? 0),
    hatchAngle: Number(a.hatch_angle ?? 45),
    hatchStep: Number(a.hatch_step ?? 8),
    paperTex: Number(a.paper_tex ?? 0),
    lines: a.lines || 'все',
  };
}

function syncAnimeControls() {
  const a = state.anime || { mode: 'выкл' };
  const v = animeUiValues();
  document.querySelectorAll('#anime-chips .chip').forEach((c) => {
    c.classList.toggle('active', (c.dataset.anime || '') === (a.mode || 'выкл'));
  });
  const on = (a.mode || 'выкл') !== 'выкл';
  ['anime-row', 'anime-row2', 'anime-row3'].forEach((id) => {
    const row = $(id);
    if (row) row.hidden = !on;
  });
  if ($('anime-line')) $('anime-line').value = String(v.line);
  if ($('anime-line-val')) $('anime-line-val').textContent = `${v.line.toFixed(1)} px`;
  if ($('anime-crease')) $('anime-crease').value = String(v.crease);
  if ($('anime-crease-val')) $('anime-crease-val').textContent = `${Math.round(v.crease)}°`;
  if ($('anime-toon')) $('anime-toon').value = String(v.toon);
  if ($('anime-toon-val')) $('anime-toon-val').textContent = String(v.toon);
  if ($('anime-tone')) $('anime-tone').value = String(v.tone);
  if ($('anime-tone-val')) $('anime-tone-val').textContent = v.tone.toFixed(2);
  if ($('anime-tone-on')) $('anime-tone-on').checked = v.tone > 0.001;
  if ($('anime-inner')) $('anime-inner').checked = v.inner;
  if ($('anime-seams')) $('anime-seams').checked = v.seams;
  if ($('anime-paper')) $('anime-paper').value = v.paper;
  if ($('anime-paper-scene')) $('anime-paper-scene').checked = v.paperScene;
  if ($('anime-hatch')) $('anime-hatch').value = String(v.hatch);
  if ($('anime-hatch-val')) $('anime-hatch-val').textContent = v.hatch.toFixed(2);
  if ($('anime-hatch-angle')) $('anime-hatch-angle').value = String(Math.round(v.hatchAngle));
  if ($('anime-hatch-angle-val')) $('anime-hatch-angle-val').textContent = `${Math.round(v.hatchAngle)}°`;
  if ($('anime-hatch-step')) $('anime-hatch-step').value = String(Math.round(v.hatchStep));
  if ($('anime-hatch-step-val')) $('anime-hatch-step-val').textContent = `${Math.round(v.hatchStep)} px`;
  if ($('anime-paper-tex')) $('anime-paper-tex').checked = v.paperTex > 0.001;
  if ($('anime-lines')) $('anime-lines').value = v.lines;
}

function applyAnime(patch) {
  const base = Object.assign({}, state.anime || {});
  const next = Object.assign(base, patch || {});
  if (!next.mode || next.mode === 'выкл') {
    state.anime = { mode: 'выкл' };
  } else {
    state.anime = next;
  }
  if (state.viewer) {
    state.viewer.setAnime(state.anime.mode === 'выкл' ? null : state.anime);
  }
  syncAnimeControls();
}

document.querySelectorAll('#anime-chips .chip').forEach((chip) => {
  chip.addEventListener('click', () => {
    const mode = chip.dataset.anime || 'выкл';
    if (mode === 'выкл') {
      applyAnime({ mode: 'выкл' });
      toast('Обычный вид');
      return;
    }
    const preset = Object.assign({}, ANIME_MODES[mode] || { mode });
    if (state.anime && state.anime.mode === mode) {
      // повторный щелчок по активному стилю не сбрасывает настройки
      applyAnime({ mode });
      return;
    }
    // смена режима начинается с его пресета: «линия» не должна оставлять
    // после себя выключенное затенение у «аниме»
    state.anime = preset;
    state.viewer?.setAnime(state.anime);
    syncAnimeControls();
    toast(`Стиль «${mode}»`);
  });
});
$('anime-line')?.addEventListener('input', (e) => {
  applyAnime({ line: Number(e.target.value) });
  if ($('anime-line-val')) $('anime-line-val').textContent = `${Number(e.target.value).toFixed(1)} px`;
});
$('anime-crease')?.addEventListener('input', (e) => {
  applyAnime({ crease: Number(e.target.value) });
  if ($('anime-crease-val')) $('anime-crease-val').textContent = `${Math.round(Number(e.target.value))}°`;
});
$('anime-inner')?.addEventListener('change', (e) => applyAnime({ inner: e.target.checked }));
$('anime-seams')?.addEventListener('change', (e) => applyAnime({ seams: e.target.checked }));
$('anime-toon')?.addEventListener('input', (e) => {
  applyAnime({ toon: Number(e.target.value) });
  if ($('anime-toon-val')) $('anime-toon-val').textContent = String(e.target.value);
});
$('anime-tone')?.addEventListener('input', (e) => {
  const v = Number(e.target.value);
  applyAnime({ tone: v });
  if ($('anime-tone-val')) $('anime-tone-val').textContent = v.toFixed(2);
  if ($('anime-tone-on')) $('anime-tone-on').checked = v > 0.001;
});
$('anime-tone-on')?.addEventListener('change', (e) => {
  applyAnime({ tone: e.target.checked ? 0.75 : 0 });
});
$('anime-paper')?.addEventListener('input', (e) => applyAnime({ paper: e.target.value }));
$('anime-paper-scene')?.addEventListener('change', (e) => {
  applyAnime({ paper: e.target.checked ? null : ($('anime-paper')?.value || '#ffffff') });
});
$('anime-hatch')?.addEventListener('input', (e) => {
  const v = Number(e.target.value);
  applyAnime({ hatch: v });
  if ($('anime-hatch-val')) $('anime-hatch-val').textContent = v.toFixed(2);
});
$('anime-hatch-angle')?.addEventListener('input', (e) => {
  const v = Number(e.target.value);
  applyAnime({ hatch_angle: v });
  if ($('anime-hatch-angle-val')) $('anime-hatch-angle-val').textContent = `${Math.round(v)}°`;
});
$('anime-hatch-step')?.addEventListener('input', (e) => {
  const v = Number(e.target.value);
  applyAnime({ hatch_step: v });
  if ($('anime-hatch-step-val')) $('anime-hatch-step-val').textContent = `${Math.round(v)} px`;
});
$('anime-paper-tex')?.addEventListener('change', (e) => {
  applyAnime({ paper_tex: e.target.checked ? 0.6 : 0 });
});
$('anime-lines')?.addEventListener('change', (e) => applyAnime({ lines: e.target.value }));

/** Строка сценария для текущих настроек стиля. */
function animeCommand() {
  const a = state.anime || { mode: 'выкл' };
  if (!a.mode || a.mode === 'выкл') return 'anime off=да';
  const v = animeUiValues();
  const parts = [`mode=${a.mode}`, `line=${v.line.toFixed(1)}`, `crease=${Math.round(v.crease)}`,
    `toon=${Math.round(v.toon)}`];
  if (v.tone > 0.001) parts.push(`tone=${v.tone.toFixed(2)}`);
  if (!v.inner) parts.push('inner=нет');
  if (!v.seams) parts.push('seams=нет');
  if (a.shade === false) parts.push('shade=нет');
  if (v.hatch > 0.001) {
    parts.push(`hatch=${v.hatch.toFixed(2)}`);
    parts.push(`hatch_angle=${Math.round(v.hatchAngle)}`);
    parts.push(`hatch_step=${Math.round(v.hatchStep)}`);
  }
  if (v.paperTex > 0.001) parts.push(`paper_tex=${v.paperTex.toFixed(2)}`);
  if (v.lines && v.lines !== 'все') parts.push(`lines=${v.lines}`);
  parts.push(v.paperScene ? 'paper=сцена' : `paper=${v.paper}`);
  return 'anime ' + parts.join(' ');
}

$('anime-insert')?.addEventListener('click', () => {
  insertTool(animeCommand(), 'аниме-стиль');
});

syncAnimeControls();

$('exposure')?.addEventListener('input', (e) => {
  const v = Number(e.target.value);
  $('exposure-val').textContent = v.toFixed(2);
  state.viewer?.setExposure(v);
});
// Ползунки вида пишут себя в сценарий: иначе пересборка возвращала старый вид
$('exposure')?.addEventListener('change', writeViewScript);
$('bloom')?.addEventListener('input', (e) => {
  const v = Number(e.target.value);
  $('bloom-val').textContent = v.toFixed(2);
  state.viewer?.setBloomStrength(v);
});
$('bloom')?.addEventListener('change', writeViewScript);
['opt-shadows', 'opt-grid', 'opt-ground', 'opt-axes', 'opt-poly'].forEach((id) => {
  $(id)?.addEventListener('change', writeViewScript);
});
$('btn-clear-script')?.addEventListener('click', clearScriptNow);
$('btn-clear-scene')?.addEventListener('click', clearSceneNow);
$('shading')?.addEventListener('change', (e) => state.viewer?.setShading(e.target.value));
$('opt-shadows')?.addEventListener('change', (e) => state.viewer?.applySettings({ shadows: e.target.checked }));
$('opt-grid')?.addEventListener('change', (e) => state.viewer?.setGrid(e.target.checked));
$('opt-ground')?.addEventListener('change', (e) => state.viewer?.setGround(e.target.checked));
$('opt-axes')?.addEventListener('change', (e) => state.viewer?.setAxes(e.target.checked));
$('opt-poly')?.addEventListener('change', (e) => {
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
  if (state.viewer) state.viewer.objectAxes[name] = obj.axes || null;
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
                     transmission: obj.transmission ?? 0,
                     mirror: obj.mirror ?? 0 };
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
    $('mat-mirror').value = state.material.mirror;
    $('mat-mirror-val').textContent = state.material.mirror;
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
$('mat-mirror')?.addEventListener('input', (e) => {
  state.material.mirror = Number(e.target.value);
  $('mat-mirror-val').textContent = e.target.value;
  rememberMaterial({ mirror: Number(e.target.value) });
  state.viewer?.applyMaterial(state.selected?.name, {
    mirror: Number(e.target.value), metal: state.material.metal, rough: state.material.rough,
  });
});
// по отпусканию ползунка записываем значение в сценарий, чтобы оно жило после пересборки
['mat-color', 'mat-metal', 'mat-rough', 'mat-emissive', 'mat-glow', 'mat-trans', 'mat-mirror'].forEach((id) => {
  $(id)?.addEventListener('change', () => {
    if (!state.selected) return;
    writeMaterialScript({ rebuild: true });
  });
});
$('mat-close')?.addEventListener('click', () => selectObject(''));

function writeMaterialScript({ rebuild = true } = {}) {
  if (!state.selected) return;
  const { color, metal, rough, emissive, glow, transmission, mirror } = state.material;
  const tex = $('mat-tex')?.value || '';
  const m = state.selected.name;
  const lines = currentScript().split('\n').filter((l) => {
    const t = l.trim();
    return !(t.startsWith(`color ${m} `) || t.startsWith(`texture ${m} `) || t.startsWith(`материал ${m} `));
  });
  let line = `color ${m} ${color} metal=${metal} rough=${rough}`;
  if (emissive) line += ` emissive=${emissive} emissive_strength=${glow}`;
  if (transmission > 0) line += ` transmission=${transmission}`;
  if (mirror > 0) line += ` mirror=${mirror}`;
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
  const budget = fmt(sel.budget_cm3 ?? sel.volume_cm3);
  const grid = state.payload?.grid;
  let status = '';
  if (grid) {
    const warn = (state.payload?.analysis?.warnings || []).find((w) => w.includes('Вне кубической сетки'));
    const gridCells = Number(grid.cells?.length || 0);
    status = warn
      ? `<br><span class="budget-bad">⚠ ${escapeHtml(warn)}</span>`
      : `<br><span class="budget-ok">Сценарий уже в бюджете: ${gridCells} куб.`
        + ` (${fmt((grid.volume_mm3 || 0) / 1000)} см³)</span>`;
  }
  info.innerHTML = `секторов: <b>${sel.cells}</b> · куб <b>${fmt(sel.cell)}</b> мм<br>`
    + `индексы: <b>${escapeHtml(sel.indices || '')}</b><br>`
    + `центр сцены: <b>(${escapeHtml(c)})</b> мм · размер <b>${escapeHtml(sz)}</b> мм<br>`
    + `бюджет объёма: <b>${escapeHtml(budget)} см³</b>`
    + `<span class="dim"> · Shift — добавить, Ctrl — убрать</span>`
    + status;
  const card = $('space-card');
  if (card) card.classList.toggle('budget-alert', Boolean(status.includes('budget-bad')));
}

/** Записать выбранные кубы в сценарий как кубическую сетку-бюджет. */
function applyGridScript() {
  const sel = state.space || state.viewer?.spaceSelection();
  if (!sel || !sel.cells) { toast('Сначала выделите кубы', 'bad'); return; }
  if (!sel.script) { toast('Не удалось построить команду сетки', 'bad'); return; }
  const script = currentScript().replace(/\s+$/, '');
  setScript(script ? `${script}\n${sel.script}\n` : `${sel.script}\n`,
    { label: 'бюджет кубов' });
  toast(`Бюджет записан: ${sel.cells} куб. по ${fmt(sel.cell)} мм`);
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
$('space-budget')?.addEventListener('click', applyGridScript);

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
      exportSaved(res, `Сечение ${res.name}`);
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
    const blob = new Blob([data], { type: 'image/gif' });
    toast('GIF: записываю в «Загрузки»…');
    const saved = await saveBlob(blob, animExportName('gif'));
    toastSaved(saved, `GIF ${size.w}×${size.h}, ${total} кадров`);
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
    const saved = await saveBlob(blob, animExportName('webm'));
    toastSaved(saved, `Видео ${(blob.size / 1024 / 1024).toFixed(1)} МБ`);
  } catch (err) {
    toast(err.message || 'Не удалось записать видео', 'bad');
  } finally {
    viewer.applyTime(keep);
    setAnimExportBusy(false);
  }
}

$('btn-open-downloads')?.addEventListener('click', async () => {
  const saved = state.lastSaved;
  if (!saved) return;
  try {
    await api('/api/reveal', { path: saved.path || saved.downloads });
    toast(`Открыл папку: ${saved.downloads || saved.path}`);
  } catch (err) {
    // на другой машине (окно в браузере удалённого сервера) папку не открыть —
    // показываем адрес, чтобы его можно было скопировать
    toast(`Папка: ${saved.downloads || saved.path}`, 'warn');
  }
});

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
    exportSaved(res, `Экспорт ${res.name || fmt}`);
  } catch (err) {
    toast(err.message || 'Ошибка экспорта', 'bad');
  }
});


/* ------------------------------------------------------------------ */
/*  0.15: «Инструменты» — готовые фигуры и приёмы с параметрами        */
/* ------------------------------------------------------------------ */
/** Ползунок «степень детализации» — общий для всех примитивов. */
function detailParam(value, hint) {
  return {
    k: 'detail', label: 'детализация', v: value, min: 0, max: 5, step: 1,
    kind: 'slider', hint: hint || 'чем больше, тем глаже и тем больше треугольников',
  };
}

const TOOL_SHAPES = [
  {
    op: 'sheet', name: 'лист', title: 'Лист', group: 'Стандартные примитивы',
    desc: 'Тонкий параллелепипед с объёмом: бумага, металл, картон. Волнистость с шагом и амплитудой, свёртка в рулон с зазором между витками.',
    params: [
      { k: 'width', label: 'ширина', v: 120, step: 10, min: 0.5, max: 5000 },
      { k: 'length', label: 'длина', v: 200, step: 10, min: 0.5, max: 8000 },
      { k: 'thickness', label: 'толщина', v: 1.2, step: 0.2, min: 0.2, max: 80 },
      { k: 'step', label: 'шаг волны', v: 0, step: 2, min: 0, max: 1000 },
      { k: 'amp', label: 'амплитуда', v: 0, step: 1, min: 0, max: 300 },
      { k: 'wave', label: 'волна', v: 'вдоль', kind: 'raw', choices: ['вдоль', 'поперёк', 'крест'] },
      { k: 'roll', label: 'оборотов', v: 0, step: 1, min: 0, max: 60 },
      { k: 'gap', label: 'зазор', v: 0, step: 0.2, min: 0, max: 400 },
    ],
  },
  {
    op: 'fold_sheet', name: 'сгибаемый_лист', title: 'Сгибаемый лист', group: 'Стандартные примитивы',
    desc: 'Один сгиб или гармошка вдоль X, Y, диагонали и произвольного угла; просвет и острота складки настраиваются.',
    params: [
      { k: 'width', label: 'ширина', v: 120, step: 10, min: 0.5, max: 5000 },
      { k: 'length', label: 'длина', v: 200, step: 10, min: 0.5, max: 8000 },
      { k: 'thickness', label: 'толщина', v: 1.2, step: 0.2, min: 0.2, max: 80 },
      { k: 'parts', label: 'частей', v: 2, step: 1, min: 2, max: 12 },
      { k: 'angle', label: 'угол сгиба°', v: 120, step: 5, min: 1, max: 180 },
      { k: 'gap', label: 'зазор слоёв', v: 0.6, step: 0.2, min: 0, max: 400 },
      { k: 'sharp', label: 'острота', v: 0, step: 0.1, min: 0, max: 1 },
      { k: 'axis', label: 'направление', v: 'x', kind: 'raw', choices: ['x', 'y', 'диагональ'] },
      { k: 'direction', label: 'свой угол°', v: '', step: 5, min: -180, max: 180, auto: true },
      { k: 'offset', label: 'место сгиба', v: 0.5, step: 0.05, min: 0.1, max: 0.9 },
    ],
  },
  {
    op: 'box', name: 'куб', title: 'Куб / параллелепипед', group: 'Стандартные примитивы',
    desc: 'Независимый верх и параллелограмм; одновременные отверстия по X/Y/Z: круг, квадрат или прямой овал.',
    params: [
      { k: 'size', label: 'размер низа', v: '120,80,60', kind: 'vec' },
      { k: 'top_size', label: 'размер верха', v: '120,80', kind: 'vec' },
      { k: 'top_offset', label: 'сдвиг верха', v: '0,0', kind: 'vec' },
      { k: 'base_angle', label: 'угол основ.', v: 90, step: 5, min: 15, max: 165 },
      { k: 'round', label: 'скругл.', v: 3, step: 1, min: 0, max: 1000 },
      { k: 'hole_x', label: 'отверстие X', v: 0, step: 1, min: 0, max: 10000 },
      { k: 'hole_x_shape', label: 'форма X', v: 'круг', kind: 'raw', choices: ['круг', 'квадрат', 'овал'] },
      { k: 'hole_y', label: 'отверстие Y', v: 0, step: 1, min: 0, max: 10000 },
      { k: 'hole_y_shape', label: 'форма Y', v: 'круг', kind: 'raw', choices: ['круг', 'квадрат', 'овал'] },
      { k: 'hole_z', label: 'отверстие Z', v: 0, step: 1, min: 0, max: 10000 },
      { k: 'hole_z_shape', label: 'форма Z', v: 'круг', kind: 'raw', choices: ['круг', 'квадрат', 'овал'] },
      { k: 'oval_aspect', label: 'овальность', v: 1.8, step: 0.1, min: 1, max: 8 },
      detailParam(3, 'детализация скругления: 0 — гранёные углы, 5 — гладкие'),
    ],
  },
  {
    op: 'face_box', name: 'куб_граней', title: 'Куб с формой граней', group: 'Стандартные примитивы',
    desc: 'Ровные, выпуклые или вогнутые грани: линза, трапеция или прямой квадрат; одиночные, групповые и общие срезы углов.',
    params: [
      { k: 'size', label: 'размер', v: '80,80,80', kind: 'vec' },
      { k: 'mode', label: 'рельеф', v: 'ровный', kind: 'raw', choices: ['ровный', 'выпуклый', 'вогнутый'] },
      { k: 'profile', label: 'профиль', v: 'линза', kind: 'raw', choices: ['линза', 'трапеция', 'квадрат'] },
      { k: 'faces', label: 'грани', v: 'все', kind: 'raw' },
      { k: 'relief', label: 'высота/глубина', v: 7, step: 1, min: 0.1, max: 1000 },
      { k: 'margin', label: 'поле грани', v: 8, step: 1, min: 0, max: 1000 },
      { k: 'taper', label: 'сужение', v: 0.35, step: 0.05, min: 0, max: 0.9 },
      { k: 'corner_cut', label: 'срез угла', v: 0, step: 1, min: 0, max: 10000 },
      { k: 'corners', label: 'какие углы', v: 'один', kind: 'raw', choices: ['один', 'верх', 'низ', 'все', 'нет'] },
      { k: 'corner', label: 'один угол', v: 'перед_право_верх', kind: 'raw', choices: ['перед_право_верх', 'перед_лево_верх', 'зад_право_верх', 'зад_лево_верх', 'перед_право_низ', 'перед_лево_низ', 'зад_право_низ', 'зад_лево_низ'] },
    ],
  },
  {
    op: 'prism', name: 'призма', title: 'Призма', group: 'Стандартные примитивы',
    desc: 'Призма со сдвигом и масштабом верха, параллелограммом и Loop-сглаживанием.',
    params: [
      { k: 'sides', label: 'сторон', v: 6, step: 1, min: 3, max: 64 },
      { k: 'radius', label: 'радиус низа', v: 40, step: 1, min: 0.1, max: 5000 },
      { k: 'r2', label: 'радиус верха', v: 40, step: 1, min: 0, max: 5000 },
      { k: 'height', label: 'высота', v: 60, step: 1, min: 0.1, max: 5000 },
      { k: 'top_scale', label: 'масштаб верха', v: '1,1', kind: 'vec' },
      { k: 'top_offset', label: 'сдвиг верха', v: '0,0', kind: 'vec' },
      { k: 'base_angle', label: 'угол основ.', v: 90, step: 5, min: 15, max: 165 },
      { k: 'smooth', label: 'сглаживание', v: 0, min: 0, max: 4, step: 1,
        kind: 'slider', hint: 'Loop: реально скругляет форму; 0 — плоские грани' },
    ],
  },
  {
    op: 'octa', name: 'октаэдр', title: 'Октаэдр', group: 'Стандартные примитивы',
    desc: 'Симметричная двойная пирамида: faces задаёт чётное число исходных граней, divisions отдельно дробит каждую без изменения формы.',
    params: [
      { k: 'radius', label: 'радиус', v: 30, step: 1, min: 0.1, max: 5000 },
      { k: 'height', label: 'высота', v: 80, step: 2, min: 0.1, max: 5000 },
      { k: 'faces', label: 'исходных граней', v: 8, step: 2, min: 6, max: 64 },
      { k: 'divisions', label: 'дробление', v: 0, min: 0, max: 4, step: 1,
        kind: 'slider', hint: 'добавляет вершины, не меняя исходную форму' },
      { k: 'smooth', label: 'сглаживание', v: 0, min: 0, max: 4, step: 1,
        kind: 'slider', hint: 'Loop: округляет октаэдр; 0 — плоские грани' },
    ],
  },
  {
    op: 'pyramid', name: 'пирамида', title: 'Пирамида', group: 'Стандартные примитивы',
    desc: 'Пирамида с вершиной над центром, ребром или углом; параллелограмм и сглаживание.',
    params: [
      { k: 'sides', label: 'сторон', v: 4, step: 1, min: 3, max: 64 },
      { k: 'radius', label: 'радиус', v: 60, step: 2, min: 0.1, max: 5000 },
      { k: 'height', label: 'высота', v: 90, step: 5, min: 0.1, max: 5000 },
      { k: 'tip_at', label: 'вершина над', v: 'center', kind: 'raw',
        choices: ['center', 'edge', 'corner'] },
      { k: 'tip_index', label: 'индекс грани', v: 0, step: 1, min: 0, max: 63,
        hint: 'для center не участвует; edge/corner — номер ребра или угла' },
      { k: 'base_angle', label: 'угол основ.', v: 90, step: 5, min: 15, max: 165 },
      { k: 'smooth', label: 'сглаживание', v: 0, min: 0, max: 4, step: 1,
        kind: 'slider', hint: 'Loop: скругляет форму; 0 — плоские грани' },
    ],
  },
  {
    op: 'cone', name: 'конус', title: 'Конус', group: 'Стандартные примитивы',
    desc: 'Конус с вершиной вверх — воронки, ножки, сопла.',
    params: [
      { k: 'radius', label: 'радиус', v: 45, step: 1, min: 0.01, max: 5000 },
      { k: 'height', label: 'высота', v: 90, step: 1, min: 0.01, max: 5000 },
      detailParam(3, 'детализация: сколько граней по кругу'),
    ],
  },
  {
    op: 'cylinder', name: 'цилиндр', title: 'Цилиндр', group: 'Стандартные примитивы',
    desc: 'Цилиндр с отдельным радиусом, эллиптическим масштабом и сдвигом верхней плоскости.',
    params: [
      { k: 'radius', label: 'радиус низа', v: 40, step: 1, min: 0.1, max: 5000 },
      { k: 'r2', label: 'радиус верха', v: 40, step: 1, min: 0, max: 5000 },
      { k: 'height', label: 'высота', v: 100, step: 1, min: 0.1, max: 5000 },
      { k: 'top_scale', label: 'масштаб верха', v: '1,1', kind: 'vec' },
      { k: 'top_offset', label: 'сдвиг верха', v: '0,0', kind: 'vec' },
      detailParam(3, 'детализация: сколько граней у бока'),
    ],
  },
  {
    op: 'sphere', name: 'шар', title: 'Шар (сфера)', group: 'Стандартные примитивы',
    desc: 'Шар с плоским срезом сверху; slice=1 — полусфера, round скругляет новую кромку.',
    params: [
      { k: 'radius', label: 'радиус', v: 50, step: 1, min: 0.1, max: 5000 },
      { k: 'slice', label: 'срез сверху', v: 0, step: 0.05, min: 0, max: 1,
        kind: 'slider', hint: 'доля радиуса: 0 — целый шар, 0.5 — срез на R/2, 1 — полусфера' },
      { k: 'round', label: 'кромка', v: 0, step: 0.5, min: 0, max: 1000,
        hint: 'радиус скругления плоского среза; работает при slice>0' },
      detailParam(4, 'детализация: 0 — гранёный шар, 5 — максимально гладкий'),
    ],
  },
  {
    op: 'icosphere', name: 'икосфера', title: 'Икосфера', group: 'Стандартные примитивы',
    desc: 'Геодезическая сфера: треугольники, квадраты, пятиугольники или сота с шестиугольниками.',
    params: [
      { k: 'radius', label: 'радиус', v: 40, step: 2, min: 0.1, max: 5000 },
      { k: 'mode', label: 'ячейки', v: 'triangle', kind: 'raw',
        choices: ['triangle', 'quad', 'pentagon', 'сота'] },
      { k: 'divisions', label: 'уровень', v: 2, step: 1, min: 0, max: 5,
        kind: 'slider', suffix: ' ур.',
        hint: '0 — исходная форма; сота 0 — 12 пятиугольников и 20 шестиугольников' },
    ],
  },
  {
    op: 'ellipsoid', name: 'эллипсоид', title: 'Эллипсоид', group: 'Стандартные примитивы',
    desc: 'Шар, растянутый по каждой оси отдельно: полуоси в миллиметрах, без команды scale. '
      + 'Основа для голов, камней, капель и посуды.',
    params: [
      { k: 'x', label: 'полуось X', v: 60, step: 1, min: 0.1, max: 5000 },
      { k: 'y', label: 'полуось Y', v: 40, step: 1, min: 0.1, max: 5000 },
      { k: 'z', label: 'полуось Z', v: 22, step: 1, min: 0.1, max: 5000 },
      { k: 'divisions', label: 'геодетализация', v: 2, min: 0, max: 5, step: 1,
        kind: 'slider', hint: '20 → 80 → 320… треугольников; полуоси сохраняются на каждом уровне' },
    ],
  },
  {
    op: 'capsule', name: 'капсула', title: 'Капсула', group: 'Стандартные примитивы',
    desc: 'Цилиндр с полусферическими концами.',
    params: [
      { k: 'radius', label: 'радиус', v: 18, step: 1, min: 0.01, max: 5000 },
      { k: 'height', label: 'длина', v: 90, step: 5, min: 0.02, max: 5000 },
      detailParam(3, 'детализация скруглений'),
    ],
  },
  {
    op: 'torus', name: 'тор', title: 'Тор', group: 'Стандартные примитивы',
    desc: 'Кольцо-бублик: радиус кольца, радиус трубки и гладкость.',
    params: [
      { k: 'major', label: 'радиус', v: 55, step: 1, min: 0.1, max: 5000 },
      { k: 'minor', label: 'трубка', v: 12, step: 1, min: 0.01, max: 5000 },
      detailParam(3, 'детализация: сглаженность кольца и трубки'),
    ],
  },
  {
    op: 'ring', name: 'кольцо', title: 'Кольцо', group: 'Стандартные примитивы',
    desc: 'Обод с плоскими сторонами и скруглёнными краями.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 20, step: 1, min: 1, max: 5000 },
      { k: 'width', label: 'ширина', v: 6, step: 0.5, min: 0.4, max: 5000 },
      { k: 'thickness', label: 'толщина', v: 2.2, step: 0.2, min: 0.2, max: 5000 },
      { k: 'round', label: 'скругл.', v: 0.6, step: 0.1, min: 0, max: 1000 },
    ],
  },
  {
    op: 'washer', name: 'шайба', title: 'Шайба', group: 'Стандартные примитивы',
    desc: 'Плоское кольцо с фаской; размеры в миллиметрах.',
    params: [
      { k: 'outer', label: 'наружн.', v: 40, step: 1, min: 1, max: 5000 },
      { k: 'inner', label: 'отверстие', v: 16, step: 1, min: 0.2, max: 5000 },
      { k: 'thickness', label: 'толщина', v: 4, step: 0.5, min: 0.2, max: 5000 },
    ],
  },
  {
    op: 'disc', name: 'круг', title: 'Круг', group: 'Стандартные примитивы',
    desc: 'Круг с плоским, вогнутым или выпуклым параболическим верхом; низ плоский.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 120, step: 5, min: 0.5, max: 5000 },
      { k: 'thickness', label: 'толщина', v: 8, step: 1, min: 0.2, max: 5000 },
      { k: 'top', label: 'верх', v: 'плоская', kind: 'raw', choices: ['плоская', 'вогнутая', 'выпуклая'] },
      { k: 'sag', label: 'кривизна', v: 2, step: 0.5, min: 0.01, max: 1000 },
      { k: 'round', label: 'кромка', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'oval', name: 'овал', title: 'Овал', group: 'Стандартные примитивы',
    desc: 'Овальная плита с плоским, вогнутым или выпуклым верхом и плоским низом.',
    params: [
      { k: 'width', label: 'ширина', v: 200, step: 10, min: 1, max: 5000 },
      { k: 'length', label: 'длина', v: 120, step: 10, min: 1, max: 5000 },
      { k: 'thickness', label: 'толщина', v: 8, step: 1, min: 0.2, max: 5000 },
      { k: 'top', label: 'верх', v: 'плоская', kind: 'raw', choices: ['плоская', 'вогнутая', 'выпуклая'] },
      { k: 'sag', label: 'кривизна', v: 2, step: 0.5, min: 0.01, max: 1000 },
      { k: 'round', label: 'кромка', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'strip', name: 'полоса', title: 'Полоса', group: 'Стандартные примитивы',
    desc: 'Тонкая объёмная лента: концы, независимые кромки, S/зигзаг, выемка и дуга.',
    params: [
      { k: 'length', label: 'длина', v: 200, step: 10, min: 10, max: 10000 },
      { k: 'width', label: 'ширина', v: 40, step: 2, min: 1, max: 5000 },
      { k: 'thickness', label: 'толщина', v: 4, step: 0.5, min: 0.1, max: 1000 },
      { k: 'ends', label: 'концы', v: 'прямоугольные', kind: 'raw', choices: ['прямоугольные', 'треугольные', 'овальные'] },
      { k: 'collapse_left', label: 'левая кромка', v: 0, step: 0.05, min: 0, max: 0.95 },
      { k: 'collapse_right', label: 'правая кромка', v: 0, step: 0.05, min: 0, max: 0.95 },
      { k: 'smooth', label: 'сглаживание', v: 0, step: 1, min: 0, max: 4 },
      { k: 'bend', label: 'угол дуги°', v: 0, step: 5, min: -180, max: 180 },
      { k: 'path', label: 'контур', v: 'прямая', kind: 'raw', choices: ['прямая', 'S', 'зигзаг'] },
      { k: 'curve', label: 'амплитуда', v: 30, step: 5, min: 0.1, max: 5000 },
      { k: 'recess', label: 'выемка', v: 'нет', kind: 'raw', choices: ['нет', 'круг', 'прямоугольник', 'квадрат', 'треугольник'] },
      { k: 'recess_size', label: 'ширина выемки', v: 16, step: 1, min: 0.5, max: 5000 },
      { k: 'recess_length', label: 'длина выемки', v: 24, step: 1, min: 0.5, max: 5000 },
    ],
  },
  {
    op: 'grating', name: 'решётка', title: 'Решётка', group: 'Производные примитивы',
    desc: 'Рамка и рейки одним телом; планки, квадратная клетка или настоящие сквозные соты.',
    params: [
      { k: 'width', label: 'ширина', v: 200, step: 10, min: 10, max: 10000 },
      { k: 'height', label: 'высота', v: 120, step: 10, min: 10, max: 10000 },
      { k: 'depth', label: 'толщина', v: 4, step: 0.5, min: 0.2, max: 1000 },
      { k: 'pattern', label: 'ячейки', v: 'планки', kind: 'raw', choices: ['планки', 'клетка', 'соты'] },
      { k: 'bar', label: 'рейки', v: 3, step: 0.5, min: 0.2, max: 1000 },
      { k: 'frame', label: 'рамка', v: 6, step: 1, min: 0.4, max: 2000 },
      { k: 'bars', label: 'число реек', v: 7, step: 1, min: 1, max: 200 },
      { k: 'cols', label: 'ячеек X', v: 5, step: 1, min: 1, max: 100 },
      { k: 'rows', label: 'ячеек Y', v: 4, step: 1, min: 1, max: 100 },
      { k: 'cell', label: 'сота', v: 22, step: 1, min: 2, max: 5000 },
    ],
  },
  {
    op: 'spikes', name: 'шипы', title: 'Шипы', group: 'Производные примитивы',
    desc: 'Общая площадка и настраиваемые шипы: форма, высота, остриё, наклон и ряды.',
    params: [
      { k: 'width', label: 'ширина', v: 120, step: 5, min: 5, max: 10000 },
      { k: 'length', label: 'длина', v: 80, step: 5, min: 5, max: 10000 },
      { k: 'base_h', label: 'площадка', v: 4, step: 0.5, min: 0.2, max: 1000 },
      { k: 'cols', label: 'шипов X', v: 4, step: 1, min: 1, max: 100 },
      { k: 'rows', label: 'шипов Y', v: 3, step: 1, min: 1, max: 100 },
      { k: 'height', label: 'высота шипа', v: 28, step: 1, min: 0.5, max: 5000 },
      { k: 'base_d', label: 'основание', v: 12, step: 1, min: 0.4, max: 5000 },
      { k: 'tip_d', label: 'остриё', v: 0.8, step: 0.2, min: 0, max: 5000 },
      { k: 'sides', label: 'граней', v: 24, step: 1, min: 3, max: 64 },
      { k: 'lean', label: 'наклон°', v: 0, step: 1, min: -45, max: 45 },
      { k: 'direction', label: 'азимут°', v: 0, step: 5, min: -360, max: 360 },
    ],
  },
  {
    op: 'hemisphere', name: 'полусфера', title: 'Полусфера', group: 'Производные примитивы',
    desc: 'wall=0 — сплошная полусфера, wall>0 — чаша с плоской кромкой; round её скругляет.',
    params: [
      { k: 'radius', label: 'радиус', v: 60, step: 1, min: 1, max: 5000 },
      { k: 'wall', label: 'стенка', v: 0, step: 0.5, min: 0, max: 1000 },
      { k: 'round', label: 'кромка', v: 0, step: 0.2, min: 0, max: 1000 },
    ],
  },
  {
    op: 'cavity_frame', name: 'рамка_полость', title: 'Рамка с полостью', group: 'Производные примитивы',
    desc: 'Сквозная Г-полость, линия или угловое окно; у круглой рамки линия становится овалом, угловой квадрат — кругом.',
    params: [
      { k: 'size', label: 'наружный размер', v: '100,90', kind: 'vec' },
      { k: 'depth', label: 'толщина', v: 8, step: 1, min: 0.2, max: 1000 },
      { k: 'outer', label: 'рамка', v: 'квадрат', kind: 'raw', choices: ['квадрат', 'круг'] },
      { k: 'cavity', label: 'полость', v: 'Г', kind: 'raw', choices: ['Г', 'линия', 'квадрат', 'круг', 'овал'] },
      { k: 'cavity_size', label: 'размер полости', v: '50,40', kind: 'vec' },
      { k: 'line_width', label: 'ширина линии', v: 6, step: 1, min: 0.2, max: 500 },
      { k: 'margin', label: 'поле до края', v: 8, step: 1, min: 0.5, max: 1000 },
      { k: 'corner', label: 'угол', v: 'право_верх', kind: 'raw', choices: ['право_верх', 'лево_верх', 'право_низ', 'лево_низ'] },
      { k: 'round', label: 'скругление', v: 0, step: 0.5, min: 0, max: 1000 },
      { k: 'plane', label: 'плоскость', v: 'фронт', kind: 'raw', choices: ['фронт', 'плашмя'] },
    ],
  },
  {
    op: 'sector', name: 'сектор', title: 'Сектор шара', group: 'Производные примитивы',
    desc: 'Долька шара с любым углом: 90° — четвертинка, 180° — полусфера.',
    params: [
      { k: 'radius', label: 'радиус', v: 50, step: 2, min: 0.5, max: 5000 },
      { k: 'angle', label: 'угол°', v: 90, step: 5, min: 1, max: 360 },
      { k: 'thickness', label: 'стенка', v: 0, step: 1, min: 0, max: 5000 },
      { k: 'smooth', label: 'сглаж.', v: 0, step: 1, min: 0, max: 4 },
    ],
  },
  {
    op: 'bracket', name: 'уголок', title: 'Уголок', group: 'Производные примитивы',
    desc: 'Две полки с углом 0…180°, шарнир и скругление только рёбер; заполненный угол закрывается без зазора.',
    params: [
      { k: 'width', label: 'ширина', v: 60, step: 5, min: 5, max: 600 },
      { k: 'depth', label: 'глубина', v: 40, step: 5, min: 3, max: 600 },
      { k: 'height', label: 'высота', v: 40, step: 5, min: 3, max: 600 },
      { k: 'thickness', label: 'сталь', v: 3, step: 0.5, min: 0.4, max: 30 },
      { k: 'angle', label: 'угол°', v: 90, step: 5, min: 0, max: 180 },
      { k: 'round', label: 'шарнир', v: 0, step: 0.5, min: 0, max: 1000 },
      { k: 'corner', label: 'наружный угол', v: 'обычный', kind: 'raw', choices: ['обычный', 'заполненный'] },
      { k: 'smooth', label: 'кромки', v: 0, step: 1, min: 0, max: 4 },
    ],
  },
  {
    op: 'полуовал', name: 'полуовал', title: 'Полуовал', group: 'Производные примитивы',
    desc: 'Пластина-полуовал: подвес, накладка, подпятник, ушко. '
      + 'Отверстие по центру есть или его нет — ползунок «отверстие» в ноль.',
    params: [
      { k: 'width', label: 'ширина', v: 90, step: 2, min: 0.5, max: 5000 },
      { k: 'height', label: 'высота', v: 55, step: 2, min: 0.5, max: 5000 },
      { k: 'thickness', label: 'толщина', v: 8, step: 0.5, min: 0.2, max: 1000 },
      { k: 'hole', label: 'отверстие', v: 16, step: 1, min: 0, auto: true, max: 1000 },
      { k: 'smooth', label: 'сглаж.', v: 0, step: 1, min: 0, max: 4 },
    ],
  },
  {
    op: 'arch', name: 'арка', title: 'Арка', group: 'Производные примитивы',
    desc: 'Полукольцо с прямоугольным сечением: проём, свод, тоннель.',
    params: [
      { k: 'radius', label: 'радиус', v: 200, step: 10, min: 2, max: 5000 },
      { k: 'width', label: 'сечение', v: 60, step: 5, min: 1, max: 5000 },
      { k: 'thickness', label: 'толщина', v: 40, step: 5, min: 1, max: 5000 },
      { k: 'angle', label: 'угол', v: 180, step: 15, min: 5, max: 360 },
      { k: 'smooth', label: 'сглаж.', v: 0, step: 1, min: 0, max: 4 },
    ],
  },
  {
    op: 'воронка', name: 'воронка', title: 'Воронка', group: 'Производные примитивы',
    desc: 'Широкий конус, трубка-носок и стенка заданной толщины. Кромка сверху '
      + 'открыта, канал сквозной — деталь печатается. Высота борта работает и при rim=0.',
    params: [
      { k: 'top', label: 'верх', v: 120, step: 5, min: 2, max: 5000 },
      { k: 'bottom', label: 'носок', v: 16, step: 1, min: 0.6, max: 5000 },
      { k: 'height', label: 'высота', v: 80, step: 5, min: 1, max: 5000 },
      { k: 'spout', label: 'трубка', v: 40, step: 2, min: 0, max: 5000 },
      { k: 'wall', label: 'стенка', v: 3, step: 0.5, min: 0.2, max: 1000 },
      { k: 'rim', label: 'бортик', v: 2.5, step: 0.5, min: 0, max: 1000 },
      { k: 'rim_height', label: 'высота борта', v: 2, step: 0.5, min: 0, max: 1000 },
      { k: 'smooth', label: 'сглаж.', v: 0, step: 1, min: 0, max: 4 },
      detailParam(3, 'детализация: сколько граней у конуса'),
    ],
  },
  {
    op: 'скоба', name: 'скоба', title: 'Скоба (П / U)', group: 'Производные примитивы',
    desc: 'Единая скоба: прямоугольная П/U или овальная U; скругляются только кромки, полки не стягиваются.',
    params: [
      { k: 'length', label: 'длина', v: 120, step: 5, min: 1, max: 5000 },
      { k: 'width', label: 'ширина', v: 40, step: 2, min: 2, max: 5000 },
      { k: 'height', label: 'высота', v: 30, step: 2, min: 2, max: 5000 },
      { k: 'wall', label: 'лист', v: 3, step: 0.5, min: 0.2, max: 1000 },
      { k: 'shape', label: 'сечение', v: 'прямоугольная', kind: 'raw', choices: ['прямоугольная', 'овал'] },
      { k: 'open', label: 'открытие', v: 'вверх', choices: ['вверх', 'вниз'] },
      { k: 'smooth', label: 'сглаж.', v: 0, step: 1, min: 0, max: 4 },
    ],
  },
  {
    op: 'lens', name: 'линза', title: 'Линза', group: 'Производные примитивы',
    desc: 'Оптическая линза со сферическими поверхностями: выпуклая, вогнутая, '
      + 'плосковыпуклая, плосковогнутая, мениск. sag — глубина прогиба, '
      + 'кромка — толщина по краю.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 70, step: 5, min: 3, max: 5000 },
      { k: 'sag', label: 'прогиб', v: 12, step: 1, min: 0.05, max: 5000 },
      { k: 'mode', label: 'вид', v: 'выпуклая', kind: 'raw', choices: ['выпуклая', 'вогнутая', 'плосковыпуклая', 'плосковогнутая', 'мениск'] },
      { k: 'edge', label: 'кромка', v: '', step: 1, auto: true, min: 0.2 },
    ],
  },
  {
    op: 'полукапсула', name: 'полукапсула', title: 'Полукапсула', group: 'Производные примитивы',
    desc: 'Плоское основание, цилиндр и полусфера; бортик как у короны, без режимов патрона.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 20, step: 1, min: 0.6, max: 5000 },
      { k: 'length', label: 'длина', v: 50, step: 1, min: 0.6, max: 5000 },
      { k: 'rim', label: 'бортик', v: 2, step: 0.5, min: 0, max: 1000 },
      { k: 'rim_height', label: 'высота борта', v: 3, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'ingot', name: 'слиток', title: 'Слиток', group: 'Производные примитивы',
    desc: 'Объёмная трапеция: нижняя площадка больше верхней, бока скошены. '
      + 'Слиток металла, груз, кирпич-трапеция, основание под наклонные стенки.',
    params: [
      { k: 'length', label: 'длина', v: 100, step: 5, min: 1, max: 5000 },
      { k: 'width', label: 'ширина', v: 50, step: 5, min: 1, max: 5000 },
      { k: 'height', label: 'высота', v: 22, step: 2, min: 1, max: 5000 },
      { k: 'taper', label: 'скос', v: 8, step: 1, min: 0, max: 5000 },
      { k: 'taper_mode', label: 'скос сторон', v: 'все', kind: 'raw', choices: ['все', 'бока'] },
      { k: 'top_size', label: 'верх X,Y', v: '', kind: 'vec' },
      { k: 'top_offset', label: 'сдвиг верха', v: '0,0', kind: 'vec' },
      { k: 'round', label: 'углы', v: 0, step: 1, min: 0, max: 1000 },
      { k: 'smooth', label: 'кромки', v: 0, step: 1, min: 0, max: 4 },
    ],
  },
  {
    op: 'paraboloid', name: 'параболоид', title: 'Параболоид', group: 'Производные примитивы',
    desc: 'Гладкая чаша или купол: антенна, плафон, миска. wall=0 — сплошной '
      + 'купол, wall>0 — настоящая чаша со стенкой. Склон выполаживается к краю.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 140, step: 5, min: 1, max: 5000 },
      { k: 'height', label: 'высота', v: 34, step: 2, min: 1, max: 5000 },
      { k: 'wall', label: 'стенка', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'saddle', name: 'седло', title: 'Седло (гипар)', group: 'Производные примитивы',
    desc: 'Гиперболический параболоид: в одну сторону вверх, в другую вниз. '
      + 'гипар — крыша с прямыми рёбрами, седло — чаша-чипс. Толщина делает плиту.',
    params: [
      { k: 'length', label: 'длина', v: 160, step: 10, min: 1, max: 5000 },
      { k: 'width', label: 'ширина', v: 120, step: 10, min: 1, max: 5000 },
      { k: 'rise', label: 'перепад', v: 40, step: 5, min: 1, max: 5000 },
      { k: 'thickness', label: 'толщина', v: 4, step: 0.5, min: 0.3, max: 5000 },
      { k: 'mode', label: 'форма', v: 'гипар', choices: ['гипар', 'седло'] },
    ],
  },
  {
    op: 'pie', name: 'сектор_круга', title: 'Сектор круга', group: 'Производные примитивы',
    desc: 'Кусок пирога с объёмом: угол, поворот и толщина. Стрелки-указатели, '
      + 'козырьки, сегменты диаграмм. angle=360 даёт целый круг.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 140, step: 5, min: 1, max: 5000 },
      { k: 'angle', label: 'угол', v: 90, step: 5, min: 1, max: 360 },
      { k: 'start', label: 'начало', v: 0, step: 5, min: -360, max: 360 },
      { k: 'thickness', label: 'толщина', v: 8, step: 1, min: 0.2, max: 5000 },
      { k: 'hole', label: 'отверстие', v: 0, step: 1, min: 0, max: 1000 },
      { k: 'smooth', label: 'сглаж.', v: 0, step: 1, min: 0, max: 4 },
    ],
  },
  {
    op: 'bead', name: 'бусина', title: 'Бусина', group: 'Производные примитивы',
    desc: 'Шар с отверстием под шнур по оси Z. Высота меньше диаметра — '
      + 'сплюснутая, больше — бочонок. chamfer снимает фаску у входа.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 16, step: 1, min: 1, max: 5000 },
      { k: 'height', label: 'высота', v: 16, step: 1, min: 0.5, max: 5000 },
      { k: 'hole', label: 'отверстие', v: 4, step: 0.5, min: 0.2, max: 1000 },
      { k: 'chamfer', label: 'фаска', v: 0, step: 0.5, min: 0, max: 1000 },
      { k: 'slice', label: 'срез доля', v: 0, step: 0.1, min: 0, max: 1 },
      { k: 'round', label: 'кромка среза', v: 0, step: 0.2, min: 0, max: 1000 },
    ],
  },
  {
    op: 'tri_prism', name: 'призма', title: 'Треугольная призма', group: 'Производные примитивы',
    desc: 'Треугольник в основании с любыми углами: равнобедренный, прямоугольный, '
      + 'косоугольный. Стороны a, b, c подбираются числами — из них и складывается '
      + 'наклон граней. round скругляет рёбра основания.',
    params: [
      { k: 'a', label: 'сторона a', v: 100, step: 5, min: 1, max: 5000 },
      { k: 'b', label: 'сторона b', v: 100, step: 5, min: 1, max: 5000 },
      { k: 'c', label: 'сторона c', v: 40, step: 5, min: 1, max: 5000 },
      { k: 'height', label: 'высота', v: 70, step: 5, min: 1, max: 5000 },
      { k: 'round', label: 'скругление', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'arc_prism', name: 'дуговая_призма', title: 'Дуговая призма', group: 'Производные примитивы',
    desc: 'Три независимые параболические стороны: + выпуклость, − вогнутость, 0 плоско.',
    params: [
      { k: 'a', label: 'низ a', v: 100, step: 5, min: 1, max: 10000 },
      { k: 'b', label: 'левая b', v: 90, step: 5, min: 0.5, max: 10000 },
      { k: 'c', label: 'правая c', v: 90, step: 5, min: 0.5, max: 10000 },
      { k: 'height', label: 'высота', v: 120, step: 5, min: 0.5, max: 10000 },
      { k: 'arc_a', label: 'дуга a', v: 0, step: 1, min: -5000, max: 5000 },
      { k: 'arc_b', label: 'дуга b', v: -12, step: 1, min: -5000, max: 5000 },
      { k: 'arc_c', label: 'дуга c', v: 0, step: 1, min: -5000, max: 5000 },
    ],
  },
  {
    op: 'torus_sector', name: 'сектор_тора', title: 'Сектор тора', group: 'Производные примитивы',
    desc: 'Дуга бублика; hole — продольный туннель внутри трубки по всей дуге, '
      + 'открытый на торцах, а не поперечное сверление.',
    params: [
      { k: 'major', label: 'кольцо', v: 60, step: 5, min: 1, max: 5000 },
      { k: 'minor', label: 'трубка', v: 10, step: 1, min: 0.5, max: 5000 },
      { k: 'angle', label: 'угол', v: 180, step: 10, min: 2, max: 360 },
      { k: 'start', label: 'начало', v: 0, step: 15, min: -360, max: 360 },
      { k: 'hole', label: 'отверстие', v: 0, step: 1, min: 0, max: 1000 },
    ],
  },
  {
    op: 'egg', name: 'яйцо', title: 'Яйцо', group: 'Природные примитивы',
    desc: 'Объёмное яйцо или плоский силуэт; wall>0 делает сквозную формочку с равномерной стенкой.',
    params: [
      { k: 'height', label: 'высота', v: 60, step: 1, min: 1, max: 5000 },
      { k: 'diameter', label: 'диаметр', v: 42, step: 1, min: 1, max: 5000 },
      { k: 'proportion', label: 'яйцевидн.', v: 0.55, step: 0.05, min: 0, max: 1 },
      { k: 'sharp', label: 'острый', v: 'верх', kind: 'raw', choices: ['верх', 'низ'] },
      { k: 'flat', label: 'плоский силуэт', v: false, kind: 'bool' },
      { k: 'depth', label: 'толщина силуэта', v: 6, step: 1, min: 0.2, max: 1000 },
      { k: 'wall', label: 'формочка', v: 0, step: 0.5, min: 0, max: 1000 },
      { k: 'round', label: 'кромки', v: 0, step: 0.5, min: 0, max: 1000 },
      { k: 'plane', label: 'плоскость', v: 'фронт', kind: 'raw', choices: ['фронт', 'плашмя'] },
    ],
  },
  {
    op: 'drop', name: 'капля', title: 'Капля', group: 'Природные примитивы',
    desc: 'Объёмная капля или плоский силуэт; wall>0 включает сквозную формочку.',
    params: [
      { k: 'radius', label: 'радиус', v: 14, step: 1, min: 0.5, max: 5000 },
      { k: 'height', label: 'высота', v: 36, step: 1, min: 1, max: 5000 },
      { k: 'tip', label: 'острота', v: 0.5, step: 0.05, min: 0, max: 1 },
      { k: 'flat', label: 'плоский силуэт', v: false, kind: 'bool' },
      { k: 'depth', label: 'толщина силуэта', v: 6, step: 1, min: 0.2, max: 1000 },
      { k: 'wall', label: 'формочка', v: 0, step: 0.5, min: 0, max: 1000 },
      { k: 'round', label: 'кромки', v: 0, step: 0.5, min: 0, max: 1000 },
      { k: 'plane', label: 'плоскость', v: 'фронт', kind: 'raw', choices: ['фронт', 'плашмя'] },
    ],
  },
  {
    op: 'crescent', name: 'полумесяц', title: 'Полумесяц', group: 'Природные примитивы',
    desc: 'Серп: из круга выкушен второй круг; wall>0 делает сквозную формочку по контуру.',
    params: [
      { k: 'radius', label: 'радиус', v: 50, step: 5, min: 0.5, max: 5000 },
      { k: 'thickness', label: 'толщина', v: 18, step: 2, min: 0.1, max: 5000 },
      { k: 'bite', label: 'выкус', v: 1, step: 0.05, min: 0.5, max: 1.6 },
      { k: 'depth', label: 'толщина Z', v: 12, step: 1, min: 0.1, max: 1000 },
      { k: 'wall', label: 'формочка', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'star', name: 'звезда', title: 'Звезда', group: 'Природные примитивы',
    desc: 'Лучи, глубина впадин, фаска и плавное скругление кромки.',
    params: [
      { k: 'points', label: 'лучи', v: 5, step: 1, min: 3, max: 64 },
      { k: 'outer', label: 'радиус', v: 55, step: 1, min: 0.5, max: 5000 },
      { k: 'inner', label: 'впадина', v: 22, step: 1, min: 0.1, max: 5000 },
      { k: 'depth', label: 'толщина', v: 12, step: 1, min: 0.2, max: 1000 },
      { k: 'bevel', label: 'фаска', v: 2, step: 0.5, min: 0, max: 1000 },
      { k: 'smooth', label: 'сглаж.', v: 0.4, step: 0.1, min: 0, max: 1 },
      { k: 'twist', label: 'закрутка', v: 0, step: 5, min: -360, max: 360 },
      { k: 'blade', label: 'лезвия', v: 0, step: 0.1, min: 0, max: 0.9 },
      { k: 'hole', label: 'отверстие', v: 0, step: 1, min: 0, max: 1000 },
      { k: 'wall', label: 'формочка', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'lightning', name: 'молния', title: 'Молния', group: 'Природные примитивы',
    desc: 'Классический зигзаг с двумя остриями.',
    params: [
      { k: 'height', label: 'высота', v: 90, step: 5, min: 2, max: 5000 },
      { k: 'width', label: 'ширина', v: 44, step: 2, min: 1, max: 5000 },
      { k: 'depth', label: 'толщина Z', v: 10, step: 1, min: 0.1, max: 1000 },
      { k: 'round', label: 'скругл.', v: 1.5, step: 0.5, min: 0, max: 1000 },
      { k: 'wall', label: 'формочка', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'heart', name: 'сердце', title: 'Сердце', group: 'Природные примитивы',
    desc: 'Настоящая форма сердца: два лепестка и остриё. Ширина, толщина, скругление.',
    params: [
      { k: 'width', label: 'ширина', v: 60, step: 2, min: 1, max: 5000 },
      { k: 'depth', label: 'толщина', v: 18, step: 1, min: 0.2, max: 1000 },
      { k: 'round', label: 'скругл.', v: 2, step: 0.5, min: 0, max: 1000 },
      { k: 'wall', label: 'формочка', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'cloud', name: 'облако', title: 'Облако', group: 'Природные примитивы',
    desc: 'Плавно слитое облако с вытянутым основанием и долями, без рваных швов; flat даёт настоящее плоское дно.',
    params: [
      { k: 'size', label: 'размер', v: '180,90,70', kind: 'vec' },
      { k: 'puffs', label: 'долей', v: 9, step: 1, min: 3, max: 40 },
      { k: 'seed', label: 'зерно', v: 3, step: 1, min: 0, max: 999999 },
      { k: 'rough', label: 'разброс', v: 0.35, step: 0.05, min: 0, max: 1 },
      { k: 'flat', label: 'плоское дно', v: true, kind: 'bool' },
      { k: 'segments', label: 'плотность', v: 24, step: 2, min: 8, max: 64 },
    ],
  },
  {
    op: 'diamond', name: 'алмаз', title: 'Алмаз', group: 'Природные примитивы',
    desc: 'Нижний конус и верхняя огранка с площадкой; sharp — острая трапецевидная призма.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 40, step: 2, min: 1, max: 5000 },
      { k: 'crown', label: 'верх', v: 14, step: 1, min: 0.2, max: 5000 },
      { k: 'pavilion', label: 'низ', v: 26, step: 1, min: 0.2, max: 5000 },
      { k: 'sides', label: 'граней', v: 8, step: 1, min: 3, max: 64 },
      { k: 'sharp', label: 'острый', v: false, kind: 'bool' },
    ],
  },
  {
    op: 'horn', name: 'рог', title: 'Рог', group: 'Природные примитивы',
    desc: 'Изогнутый сужающийся рог — природа, трофей, декор.',
    params: [
      { k: 'length', label: 'длина', v: 160, step: 10, min: 10, max: 5000 },
      { k: 'radius', label: 'основание', v: 22, step: 2, min: 1, max: 5000 },
      { k: 'tip', label: 'кончик', v: 3, step: 0.5, min: 0.3, max: 5000 },
      { k: 'bend', label: 'изгиб', v: 55, step: 5, min: -400, max: 400 },
      { k: 'wall', label: 'полость', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'rock', name: 'камень', title: 'Камень', group: 'Природные примитивы',
    desc: 'Выпуклая оболочка: всегда замкнутый, seed повторяет форму.',
    params: [
      { k: 'size', label: 'размер', v: '120,90,55', kind: 'vec' },
      { k: 'seed', label: 'зерно', v: 3, step: 1, min: 0, max: 999999 },
      { k: 'rough', label: 'грубость', v: 0.35, step: 0.05, min: 0, max: 1 },
    ],
  },
  {
    op: 'leaf', name: 'листок', title: 'Лист растения', group: 'Природные примитивы',
    desc: 'Лист с изгибом; у клёна — глубокие пазухи, разнесённые лопасти и зубчатая центральная вершина.',
    params: [
      { k: 'length', label: 'длина', v: 90, step: 5, min: 5, max: 5000 },
      { k: 'width', label: 'ширина', v: 45, step: 5, min: 3, max: 5000 },
      { k: 'kind', label: 'вид', v: 'овал', kind: 'raw', choices: ['овал', 'липа', 'дуб', 'клен', 'заострённый'] },
      { k: 'curl', label: 'изгиб', v: 0.25, step: 0.05, min: 0, max: 1 },
    ],
  },
  {
    op: 'banana', name: 'банан', title: 'Банан / бровь', group: 'Природные примитивы',
    desc: 'Дуга с утолщением в середине: банан, бровь, стручок, скоба.',
    params: [
      { k: 'length', label: 'длина', v: 120, step: 5, min: 2, max: 5000 },
      { k: 'bend', label: 'изгиб°', v: 110, step: 10, min: 0, max: 340 },
      { k: 'thick', label: 'толщина', v: 28, step: 2, min: 0.4, max: 5000 },
      { k: 'flat', label: 'плоскость', v: 0.75, step: 0.05, min: 0.15, max: 1 },
      { k: 'taper', label: 'кончики', v: 0.32, step: 0.05, min: 0.03, max: 0.95 },
    ],
  },
  {
    op: 'yin_yang', name: 'инь_ян', title: 'Инь-ян (запятая)', group: 'Готовые детали',
    desc: 'Одна отдельная «шестёрка» площадью в половину круга; wall=0 — фигура, wall>0 — рамка.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 120, step: 5, min: 6, max: 5000 },
      { k: 'thick', label: 'толщина', v: 16, step: 2, min: 0.4, max: 5000 },
      { k: 'round', label: 'скругл.', v: 0, step: 0.5, min: 0, max: 1000 },
      { k: 'side', label: 'сторона', v: 'левый', kind: 'raw', choices: ['левый', 'правый'] },
      { k: 'hole', label: 'точка-отверстие', v: 0, step: 1, min: 0, max: 1000 },
      { k: 'wall', label: 'стенка рамки', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'crown', name: 'корона', title: 'Корона', group: 'Готовые детали',
    desc: 'Кольцо с зазубринами сверху: число зубьев, высота, скругление вершин, '
      + 'форма (треугольные, скруглённые, волна) и бортик по низу.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 150, step: 5, min: 4, max: 5000 },
      { k: 'height', label: 'обод', v: 48, step: 2, min: 0.5, max: 5000 },
      { k: 'wall', label: 'стенка', v: 4, step: 0.5, min: 0.4, max: 1000 },
      { k: 'teeth', label: 'зубьев', v: 12, step: 1, min: 3, max: 200 },
      { k: 'tooth', label: 'зуб', v: 30, step: 2, min: 0, max: 5000 },
      { k: 'tip', label: 'скругл.', v: 0.35, step: 0.05, min: 0, max: 1 },
      { k: 'shape', label: 'форма', v: 'треугольные', kind: 'raw', choices: ['треугольные', 'скруглённые', 'волна'] },
      { k: 'rim', label: 'бортик', v: 3, step: 1, min: 0, max: 1000 },
    ],
  },
  {
    op: 'arrow', name: 'стрелка', title: 'Стрелка', group: 'Готовые детали',
    desc: 'Указатель остриём вправо: древко, наконечник, вырез в хвосте.',
    params: [
      { k: 'length', label: 'длина', v: 120, step: 5, min: 1, max: 5000 },
      { k: 'width', label: 'древко', v: 26, step: 2, min: 0.2, max: 5000 },
      { k: 'head', label: 'наконеч.', v: 42, step: 2, min: 0.2, max: 5000 },
      { k: 'head_width', label: 'размах', v: 68, step: 2, min: 0.2, max: 5000 },
      { k: 'tail', label: 'вырез', v: 0, step: 2, min: 0, max: 5000 },
      { k: 'depth', label: 'толщина', v: 12, step: 1, min: 0.1, max: 1000 },
      { k: 'round', label: 'скругл.', v: 2, step: 0.5, min: 0, max: 1000 },
      { k: 'wall', label: 'формочка', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'tee', name: 'тавр', title: 'Форма Т', group: 'Готовые детали',
    desc: 'Буква Т: капсулы или бруски как у Y, одинаковая ширина всех ветвей, слитная развилка.',
    params: [
      { k: 'arm', label: 'переклад.', v: 90, step: 5, min: 1, max: 5000 },
      { k: 'bar', label: 'толщина', v: 20, step: 2, min: 0.4, max: 5000 },
      { k: 'stem', label: 'ножка', v: 22, step: 2, min: 0.4, max: 5000 },
      { k: 'leg', label: 'длина нож.', v: 60, step: 5, min: 0.4, max: 5000 },
      { k: 'depth', label: 'толщина Z', v: 14, step: 1, min: 0.1, max: 1000 },
      { k: 'round', label: 'скругл.', v: 2, step: 0.5, min: 0, max: 1000 },
      { k: 'shape', label: 'ветви', v: 'бруски', kind: 'raw', choices: ['бруски', 'капсулы'] },
    ],
  },
  {
    op: 'yoke', name: 'рогатка', title: 'Форма Y', group: 'Готовые детали',
    desc: 'Буква Y: капсулы/бруски и фактическое сглаживание кромок в месте слияния ветвей.',
    params: [
      { k: 'height', label: 'высота', v: 110, step: 5, min: 2, max: 5000 },
      { k: 'spread', label: 'размах', v: 64, step: 4, min: 0, max: 5000 },
      { k: 'arm', label: 'ветвь', v: 16, step: 1, min: 0.4, max: 5000 },
      { k: 'shape', label: 'ветви', v: 'капсулы', kind: 'raw', choices: ['капсулы', 'бруски'] },
      { k: 'fork', label: 'развилка', v: 0.38, step: 0.02, min: 0.1, max: 0.9 },
      { k: 'depth', label: 'толщина Z', v: 14, step: 1, min: 0.1, max: 1000 },
      { k: 'smooth', label: 'сглаживание', v: 0, step: 1, min: 0, max: 4 },
    ],
  },
  {
    op: 'plate', name: 'тарелка', title: 'Тарелка', group: 'Готовые детали',
    desc: 'Независимая глубина дна и прямой верхний бортик; rim_height работает и при rim=0.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 220, step: 5, min: 5, max: 5000 },
      { k: 'depth', label: 'глубина', v: 26, step: 1, min: 1, max: 1000 },
      { k: 'wall', label: 'стенка', v: 4, step: 0.5, min: 0.3, max: 1000 },
      { k: 'well', label: 'дно', v: 0.62, step: 0.02, min: 0.2, max: 0.9 },
      { k: 'rim', label: 'бортик', v: 4, step: 0.5, min: 0, max: 1000 },
      { k: 'rim_height', label: 'высота борта', v: 3, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'spring', name: 'пружина', title: 'Пружина', group: 'Готовые детали',
    desc: 'Винтовая пружина: средний диаметр, проволока, витки и шаг.',
    params: [
      { k: 'diameter', label: 'виток', v: 22, step: 1, min: 1, max: 5000 },
      { k: 'wire', label: 'провол.', v: 3, step: 0.2, min: 0.2, max: 5000 },
      { k: 'turns', label: 'витки', v: 8, step: 1, min: 0.5, max: 200 },
      { k: 'pitch', label: 'шаг', v: 6, step: 0.5, min: 0.2, max: 5000 },
      { k: 'right', label: 'правая', v: true, kind: 'bool' },
    ],
  },
  {
    op: 'gear', name: 'шестерня', title: 'Шестерня', group: 'Готовые детали',
    desc: 'Прямозубая: число зубьев, модуль, толщина, ступица и отверстие.',
    params: [
      { k: 'teeth', label: 'зубья', v: 20, step: 1, min: 6, max: 200 },
      { k: 'module', label: 'модуль', v: 2, step: 0.25, min: 0.05, max: 5000 },
      { k: 'thickness', label: 'толщина', v: 8, step: 1, min: 0.2, max: 5000 },
      { k: 'bore', label: 'отверстие', v: 8, step: 1, min: 0, max: 5000 },
      { k: 'hub', label: 'ступица', v: 0, step: 2, min: 0, max: 5000 },
    ],
  },
  {
    op: 'saw', name: 'пила', title: 'Дисковая пила', group: 'Готовые детали',
    desc: 'Плоское полотно с зубьями; hole=0 даёт сплошной центр. Зубья: треугольные, трапеция, крюк, волна; передний угол rake.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 200, step: 10, min: 20, max: 4000 },
      { k: 'thickness', label: 'толщина', v: 2.5, step: 0.5, min: 0.3, max: 60 },
      { k: 'teeth', label: 'зубьев', v: 24, step: 2, min: 4, max: 200 },
      { k: 'tooth', label: 'высота зуба', v: 10, step: 1, min: 0.2, max: 5000 },
      { k: 'shape', label: 'форма зубьев', v: 'трапеция', kind: 'raw', choices: ['треугольные', 'трапеция', 'крюк', 'волна'] },
      { k: 'rake', label: 'передний угол', v: 10, step: 5, min: -75, max: 75 },
      { k: 'taper', label: 'лезвие', v: 0, step: 0.1, min: 0, max: 0.9 },
      { k: 'hole', label: 'отверстие', v: 22, step: 2, min: 0, max: 1000 },
      { k: 'windows', label: 'окон', v: 0, step: 1, min: 0, max: 12 },
    ],
  },
  {
    op: 'nut', name: 'гайка', title: 'Гайка', group: 'Готовые детали',
    desc: 'Шестигранная гайка с настоящей внутренней резьбой.',
    params: [
      { k: 'd', label: 'резьба', v: 8, step: 1, min: 1, max: 300 },
      { k: 'pitch', label: 'шаг', v: 1.25, step: 0.25, min: 0.1, max: 20 },
      { k: 'h', label: 'высота', v: 6.4, step: 0.2, min: 0.6, max: 400 },
    ],
  },
  {
    op: 'bolt', name: 'болт', title: 'Болт', group: 'Готовые детали',
    desc: 'Шестигранная головка и резьба на стержне.',
    params: [
      { k: 'd', label: 'резьба', v: 8, step: 1, min: 1, max: 300 },
      { k: 'length', label: 'длина', v: 30, step: 1, min: 1, max: 2000 },
      { k: 'pitch', label: 'шаг', v: 1.25, step: 0.25, min: 0.1, max: 20 },
    ],
  },
  {
    op: 'screw', name: 'винт', title: 'Винт / саморез', group: 'Готовые детали',
    desc: 'Головка с крестом или шестилопастным Torx; neck=0 подводит резьбу сразу к головке.',
    params: [
      { k: 'd', label: 'диаметр', v: 4, step: 0.5, min: 0.5, max: 100 },
      { k: 'length', label: 'длина', v: 25, step: 1, min: 1, max: 1000 },
      { k: 'head', label: 'головка', v: 'потай', kind: 'raw', choices: ['потай', 'полукруг', 'шестигранник', 'нет'] },
      { k: 'drive', label: 'шлиц', v: 'крест', kind: 'raw', choices: ['крест', 'шлиц', 'звезда', 'шестигранник', 'нет'] },
      { k: 'drive_depth', label: 'глубина шлица', v: '', step: 0.2, min: 0.1, auto: true },
      { k: 'neck', label: 'гладкая шейка', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'pulley', name: 'шкив', title: 'Шкив', group: 'Готовые детали',
    desc: 'Обод с канавкой под ремень; bore=0 делает шкив сплошным, без осевого отверстия.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 80, step: 5, min: 10, max: 1000 },
      { k: 'width', label: 'ширина', v: 20, step: 1, min: 4, max: 300 },
      { k: 'bore', label: 'вал (0 — сплошной)', v: 10, step: 1, min: 0, max: 5000 },
      { k: 'grooves', label: 'ручьёв', v: 1, step: 1, min: 1, max: 8 },
      { k: 'groove', label: 'ширина ручья', v: 6, step: 1, min: 1, max: 1000 },
      { k: 'groove_depth', label: 'глубина ручья', v: 2.4, step: 0.2, min: 0.2, max: 1000 },
    ],
  },
  {
    op: 'box_body', name: 'ящик', title: 'Коробка с полостью', group: 'Готовые детали',
    desc: 'Открытый сверху корпус с дном и стенками — ящик, лоток, кожух.',
    params: [
      { k: 'size', label: 'размер', v: '200,150,80', kind: 'vec' },
      { k: 'wall', label: 'стенка', v: 4, step: 0.5, min: 0.2, max: 1000 },
      { k: 'bottom', label: 'дно', v: 6, step: 0.5, min: 0.2, max: 5000 },
      { k: 'round', label: 'скругл.', v: 8, step: 1, min: 0, max: 1000 },
    ],
  },
  {
    op: 'shaft', name: 'вал', title: 'Вал с буртиком', group: 'Готовые детали',
    desc: 'Ступенчатый вал: буртик задаётся шириной и диаметром, фаски и осевое отверстие.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 20, step: 1, min: 0.5, max: 5000 },
      { k: 'length', label: 'длина', v: 120, step: 5, min: 1, max: 5000 },
      { k: 'flange', label: 'буртик', v: 6, step: 1, min: 0, max: 5000 },
      { k: 'flange_d', label: 'Ø буртика', v: 46, step: 1, min: 0.01, max: 5000 },
      { k: 'bore', label: 'осевое', v: 6, step: 1, min: 0, max: 5000 },
    ],
  },
  {
    op: 'wheel', name: 'колесо', title: 'Колесо', group: 'Готовые детали',
    desc: 'Шина, обод, спицы и ступица. Ось по Y; 1 спица — сплошной диск.',
    params: [
      { k: 'diameter', label: 'Ø по шине', v: 300, step: 10, min: 20, max: 5000 },
      { k: 'width', label: 'ширина', v: 90, step: 5, min: 6, max: 5000 },
      { k: 'tire', label: 'шина', v: 21, step: 1, min: 2, max: 5000 },
      { k: 'rim', label: 'обод', v: 18, step: 1, min: 2, max: 1000 },
      { k: 'spokes', label: 'спиц', v: 5, step: 1, min: 1, max: 24 },
      { k: 'hub', label: 'ступица', v: 40, step: 2, min: 6, max: 5000 },
    ],
  },
  {
    op: 'spiral', name: 'спираль', title: 'Спираль', group: 'Готовые детали',
    desc: 'Плоская улитка из центра наружу: пружинка, завиток, креманка.',
    params: [
      { k: 'radius', label: 'радиус', v: 60, step: 2, min: 1, max: 5000 },
      { k: 'turns', label: 'витки', v: 3, step: 0.5, min: 0.25, max: 40 },
      { k: 'wire', label: 'нить', v: 6, step: 0.5, min: 0.2, max: 5000 },
      { k: 'height', label: 'высота', v: 6, step: 1, min: 0.05, max: 5000 },
    ],
  },
  {
    op: 'plus', name: 'плюс', title: 'Плюс', group: 'Готовые детали',
    desc: 'Перекрестие из двух брусьев: аптечка, крест, перекладина.',
    params: [
      { k: 'arm', label: 'длина', v: 60, step: 2, min: 1, max: 5000 },
      { k: 'thick', label: 'брус', v: 18, step: 1, min: 0.5, max: 5000 },
      { k: 'depth', label: 'толщина', v: 14, step: 1, min: 0.2, max: 1000 },
      { k: 'round', label: 'скругл.', v: 1.5, step: 0.5, min: 0, max: 1000 },
      { k: 'wall', label: 'формочка', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'rope', name: 'верёвка', title: 'Верёвка', group: 'Готовые детали',
    desc: 'Кручёные нити вокруг общей оси: канат, шнур, трос.',
    params: [
      { k: 'length', label: 'длина', v: 200, step: 10, min: 2, max: 5000 },
      { k: 'diameter', label: '⌀', v: 20, step: 1, min: 0.5, max: 5000 },
      { k: 'strands', label: 'нити', v: 3, step: 1, min: 2, max: 12 },
      { k: 'twist', label: 'свивка', v: 55, step: 5, min: 1, max: 10000 },
    ],
  },
  {
    op: 'цепь', name: 'цепочка', title: 'Цепь', group: 'Готовые детали',
    desc: 'Настоящая цепь: звенья вытянутые, соседние повёрнуты на 90° и '
      + 'зацеплены друг за друга — не ряд колец рядом. Размер звена, толщина '
      + 'прутка и направление.',
    params: [
      { k: 'links', label: 'звеньев', v: 8, step: 1, min: 1, max: 200 },
      { k: 'size', label: 'звено', v: 24, step: 2, min: 1, max: 2000 },
      { k: 'wire', label: 'пруток', v: 3, step: 0.5, min: 0.2, max: 5000 },
    ],
  },
  {
    op: 'крюк', name: 'крюк', title: 'Крюк', group: 'Готовые детали',
    desc: 'Одна непрерывная дуга без кольца; смещённая дуга соединяется плавной кривой с согласованными касательными.',
    params: [
      { k: 'wire', label: 'пруток', v: 6, step: 0.5, min: 0.4, max: 200 },
      { k: 'radius', label: 'изгиб', v: 22, step: 1, min: 0.01, max: 2000 },
      { k: 'length', label: 'хвост', v: 70, step: 5, min: 0, max: 5000 },
      { k: 'open', label: 'загиб', v: 240, min: 45, max: 350, step: 15,
        kind: 'slider', suffix: '°' },
      { k: 'offset', label: 'сдвиг дуги X,Z', v: '0,0', kind: 'vec' },
      { k: 'aspect', label: 'овальность', v: 1, step: 0.1, min: 0.35, max: 2.5 },
      { k: 'curve', label: 'боковой прогиб', v: 0, step: 1, min: -2000, max: 2000 },
      { k: 'tip', label: 'кончик', v: 'капсула', kind: 'raw', choices: ['капсула', 'острый'] },
      { k: 'taper', label: 'сужение', v: 0.94, step: 0.02, min: 0, max: 0.98 },
    ],
  },
  {
    op: 'handle', name: 'ручка', title: 'Ручка-скоба', group: 'Готовые детали',
    desc: 'Независимые перекладина и стойки. Сквозные стойки видны над перекладиной: одна или обе, с настройкой выхода.',
    params: [
      { k: 'length', label: 'длина', v: 160, step: 10, min: 21, max: 5000 },
      { k: 'height', label: 'вынос', v: 34, step: 2, min: 12, max: 2000 },
      { k: 'diameter', label: 'толщина', v: 10, step: 1, min: 1, max: 500 },
      { k: 'bar_shape', label: 'перекладина', v: 'капсула', kind: 'raw', choices: ['цилиндр', 'капсула', 'брусок'] },
      { k: 'post_shape', label: 'стойки', v: 'капсула', kind: 'raw', choices: ['цилиндр', 'капсула', 'брусок'] },
      { k: 'posts', label: 'стоек', v: 2, step: 1, min: 1, max: 2 },
      { k: 'post_mode', label: 'стойки вверху', v: 'стык', kind: 'raw', choices: ['стык', 'сквозь'] },
      { k: 'post_top', label: 'выход над перекладиной', v: 10, step: 1, min: 0, max: 2000 },
      { k: 'plates', label: 'площадки', v: true, kind: 'bool' },
      { k: 'plate_d', label: 'Ø площадки', v: 24, step: 1, min: 12, max: 200 },
    ],
  },
  {
    op: 'cardboard', name: 'картон', title: 'Гофрокартон', group: 'Готовые детали',
    desc: 'Гофрированный картон одним телом: плоские линеры и гофра между ними. 2 слоя — линер и гофра, 3 — с обеих сторон.',
    params: [
      { k: 'width', label: 'ширина', v: 200, step: 10, min: 2, max: 5000 },
      { k: 'height', label: 'высота', v: 300, step: 10, min: 2, max: 5000 },
      { k: 'liner', label: 'линер', v: 0.4, step: 0.1, min: 0.1, max: 20 },
      { k: 'flute', label: 'гофра', v: 3.5, step: 0.5, min: 0.4, max: 200 },
      { k: 'step', label: 'шаг', v: 8, step: 1, min: 1, max: 400 },
      { k: 'layer', label: 'слоёв', v: 3, step: 1, min: 2, max: 3 },
    ],
  },
  {
    op: 'swirl', name: 'завиток', title: 'Завиток', group: 'Готовые детали',
    desc: 'Непрерывная спираль; merge сращивает витки без промежутков, base скрывает начало в плоском основании крема.',
    params: [
      { k: 'radius', label: 'радиус', v: 40, step: 2, min: 2, max: 5000 },
      { k: 'height', label: 'высота', v: 64, step: 4, min: 3, max: 10000 },
      { k: 'coils', label: 'витков', v: 3, step: 1, min: 1, max: 12 },
      { k: 'wire', label: 'Ø трубы', v: 16, step: 1, min: 0.2, max: 20 },
      { k: 'taper', label: 'сужение', v: 0.62, step: 0.05, min: 0, max: 0.92 },
      { k: 'merge', label: 'слить витки', v: false, kind: 'bool' },
      { k: 'base', label: 'плоское основание', v: false, kind: 'bool' },
    ],
  },

  {
    op: 'stairs', name: 'ступеньки', title: 'Ступеньки', group: 'Готовые детали',
    desc: 'Прямой марш без скосов. Наружная кромка и внутренний угол независимо бывают прямыми или скруглёнными.',
    params: [
      { k: 'steps', label: 'ступеней', v: 6, step: 1, min: 1, max: 120 },
      { k: 'rise', label: 'подъём', v: 18, step: 1, min: 0.5, max: 2000 },
      { k: 'run', label: 'проступь', v: 28, step: 1, min: 0.5, max: 5000 },
      { k: 'width', label: 'ширина', v: 120, step: 10, min: 1, max: 10000 },
      { k: 'shape', label: 'наружная кромка', v: 'прямая', kind: 'raw', choices: ['прямая', 'скруглённая'] },
      { k: 'round', label: 'радиус кромки', v: 4.5, step: 0.5, min: 0, max: 8.1 },
      { k: 'inner', label: 'внутренний угол', v: 'прямой', kind: 'raw', choices: ['прямой', 'скруглённый'] },
      { k: 'inner_r', label: 'радиус угла', v: 4.5, step: 0.5, min: 0, max: 8.1 },
    ],
  },
  {
    op: 'ladder', name: 'лестница', title: 'Лестница', group: 'Готовые детали',
    desc: 'Две рейки и чисто состыкованные перекладины. Овал — плоские бока и полукруглые торцы, не эллипсоид.',
    params: [
      { k: 'length', label: 'длина', v: 1800, step: 50, min: 50, max: 10000 },
      { k: 'width', label: 'ширина', v: 420, step: 10, min: 20, max: 5000 },
      { k: 'rail', label: 'рейка', v: 'капсула', kind: 'raw', choices: ['капсула', 'брусок', 'овал'] },
      { k: 'rail_d', label: 'толщина рейки', v: 38, step: 2, min: 2, max: 1000 },
      { k: 'rungs', label: 'перекладин', v: 9, step: 1, min: 1, max: 80 },
      { k: 'rung', label: 'перекладина', v: 'цилиндр', kind: 'raw', choices: ['цилиндр', 'брусок'] },
      { k: 'rung_d', label: 'толщина перекл.', v: 30, step: 2, min: 1, max: 38 },
      { k: 'tilt', label: 'наклон', v: 72, step: 3, min: 0, max: 90 },
    ],
  },
  {
    op: 'lever', name: 'рычаг', title: 'Рычаг', group: 'Готовые детали',
    desc: 'Палка и шар или цилиндр на конце. Длина наконечника работает и для шара; палка не проходит сквозь него.',
    params: [
      { k: 'length', label: 'общая длина', v: 180, step: 10, min: 60, max: 10000 },
      { k: 'shaft', label: 'палка', v: 'цилиндр', kind: 'raw', choices: ['цилиндр', 'брусок'] },
      { k: 'diameter', label: 'толщина', v: 14, step: 1, min: 0.5, max: 34 },
      { k: 'knob', label: 'наконечник', v: 'шар', kind: 'raw', choices: ['шар', 'цилиндр'] },
      { k: 'knob_d', label: 'толщина наконечника', v: 34, step: 2, min: 20, max: 2000 },
      { k: 'knob_h', label: 'длина наконечника', v: 60, step: 5, min: 1, max: 180 },
      { k: 'angle', label: 'наклон', v: 0, step: 5, min: -89, max: 89 },
    ],
  },
  {
    op: 'button', name: 'кнопка', title: 'Кнопка (2 детали)', group: 'Готовые детали',
    desc: 'Подвижная шляпка и отдельное гнездо; скругляются только переходные кромки, рабочие плоскости и посадка сохраняются.',
    params: [
      { k: 'diameter', label: '⌀ шляпки', v: 30, step: 1, min: 1, max: 1000 },
      { k: 'height', label: 'высота шляпки', v: 10, step: 1, min: 0.6, max: 1000 },
      { k: 'top', label: 'верх', v: 'вогнутая', kind: 'raw', choices: ['плоская', 'вогнутая', 'выпуклая'] },
      { k: 'base', label: 'гнездо', v: 'цилиндр', kind: 'raw', choices: ['цилиндр', 'квадрат'] },
      { k: 'base_d', label: 'размер гнезда', v: 66, step: 2, min: 31.5, max: 2000 },
      { k: 'base_h', label: 'высота гнезда', v: 8, step: 1, min: 1, max: 1000 },
      { k: 'fit', label: 'посадка', v: 'плотно', kind: 'raw', choices: ['плотно', 'зазор'] },
      { k: 'gap', label: 'зазор', v: 3, step: 0.5, min: 0, max: 100 },
      { k: 'smooth', label: 'сглаживание', v: 0, step: 1, min: 0, max: 4 },
    ],
  },
  {
    op: 'gusset', name: 'косынка', title: 'Косынка', group: 'Готовые детали',
    desc: 'Прямой треугольник или прежняя круглая горка с одним прямоугольным вырезом настраиваемой глубины и ширины.',
    params: [
      { k: 'leg', label: 'катет', v: 70, step: 5, min: 0.2, max: 10000 },
      { k: 'height', label: 'высота', v: 55, step: 5, min: 0.2, max: 10000 },
      { k: 'thickness', label: 'толщина', v: 6, step: 1, min: 0.05, max: 2000 },
      { k: 'shape', label: 'форма', v: 'прямо', kind: 'raw', choices: ['прямо', 'горка'] },
      { k: 'notch', label: 'глубина выреза', v: 8, step: 1, min: 0, max: 1000 },
      { k: 'notch_width', label: 'ширина выреза', v: 24, step: 1, min: 0.2, max: 5000 },
    ],
  },
  {
    op: 'grommet', name: 'люверс', title: 'Люверс', group: 'Готовые детали',
    desc: 'Втулка с бортиком под шнур или провод, с необязательным Loop-сглаживанием.',
    params: [
      { k: 'diameter', label: 'внутри', v: 12, step: 1, min: 1, max: 5000 },
      { k: 'height', label: 'высота', v: 8, step: 1, min: 1, max: 2000 },
      { k: 'wall', label: 'стенка', v: 1.6, step: 0.2, min: 0.3, max: 1000 },
      { k: 'flange', label: 'борт', v: 3, step: 0.5, min: 0.2, max: 1000 },
      { k: 'smooth', label: 'сглаживание', v: 0, step: 1, min: 0, max: 4 },
    ],
  },
  {
    op: 'blade', name: 'клинок', title: 'Клинок', group: 'Готовые детали',
    desc: 'kind реально меняет геометрию: одна кромка с тупой спинкой, две кромки или крюк серпа; сгиб идёт вверх/вниз в плоскости клинка.',
    params: [
      { k: 'length', label: 'длина', v: 700, step: 20, min: 40, max: 10000 },
      { k: 'width', label: 'ширина', v: 32, step: 2, min: 2, max: 2000 },
      { k: 'thick', label: 'толщина', v: 7, step: 0.5, min: 0.6, max: 22.4 },
      { k: 'curve', label: 'сгиб', v: 20, step: 5, min: -350, max: 350 },
      { k: 'kind', label: 'вид', v: 'катана', kind: 'raw', choices: ['катана', 'танто', 'ятоган', 'стилет', 'двуручник', 'серп', 'нож'] },
      { k: 'profile', label: 'силуэт', v: 'прямой', kind: 'raw', choices: ['прямой', 'суженный', 'листовой'] },
      { k: 'section', label: 'сечение', v: 'клин', kind: 'raw', choices: ['линза', 'клин', 'плоский', 'алмаз'] },
      { k: 'tip', label: 'остриё', v: 'киссаки', kind: 'raw', choices: ['острое', 'киссаки', 'закруглённое', 'тупое'] },
      { k: 'taper', label: 'сужение', v: 0.55, step: 0.05, min: 0, max: 0.9 },
      { k: 'kissaki', label: 'зона острия', v: 0.06, step: 0.01, min: 0.01, max: 0.35 },
    ],
  },
  {
    op: 'column', name: 'колонна', title: 'Колонна', group: 'Готовые детали',
    desc: 'Площадка, вертикальный стержень и бортик: ровный, конус или песочные часы.',
    params: [
      { k: 'height', label: 'высота', v: 180, step: 5, min: 10, max: 10000 },
      { k: 'width', label: 'ширина', v: 42, step: 2, min: 1, max: 5000 },
      { k: 'depth', label: 'глубина', v: 42, step: 2, min: 1, max: 5000 },
      { k: 'form', label: 'стержень', v: 'ровная', kind: 'raw', choices: ['ровная', 'конус', 'песочные'] },
      { k: 'waist', label: 'талия', v: 0.55, step: 0.05, min: 0.2, max: 1 },
      { k: 'taper', label: 'сужение', v: 0.35, step: 0.05, min: 0, max: 0.85 },
      { k: 'section', label: 'сечение', v: 'цилиндр', kind: 'raw', choices: ['цилиндр', 'брусок'] },
      { k: 'base', label: 'площадка', v: 'да', kind: 'raw', choices: ['да', 'нет'] },
      { k: 'base_size', label: 'размер площадки', v: 72, step: 2, min: 1, max: 5000 },
      { k: 'base_h', label: 'высота площадки', v: 12, step: 1, min: 0, max: 5000 },
      { k: 'rim', label: 'вылет бортика', v: 8, step: 1, min: 0, max: 1000 },
      { k: 'rim_h', label: 'высота бортика', v: 10, step: 1, min: 0, max: 5000 },
      { k: 'smooth', label: 'сглаживание', v: 0, step: 1, min: 0, max: 4 },
      { k: 'segments', label: 'сегментов', v: 48, step: 4, min: 12, max: 128 },
    ],
  },
  {
    op: 'profile2020', name: 'профиль2020', title: 'Профиль 2020', group: 'Готовые детали',
    desc: 'Четыре продольных паза, форма угловых реек и осевое отверстие четырёх форм.',
    params: [
      { k: 'length', label: 'длина', v: 300, step: 10, min: 5, max: 10000 },
      { k: 'size', label: 'сечение', v: 20, step: 1, min: 8, max: 1000 },
      { k: 'slot', label: 'горловина', v: 6, step: 0.5, min: 0.8, max: 500 },
      { k: 'channel', label: 'углубление', v: 9, step: 0.5, min: 1, max: 500 },
      { k: 'depth', label: 'глубина паза', v: 4, step: 0.5, min: 0.6, max: 500 },
      { k: 'groove', label: 'форма паза', v: 'прямоугольная', kind: 'raw', choices: ['прямоугольная', 'треугольная', 'овальная'] },
      { k: 'rail', label: 'рейки', v: 'скруглённая', kind: 'raw', choices: ['прямая', 'скруглённая', 'фаска'] },
      { k: 'rail_r', label: 'радиус/фаска', v: 1.2, step: 0.2, min: 0.1, max: 100 },
      { k: 'bore', label: 'осевое отверстие', v: 5, step: 0.5, min: 0, max: 500 },
      { k: 'bore_shape', label: 'форма оси', v: 'круг', kind: 'raw', choices: ['круг', 'квадрат', 'треугольник', 'шестигранник'] },
    ],
  },
  {
    op: 'cube_hole', name: 'кубик', title: 'Кубик с отверстием', group: 'Готовые детали',
    desc: 'Брусок со сквозным круглым, квадратным или треугольным отверстием.',
    params: [
      { k: 'size', label: 'размер', v: '40,40,40', kind: 'vec' },
      { k: 'hole', label: 'отверстие', v: 16, step: 1, min: 0.2, max: 1000 },
      { k: 'hole_shape', label: 'форма', v: 'круг', kind: 'raw', choices: ['круг', 'квадрат', 'треугольник'] },
      { k: 'axis', label: 'ось', v: 'z', kind: 'raw', choices: ['z', 'x', 'y'] },
      { k: 'round', label: 'скругл.', v: 2, step: 0.5, min: 0, max: 1000 },
    ],
  },



  {
    op: 'pipe', name: 'трубка', title: 'Труба со стенкой', group: 'Готовые детали',
    desc: 'Простая длина и угол без координат; плавный радиус или острый стык, настоящая стенка.',
    params: [
      { k: 'length', label: 'длина', v: 200, step: 10, min: 1, max: 100000 },
      { k: 'angle', label: 'сгиб°', v: 90, step: 5, min: -180, max: 180 },
      { k: 'radius', label: 'радиус', v: 80, step: 5, min: 0.5, max: 100000 },
      { k: 'joint', label: 'сгиб', v: 'плавный', kind: 'raw', choices: ['плавный', 'острый'] },
      { k: 'diameter', label: 'диаметр', v: 32, step: 1, min: 1, max: 5000 },
      { k: 'wall', label: 'стенка', v: 2, step: 0.5, min: 0.2, max: 1000 },
      { k: 'sides', label: 'сегментов', v: 24, step: 4, min: 8, max: 96 },
    ],
  },





  {
    op: 'worm_shaft', name: 'червяк', title: 'Червячный вал', group: 'Готовые детали',
    desc: 'Цилиндр с настоящим винтовым витком: шаг, глубина, заходы.',
    params: [
      { k: 'length', label: 'длина', v: 90, step: 5, min: 6, max: 5000 },
      { k: 'diameter', label: 'диаметр', v: 30, step: 2, min: 4, max: 5000 },
      { k: 'pitch', label: 'шаг', v: 8, step: 1, min: 1, max: 5000 },
      { k: 'depth', label: 'виток', v: 4, step: 0.5, min: 0.4, max: 1000 },
    ],
  },
  {
    op: 'seven_seg', name: 'индикатор', title: 'Семисегментный', group: 'Готовые детали',
    desc: 'Светодиодные цифры: «21:38». С материалом led сразу горит.',
    params: [
      { k: 'text', label: 'текст', v: '21:38', kind: 'raw' },
      { k: 'height', label: 'высота', v: 54, step: 2, min: 1, max: 5000 },
      { k: 'depth', label: 'толщина', v: 2, step: 0.5, min: 0.05, max: 1000 },
    ],
  },
  {
    op: 'display', name: 'экран', title: 'Экран', group: 'Готовые детали',
    group: 'Люди и вещи',
    desc: 'Смартфон, будильник, монитор: корпус, тёмная панель, горящие цифры и стекло.',
    params: [
      { k: 'width', label: 'ширина', v: 160, step: 5, min: 6, max: 5000 },
      { k: 'height', label: 'высота', v: 90, step: 5, min: 6, max: 5000 },
      { k: 'thick', label: 'толщина', v: 40, step: 2, min: 1, max: 5000 },
      { k: 'style', label: 'вид', v: 'будильник', kind: 'raw', choices: ['смартфон', 'будильник', 'монитор'] },
      { k: 'content', label: 'на экране', v: 'led', kind: 'raw' },
      { k: 'text', label: 'надпись', v: '21:38', kind: 'raw' },
    ],
  },
  {
    op: 'mirror_plate', name: 'зеркало', title: 'Зеркало', group: 'Готовые детали',
    group: 'Люди и вещи',
    desc: 'Рама, отражающая пластина и подвес: прямоугольное, круглое или овальное.',
    params: [
      { k: 'width', label: 'ширина', v: 600, step: 20, min: 20, max: 5000 },
      { k: 'height', label: 'высота', v: 900, step: 20, min: 20, max: 5000 },
      { k: 'frame', label: 'рама', v: 40, step: 2, min: 2, max: 5000 },
      { k: 'shape', label: 'форма', v: 'прямоуг', kind: 'raw', choices: ['прямоуг', 'круг', 'овал'] },
    ],
  },
  {
    op: 'dent', name: 'вмятина', title: 'Вмятина от удара', group: 'Скульпт',
    base: 'box size=[60, 60, 60] round=4', baseName: 'заготовка',
    desc: 'Поверхность проминается внутрь, перед ударом сетка дробится под '
      + 'размер пятна. soft задаёт мягкость: у мягкого материала вмятина '
      + 'широкая и гладкая, у жёсткого — узкая, с валиком по краю.',
    params: [
      { k: 'depth', label: 'глубина', v: 8, step: 0.5, min: 0.1, max: 1000 },
      { k: 'radius', label: 'пятно', v: 18, step: 1, min: 1, max: 5000 },
      { k: 'soft', label: 'мягкость', v: 0.5, step: 0.1, min: 0, max: 1 },
      { k: 'rim', label: 'валик', v: 0.3, step: 0.1, min: 0, max: 1 },
    ],
  },
  {
    op: 'blow', name: 'выдутая', title: 'Выдувание объёма', group: 'Скульпт',
    base: 'sphere radius=30 segments=40', baseName: 'заготовка',
    desc: 'Как у стеклодува: поверхность расходится вдоль своих нормалей. '
      + 'Шар надувается шаром, цилиндр — бочкой.',
    params: [
      { k: 'height', label: 'выдуть', v: 12, step: 0.5, min: 0.1, max: 5000 },
      { k: 'radius', label: 'пятно', v: 40, step: 1, min: 1, max: 5000 },
      { k: 'soft', label: 'мягкость', v: 0.7, step: 0.1, min: 0, max: 1 },
    ],
  },
  {
    op: 'pinch', name: 'щипок', title: 'Щипок', group: 'Скульпт',
    base: 'sphere radius=30 segments=40', baseName: 'заготовка',
    desc: 'Давление с двух сторон: деталь сжимается по оси, материал '
      + 'выдавливается наружу — как если ухватить пальцами.',
    params: [
      { k: 'amount', label: 'сжать', v: 0.4, step: 0.05, min: 0.01, max: 0.9 },
      { k: 'bulge', label: 'выдавить', v: 0.8, step: 0.1, min: 0, max: 2 },
      { k: 'radius', label: 'захват', v: 16, step: 1, min: 1, max: 5000 },
      { k: 'axis', label: 'ось', v: 'x', kind: 'raw', choices: ['x', 'y', 'z'] },
    ],
  },
  {
    op: 'flatten', name: 'плоская', title: 'Разровнять в плоскость', group: 'Скульпт',
    base: 'sphere radius=32 segments=48', baseName: 'заготовка',
    desc: 'Подтягивает участок к плоскости: сила 1 — совсем плоско, меньше — '
      + 'мягко. Не путать с разглаживанием: тут именно плоскость.',
    params: [
      { k: 'radius', label: 'пятно', v: 24, step: 1, min: 1, max: 5000 },
      { k: 'strength', label: 'сила', v: 0.9, step: 0.05, min: 0, max: 1 },
      { k: 'soft', label: 'переход', v: 0.6, step: 0.1, min: 0, max: 1 },
    ],
  },
  {
    op: 'polish', name: 'гладкая', title: 'Разгладить поверхность', group: 'Скульпт',
    base: 'sphere radius=30 segments=10', baseName: 'заготовка',
    desc: 'Убирает шероховатость и «лесенки», но не делает плоскостью: '
      + 'форма и объём остаются. Проходов больше — глаже.',
    params: [
      { k: 'passes', label: 'проходов', v: 4, step: 1, min: 1, max: 20 },
      { k: 'strength', label: 'сила', v: 0.6, step: 0.05, min: 0.05, max: 1 },
    ],
  },
  {
    op: 'shave', name: 'стёсанная', title: 'Стесать поверхность', group: 'Скульпт',
    base: 'box size=[50, 50, 90] round=3', baseName: 'заготовка',
    desc: 'Снимает слой ровной фасеткой под любым углом — как ножом или '
      + 'наждаком. Круг ограничивает пятно, 0 — вся поверхность.',
    params: [
      { k: 'depth', label: 'снять', v: 12, step: 1, min: 0.1, max: 1000 },
      { k: 'radius', label: 'пятно', v: 0, step: 2, min: 0, max: 5000 },
    ],
  },
  {
    op: 'point', name: 'заострённая', title: 'Заострить (точилка)', group: 'Скульпт',
    base: 'cylinder radius=8 height=90 segments=40', baseName: 'заготовка',
    desc: 'Снимает конус с торца — как точилка карандаш. Длина конуса '
      + 'задаётся, вершина встаёт ровно на прежний торец.',
    params: [
      { k: 'length', label: 'конус', v: 25, step: 1, min: 0.2, max: 5000 },
      { k: 'side', label: 'торец', v: 'верх', kind: 'raw', choices: ['верх', 'низ'] },
    ],
  },
  {
    op: 'bore', name: 'сверлёная', title: 'Сверление с формой дна', group: 'Скульпт',
    base: 'box size=[80, 70, 22]', baseName: 'заготовка',
    desc: 'Отверстие нужной формы: плоское дно, конус сверла, сфера или '
      + 'ступень под шляпку. Зенковка — по желанию.',
    params: [
      { k: 'diameter', label: 'диаметр', v: 14, step: 1, min: 0.4, max: 5000 },
      { k: 'depth', label: 'глубина', v: 14, step: 1, min: 0.2, max: 1000 },
      { k: 'tip', label: 'дно', v: 'конус', kind: 'raw', choices: ['плоский', 'конус', 'сфера', 'ступень'] },
      { k: 'countersink', label: 'зенковка', v: 0, step: 0.5, min: 0, max: 1000 },
    ],
  },
  {
    op: 'refine', name: 'плотная', title: 'Полигонаж (плотность сетки)', group: 'Скульпт',
    base: 'sphere radius=30 segments=12', baseName: 'заготовка',
    desc: 'Повышает плотность сетки перед тонкой работой: вмятины и складки '
      + 'лягут гладко, без гранёных краёв. length — целевая длина ребра.',
    params: [
      { k: 'length', label: 'ребро', v: 2, step: 0.5, min: 0.05, max: 5000 },
    ],
  },
  {
    op: 'wrinkle', name: 'складки', title: 'Складки и мятая поверхность', group: 'Поверхность',
    group: 'Поверхность', base: 'box size=[80,80,80]',
    desc: 'Волны по поверхности: ткань, гофра, кора, пемза. Режимы: радиус, высота, шум, клетка, трещины.',
    params: [
      { k: 'amp', label: 'высота', v: 3, step: 0.5, min: 0, max: 1000 },
      { k: 'freq', label: 'частота', v: 6, step: 1, min: 0.5, max: 1000 },
      { k: 'mode', label: 'режим', v: 'радиус', kind: 'raw', choices: ['радиус', 'высота', 'шум', 'клетка', 'трещины'] },
    ],
  },
  {
    op: 'relief', name: 'рельеф', title: 'Рельеф по картинке', group: 'Поверхность',
    group: 'Поверхность', base: 'box size=[120,80,10]',
    desc: 'Выдавливает карту высот (PNG) на поверхность: логотип, узор, текст. Обёртка вокруг тела или плоскость.',
    params: [
      { k: 'image', label: 'карта', v: 'docs/pattern.png', kind: 'raw' },
      { k: 'depth', label: 'глубина', v: 2, step: 0.5, min: 0.01, max: 1000 },
      { k: 'mode', label: 'режим', v: 'плоскость', kind: 'raw', choices: ['обёртка', 'плоскость'] },
    ],
  },
  {
    op: 'porous', name: 'пористый', title: 'Поры и губка', group: 'Поверхность',
    group: 'Поверхность', base: 'sphere radius=40',
    desc: 'Поры, ячеи, пузыри и глазки настоящими углублениями — пемза, губка, сыр.',
    params: [
      { k: 'mode', label: 'режим', v: 'поры', kind: 'raw', choices: ['поры', 'ячеи', 'пузыри', 'глазки'] },
      { k: 'size', label: 'размер', v: 4, step: 0.5, min: 0.2, max: 5000 },
      { k: 'count', label: 'сколько', v: 60, step: 5, min: 1, max: 600 },
    ],
  },
  {
    op: 'scales', name: 'чешуя', title: 'Чешуя', group: 'Поверхность',
    group: 'Поверхность', base: 'sphere radius=40',
    desc: 'Наложенные чешуйки: рыба, дракон, шишка. Ряды, шаг и подъём задаются числами.',
    params: [
      { k: 'rows', label: 'рядов', v: 10, step: 1, min: 1, max: 60 },
      { k: 'per_row', label: 'в ряду', v: 16, step: 1, min: 3, max: 120 },
      { k: 'length', label: 'размер', v: 8, step: 1, min: 0.3, max: 5000 },
    ],
  },
  {
    op: 'lattice', name: 'решётка', title: 'Решётка', group: 'Поверхность',
    group: 'Поверхность', base: 'sphere radius=60',
    desc: 'Сетка из прутьев сквозь тело: купол, окно, корзина. Узор: прямоуг, ромб, соты.',
    params: [
      { k: 'cell', label: 'ячейка', v: 18, step: 1, min: 2, max: 5000 },
      { k: 'wire', label: 'прут', v: 4, step: 0.5, min: 0.3, max: 5000 },
      { k: 'mode', label: 'узор', v: 'ромб', kind: 'raw', choices: ['прямоуг', 'ромб', 'соты'] },
    ],
  },
  {
    op: 'bark', name: 'кора', title: 'Кора дерева', group: 'Поверхность',
    group: 'Поверхность',
    desc: 'Ствол с бороздами коры и сужением кверху — сразу готовое тело.',
    params: [
      { k: 'height', label: 'высота', v: 600, step: 20, min: 5, max: 5000 },
      { k: 'radius', label: 'радиус', v: 90, step: 5, min: 1, max: 5000 },
      { k: 'grooves', label: 'борозд', v: 14, step: 1, min: 3, max: 64 },
      { k: 'depth', label: 'глубина', v: 9, step: 1, min: 0, max: 1000 },
    ],
  },
  {
    op: 'bricks', name: 'кладка', title: 'Кирпичная кладка', group: 'Поверхность',
    group: 'Поверхность',
    desc: 'Стена или камин кладкой вперевязку: кирпич, шов и глубина шва.',
    params: [
      { k: 'width', label: 'ширина', v: 400, step: 20, min: 10, max: 5000 },
      { k: 'height', label: 'высота', v: 300, step: 20, min: 10, max: 5000 },
      { k: 'thick', label: 'толщина', v: 40, step: 5, min: 2, max: 5000 },
      { k: 'brick', label: 'кирпич', v: '90, 42', kind: 'vec' },
      { k: 'joint', label: 'шов', v: 7, step: 1, min: 0.2, max: 1000 },
    ],
  },
  {
    op: 'repair', name: 'починка', title: 'Починка скана', group: 'Поверхность',
    group: 'Поверхность', base: 'sphere radius=40',
    desc: 'Сглаживает и упрощает сетку, убирает мусор — доводит скан до рабочего тела.',
    params: [
      { k: 'smooth', label: 'сглаж.', v: 1, step: 1, min: 0, max: 5 },
    ],
  },
  {
    op: 'corrugate', name: 'гофра', title: 'Гофрирование', group: 'Поверхность',
    base: 'sheet width=160 length=220 thickness=1', baseName: 'заготовка',
    desc: 'Гофра, вафля, рифление или зигзаг по готовой детали: шаг узора и высота волны. Валики, рифлёный металл, гофробумага.',
    params: [
      { k: 'step', label: 'шаг', v: 22, step: 2, min: 0.2, max: 4000 },
      { k: 'amp', label: 'высота', v: 5, step: 0.5, min: 0, max: 500 },
      { k: 'mode', label: 'узор', v: 'гофра', kind: 'raw', choices: ['гофра', 'вафля', 'рифление', 'зигзаг'] },
      { k: 'angle', label: 'поворот', v: 0, step: 15, min: -180, max: 180 },
    ],
  },
  {
    op: 'fold', name: 'сложенный', title: 'Сложить (оригами)', group: 'Форма',
    base: 'sheet width=120 length=240 thickness=1', baseName: 'заготовка',
    desc: 'Складывает деталь как бумагу: пополам, на треть, гармошкой. gap — просвет между слоями; поверхность не пересекает себя.',
    params: [
      { k: 'parts', label: 'на части', v: 2, step: 1, min: 2, max: 12 },
      { k: 'angle', label: 'угол', v: 180, step: 10, min: 1, max: 180 },
      { k: 'gap', label: 'просвет', v: 0.5, step: 0.25, min: 0.02, max: 5000 },
      { k: 'sharp', label: 'жёсткость', v: 0, step: 0.1, min: 0, max: 1 },
      { k: 'axis', label: 'вдоль', v: 'x', kind: 'raw', choices: ['x', 'y'] },
    ],
  },
  {
    op: 'сгиб', name: 'сгиб_угол', title: 'Сгиб от угла', group: 'Форма',
    base: 'sheet width=120 length=120 thickness=1', baseName: 'заготовка',
    desc: 'Складывает лист по произвольной линии: от угла, по диагонали, под '
      + 'любым углом к краю. dir — куда идёт линия (0 — вдоль X, 45 — от угла), '
      + 'angle — насколько сложить, side — какая половина подвижная. Бумага не '
      + 'тянется: это честная изометрия.',
    params: [
      { k: 'at', label: 'точка', v: '[0, 0, 1]', kind: 'raw' },
      { k: 'dir', label: 'линия, °', v: 45, step: 15, min: -180, max: 180 },
      { k: 'angle', label: 'сложить, °', v: 120, step: 10, min: 1, max: 180 },
      { k: 'side', label: 'сторона', v: '1', kind: 'raw', choices: ['1', '-1'] },
    ],
  },
  {
    op: 'складка', name: 'залом', title: 'Складка / залом', group: 'Форма',
    base: 'box size=[80, 40, 120] round=6', baseName: 'заготовка',
    desc: 'След сгиба на поверхности: валик или канавка по линии from→to. '
      + 'Именно это делает одежду одеждой — заломы у локтя, рёбра на бумаге. '
      + 'bend изгибает линию, taper сужает концы.',
    params: [
      { k: 'from', label: 'от', v: '[-30, -20, 60]', kind: 'raw' },
      { k: 'to', label: 'до', v: '[30, -20, 60]', kind: 'raw' },
      { k: 'r', label: 'радиус', v: 4, step: 0.5, min: 0.2, max: 200 },
      { k: 'mode', label: 'вид', v: 'канавка', kind: 'raw', choices: ['гребень', 'канавка'] },
      { k: 'bend', label: 'изгиб', v: 0, step: 2, min: -200, max: 200 },
    ],
  },
  {
    op: 'ряд', name: 'градация', title: 'Ряд с градацией', group: 'Массивы',
    base: 'torus major=10 minor=2', baseName: 'кольцо',
    desc: 'Копии не одинаковые, а со ступенями изменения: каждая следующая '
      + 'сдвинута на step, выросла в grow раз и повёрнута на turn. '
      + 'А если задать инструмент — его сила растёт по шагу_силы: вмятины '
      + 'всё глубже, кольца всё шире. Так рисуют значок Wi-Fi.',
    params: [
      { k: 'count', label: 'копий', v: 4, step: 1, min: 1, max: 60 },
      { k: 'grow', label: 'рост', v: 1.4, step: 0.05, min: 0.2, max: 5 },
      { k: 'turn', label: 'поворот, °', v: 0, step: 15, min: -360, max: 360 },
      { k: 'step', label: 'сдвиг', v: '[0, 0, 0]', kind: 'raw' },
    ],
  },
  {
    op: 'размер', name: 'по_мерке', title: 'Размер по мерке', group: 'Массивы',
    base: 'box size=[80, 50, 30]', baseName: 'ящик',
    desc: 'Задаёт детали габарит не множителем, а числом или меркой соседа: '
      + 'width=1.5*width(ящик) — ширина ровно в полтора раза больше ящика. '
      + 'Остальные оси не меняются, keep=да сохранит пропорции.',
    params: [
      { k: 'width', label: 'ширина, мм', v: 120, step: 5, min: 0.1, max: 5000 },
      { k: 'height', label: 'высота, мм', v: 30, step: 5, min: 0.1, max: 5000 },
    ],
  },
  {
    op: 'hair', name: 'волосы', title: 'Волосы', group: 'Люди и вещи',
    group: 'Люди и вещи',
    desc: 'Причёска из прядей одним телом: аниме, хвост, короткий, мех. Пряди, рваность, толщина.',
    params: [
      { k: 'length', label: 'длина', v: 200, step: 10, min: 2, max: 5000 },
      { k: 'radius', label: 'голова', v: 65, step: 5, min: 3, max: 5000 },
      { k: 'style', label: 'стиль', v: 'аниме', kind: 'raw', choices: ['аниме', 'хвост', 'короткий', 'мех'] },
      { k: 'clumps', label: 'прядей', v: 24, step: 2, min: 3, max: 400 },
    ],
  },
  {
    op: 'skirt', name: 'юбка', title: 'Юбка', group: 'Люди и вещи',
    group: 'Люди и вещи',
    desc: 'Юбка со складками: пояс, подол, толщина ткани — полая, её можно надеть на фигуру.',
    params: [
      { k: 'waist', label: 'пояс', v: 76, step: 2, min: 5, max: 5000 },
      { k: 'hem', label: 'подол', v: 190, step: 5, min: 5, max: 5000 },
      { k: 'length', label: 'длина', v: 240, step: 10, min: 3, max: 5000 },
      { k: 'pleats', label: 'складок', v: 12, step: 2, min: 0, max: 120 },
      { k: 'depth', label: 'глубина', v: 10, step: 1, min: 0, max: 1000 },
      { k: 'thick', label: 'ткань', v: 3, step: 0.5, min: 0.2, max: 5000 },
    ],
  },
  {
    op: 'jacket', name: 'пиджак', title: 'Пиджак', group: 'Люди и вещи',
    group: 'Люди и вещи',
    desc: 'Пиджак с рукавами, лацканами и пуговицами: обхваты в миллиметрах, силуэт по талии.',
    params: [
      { k: 'height', label: 'высота', v: 740, step: 20, min: 50, max: 5000 },
      { k: 'chest', label: 'грудь', v: 1040, step: 20, min: 100, max: 5000 },
      { k: 'waist', label: 'талия', v: 920, step: 20, min: 100, max: 5000 },
      { k: 'buttons', label: 'пуговиц', v: 2, step: 1, min: 0, max: 4 },
    ],
  },
  {
    op: 'pattern', name: 'узор', title: 'Покраска узором', group: 'Покраска',
    group: 'Покраска', base: 'box size=[60,60,60]',
    desc: 'Фигуры на поверхности: круги (горошек), кольца, полосы, клетка, треугольники, ромбы, волны.',
    params: [
      { k: 'color', label: 'цвет', v: '#d94f3d', kind: 'raw' },
      { k: 'shape', label: 'фигура', v: 'круги', kind: 'raw', choices: ['круги', 'кольца', 'полосы', 'клетка', 'треугольники', 'ромбы', 'волны'] },
      { k: 'size', label: 'размер', v: 12, step: 1, min: 0.01, max: 5000 },
      { k: 'step', label: 'шаг', v: 24, step: 1, min: 0.01, max: 5000 },
      { k: 'angle', label: 'угол', v: 0, step: 5, min: -360, max: 360 },
    ],
  },
  {
    op: 'anime', name: 'аниме-стиль', title: 'Аниме / манга', group: 'Покраска',
    noTarget: true,
    base: 'ваза = lathe points=[[0,0],[26,0],[40,30],[30,62],[16,90],[0,92]]',
    desc: 'Чёрные контуры по форме: силуэт, рёбра и стыки деталей. Плюс ступени '
      + 'тона, растр и бумага — и в окне, и на снимках.',
    params: [
      { k: 'mode', label: 'стиль', v: 'аниме', kind: 'raw', choices: ['аниме', 'манга', 'комикс', 'скетч', 'линия', 'выкл'] },
      { k: 'line', label: 'контур', v: 1.8, step: 0.1, min: 0, max: 12 },
      { k: 'crease', label: 'излом', v: 32, step: 1, min: 1, max: 89 },
      { k: 'toon', label: 'ступени', v: 3, step: 1, min: 0, max: 8 },
      { k: 'tone', label: 'растр', v: 0, step: 0.05, min: 0, max: 1 },
    ],
  },
];


/* Ступени каталога: сначала тела, потом приёмы. Списки заодно задают порядок
   групп в панели — карточки внутри группы идут в порядке массива. */
const PRIMITIVE_GROUPS = ['Стандартные примитивы', 'Производные примитивы',
  'Природные примитивы', 'Готовые детали'];
const TOOL_GROUP_ORDER = ['Скульпт', 'Поверхность', 'Форма', 'Массивы',
  'Люди и вещи', 'Покраска'];
const TOOL_RECIPES = [
  {
    title: 'Наполнение',
    desc: 'Сыплет зёрна в открытую посуду: тарелка, миска, ящик. Уровень, плотность и seed '
      + 'задают раскладку — одна и та же строка всегда даёт одну и ту же кашу.',
    fields: [
      { k: 'd', label: '⌀ посуды', v: 180 },
      { k: 'depth', label: 'глубина', v: 55 },
      { k: 'grain', label: 'зерно', v: 'зерно', kind: 'raw', choices: ['шар', 'горох', 'зерно', 'капля', 'куб', 'галька'] },
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
      { k: 'grain', label: 'зерно', v: 'галька', kind: 'raw', choices: ['шар', 'горох', 'зерно', 'капля', 'куб', 'галька'] },
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
      { k: 'mode', label: 'режим', v: 'авто', kind: 'raw', choices: ['авто', 'скругление', 'фаска'] },
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
      { k: 'open', label: 'открыт', v: 'top', kind: 'raw', choices: ['top', 'bottom', 'both'] },
    ],
    build: (v) => `корпус_полый = box size=[${rvec(v.size, [120, 80, 50]).join(', ')}] round=4\n`
      + `корпус_полый = shell [корпус_полый] thickness=${fnum(rnum(v.thickness, 3))} open=${v.open || 'top'}`,
  },
  {
    title: 'Зеркальная пара',
    desc: 'mirror_copy оставляет деталь и добавляет её отражение — парные кронштейны, ручки.',
    fields: [
      { k: 'size', label: 'размер', v: '30,20,60', kind: 'vec' },
      { k: 'plane', label: 'плоскость', v: 'x', kind: 'raw', choices: ['x', 'y', 'z'] },
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
  {
    title: 'Деталь по осям хозяина',
    desc: 'Корпус повёрнут — и его верх больше не +Z. place осями=хозяина ставит '
      + 'деталь на настоящий верх корпуса и разворачивает её вместе с ним.',
    fields: [
      { k: 'angle', label: 'поворот', v: 90 },
      { k: 'side', label: 'сторона', v: 'top', kind: 'raw',
        choices: ['top', 'bottom', 'left', 'right', 'front', 'back'] },
    ],
    build: (v) => `корпус = box size=[140,40,40] round=3\n`
      + `корпус = rotate [корпус] angle=${fnum(rnum(v.angle, 90))} axis=y\n`
      + 'крышка = cylinder radius=18 height=6\n'
      + `крышка = place [крышка] on=корпус side=${v.side || 'top'} осями=хозяина`,
  },
  {
    title: 'Деталь на границу',
    desc: 'на_границе ищет не центр габарита, а настоящую поверхность: шайба садится '
      + 'на кольцо тора, шарик — на его бок. align=нормаль разворачивает деталь по нормали.',
    fields: [
      { k: 'obj', label: 'деталь', v: '', kind: 'raw' },
      { k: 'host', label: 'хозяин', v: '', kind: 'raw' },
      { k: 'point', label: 'точка', v: '60,0,8', kind: 'vec' },
      { k: 'offset', label: 'зазор', v: 0 },
      { k: 'align', label: 'по нормали', v: true, kind: 'bool' },
    ],
    build: (v) => {
      let obj = String(v.obj || '').trim();
      let host = String(v.host || '').trim();
      let head = '';
      if (!obj) { obj = 'шайба'; head += 'шайба = cylinder radius=6 height=4\n'; }
      if (!host) { host = 'кольцо'; head += 'кольцо = torus major=40 minor=8\n'; }
      const p = rvec(v.point, [60, 0, 8]);
      const align = v.align ? ' align=нормаль' : '';
      return head + `${obj} = на_границе [${obj}] on=${host} `
        + `point=[${p.map(fnum).join(', ')}] offset=${fnum(rnum(v.offset, 0))}${align}`;
    },
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

/** Палитра для стрелочек у цвета: ▴/▾ листают оттенки. */
const TOOL_COLOR_STEPS = ['#d94f3d', '#e0a33a', '#e8d44d', '#3ac07a', '#3aa9e0',
  '#8b5cf6', '#f2f4f8', '#2b2f38'];

/** Число из текста поля или null, если это не число («40, 30» — уже не число). */
function numFromText(raw) {
  const t = String(raw ?? '').trim().replace(',', '.');
  return /^[-+]?(\d+\.?\d*|\.\d+)$/.test(t) ? Number(t) : null;
}

/**
 * Следующее значение поля при шаге стрелкой.
 *
 * * число — прибавляем step (и держимся в min…max);
 * * текст с вариантами (`choices`) — следующий вариант: kind, mode, side…;
 * * цвет `#rrggbb` — следующий оттенок из палитры;
 * * время `21:38` — минута с переходом через час;
 * * текст с числом на конце — это число.
 *
 * null — шагать нечем, стрелки у такого поля не показываем.
 */
function stepToolValue(p, raw, dir) {
  const text = String(raw ?? '').trim();
  const choices = Array.isArray(p.choices) ? p.choices : null;
  if (choices && choices.length > 1) {
    const low = text.toLowerCase();
    let i = choices.findIndex((c) => String(c).toLowerCase() === low);
    if (i < 0) i = dir > 0 ? -1 : 0;
    return String(choices[(i + dir + choices.length * 2) % choices.length]);
  }
  // пустое поле с пометкой «авто» (например, кромка линзы): шагаем от нуля,
  // а min/max не дадут уйти в бессмыслицу
  const num = text === '' && p.auto ? 0 : numFromText(text);
  if (num !== null) {
    const step = Number(p.step ?? 1) || 1;
    let v = num + step * dir;
    if (p.min !== undefined && p.min !== null) v = Math.max(Number(p.min), v);
    if (p.max !== undefined && p.max !== null) v = Math.min(Number(p.max), v);
    return fnum(v);
  }
  const time = text.match(/^(\d{1,2}):(\d{2})$/);
  if (time) {
    let h = Number(time[1]);
    let m = Number(time[2]) + dir;
    if (m > 59) { m = 0; h = (h + 1) % 24; }
    if (m < 0) { m = 59; h = (h + 23) % 24; }
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  }
  if (/^#[0-9a-f]{6}$/i.test(text)) {
    let i = TOOL_COLOR_STEPS.findIndex((c) => c.toLowerCase() === text.toLowerCase());
    if (i < 0) i = dir > 0 ? -1 : 0;
    return TOOL_COLOR_STEPS[(i + dir + TOOL_COLOR_STEPS.length * 2) % TOOL_COLOR_STEPS.length];
  }
  if (p.kind === 'vec' || p.kind === 'raw') return null;
  const tail = text.match(/^(.*?)(\d+)(\D*)$/);
  if (!tail) return null;
  const n = Math.max(0, parseInt(tail[2], 10) + dir);
  return tail[1] + String(n).padStart(tail[2].length, '0') + tail[3];
}

/** Стрелки шага у поля: короткий щелчок — один шаг, удержание — повтор. */
function attachToolStep(p, input) {
  const wrap = document.createElement('span');
  wrap.className = 'tool-step-wrap';
  const wide = p.kind === 'vec' || p.kind === 'raw';
  const canStep = stepToolValue(p, input.value, 1) !== null
    || stepToolValue(p, input.value, -1) !== null;
  if (!canStep) {
    wrap.appendChild(input);
    return wrap;
  }
  // с кнопками поле чуть уже: карточка узкая, перенос строки не нужен
  input.style.width = wide ? '104px' : '52px';
  const apply = (dir) => {
    const next = stepToolValue(p, input.value, dir);
    if (next === null) return;
    input.value = next;
    // то же событие, что и при ручном вводе: миниатюра пересобирается сама
    input.dispatchEvent(new Event('input', { bubbles: true }));
  };
  const button = (dir) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'tool-step';
    b.dataset.dir = String(dir);
    b.textContent = dir > 0 ? '▴' : '▾';
    b.tabIndex = -1;
    b.title = dir > 0
      ? 'Больше / следующий вариант (↑ в поле)'
      : 'Меньше / предыдущий вариант (↓ в поле)';
    let hold = null;
    let timer = null;
    const stop = () => {
      clearTimeout(hold);
      clearInterval(timer);
      hold = null;
      timer = null;
    };
    b.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      apply(dir);
      hold = setTimeout(() => { timer = setInterval(() => apply(dir), 110); }, 420);
    });
    ['pointerup', 'pointerleave', 'pointercancel'].forEach((ev) => {
      b.addEventListener(ev, stop);
    });
    b.addEventListener('click', (e) => e.preventDefault());
    return b;
  };
  input.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    e.preventDefault();
    apply(e.key === 'ArrowUp' ? 1 : -1);
  });
  wrap.append(button(-1), input, button(1));
  return wrap;
}

/**
 * Поле карточки инструмента: подпись, ввод и стрелки шага.
 *
 * Стрелки работают и для чисел, и для текстовых значений: у параметра с
 * готовыми вариантами они листают варианты (вид линзы, сторона инь-яна,
 * тип патрона, стиль аниме), у цвета — палитру, у времени — минуту.
 */
function buildToolField(p) {
  const row = document.createElement('div');
  row.className = 'tool-field';
  const caption = document.createElement('span');
  caption.className = 'tool-field-cap';
  caption.textContent = p.label;
  // длинная подпись не сжимает поле: она обрезается с многоточием и
  // раскрывается подсказкой
  caption.title = p.label;
  row.appendChild(caption);
  if (p.kind === 'slider') {
    // Ползунок для «степени детализации»: тянешь — миниатюра и число
    // треугольников меняются сразу, без ввода цифр с клавиатуры.
    row.classList.add('tool-field-slider');
    row.style.gridColumn = 'span 2';
    const box = document.createElement('span');
    box.className = 'tool-slider-wrap';
    const input = document.createElement('input');
    input.type = 'range';
    input.min = String(p.min ?? 0);
    input.max = String(p.max ?? 5);
    input.step = String(p.step ?? 1);
    input.value = String(p.v ?? p.min ?? 0);
    input.dataset.key = p.k;
    input.title = p.hint || `параметр «${p.k}»`;
    const out = document.createElement('output');
    out.className = 'tool-slider-val';
    out.textContent = sliderText(p, input.value);
    input.addEventListener('input', () => { out.textContent = sliderText(p, input.value); });
    box.append(input, out);
    row.appendChild(box);
    return row;
  }
  if (p.kind === 'bool') {
    row.classList.add('tool-field-bool');
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = p.v !== false;
    box.dataset.key = p.k;
    row.appendChild(box);
    return row;
  }
  const input = document.createElement('input');
  input.type = 'text';
  input.value = String(p.v ?? '');
  const wide = p.kind === 'vec' || p.kind === 'raw';
  if (!wide && !p.choices) input.inputMode = 'decimal';
  // ширина — по сетке карточки: вектору даём две колонки
  if (wide) row.style.gridColumn = 'span 2';
  if (p.auto) input.placeholder = 'авто';
  const tips = [`параметр «${p.k}»`];
  if (p.choices && p.choices.length) {
    tips.push('варианты: ' + p.choices.join(' · ') + ' (стрелки листают)');
  }
  if (p.min !== undefined || p.max !== undefined) {
    tips.push(`допустимо ${p.min ?? '…'}…${p.max ?? '…'}`);
  }
  input.title = tips.join(' · ');
  input.dataset.key = p.k;
  row.appendChild(attachToolStep(p, input));
  return row;
}

/** Что показать справа от ползунка: само значение и (для детализации) ×. */
function sliderText(p, value) {
  if (p.kind === 'slider' && p.suffix) return `${value}${p.suffix}`;
  return String(value);
}

/** Поля рецепта — те же, что у фигур: подпись, поле ввода и стрелки шага. */
function recipeFields(params) {
  const wrap = document.createElement('div');
  wrap.className = 'tool-fields';
  (params || []).forEach((p) => wrap.appendChild(buildToolField(p)));
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

/** Значения полей карточки в строку «ключ=значение». */
function shapeParams(tool, card) {
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
    } else {
      parts.push(`${p.k}=${raw}`);
    }
  });
  return parts;
}

/** Готовый сценарий карточки: заготовка (если нужна) + сама команда. */
function shapeScript(tool, card, { unique = false } = {}) {
  const parts = shapeParams(tool, card);
  const tail = parts.length ? ' ' + parts.join(' ') : '';
  const script = unique ? currentScript() : '';
  if (tool.base) {
    const baseName = unique
      ? uniqueObjectName(tool.baseName || 'заготовка', script)
      : (tool.baseName || 'заготовка');
    if (tool.noTarget) {
      return `${baseName} = ${tool.base}\n${tool.op}${tail}`;
    }
    return `${baseName} = ${tool.base}\n${tool.op} ${baseName}${tail}`;
  }
  const name = unique ? uniqueObjectName(tool.name, script) : tool.name;
  return `${name} = ${tool.op} ${parts.join(' ')}`.trim();
}

function addShapeTool(tool, card) {
  insertTool(shapeScript(tool, card, { unique: true }), tool.title);
}

/* ---------------- живые миниатюры в карточках инструментов ---------------- */
const toolThumbs = new ToolThumbs();
state.thumbsOn = state.thumbsOn !== false;
// сценарий → {url, tris, size}: повторные карточки не дёргают сервер
const thumbUrls = new Map();
const thumbTimers = new Map();
let thumbObserver = null;
const THUMB_W = 480;
const THUMB_H = 360;

function thumbScript(tool, card) {
  return shapeScript(tool, card);
}

async function thumbUrl(script) {
  if (thumbUrls.has(script)) return thumbUrls.get(script);
  // Деталь миниатюры сервер уже построил: берём из ответа и число
  // треугольников — карточка сразу пишет, сколько будет «весить» примитив.
  const res = await api('/api/preview', { script });
  if (!res.ok) {
    const err = res.error || {};
    // Причину не теряем: имя параметра и его рамки едут в интерфейс
    const fail = new Error(err.message || res.message || 'не удалось построить');
    fail.param = err.param || '';
    fail.bounds = err.bounds || '';
    fail.hint = err.hint || '';
    fail.detail = err;
    throw fail;
  }
  const url = res.url + (res.url.includes('?') ? '&' : '?')
    + 'token=' + encodeURIComponent(TOKEN);
  const info = { url, tris: res.tris || 0, size: res.size || [], objects: res.objects || 1 };
  thumbUrls.set(script, info);
  return info;
}

/** Подпись под миниатюрой: сколько треугольников и какой габарит. */
function toolTrisText(info) {
  const bits = [];
  if (info.tris) bits.push(`${fmtInt(info.tris)} трис`);
  const size = (info.size || []).filter((v) => Number.isFinite(Number(v)));
  if (size.length === 3) {
    bits.push(size.map((v) => fmt(Math.round(Number(v)))).join(' × ') + ' мм');
  }
  if (info.objects > 1) bits.push(`${info.objects} детали`);
  return bits.join(' · ');
}

function showToolTris(card, info) {
  const badge = card.querySelector('.tool-tris');
  if (!badge) return;
  const text = toolTrisText(info || {});
  badge.textContent = text;
  badge.hidden = !text;
}

/** Собирает миниатюру карточки. Ракурс не сбрасываем — так видно правку. */
/** Красит поле карточки, из-за которого деталь не построилась, и пишет рамки. */
function markToolFieldError(card, err) {
  card.querySelectorAll('.tool-field.bad').forEach((row) => {
    row.classList.remove('bad');
    const note = row.querySelector('.tool-field-note');
    if (note) note.remove();
  });
  const key = err?.param;
  if (!key) return;
  const input = card.querySelector(`.tool-field input[data-key="${key}"]`);
  const row = input?.closest('.tool-field');
  if (!row) return;
  row.classList.add('bad');
  const note = document.createElement('span');
  note.className = 'tool-field-note';
  note.textContent = err.bounds ? `допустимо ${err.bounds}` : 'недопустимое значение';
  row.appendChild(note);
  input.title = `${err.message || ''}${err.hint ? `\n${err.hint}` : ''}`;
}

async function refreshThumb(card) {
  const canvas = card.querySelector('canvas.tool-shot');
  if (!canvas || !card.dataset.toolId) return;
  const tool = (TOOL_SHAPES.find((t, i) => String(i) === card.dataset.toolId));
  if (!tool) return;
  if (!state.thumbsOn || !toolThumbs.enabled) return;
  const script = thumbScript(tool, card);
  const stamp = String(Date.now());
  card.dataset.thumbBusy = '1';
  try {
    const info = await thumbUrl(script);
    if (card.dataset.thumbBusy !== '1') return;   // карточку уже перерисовали
    canvas.dataset.url = info.url;
    toolThumbs.show(canvas, info.url);
    canvas.classList.add('ready');
    showToolTris(card, info);
  } catch (err) {
    if (card.dataset.thumbBusy === '1') {
      showToolTris(card, null);
      toolThumbs.fail(canvas, {
        reason: err?.message || 'деталь не построилась',
        bounds: err?.bounds || '',
        hint: err?.hint || '',
        title: err?.message || 'Деталь не построилась',
      });
      markToolFieldError(card, err);
    }
  } finally {
    if (card.dataset.thumbBusy === '1') delete card.dataset.thumbBusy;
    void stamp;
  }
}

function scheduleThumb(card, delay = 420) {
  const id = card.dataset.toolId;
  if (id === undefined) return;
  clearTimeout(thumbTimers.get(id));
  thumbTimers.set(id, setTimeout(() => refreshThumb(card), delay));
}

/** Следим за видимостью: строим только те карточки, что на экране. */
function observeThumbs(root) {
  thumbObserver?.disconnect();
  if (!('IntersectionObserver' in window)) return;
  thumbObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const card = entry.target;
      thumbObserver.unobserve(card);
      scheduleThumb(card, 30);
    });
  }, { root, rootMargin: '260px 0px', threshold: 0.01 });
  document.querySelectorAll('#tools-body .tool-card[data-tool-id]').forEach((card) => {
    thumbObserver.observe(card);
  });
}

function makeThumbCanvas() {
  const canvas = document.createElement('canvas');
  canvas.className = 'tool-shot';
  canvas.width = THUMB_W;
  canvas.height = THUMB_H;
  canvas.title = 'Потяните мышью — деталь повернётся, колесо — приблизит, '
    + 'двойной щелчок — сброс ракурса';
  return canvas;
}

/* ---------------- 3D-превью детали из «Инструментов» ---------------- */
let preview3d = null;
let previewTool = null;
let previewCard = null;

function previewOpen() {
  return !$('preview-modal')?.hidden;
}

async function loadToolPreview() {
  if (!previewTool || !previewCard) return;
  const script = shapeScript(previewTool, previewCard);
  $('preview-loading').hidden = false;
  $('preview-error').hidden = true;
  $('preview-meta').textContent = '';
  try {
    const res = await api('/api/preview', { script });
    if (!res.ok) {
      const err = res.error || { message: res.message || 'Не удалось построить деталь' };
      throw err;
    }
    const url = res.url + (res.url.includes('?') ? '&' : '?') + 'token='
      + encodeURIComponent(TOKEN);
    await preview3d.load(url);
    preview3d.setWire($('preview-wire')?.classList.contains('active'));
    const size = (res.size || []).map((v) => Math.round(v));
    const bits = [];
    if (size.length === 3) bits.push(`${size[0]}×${size[1]}×${size[2]} мм`);
    if (res.tris) bits.push(`${fmtInt(res.tris)} трис`);
    $('preview-meta').textContent = bits.join(' · ');
  } catch (err) {
    const box = $('preview-error');
    if (box) {
      box.innerHTML = '';
      const head = document.createElement('strong');
      head.textContent = 'Почему нет модели';
      box.appendChild(head);
      const why = document.createElement('p');
      why.className = 'preview-error-why';
      why.textContent = err?.message || 'Не удалось построить превью';
      box.appendChild(why);
      if (err?.param) {
        const param = document.createElement('p');
        param.className = 'preview-error-param';
        param.textContent = err.bounds
          ? `параметр «${err.param}» — допустимо ${err.bounds}`
          : `параметр «${err.param}»`;
        box.appendChild(param);
      }
      if (err?.hint) {
        const hint = document.createElement('p');
        hint.className = 'preview-error-hint';
        hint.textContent = err.hint;
        box.appendChild(hint);
      }
      box.hidden = false;
    }
  } finally {
    $('preview-loading').hidden = true;
  }
}

async function openToolPreview(tool, card) {
  previewTool = tool;
  previewCard = card;
  $('preview-title').textContent = `${tool.title} · ${tool.op}`;
  $('preview-modal').hidden = false;
  if (!preview3d) preview3d = new Preview3D($('preview-canvas'));
  else preview3d.resize();
  $('preview-spin')?.classList.add('active');
  preview3d.setSpin(true);
  await loadToolPreview();
}

function closeToolPreview() {
  $('preview-modal').hidden = true;
  previewTool = null;
  previewCard = null;
}

$('preview-close')?.addEventListener('click', closeToolPreview);
$('preview-modal')?.addEventListener('click', (e) => {
  if (e.target === $('preview-modal')) closeToolPreview();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && previewOpen()) closeToolPreview();
});
$('preview-refresh')?.addEventListener('click', () => loadToolPreview());
$('preview-add')?.addEventListener('click', () => {
  if (!previewTool || !previewCard) return;
  addShapeTool(previewTool, previewCard);
  closeToolPreview();
});
$('preview-spin')?.addEventListener('click', (e) => {
  const on = !e.currentTarget.classList.contains('active');
  e.currentTarget.classList.toggle('active', on);
  preview3d?.setSpin(on);
});
$('preview-fit')?.addEventListener('click', () => preview3d?.fit());
$('preview-wire')?.addEventListener('click', (e) => {
  const on = !e.currentTarget.classList.contains('active');
  e.currentTarget.classList.toggle('active', on);
  preview3d?.setWire(on);
});

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
  if (c.orientation) {
    const orientation = document.createElement('div');
    orientation.className = 'tool-desc';
    orientation.textContent = 'Исходная ориентация: ' + c.orientation;
    card.appendChild(orientation);
  }
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
    c.orientation || '', ...(c.params || []).map((p) => p.name + ' ' + p.desc)]
    .join(' ').toLowerCase();
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
    const key = tool.group || 'Готовые детали';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(tool);
  });
  // Порядок жёсткий: стандартные тела → производные → природные → готовые
  // детали, и только потом инструменты. Иначе список открывается случайной
  // фигурой, а не кубом.
  // имя не `order`: ниже в этой же функции уже есть `order` для категорий
  // справочника — повторное объявление роняло весь модуль
  const groupOrder = PRIMITIVE_GROUPS.filter((g) => groups.has(g))
    .concat(TOOL_GROUP_ORDER.filter((g) => groups.has(g)))
    .concat([...groups.keys()].filter((g) => !PRIMITIVE_GROUPS.includes(g)
      && !TOOL_GROUP_ORDER.includes(g)));
  let sectionName = '';
  groupOrder.forEach((title) => {
    const tools = groups.get(title);
    const wanted = PRIMITIVE_GROUPS.includes(title) ? 'Примитивы' : 'Инструменты и способы';
    if (wanted !== sectionName) {
      sectionName = wanted;
      const bar = document.createElement('div');
      bar.className = 'tool-sec';
      bar.innerHTML = `<h3>${wanted}</h3><span>${wanted === 'Примитивы'
        ? 'стандартные тела → производные → природные → готовые детали'
        : 'приёмы и способы: лепка, поверхности, массивы, стиль'}</span>`;
      body.appendChild(bar);
    }
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
      card.dataset.toolId = String(TOOL_SHAPES.indexOf(tool));
      const cardHead = document.createElement('div');
      cardHead.className = 'tool-card-head';
      cardHead.innerHTML = `<b>${escapeHtml(tool.title)}</b><code>${escapeHtml(tool.op)}</code>`;
      card.appendChild(cardHead);
      const desc = document.createElement('div');
      desc.className = 'tool-desc';
      desc.textContent = tool.desc;
      card.appendChild(desc);
      // Живая миниатюра: деталь видно сразу, без отдельного окна. Поля ниже
      // пересобирают её на лету — правка видна, не отрываясь от карточки.
      card.appendChild(makeThumbCanvas());
      // Сколько треугольников в детали при текущих ползунках — видно сразу,
      // до добавления в сценарий (число приходит вместе с миниатюрой).
      const trisBadge = document.createElement('div');
      trisBadge.className = 'tool-tris';
      trisBadge.hidden = true;
      card.appendChild(trisBadge);
      const fields = document.createElement('div');
      fields.className = 'tool-fields';
      tool.params.forEach((p) => fields.appendChild(buildToolField(p)));
      card.appendChild(fields);
      card.dataset.search = [tool.title, tool.op, tool.name, tool.desc, title,
        ...tool.params.map((p) => p.label)].join(' ').toLowerCase();
      const actions = document.createElement('div');
      actions.className = 'tool-actions';
      const view3d = document.createElement('button');
      view3d.className = 'small tool-preview-btn';
      view3d.innerHTML = '<span class="tool-cube">◧</span> 3D';
      view3d.title = 'Посмотреть деталь в объёме и покрутить, не добавляя в сценарий';
      view3d.addEventListener('click', () => openToolPreview(tool, card));
      const btn = document.createElement('button');
      btn.className = 'small primary';
      btn.textContent = 'Добавить';
      btn.addEventListener('click', () => addShapeTool(tool, card));
      actions.append(view3d, btn);
      card.appendChild(actions);
      fields.addEventListener('input', () => scheduleThumb(card));
      fields.addEventListener('change', () => scheduleThumb(card, 60));
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
  document.querySelectorAll('#tools-body canvas.tool-shot').forEach((canvas) => {
    canvas.hidden = !state.thumbsOn;
  });
  // миниатюры строим по мере прокрутки: десятки карточек сразу не нужны
  requestAnimationFrame(() => observeThumbs(body));
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
  // Заголовок «Примитивы» / «Инструменты» прячется, если под ним пусто.
  body.querySelectorAll('.tool-sec').forEach((bar) => {
    let node = bar.nextElementSibling;
    let any = false;
    while (node && !node.classList.contains('tool-sec')) {
      if (node.classList.contains('tool-group') && !node.hidden) { any = true; break; }
      node = node.nextElementSibling;
    }
    bar.hidden = !any;
  });
  const label = $('tools-count');
  if (label) label.textContent = q ? `нашлось ${shown} из ${total}` : `всего ${total}`;
  scheduleThumbsReobserve();
}
$('tools-search')?.addEventListener('input', applyToolsFilter);
let thumbObserveTimer = 0;
function scheduleThumbsReobserve() {
  clearTimeout(thumbObserveTimer);
  thumbObserveTimer = setTimeout(() => {
    if (!$('tools-modal') || $('tools-modal').hidden) return;
    observeThumbs($('tools-body'));
  }, 260);
}
$('tools-thumbs')?.addEventListener('change', (e) => {
  state.thumbsOn = e.target.checked;
  toolThumbs.enabled = state.thumbsOn;
  document.querySelectorAll('#tools-body .tool-card').forEach((card) => {
    const canvas = card.querySelector('canvas.tool-shot');
    if (canvas) canvas.hidden = !state.thumbsOn;
  });
  if (state.thumbsOn) observeThumbs($('tools-body'));
});

function openTools() {
  $('tools-modal').hidden = false;
  renderTools();
}
$('btn-tools')?.addEventListener('click', openTools);
function closeTools() {
  $('tools-modal').hidden = true;
  thumbObserver?.disconnect();
}
$('tools-close')?.addEventListener('click', closeTools);
$('tools-modal')?.addEventListener('click', (e) => {
  if (e.target === $('tools-modal')) closeTools();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !$('tools-modal').hidden) closeTools();
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
      (c.orientation || '') + ' ' +
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
        ${c.orientation ? `<div class="cmd-summary"><b>Исходная ориентация:</b> ${escapeHtml(c.orientation)}</div>` : ''}
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

async function copyInstruction(kind, label) {
  try {
    const res = await api('/api/instruction?kind=' + encodeURIComponent(kind));
    const text = res.text || '';
    if (!text) { toast('Пустой справочник', 'bad'); return; }
    // Справочник — отдельно от запроса: поле запроса не трогаем,
    // иначе скопированная инструкция затрёт уже сформированный текст.
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const tmp = document.createElement('textarea');
      tmp.value = text;
      tmp.style.position = 'fixed';
      tmp.style.opacity = '0';
      document.body.appendChild(tmp);
      tmp.select();
      try { document.execCommand('copy'); } finally { tmp.remove(); }
    }
    const out = $('instruction-out');
    if (out) { out.value = text; out.hidden = false; }
    toast(`${label}: ${text.length.toLocaleString('ru-RU')} символов скопировано`);
  } catch (e) { toast(e.message || 'Ошибка', 'bad'); }
}

$('btn-copy-instruction')?.addEventListener('click', () => copyInstruction('full', 'Инструкция для ИИ'));
$('btn-copy-commands')?.addEventListener('click', () => copyInstruction('commands', 'Все команды'));

$('btn-instruction-save')?.addEventListener('click', async () => {
  try {
    const full = await api('/api/instruction?kind=full');
    const commands = await api('/api/instruction?kind=commands');
    const text = (full.text || '') + '\n\n---\n\n' + (commands.text || '');
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
    const saved = await saveBlob(blob, 'Форма3D_инструкция_и_команды.md');
    exportSaved(saved, 'Справочник сохранён');
  } catch (e) { toast(e.message || 'Ошибка', 'bad'); }
});

$('btn-prompt-save').addEventListener('click', async () => {
  if (!$('prompt-out').value) { toast('Сначала сформируйте запрос', 'bad'); return; }
  try {
    const res = await api('/api/export', { format: 'prompt' });
    exportSaved(res, `Запрос ${res.name}`);
  } catch (e) { toast(e.message || 'Ошибка', 'bad'); }
});

/* ------------------------------------------------------------------ */
/*  Старт                                                             */
/* ------------------------------------------------------------------ */
async function init() {
  initViewer();
  // Границы панелей: тянуть мышью, двойной щелчок — свернуть, «⤢» — во всё окно.
  state.panels = installPanelLayout({
    onResize: () => state.viewer?.resize(),
  });
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
