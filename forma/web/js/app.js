import { Viewer } from './viewer.js';

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
  notes: [],
  actions: [],
  cmdHistory: [],
  cmdIndex: -1,
  history: [],
  historyInfo: [],
  future: [],
  futureInfo: [],
  hidden: new Set(),
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
      await loadModel(payload.glb_url, payload.timeline || payload.animation);
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
    renderSections(null);
    state.anim.frames = [];
    state.anim.playing = false;
    updateAnimState();
    return;
  }

  hideError();
  const stateEl = $('status-state');
  stateEl.textContent = 'модель построена';
  stateEl.className = 'status-item ok';

  // Скрытые детали (например, вошедшие в union/weld) должны оставаться
  // скрытыми, но открываться одним кликом по глазку. Держим единое состояние.
  const names = new Set((payload.objects || []).map((o) => o.name));
  [...state.hidden].forEach((n) => { if (!names.has(n)) state.hidden.delete(n); });
  (payload.objects || []).forEach((o) => { if (!o.visible) state.hidden.add(o.name); });

  renderReport(payload);
  renderSections(payload);
  renderChecks(payload);
  renderObjects(payload);
  renderDimensions(metrics);
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
    el.innerHTML = `<div class="note-meta">${escapeHtml(n.time || '')} · ${escapeHtml(n.object || '')} · `
      + `${n.tris || 0} трис · центр (${escapeHtml(c)})</div>`
      + `<div class="note-text">${escapeHtml(n.text || '')}</div>`;
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
      parts.push(`• ${n.time || ''} «${n.object || ''}» (${n.tris || 0} трис, `
        + `${n.area_mm2 || 0} мм², центр (${c})): ${n.text || ''}`);
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
        if (willHide) state.hidden.add(name); else state.hidden.delete(name);
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
    if (visible) state.hidden.delete(o.name); else state.hidden.add(o.name);
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
    state.viewer.setAxes($('opt-axes')?.checked !== false);
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
    refreshAnimSelectors();
    if (state.anim.mode === 'frames' && !state.anim.frames.length) state.anim.mode = 'clips';
    if ($('anim-mode')) $('anim-mode').value = state.anim.mode;
    updateAnimState();
    if (state.anim.mode === 'frames') {
      if (state.anim.frames.length) showFrame(0);
    } else if (animClips().length || animKeys().length) {
      state.viewer.playAnimation(true);
      state.anim.playing = state.viewer.playing;
      syncAnimUI();
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
  wait: 'пауза', morph: 'изменение формы' };
const ANIM_COLORS = { spin: '#2f4f8a', formation: '#2f7a5f', explode: '#8a5a2f',
  assembly: '#6b4f9e', move: '#2f7a8a', scale: '#8a7a2f', turn: '#8a2f6b',
  wait: '#4a4f57', morph: '#2f5f8a' };

function animPlan() {
  const p = state.payload?.timeline;
  if (p && Array.isArray(p.clips)) return p;
  const one = state.payload?.animation;
  return one && one.kind ? { clips: [one], duration: one.seconds || 4, count: 1 } : null;
}

function animClips() {
  const plan = animPlan();
  if (plan?.clips?.length) return plan.clips;
  return state.anim.preview?.clips || [];
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
      label.textContent = animFrames().length
        ? `кадры сборки: ${animFrames().length} шаг(ов)` : 'кадров сборки нет';
      label.className = 'anim-status ' + (animFrames().length ? 'ok' : '');
    } else {
      const clips = animClips();
      const keys = animKeys();
      const total = Number(animPlan()?.duration) || 0;
      const preview = Boolean(a.preview);
      const shownTotal = preview ? a.preview.duration : total;
      const tracks = animTrackList().length;
      const bits = [];
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
  a.duration = Number(animPlan()?.duration) || Number(state.viewer?.duration) || 0;
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
  const total = Number(animPlan()?.duration) || Number(a.preview?.duration) || 0;
  if (!clips.length && !keys.length) {
    box.innerHTML = '<span class="anim-empty">клипов нет: animate kind=spin seconds=6</span>';
    return;
  }
  const laneFor = (track) => {
    const row = document.createElement('div');
    row.className = 'anim-track-row';
    if (animTrackList().length > 1) {
      const name = document.createElement('span');
      name.className = 'anim-track-name';
      name.textContent = 'дорожка ' + track;
      row.appendChild(name);
    }
    const lane = document.createElement('div');
    lane.className = 'anim-lane';
    clips.filter((c) => (Number(c.track) || 1) === track).forEach((c) => {
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
  animTrackList().forEach((track) => box.appendChild(laneFor(track)));

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
  const num = (v, fallback) => (v === undefined || v === null ? fallback : Number(v));
  if (c.kind === 'scale') {
    $('ae-from').value = String(num(c.from, 1));
    $('ae-to').value = String(num(c.to, 1.5));
  }
  if (c.kind === 'turn') $('ae-angle').value = String(Number(c.angle) || 90);
  if (c.kind === 'morph') {
    $('ae-param').value = c.param || '';
    $('ae-from').value = String(num(c.from, 0));
    $('ae-to').value = String(num(c.to, 1));
    $('ae-samples').value = String(Number(c.samples) || 12);
  }
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
  show('ae-param-wrap', kind === 'morph');
  show('ae-samples-wrap', kind === 'morph');
  show('ae-object-wrap', ['move', 'scale', 'turn', 'spin', 'explode'].includes(kind));
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
  const objs = (state.payload?.objects || []).map((o) => o.name);
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
    }
    return;
  }
  if (a.seqKey) {
    a.seqKey = null;
    state.viewer?.showFinalModel();
  }
}

function showMorph(clip, value) {
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

function initViewer() {
  try {
    state.viewer = new Viewer($('viewer'));
    state.viewer.onSelect = (name) => selectObject(name);
    state.viewer.onSelection = (stats) => showSelection(stats);
    state.viewer.onTextureError = () => toast('Не удалось загрузить текстуру: проверьте соединение с окном приложения', 'bad');
    let lastClock = 0;
    state.viewer.onTime = (t) => {
      if (state.anim.mode !== 'clips') return;
      state.anim.time = t;
      updateSequence(t);
      const now = performance.now();
      if (now - lastClock > 60) { lastClock = now; syncAnimClock(); }
    };
    state.viewer.onEnd = () => { state.anim.playing = false; syncAnimUI(); };
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
/*  Материал выбранного объекта                                       */
/* ------------------------------------------------------------------ */
function selectObject(name) {
  updateCustomTexVisibility();
  if (!name) {
    state.selected = null;
    document.querySelectorAll('.obj-item').forEach((el) => el.classList.remove('selected'));
    $('material-panel').hidden = true;
    state.viewer?.clearHighlight();
    return;
  }
  const obj = (state.payload?.objects || []).find((o) => o.name === name);
  if (!obj) return;
  state.selected = obj;
  document.querySelectorAll('.obj-item').forEach((el) => {
    el.classList.toggle('selected', el.dataset.name === name);
  });
  // Подсветка прямо в окне: выбранный в списке объект видно на модели.
  if (!state.hidden.has(name)) state.viewer?.setHighlight(name);
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
// по отпусканию ползунка записываем значение в сценарий, чтобы оно жило после пересборки
['mat-color', 'mat-metal', 'mat-rough'].forEach((id) => {
  $(id)?.addEventListener('change', () => {
    if (!state.selected) return;
    writeMaterialScript({ rebuild: true });
  });
});
$('mat-close')?.addEventListener('click', () => selectObject(''));

function writeMaterialScript({ rebuild = true } = {}) {
  if (!state.selected) return;
  const { color, metal, rough } = state.material;
  const tex = $('mat-tex')?.value || '';
  const m = state.selected.name;
  const lines = currentScript().split('\n').filter((l) => {
    const t = l.trim();
    return !(t.startsWith(`color ${m} `) || t.startsWith(`texture ${m} `) || t.startsWith(`материал ${m} `));
  });
  lines.push(`color ${m} ${color} metal=${metal} rough=${rough}`);
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
  hint.textContent = state.selectMode
    ? 'выбор: ЛКМ — выделить область · ползунок — размер · «Вырезать» — убрать'
    : 'ЛКМ — вращать · колесо — масштаб · ПКМ — сдвинуть · двойной клик — вернуть вид';
}

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
  const RECIPES = { '/банан': 'banana', '/banana': 'banana', '/гриб': 'mushroom', '/mushroom': 'mushroom',
    '/кружка': 'mug', '/mug': 'mug', '/ваза': 'vase', '/vase': 'vase',
    '/шестерня': 'gear', '/gear': 'gear', '/кузов': 'car', '/car': 'car',
    '/бутылка': 'bottle', '/bottle': 'bottle', '/пришелец': 'alien', '/alien': 'alien',
    '/манекен': 'mannequin', '/mannequin': 'mannequin', '/яблоко': 'apple', '/apple': 'apple',
    '/инструменты': 'tools', '/tools': 'tools',
    '/анимация': 'animation', '/animation': 'animation' };
  if (RECIPES[low] || low === '/рецепты' || low === '/recipes') {
    $('cmd-input').value = '';
    if (RECIPES[low]) { loadExample(RECIPES[low]); return; }
    toast('Рецепты: /яблоко, /банан, /гриб, /кружка, /ваза, /бутылка, /шестерня, /кузов, /пришелец, /манекен, /инструменты, /анимация');
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
    e.preventDefault();
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

$('btn-export').parentElement.querySelector('.menu').addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-format]');
  if (!btn) return;
  const fmt = btn.dataset.format;
  document.querySelectorAll('.menu.open').forEach((m) => m.classList.remove('open'));
  if (!state.payload?.ok) { toast('Сначала соберите модель', 'bad'); return; }
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
