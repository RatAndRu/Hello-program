// Объём — интерфейс приложения
import { Capture, drawDome, beep, BANDS } from './capture.js';
import { startProcessing } from './procclient.js';
import { Viewer3D } from './viewer.js';
import { toGLB, toOBJ, toMeshPLY, toSTL, bounds, meshVolume } from './export.js';
import { toPLY as splatPLY } from './splat.js';
import { matPDF, matPNG } from './matprint.js';
import * as store from './store.js';
import { fmtT } from './pipeline.js';

export const VERSION = '1.0';
const $ = (id) => document.getElementById(id);
const S = Object.assign({ mode: 'mesh', method: 'walk', size: 'A4', height: '90', quality: 'normal' }, JSON.parse(localStorage.getItem('obyom.settings') || '{}'));
const saveSettings = () => localStorage.setItem('obyom.settings', JSON.stringify(S));

// ---------- навигация ----------
let cur = 'home';
function go(id) {
  document.querySelectorAll('.screen').forEach((s) => s.classList.toggle('active', s.id === id));
  if (id !== 'home' && cur === 'home') history.pushState({ s: id }, '');
  cur = id;
  if (id === 'home') renderList();
}
window.addEventListener('popstate', () => {
  if (cur === 'capture') { cancelCapture(); return; }
  if (cur === 'process') { history.pushState({ s: cur }, ''); toast('Идёт обработка — дождись или нажми «Остановить»'); return; }
  if (!$('sheet').classList.contains('hidden')) { closeSheet(); history.pushState({ s: cur }, ''); return; }
  go('home');
});
document.querySelectorAll('[data-go]').forEach((b) => b.addEventListener('click', () => { if (cur !== 'home') history.back(); else go(b.dataset.go); }));

let toastT = 0;
function toast(msg, ms = 2600) { const t = $('toast'); t.textContent = msg; t.classList.remove('hidden'); clearTimeout(toastT); toastT = setTimeout(() => t.classList.add('hidden'), ms); }
function sheet(html, bind) { $('sheetBody').innerHTML = html; $('sheet').classList.remove('hidden'); bind && bind($('sheetBody')); }
function closeSheet() { $('sheet').classList.add('hidden'); }
$('sheetClose').onclick = closeSheet;
$('sheet').addEventListener('click', (e) => { if (e.target.id === 'sheet') closeSheet(); });

// ---------- сохранение файлов ----------
function b64(u8) { let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000)); return btoa(s); }
async function saveFile(bytes, name, mime, share = false) {
  const N = window.ObyomNative;
  if (N && N.begin) {
    const id = N.begin(name), CH = 3 * 131072;
    for (let o = 0; o < bytes.length; o += CH) { if (!N.append(id, b64(bytes.subarray(o, o + CH)))) { toast('Не удалось записать файл'); return; } if ((o / CH) % 8 === 7) await new Promise((r) => setTimeout(r, 0)); }
    const msg = N.finish(id, name, mime, share); if (msg) toast(msg, 3800);
    return;
  }
  const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
  const a = Object.assign(document.createElement('a'), { href: url, download: name }); document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  toast('Файл сохранён: ' + name);
}
const fileBase = (name) => (name || 'scan').replace(/[\\/:*?"<>|]+/g, '_').trim().slice(0, 40) || 'scan';

// ---------- главная ----------
async function renderList() {
  let list = [];
  try { list = await store.listScans(); } catch (e) { console.warn(e); }
  const box = $('scanList'); box.innerHTML = '';
  $('emptyHint').classList.toggle('hidden', list.length > 0);
  for (const s of list) {
    const b = document.createElement('button'); b.className = 'card';
    const d = new Date(s.date);
    b.innerHTML = `<img alt="" src="${s.thumb || ''}"><div class="meta"><b></b>${s.hasMesh ? '<span class="badge">Полигоны</span>' : ''}${s.hasSplats ? '<span class="badge">Сплэты</span>' : ''}<div style="color:var(--mute)">${d.toLocaleDateString('ru-RU')} ${d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}</div></div>`;
    b.querySelector('b').textContent = s.name;
    b.onclick = () => openScan(s.id);
    box.appendChild(b);
  }
}
$('btnNew').onclick = () => { go('setup'); renderSetup(); };
$('btnMat').onclick = showMat;
$('btnHelp').onclick = showHelp;

// ---------- настройка ----------
function renderSetup() {
  document.querySelectorAll('#setup .seg').forEach((seg) => seg.querySelectorAll('button').forEach((b) => b.classList.toggle('on', S[seg.dataset.key] === b.dataset.v)));
  const it = { fast: 600, normal: 1200, best: 2400 }[S.quality];
  const sp = S.mode === 'mesh' ? '' : ` Сплэты на телефоне: ~${Math.round(it * 0.4 / 60)}–${Math.round(it * 0.7 / 60)} мин.`;
  const how = S.method === 'walk'
    ? 'Обходи предмет по кругу 2–3 раза на разной высоте: низко (~30°), выше (~55°) и почти сверху (~75°). Кадры снимаются сами.'
    : 'Телефон в держателе смотрит на коврик сверху-сбоку. Медленно крути столик. Потом подними держатель выше и сделай ещё оборот.';
  $('setupHint').textContent = how + ' Форма считается за 20–60 секунд.' + sp;
}
document.querySelectorAll('#setup .seg').forEach((seg) => seg.addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; S[seg.dataset.key] = b.dataset.v; saveSettings(); renderSetup(); }));
$('btnStart').onclick = startCapture;

// ---------- съёмка ----------
let cap = null;
async function startCapture() {
  go('capture');
  const k = S.size === 'A3' ? Math.SQRT2 : 1;
  cap = new Capture($('video'), $('overlay'), {
    size: S.size, method: S.method, Hb: +S.height,
    onState: capState,
    onShot: (n) => { beep(1046, 0.05); if (navigator.vibrate) navigator.vibrate(15); },
  });
  try { await cap.start(); } catch (e) { toast('Нет доступа к камере: ' + e.message, 4000); history.back(); }
}
let lastWarnBeep = 0;
function capState(st) {
  const msg = $('capMsg'), cov = st.coverage || [0, 0, 0, 0];
  drawDome($('dome'), cap.cells, st);
  $('capDone').textContent = `Готово · ${st.count}`; $('capDone').disabled = st.count < 10;
  let text = '', cls = '';
  const low = Math.max(cov[0], cov[1]), mid = cov[2], high = cov[3], turn = S.method === 'turn';
  if (cap.paused) { text = 'Пауза'; cls = 'warn'; }
  else if (!st.found) { text = st.markers ? 'Мало меток — отодвинь телефон, чтобы влез весь круг' : 'Наведи камеру на коврик'; cls = 'bad'; }
  else if (st.el < BANDS[0][0]) { text = 'Слишком низко — подними телефон'; cls = 'warn'; }
  else if (!st.slow) { text = turn ? 'Медленнее крути столик' : 'Медленнее'; cls = 'bad'; const now = Date.now(); if (now - lastWarnBeep > 1500) { beep(300, 0.12, 0.12); lastWarnBeep = now; } }
  else if (low < 0.75) { text = turn ? 'Крути столик медленно — первый оборот' : 'Обходи вокруг предмета, держа телефон невысоко (~30°)'; }
  else if (mid < 0.6) { text = turn ? 'Подними держатель выше (~55°) и ещё оборот' : 'Теперь ещё круг повыше (~55°)'; }
  else if (high < 0.4) { text = turn ? 'Ещё выше (~75°) — последний оборот' : 'И круг почти сверху (~75°)'; }
  else { text = 'Отлично! Можно нажимать «Готово»'; cls = 'good'; }
  msg.textContent = text; msg.className = 'capMsg ' + cls;
  $('capInfo').textContent = st.found ? `высота ${st.el.toFixed(0)}° · азимут ${st.az.toFixed(0)}° · ${Math.round(st.dist / 10)} см · меток ${st.n}${cap.f ? '' : ' · калибровка…'}` : '';
}
function cancelCapture() { if (cap) cap.stop(); cap = null; go('home'); }
$('capCancel').onclick = () => { if (!cap || cap.shots.length < 3 || confirm('Выбросить снятые кадры?')) history.back(); };
$('capPause').onclick = () => { if (!cap) return; cap.paused = !cap.paused; $('capPause').textContent = cap.paused ? '▶' : '⏸'; };
$('capDone').onclick = async () => {
  if (!cap) return;
  const shots = cap.shots.map((s) => s.blob); cap.stop(); cap = null;
  const id = 'scan-' + Date.now(), d = new Date();
  const scan = { id, name: `Скан ${d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })} ${d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`, date: Date.now(), settings: { ...S } };
  try { await store.putFrames(id, shots); } catch (e) { toast('Не удалось сохранить кадры: ' + e.message); }
  runProcessing(scan, shots);
};

// ---------- обработка ----------
let proc = null, procViewer = null;
function runProcessing(scan, blobs) {
  go('process');
  const st = scan.settings, k = st.size === 'A3' ? Math.SQRT2 : 1;
  $('procLog').textContent = ''; $('procBar').style.width = '0%'; $('procStage').textContent = 'Подготовка…'; $('procText').textContent = '';
  $('procStop').textContent = 'Остановить'; $('procView').classList.remove('on');
  const log = (t) => { $('procLog').textContent += t + '\n'; };
  log(`кадров: ${blobs.length}; режим: ${{ mesh: 'полигоны', splat: 'сплэты', both: 'полигоны + сплэты' }[st.mode]}`);
  const job = { blobs, mode: st.mode, quality: st.quality, size: st.size, theme: 'light', Hb: +st.height };
  let splatting = false;
  proc = startProcessing(job, {
    progress: (stage, p, text) => {
      $('procStage').textContent = stage; $('procBar').style.width = (p * 100).toFixed(1) + '%'; $('procText').textContent = text;
      if (stage === 'Учу сплэты' && !splatting) { splatting = true; $('procStop').textContent = 'Хватит — сохранить как есть'; }
    },
    preview: (packed) => {
      const cvs = $('procView'); cvs.classList.add('on');
      if (!procViewer) { try { procViewer = new Viewer3D(cvs); procViewer.auto = true; } catch (e) { return; } }
      procViewer.show = 'splat'; procViewer.setSplats(packed);
      if (!procViewer.home) { const b = boundsPacked(packed); procViewer.fit(b.mn, b.mx); procViewer.auto = true; }
    },
    log,
  });
  $('procStop').onclick = () => { if (splatting) { proc.stop(); toast('Сохраняю то, что успело выучиться…'); } else if (confirm('Остановить обработку? Кадры сохранены — можно пересчитать позже.')) { proc.stop(); } };
  proc.promise.then(async (r) => {
    if (procViewer) { procViewer.destroy(); procViewer = null; }
    const M = r.mesh, b = bounds(M);
    Object.assign(scan, { mode: st.mode, mesh: M, splats: r.splats || null, hasMesh: st.mode !== 'splat', hasSplats: !!r.splats,
      stats: { ...r.stats, size: b.size, volume: meshVolume(M) } });
    await openScan(null, scan);
    scan.thumb = viewer.snapshot(320);
    try { await store.putScan(scan); } catch (e) { toast('Не хватает места для сохранения: ' + e.message, 4000); }
    toast(`Готово за ${fmtT(r.stats.t)}`);
  }).catch((e) => {
    if (procViewer) { procViewer.destroy(); procViewer = null; }
    const m = e.message === 'stopped' ? 'Обработка остановлена. Кадры сохранены — их можно пересчитать из списка (⋯ → Пересчитать).' : e.message;
    log('✗ ' + m); $('procStage').textContent = 'Не получилось'; $('procStop').textContent = 'На главную';
    $('procStop').onclick = () => { history.back(); };
    // сохраним пустую запись, чтобы можно было пересчитать
    store.putScan({ ...scan, failed: m, hasMesh: false, hasSplats: false }).catch(() => {});
  });
}
function boundsPacked(p) { const mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9]; for (let i = 0; i < p.length; i += 14) for (let c = 0; c < 3; c++) { mn[c] = Math.min(mn[c], p[i + c]); mx[c] = Math.max(mx[c], p[i + c]); } return { mn, mx }; }

// ---------- просмотр ----------
let viewer = null, curScan = null;
async function openScan(id, scanObj) {
  const scan = scanObj || await store.getScan(id);
  if (!scan) { toast('Модель не найдена'); return; }
  if (scan.failed || (!scan.mesh && !scan.splats)) { moreSheet(scan); return; }
  curScan = scan;
  if (cur === 'process') { cur = 'view'; document.querySelectorAll('.screen').forEach((s) => s.classList.toggle('active', s.id === 'view')); } else go('view');
  if (!viewer) { try { viewer = new Viewer3D($('gl')); } catch (e) { toast('3D-просмотр недоступен: ' + e.message, 5000); return; } }
  viewer.setMesh(scan.mesh || null);
  viewer.setSplats(scan.splats || new Float32Array(0));
  viewer.show = scan.mode === 'splat' && scan.splats ? 'splat' : 'mesh';
  const b = bounds(scan.mesh); viewer.fit(b.mn, b.mx); viewer.auto = true;
  $('vName').value = scan.name;
  const sz = scan.stats && scan.stats.size ? scan.stats.size : b.size;
  $('vSize').textContent = `${sz.map((v) => Math.round(v)).join(' × ')} мм · ${scan.stats ? scan.stats.used + ' кадров' : ''}`;
  $('vWarn').textContent = scan.stats && scan.stats.warn || ''; $('vWarn').classList.toggle('hidden', !(scan.stats && scan.stats.warn));
  $('vShow').classList.toggle('hidden', !scan.splats);
  syncViewTools();
}
function syncViewTools() {
  $('vShow').querySelectorAll('button').forEach((b) => b.classList.toggle('on', viewer.show === b.dataset.v));
  $('vShade').querySelectorAll('button').forEach((b) => b.classList.toggle('on', String(viewer.shade) === b.dataset.v));
  $('vShade').classList.toggle('hidden', viewer.show !== 'mesh');
  $('vAuto').classList.toggle('on', viewer.auto);
}
$('vShow').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; viewer.show = b.dataset.v; viewer.dirty = true; syncViewTools(); };
$('vShade').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; viewer.shade = +b.dataset.v; viewer.dirty = true; syncViewTools(); };
$('vAuto').onclick = () => { viewer.auto = !viewer.auto; syncViewTools(); };
$('vHome').onclick = () => { viewer.reset(); };
$('vName').onchange = async () => { if (!curScan) return; curScan.name = $('vName').value.trim() || curScan.name; await store.putScan(curScan).catch(() => {}); };
setInterval(() => { if (viewer && cur === 'view') { const on = $('vAuto').classList.contains('on'); if (on !== viewer.auto) syncViewTools(); } }, 500);

$('vExp').onclick = () => {
  const s = curScan; if (!s) return;
  const base = fileBase(s.name);
  const items = [];
  if (s.mesh) items.push(
    ['glb', 'GLB', 'Blender, Godot, Unity, сайты, AR', () => saveFile(toGLB(s.mesh, s.name), base + '.glb', 'model/gltf-binary')],
    ['obj', 'OBJ', 'с цветами вершин, любые 3D-программы', () => saveFile(toOBJ(s.mesh), base + '.obj', 'text/plain')],
    ['ply', 'PLY', 'сетка с цветом (MeshLab, Blender)', () => saveFile(toMeshPLY(s.mesh), base + '.ply', 'application/octet-stream')],
    ['stl', 'STL', '3D-печать, миллиметры', () => saveFile(toSTL(s.mesh), base + '.stl', 'model/stl')]);
  if (s.splats) items.push(['splat', 'Сплэты PLY', 'SuperSplat, Brush, Blender-аддоны', () => saveFile(new Uint8Array(splatPLY(unpackSplats(s.splats))), base + '_splats.ply', 'application/octet-stream')]);
  sheet(`<h3>Экспорт «${s.name.replace(/</g, '&lt;')}»</h3><p>Файлы попадут в «Загрузки → Объём». Размер модели настоящий (${(s.stats.size || [0, 0, 0]).map((v) => Math.round(v)).join('×')} мм).</p><div class="grid2">${items.map(([k, t, d]) => `<button data-k="${k}">${t}<small>${d}</small></button>`).join('')}</div>`,
    (box) => box.querySelectorAll('button[data-k]').forEach((b) => b.onclick = async () => { const it = items.find((x) => x[0] === b.dataset.k); b.disabled = true; try { await it[3](); } catch (e) { toast('Ошибка: ' + e.message); } b.disabled = false; }));
};
// упакованные капли → объект для toPLY
function unpackSplats(p) {
  const n = p.length / 14, logit = (x) => Math.log(Math.max(1e-4, Math.min(0.9999, x)) / (1 - Math.max(1e-4, Math.min(0.9999, x))));
  const o = { n, mu: new Float32Array(n * 3), ls: new Float32Array(n * 3), q: new Float32Array(n * 4), op: new Float32Array(n), col: new Float32Array(n * 3) };
  for (let i = 0; i < n; i++) { o.mu.set(p.subarray(i * 14, i * 14 + 3), i * 3); o.ls.set(p.subarray(i * 14 + 3, i * 14 + 6), i * 3); o.q.set(p.subarray(i * 14 + 6, i * 14 + 10), i * 4); o.op[i] = logit(p[i * 14 + 10]); for (let c = 0; c < 3; c++) o.col[i * 3 + c] = logit(p[i * 14 + 11 + c]); }
  return o;
}
$('vMore').onclick = () => curScan && moreSheet(curScan);
async function moreSheet(scan) {
  const frames = await store.getFrames(scan.id).catch(() => null);
  const nf = frames ? frames.length : 0;
  sheet(`<h3>${scan.name.replace(/</g, '&lt;')}</h3>${scan.failed ? `<p style="color:var(--warn)">${scan.failed}</p>` : ''}
    ${scan.stats ? `<p>Кадров использовано: ${scan.stats.used} из ${scan.stats.frames}. Объём: ${(scan.stats.volume / 1000).toFixed(1)} см³. Обработка: ${fmtT(scan.stats.t)}.</p>` : ''}
    ${nf ? `<p>Пересчитать из сохранённых кадров (${nf} шт.) с другими настройками:</p>
    <div class="grid2"><button data-r="mesh">Полигоны</button><button data-r="splat">Сплэты</button><button data-r="both">Оба</button><button data-r="best">Оба, качество «Лучше»</button></div>
    <button data-a="dropframes">Удалить кадры (освободить место)</button>` : '<p>Кадров съёмки нет — пересчёт невозможен.</p>'}
    <button data-a="delete" style="color:var(--bad)">Удалить модель</button>`,
  (box) => {
    box.querySelectorAll('[data-r]').forEach((b) => b.onclick = () => {
      closeSheet(); const st = { ...(scan.settings || S) };
      if (b.dataset.r === 'best') { st.mode = 'both'; st.quality = 'best'; } else st.mode = b.dataset.r;
      const ns = { id: scan.id, name: scan.name, date: scan.date, settings: st };
      if (cur !== 'home') history.back(); setTimeout(() => runProcessing(ns, frames), 50);
    });
    const dz = box.querySelector('[data-a="dropframes"]'); if (dz) dz.onclick = async () => { await store.delFrames(scan.id); closeSheet(); toast('Кадры удалены'); };
    box.querySelector('[data-a="delete"]').onclick = async () => { if (!confirm('Удалить модель «' + scan.name + '»?')) return; await store.delScan(scan.id); closeSheet(); if (cur === 'view') history.back(); else renderList(); };
  });
}

// ---------- коврик и справка ----------
function showMat() {
  sheet(`<h3>Коврик для съёмки</h3>
  <p>Распечатай на обычном белом листе <b>в масштабе 100%</b> («Фактический размер», без «Вписать в страницу»). Проверь линейкой полоску «100 мм» сверху — от этого зависит настоящий размер модели.</p>
  <div class="grid2"><button data-m="pdfA4">PDF A4<small>предметы до 12 см</small></button><button data-m="pdfA3">PDF A3<small>до 17 см</small></button><button data-m="pngA4">PNG A4<small>300 dpi</small></button><button data-m="pngA3">PNG A3<small>300 dpi</small></button></div>
  <ul><li><b>Чёрные квадраты</b> по кругу — метки: по ним телефон узнаёт, откуда смотрит камера, и точный масштаб.</li>
  <li><b>Серые крапинки</b> в центре нужны, чтобы отличать тень от предмета: в тени крапинки остаются видны, а предмет их закрывает.</li>
  <li><b>Градусы и стрелка</b> — чтобы на вертушке было видно, насколько повернули.</li>
  <li>Для вертушки вырежи круг по пунктиру и приклей на столик (подойдёт крышка от банки на ленивой Сьюзен). Лист должен быть ровным, без бликов.</li></ul>`,
  (box) => box.querySelectorAll('[data-m]').forEach((b) => b.onclick = async () => {
    b.disabled = true; toast('Готовлю файл…');
    try { const k = b.dataset.m, size = k.slice(-2); if (k.startsWith('pdf')) await saveFile(await matPDF(size), `Объём-коврик-${size}.pdf`, 'application/pdf'); else await saveFile(await matPNG(size), `Объём-коврик-${size}.png`, 'image/png'); } catch (e) { toast('Ошибка: ' + e.message); }
    b.disabled = false;
  }));
}
function showHelp() {
  sheet(`<h3>Как снимать</h3>
  <ol><li>Положи коврик на стол, предмет — в центр круга. Свет — мягкий, рассеянный (у окна днём или две лампы по бокам), без резких теней.</li>
  <li><b>С рук:</b> обходи предмет медленно, держа в кадре весь круг меток. Три круга: низко (~30°), повыше (~55°) и почти сверху (~75°). Купол справа показывает, что уже снято.</li>
  <li><b>Держатель + вертушка:</b> телефон в держателе (штатив, стопка книг, прищепка-держатель) смотрит на коврик сверху-сбоку с 25–35 см. Крути столик медленно — сам пищит, когда снимает. После оборота подними держатель выше и сделай ещё оборот.</li>
  <li>Когда купол заполнен — «Готово». Форма считается за полминуты, сплэты — несколько минут; можно остановить раньше.</li></ol>
  <p><b>Что не получится:</b> прозрачные, зеркальные и блестящие предметы; глубокие впадины (внутренность чашки) — метод видит силуэты. Очень тёмные предметы снимай при ярком свете.</p>
  <p><b>На вертушке</b> свет «едет» вместе с предметом — блики на модели могут размазаться. Для блестящего лучше обход с рук.</p>
  <p>Всё считается на телефоне, без интернета и без нейросетей. Версия ${VERSION}.</p>`);
}

if ('serviceWorker' in navigator && location.protocol === 'https:' && !/ObyomAndroid/.test(navigator.userAgent)) navigator.serviceWorker.register('sw.js').catch(() => {});
renderList();
