// Объём — интерфейс приложения
import { Capture, drawDome, beep, BANDS, inkLabel } from './capture.js';
import { matLayout } from './mat.js';
import { startProcessing } from './procclient.js';
import { Viewer3D } from './viewer.js';
import { toGLB, toOBJ, toMeshPLY, toSTL, bounds, meshVolume } from './export.js';
import { toPLY as splatPLY } from './splat.js';
import { matPDF, matPNG } from './matprint.js';
import * as store from './store.js';
import { fmtT } from './pipeline.js';

export const VERSION = '1.6';
const $ = (id) => document.getElementById(id);
const S = Object.assign({ mode: 'mesh', method: 'walk', size: 'A4', height: '90', quality: 'normal', shape: 'normal', delay: '5', step: '8' }, JSON.parse(localStorage.getItem('obyom.settings') || '{}'));
const saveSettings = () => localStorage.setItem('obyom.settings', JSON.stringify(S));
// калибровка печати: { A4: {sx, sy}, ... } — во сколько раз принтер растянул лист по ширине и длине
const loadCal = () => { try { return JSON.parse(localStorage.getItem('obyom.cal') || '{}'); } catch (e) { return {}; } };
function calFor(size) { const c = loadCal(), v = c[size] || c.A4; return v ? [v.sx, v.sy] : [1, 1]; }

// ---------- навигация ----------
let cur = 'home';
function go(id) {
  document.querySelectorAll('.screen').forEach((s) => s.classList.toggle('active', s.id === id));
  if (id !== 'home' && cur === 'home') history.pushState({ s: id }, '');
  cur = id;
  if (id === 'home') renderList();
}
window.addEventListener('popstate', () => {
  if (cur === 'capture' && plateSheet && !$('sheet').classList.contains('hidden')) { closeSheet(); plateSheet = false; history.pushState({ s: cur }, ''); return; }
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
    : 'Телефон в держателе смотрит на коврик сверху-сбоку. Нажми ▶, раскрути столик и убери руку — после таймера кадры пойдут сами, каждые несколько градусов поворота (замедлился — кадры реже, остановился — пауза). Потом подними держатель выше, ⏸ → ▶ и ещё оборот. Пока коврик пустой — нажми «Фон»; после «Готово» убери предмет и сними фон ещё раз: верх выйдет без «шапки».';
  const tall = +S.height >= 200 ? ' Для высокого предмета отойди дальше, чтобы в кадр влезал и весь круг меток, и верх предмета.' : '';
  $('setupHint').textContent = how + tall + ' Форма считается за 20–60 секунд.' + sp;
}
document.querySelectorAll('#setup .seg').forEach((seg) => seg.addEventListener('click', (e) => { const b = e.target.closest('button'); if (!b) return; S[seg.dataset.key] = b.dataset.v; saveSettings(); renderSetup(); }));
$('btnStart').onclick = () => startCapture();

// ---------- съёмка ----------
let cap = null, capCtx = null; // capCtx.bottomOf — досъёмка низа для этого скана
async function startCapture(ctx) {
  capCtx = ctx && (ctx.bottomOf || ctx.closeOf) ? ctx : null;
  go('capture');
  const bo = capCtx && capCtx.bottomOf, co = capCtx && capCtx.closeOf;
  const base = bo || co;
  cap = new Capture($('video'), $('overlay'), {
    size: base ? (base.settings && base.settings.size) || S.size : S.size, method: co ? (co.settings && co.settings.method) || S.method : S.method, close: !!co, hiRes: (base ? (base.settings && base.settings.quality) : S.quality) === 'best',
    Hb: bo ? +((bo.bottom && bo.bottom.Hb) || (bo.settings && bo.settings.height) || S.height) : co ? +((co.settings && co.settings.height) || S.height) : +S.height, step: co ? 5 : +S.step || 8,
    onState: capState,
    onShot: (n, a, manual) => { beep(manual ? 1318 : 1046, 0.05); if (navigator.vibrate) navigator.vibrate(15); },
  });
  // с таймером — ждём «▶»; без таймера — снимаем сразу
  if (+S.delay > 0 && !co) { cap.paused = true; $('capPause').textContent = '▶'; } else { cap.arm(0); $('capPause').textContent = '⏸'; }
  lastCount = null;
  window.__obyomCap = cap; // для отладки и тестов
  cap.plates = []; $('capPlate').classList.toggle('hidden', S.method !== 'turn' || !!co); $('capPlate').textContent = 'Фон';
  showH();
  if (co) toast('Крупные планы: предмет не двигай! Поднеси телефон ближе (15–25 см) — чтобы в кадре был кусок предмета и хотя бы 3 метки коврика. Кадры снимаются сами при движении, 📷 — вручную', 8000);
  if (bo) toast('Доснять низ: положи предмет на бок или вверх дном в центр круга (целиком внутри рамки) и сними так же, со всех сторон', 6000);
  try { await cap.start(); } catch (e) { toast('Нет доступа к камере: ' + e.message, 4000); history.back(); }
}
let lastCount = null;
function capState(st) {
  const msg = $('capMsg'), cov = st.coverage || [0, 0, 0, 0];
  drawDome($('dome'), cap.cells, st);
  const closeMode = !!(capCtx && capCtx.closeOf);
  $('capDone').textContent = `Готово · ${st.count}`; $('capDone').disabled = st.count < (closeMode ? 3 : 10);
  let text = '', cls = '';
  const low = Math.max(cov[0], cov[1]), mid = cov[2], high = cov[3], turn = S.method === 'turn';
  if (st.countdown) { if (st.countdown !== lastCount) { lastCount = st.countdown; beep(660, 0.08); } }
  if (st.stale) { text = st.stale > 4 ? 'Камера перестала присылать кадры — перезапускаю камеру…' : 'Картинка с камеры не обновляется — жду…'; cls = 'bad'; }
  else if (cap.paused) { text = +S.delay > 0 ? `Нажми ▶ — через ${S.delay} с начнётся съёмка` : 'Пауза — нажми ▶'; cls = 'warn'; }
  else if (st.countdown) { text = `Старт через ${st.countdown}…${turn ? ' раскрути столик и убери руку' : ''}`; cls = 'warn'; }
  else if (closeMode) { text = !st.found ? (st.markers ? `Видно меток: ${st.markers} — нужно хотя бы 3 (чуть отодвинь телефон)` : 'Наведи на предмет так, чтобы были видны метки коврика') : (st.n < 3 ? 'Мало меток в кадре — чуть дальше' : `Крупно: ${Math.round(st.dist / 10)} см · медленно веди вокруг · кадров ${st.count}`); cls = st.found && st.n >= 3 ? 'good' : 'warn'; }
  else if (!st.found) {
    text = !st.markers ? 'Наведи камеру на коврик'
      : st.poseN >= 2 ? 'Метки видны, но положение неточное — блик или смаз. Убери блик, держи телефон неподвижно'
      : turn && st.ring < 2 ? `Видно меток: ${st.markers}, из них на круге ${st.ring} — нужно 2 метки круга (или весь лист на столике)`
      : `Видно меток: ${st.markers} — не хватает чёткости, подвинь телефон чуть ближе/дальше`;
    cls = 'bad';
  }
  else if (st.el < BANDS[0][0]) { text = 'Слишком низко — подними телефон'; cls = 'warn'; }
  else if (low < 0.75) { text = turn ? 'Крути столик — первый оборот (кадры идут сами)' : 'Обходи вокруг предмета, держа телефон невысоко (~30°)'; }
  else if (mid < 0.6) { text = turn ? 'Подними держатель выше (~55°) и ещё оборот' : 'Теперь ещё круг повыше (~55°)'; }
  else if (high < 0.4) { text = turn ? 'Ещё выше (~75°) — последний оборот' : 'И круг почти сверху (~75°)'; }
  else { text = 'Отлично! Можно нажимать «Готово»'; cls = 'good'; }
  msg.textContent = text; msg.className = 'capMsg ' + cls + (capCtx && capCtx.bottomOf ? ' bottomTag' : '');
  const info = st.found ? `высота ${st.el.toFixed(0)}° · азимут ${st.az.toFixed(0)}° · ${Math.round(st.dist / 10)} см · меток ${st.n} · ${st.speed.toFixed(0)}°/с · ${st.fps.toFixed(0)} к/с${cap.f ? '' : ' · калибровка…'}` : `слежение ${(st.fps || 0).toFixed(0)} к/с · меток ${st.markers || 0}${st.restarts ? ` · перезапусков камеры ${st.restarts}` : ''}`;
  $('capInfo').textContent = [info, st.why ? 'Не снимаю: ' + st.why : (st.found ? 'Снимаю' : ''), inkLabel(st.ink)].filter(Boolean).join('\n');
}
function cancelCapture() { if (cap) cap.stop(); cap = null; go('home'); }
$('capCancel').onclick = () => { if (!cap || cap.shots.length < 3 || confirm('Выбросить снятые кадры?')) history.back(); };
// Верх рамки: подгони верхнее кольцо AR-цилиндра к верху предмета (чуть выше). Всё, что выше, не попадёт в модель.
// Над предметом пространство видно только на фоне стены/стола — по коврику там не понять, где кончается предмет.
function showH() { if (cap) $('hVal').textContent = `${(cap.opt.Hb / 10).toFixed(1).replace('.0', '')} см`; }
function adjH(d) { if (!cap) return; cap.opt.Hb = Math.max(20, Math.min(400, Math.round((cap.opt.Hb + d) / 5) * 5)); showH(); }
$('hUp').onclick = () => adjH(+5); $('hDn').onclick = () => adjH(-5);
$('capShot').onclick = () => { if (!cap) return; cap.shootNow(); if (!cap.state || !cap.state.found) toast('Снято. Метки сейчас не найдены — положение кадра найдётся при обработке, если они видны'); };
$('capPause').onclick = () => {
  if (!cap) return;
  if (cap.paused) { cap.arm(+S.delay || 0); lastCount = null; $('capPause').textContent = '⏸'; }
  else { cap.paused = true; $('capPause').textContent = '▶'; }
};
// Кадр фона (вертушка): пустой коврик с того же места, где стоит телефон. Всё за кругом (стол, стена) неподвижно —
// где кадр совпал с фоном, там над предметом пусто: так вырезается «шапка» над верхом.
let plateBusy = false;
async function takePlate(btn) {
  if (!cap || plateBusy) return false;
  plateBusy = true; const wasPaused = cap.paused; cap.paused = true;
  try {
    for (let s = 3; s > 0; s--) { if (btn) btn.textContent = `Через ${s}…`; $('capMsg').textContent = `Фон через ${s} с — руки и предмет из кадра, телефон не трогать`; beep(660, 0.08); await new Promise((r) => setTimeout(r, 1000)); if (!cap) return false; }
    const blob = await cap.grab(); cap.plates.push(blob); beep(1318, 0.08); if (navigator.vibrate) navigator.vibrate(30);
    $('capPlate').textContent = cap.plates.length > 1 ? `Фон✓${cap.plates.length}` : 'Фон✓';
    return true;
  } finally { plateBusy = false; if (cap) cap.paused = wasPaused; if (btn) btn.textContent = 'Фон'; }
}
$('capPlate').onclick = async () => { if (await takePlate()) toast('Фон снят. Теперь поставь предмет в центр круга и снимай. В конце предложу снять фон ещё раз — после последнего оборота', 5000); };
let plateSheet = false;
$('capDone').onclick = async () => {
  if (!cap) return;
  if (S.method === 'turn' && !plateSheet && !(capCtx && capCtx.closeOf)) { // последнее положение держателя: предложим кадр фона
    cap.paused = true; $('capPause').textContent = '▶'; plateSheet = true;
    sheet(`<h3>Кадр фона</h3><p>Убери предмет с вертушки, <b>не сдвигая телефон и держатель</b>, и нажми «Снять фон» — через 3 секунды сниму пустой коврик. По нему вырежется пространство над предметом: верх выйдет без «шапки».</p><p style="color:var(--mute)">Фон годится для кадров, снятых с этого же места. Если в начале уже снимал «Фон» с другой высоты — он тоже пойдёт в дело.</p><button data-a="plate" class="mid primary">Снять фон</button><button data-a="skip" class="mid">Без фона — обработать</button>`, (box) => {
      box.querySelector('[data-a="plate"]').onclick = async (e) => { const ok = await takePlate(e.currentTarget); closeSheet(); if (ok) finishCapture(); else plateSheet = false; };
      box.querySelector('[data-a="skip"]').onclick = () => { closeSheet(); finishCapture(); };
    });
    return;
  }
  finishCapture();
};
async function finishCapture() {
  plateSheet = false;
  if (!cap) return;
  const shots = cap.shots.map((s) => s.blob), Hb = cap.opt.Hb, plates = cap.plates || []; cap.stop(); cap = null;
  if (capCtx && capCtx.closeOf) { // крупные планы: только для текстуры, пересчёт со всеми кадрами
    const base = capCtx.closeOf; capCtx = null;
    const fa = await store.getFrames(base.id).catch(() => null);
    if (!fa || !fa.length) { toast('Кадры основной съёмки удалены — пересчитать не из чего', 4000); history.back(); return; }
    const old = await store.getFrames(base.id + ':close').catch(() => null), all = (old || []).concat(shots);
    try { await store.putFrames(base.id + ':close', all); } catch (e) { toast('Не удалось сохранить кадры: ' + e.message); }
    const [bf, pa, bp] = await Promise.all([base.bottom ? store.getFrames(base.id + ':bottom').catch(() => null) : null, store.getFrames(base.id + ':plate').catch(() => null), store.getFrames(base.id + ':bplate').catch(() => null)]);
    const ns = { id: base.id, name: base.name, date: base.date, settings: { ...(base.settings || S) }, bottom: base.bottom, close: all.length };
    runProcessing(ns, fa, bf, { plates: pa, bottomPlates: bp, close: all });
    return;
  }
  if (capCtx) { // досъёмка низа: кадры — отдельно, обработка — обе съёмки вместе
    const base = capCtx.bottomOf; capCtx = null;
    const fa = await store.getFrames(base.id).catch(() => null);
    if (!fa || !fa.length) { toast('Кадры основной съёмки удалены — низ не к чему добавить', 4000); history.back(); return; }
    try { await store.putFrames(base.id + ':bottom', shots); await store.delFrames(base.id + ':bplate'); if (plates.length) await store.putFrames(base.id + ':bplate', plates); } catch (e) { toast('Не удалось сохранить кадры: ' + e.message); }
    const pa = await store.getFrames(base.id + ':plate').catch(() => null);
    const cl = base.close ? await store.getFrames(base.id + ':close').catch(() => null) : null;
    const ns = { id: base.id, name: base.name, date: base.date, settings: { ...(base.settings || S) }, bottom: { n: shots.length, Hb: String(Hb), method: S.method }, close: base.close };
    runProcessing(ns, fa, shots, { plates: pa, bottomPlates: plates, close: cl });
    return;
  }
  const id = 'scan-' + Date.now(), d = new Date();
  const scan = { id, name: `Скан ${d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })} ${d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}`, date: Date.now(), settings: { ...S, height: String(Hb) } };
  try { await store.putFrames(id, shots); if (plates.length) await store.putFrames(id + ':plate', plates); } catch (e) { toast('Не удалось сохранить кадры: ' + e.message); }
  runProcessing(scan, shots, null, { plates });
}

// ---------- обработка ----------
let proc = null, procViewer = null;
function runProcessing(scan, blobs, bottomBlobs, extra = {}) {
  go('process');
  const st = scan.settings;
  $('procLog').textContent = ''; $('procBar').style.width = '0%'; $('procStage').textContent = 'Подготовка…'; $('procText').textContent = '';
  $('procStop').textContent = 'Остановить'; $('procView').classList.remove('on');
  const log = (t) => { $('procLog').textContent += t + '\n'; };
  log(`кадров: ${blobs.length}; режим: ${{ mesh: 'полигоны', splat: 'сплэты', both: 'полигоны + сплэты' }[st.mode]}`);
  const job = { blobs, mode: st.mode, quality: st.quality, size: st.size, theme: 'light', Hb: +st.height, method: st.method || 'walk', shape: st.shape || 'normal', scale: calFor(st.size) };
  if (extra.close && extra.close.length && st.mode !== 'splat') { job.close = extra.close; log(`+ крупные планы: ${extra.close.length}`); }
  if (extra.plates && extra.plates.length) { job.plates = extra.plates; log(`+ кадр фона: ${extra.plates.length}`); }
  if (bottomBlobs && bottomBlobs.length && scan.bottom) { job.bottom = { blobs: bottomBlobs, Hb: +scan.bottom.Hb, method: scan.bottom.method, plates: extra.bottomPlates || null }; log(`+ досъёмка низа: ${bottomBlobs.length} кадров`); }
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
  curScan = scan; window.__obyomScan = scan; // для тестов
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
  viewer.hasTex = !!(scan.mesh && scan.mesh.uv && scan.mesh.tex);
  syncViewTools();
}
function syncViewTools() {
  $('vShow').querySelectorAll('button').forEach((b) => b.classList.toggle('on', viewer.show === b.dataset.v));
  $('vShade').querySelectorAll('button').forEach((b) => b.classList.toggle('on', String(viewer.shade) === b.dataset.v));
  $('vShade').classList.toggle('hidden', viewer.show !== 'mesh');
  $('vTex').classList.toggle('hidden', viewer.show !== 'mesh' || !viewer.hasTex || viewer.shade === 2);
  $('vTex').querySelectorAll('button').forEach((b) => b.classList.toggle('on', String(viewer.useTex === false ? 0 : 1) === b.dataset.v));
  $('vAuto').classList.toggle('on', viewer.auto);
}
$('vShow').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; viewer.show = b.dataset.v; viewer.dirty = true; syncViewTools(); };
$('vShade').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; viewer.shade = +b.dataset.v; viewer.dirty = true; syncViewTools(); };
$('vTex').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; viewer.useTex = b.dataset.v === '1'; viewer.dirty = true; syncViewTools(); };
$('vAuto').onclick = () => { viewer.auto = !viewer.auto; syncViewTools(); };
$('vHome').onclick = () => { viewer.reset(); };
$('vName').onchange = async () => { if (!curScan) return; curScan.name = $('vName').value.trim() || curScan.name; await store.putScan(curScan).catch(() => {}); };
setInterval(() => { if (viewer && cur === 'view') { const on = $('vAuto').classList.contains('on'); if (on !== viewer.auto) syncViewTools(); } }, 500);

$('vExp').onclick = () => {
  const s = curScan; if (!s) return;
  const base = fileBase(s.name);
  const items = [];
  if (s.mesh) items.push(
    ['glb', 'GLB', s.mesh.tex ? 'с текстурой внутри · Blender, Godot, Unity, сайты, AR' : 'Blender, Godot, Unity, сайты, AR', () => saveFile(toGLB(s.mesh, s.name), base + '.glb', 'model/gltf-binary')],
    ['obj', 'OBJ', s.mesh.tex ? 'три файла: .obj + .mtl + текстура .jpg' : 'с цветами вершин, любые 3D-программы', async () => { const o = toOBJ(s.mesh, base); await saveFile(o.obj, base + '.obj', 'text/plain'); if (o.mtl) { await saveFile(o.mtl, base + '.mtl', 'text/plain'); await saveFile(o.jpg, base + '.jpg', 'image/jpeg'); } }],
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
// «Доснять низ» прямо с экрана модели (раньше — только в ⋯)
$('vBottom').onclick = async () => {
  const scan = curScan; if (!scan) return;
  const fr = await store.getFrames(scan.id).catch(() => null);
  if (!fr || !fr.length) { toast('Кадры этой съёмки удалены — низ не к чему добавить. Сними предмет заново.', 4000); return; }
  history.back(); setTimeout(() => startCapture({ bottomOf: scan }), 80);
};
async function moreSheet(scan) {
  const frames = await store.getFrames(scan.id).catch(() => null);
  const nf = frames ? frames.length : 0;
  const bframes = scan.bottom ? await store.getFrames(scan.id + ':bottom').catch(() => null) : null;
  const nb = bframes ? bframes.length : 0;
  const close = await store.getFrames(scan.id + ':close').catch(() => null), nc = close ? close.length : 0;
  const plates = await store.getFrames(scan.id + ':plate').catch(() => null), bplates = scan.bottom ? await store.getFrames(scan.id + ':bplate').catch(() => null) : null;
  const bInfo = nb ? `<p>Досъёмка низа: ${nb} кадров${scan.stats && 'bottom' in scan.stats ? (scan.stats.bottom ? ' — учтена ✓' : ' — <span style="color:var(--warn)">не совместилась</span>') : ''}.</p>` : '';
  sheet(`<h3>${scan.name.replace(/</g, '&lt;')}</h3>${scan.failed ? `<p style="color:var(--warn)">${scan.failed}</p>` : ''}
    ${scan.stats ? `<p>Кадров использовано: ${scan.stats.used} из ${scan.stats.frames}. Объём: ${(scan.stats.volume / 1000).toFixed(1)} см³. Обработка: ${fmtT(scan.stats.t)}.</p>` : ''}
    ${nf ? `<button data-a="bottom" class="mid">↻ ${nb ? 'Переснять низ' : 'Доснять низ'}<small>положить предмет на бок / вверх дном и снять ещё раз — появится дно, уточнится верх</small></button>${bInfo}
    <button data-a="close" class="mid">🔍 ${nc ? 'Ещё крупные планы' : 'Крупные планы для текстуры'}<small>${nc ? `уже ${nc} кадров; ` : ''}предмет не двигать, телефон ближе — текстура станет детальнее</small></button>
    <p>Пересчитать из сохранённых кадров (${nf} шт.${nb ? ` + низ ${nb}` : ''}) с другими настройками:</p>
    <div class="grid2"><button data-r="mesh">Полигоны</button><button data-r="splat">Сплэты</button><button data-r="both">Оба</button><button data-r="best">Оба, качество «Лучше»</button></div>
    <label class="lbl">Высота предмета при пересчёте, см (чуть больше настоящей — лишний верх не достроится)</label>
    <input id="rH" class="inp" type="number" inputmode="decimal" step="0.5" min="2" max="40">
    <p>Форма предмета при пересчёте:</p>
    <div class="seg wrap3" id="rShape"><button data-v="normal">Обычная</button><button data-v="revolve">Тело вращения</button><button data-v="smooth">Гладкая</button><button data-v="box">Коробка</button><button data-v="prism">Призма</button><button data-v="planes">Плоские грани</button></div>
    ${nb ? '<label class="lbl"><input type="checkbox" id="rNoB"> пересчитать без досъёмки низа</label><button data-a="dropbottom">Удалить досъёмку низа</button>' : ''}
    ${nc ? '<button data-a="dropclose">Удалить крупные планы</button>' : ''}
    <button data-a="dropframes">Удалить кадры (освободить место)</button>` : '<p>Кадров съёмки нет — пересчёт невозможен.</p>'}
    <button data-a="delete" style="color:var(--bad)">Удалить модель</button>`,
  (box) => {
    let shape = (scan.settings && scan.settings.shape) || 'normal';
    const rs = box.querySelector('#rShape');
    const syncShape = () => rs && rs.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.v === shape));
    if (rs) { rs.onclick = (e) => { const b = e.target.closest('button'); if (b) { shape = b.dataset.v; syncShape(); } }; syncShape(); }
    const rh = box.querySelector('#rH'); if (rh) rh.value = (+((scan.settings && scan.settings.height) || S.height) / 10).toString();
    box.querySelectorAll('[data-r]').forEach((b) => b.onclick = () => {
      const hv = rh ? parseFloat(String(rh.value).replace(',', '.')) : NaN;
      closeSheet(); const st = { ...(scan.settings || S), shape };
      if (hv >= 2 && hv <= 40) st.height = String(Math.round(hv * 10));
      if (b.dataset.r === 'best') { st.mode = 'both'; st.quality = 'best'; } else st.mode = b.dataset.r;
      const noB = box.querySelector('#rNoB') && box.querySelector('#rNoB').checked;
      const ns = { id: scan.id, name: scan.name, date: scan.date, settings: st, bottom: scan.bottom };
      if (cur !== 'home') history.back(); ns.close = scan.close; setTimeout(() => runProcessing(ns, frames, noB ? null : bframes, { plates, bottomPlates: bplates, close }), 50);
    });
    const bb = box.querySelector('[data-a="bottom"]'); if (bb) bb.onclick = () => { closeSheet(); const go2 = () => startCapture({ bottomOf: scan }); if (cur !== 'home') { history.back(); setTimeout(go2, 80); } else go2(); };
    const cb2 = box.querySelector('[data-a="close"]'); if (cb2) cb2.onclick = () => { closeSheet(); const go2 = () => startCapture({ closeOf: scan }); if (cur !== 'home') { history.back(); setTimeout(go2, 80); } else go2(); };
    const dc = box.querySelector('[data-a="dropclose"]'); if (dc) dc.onclick = async () => { await store.delFrames(scan.id + ':close'); delete scan.close; await store.putScan(scan).catch(() => {}); closeSheet(); toast('Крупные планы удалены (текстура останется, пока не пересчитаешь)'); };
    const db = box.querySelector('[data-a="dropbottom"]'); if (db) db.onclick = async () => { await store.delFrames(scan.id + ':bottom'); await store.delFrames(scan.id + ':bplate').catch(() => {}); delete scan.bottom; await store.putScan(scan).catch(() => {}); closeSheet(); toast('Досъёмка низа удалена (модель останется, пока не пересчитаешь)'); };
    const dz = box.querySelector('[data-a="dropframes"]'); if (dz) dz.onclick = async () => { await store.delFrames(scan.id); await store.delFrames(scan.id + ':bottom'); for (const k of [':plate', ':bplate', ':close']) await store.delFrames(scan.id + k).catch(() => {}); closeSheet(); toast('Кадры удалены'); };
    box.querySelector('[data-a="delete"]').onclick = async () => { if (!confirm('Удалить модель «' + scan.name + '»?')) return; await store.delScan(scan.id); closeSheet(); if (cur === 'view') history.back(); else renderList(); };
  });
}

// ---------- коврик и справка ----------
function showMat() {
  sheet(`<h3>Коврик для съёмки</h3>
  <p>Печатай на обычном белом листе <b>в масштабе 100%</b> («Фактический размер», без «Вписать в страницу»). Сероватая печать — не страшно; индикатор при съёмке подскажет, хватает ли контраста.</p>
  <p><b>Весь лист</b> — для съёмки с рук; вырезать ничего не нужно, лист просто лежит на столе.</p>
  <div class="grid2"><button data-m="pdf:A4:full">PDF A4<small>предметы до 12 см</small></button><button data-m="pdf:A3:full">PDF A3<small>до 17 см</small></button><button data-m="pdf:A2:full">PDF A2<small>до 24 см (копицентр)</small></button><button data-m="png:A4:full">PNG A4<small>картинка</small></button></div>
  <p><b>Круг для вертушки</b> — без угловых меток. Вырежи по пунктиру; если столик меньше круга, подложи картон: круг должен лежать ровно, не свисать.</p>
  <div class="grid2"><button data-m="pdf:A4:round">Круг A4</button><button data-m="pdf:A3:round">Круг A3</button></div>
  <button id="btnCal" class="mid">📏 Калибровка печати${calInfo()}</button>
  <ul><li><b>Чёрные квадраты</b> по кругу — метки: по ним телефон узнаёт, откуда смотрит камера, и масштаб.</li>
  <li><b>Серые крапинки</b> — чтобы отличать тень от предмета: в тени крапинки видны, а предмет их закрывает.</li>
  <li><b>Градусы и стрелка</b> — только для тебя (видно, насколько повернул столик). Телефон на них не смотрит.</li>
  <li>На вертушке приложение смотрит только на кольцо меток: всё, что за кругом, ему не важно.</li></ul>`,
  (box) => {
    box.querySelectorAll('[data-m]').forEach((b) => b.onclick = async () => {
      b.disabled = true; toast('Готовлю файл…');
      try {
        const [kind, size, variant] = b.dataset.m.split(':'), suf = variant === 'round' ? '-круг' : '';
        if (kind === 'pdf') await saveFile(await matPDF(size, 'light', variant), `Объём-коврик-${size}${suf}.pdf`, 'application/pdf');
        else await saveFile(await matPNG(size, 'light', variant), `Объём-коврик-${size}${suf}.png`, 'image/png');
      } catch (e) { toast('Ошибка: ' + e.message); }
      b.disabled = false;
    });
    box.querySelector('#btnCal').onclick = showCal;
  });
}
function calInfo() { const c = loadCal(); const ks = Object.keys(c); return ks.length ? `<small>${ks.map((k) => `${k}: ×${c[k].sx.toFixed(3)} / ×${c[k].sy.toFixed(3)}`).join(' · ')}</small>` : '<small>не сделана — размеры как есть</small>'; }
function showCal() {
  const c = loadCal();
  sheet(`<h3>Калибровка печати</h3>
  <p>Принтер часто чуть уменьшает или растягивает лист (на 1–3%) — тогда и модель выйдет на столько же меньше. Измерь линейкой на напечатанном коврике:</p>
  <ol><li><b>Сверху вниз:</b> от внешнего (дальнего от центра) края верхней чёрной метки до внешнего края нижней.</li>
  <li><b>Слева направо:</b> то же для левой и правой меток.</li></ol>
  <label class="lbl">Лист</label>
  <div class="seg" id="calSize"><button data-v="A4">A4</button><button data-v="A3">A3</button><button data-v="A2">A2</button></div>
  <p id="calNom" class="hint"></p>
  <label class="lbl">Сверху вниз, мм</label><input id="calV" type="number" inputmode="decimal" step="0.5" class="inp">
  <label class="lbl">Слева направо, мм</label><input id="calH" type="number" inputmode="decimal" step="0.5" class="inp">
  <div class="grid2"><button id="calSave" class="primary">Сохранить</button><button id="calReset">Сбросить</button></div>`,
  (box) => {
    let size = S.size;
    const sync = () => {
      box.querySelectorAll('#calSize button').forEach((b) => b.classList.toggle('on', b.dataset.v === size));
      const nom = matLayout(size).calSpan, v = c[size];
      box.querySelector('#calNom').textContent = `Должно быть ${nom.toFixed(0)} мм в обе стороны.`;
      box.querySelector('#calV').value = v ? (nom * v.sy).toFixed(1) : ''; box.querySelector('#calH').value = v ? (nom * v.sx).toFixed(1) : '';
    };
    box.querySelector('#calSize').onclick = (e) => { const b = e.target.closest('button'); if (b) { size = b.dataset.v; sync(); } };
    box.querySelector('#calSave').onclick = () => {
      const nom = matLayout(size).calSpan, V = parseFloat(String(box.querySelector('#calV').value).replace(',', '.')), H = parseFloat(String(box.querySelector('#calH').value).replace(',', '.'));
      if (!(V > nom * 0.85 && V < nom * 1.15 && H > nom * 0.85 && H < nom * 1.15)) { toast(`Проверь числа: должно быть около ${nom.toFixed(0)} мм`); return; }
      c[size] = { sx: H / nom, sy: V / nom }; localStorage.setItem('obyom.cal', JSON.stringify(c));
      toast(`Сохранено: ширина ×${(H / nom).toFixed(3)}, длина ×${(V / nom).toFixed(3)}. Учтётся при обработке (и при пересчёте старых сканов).`, 4500); closeSheet();
    };
    box.querySelector('#calReset').onclick = () => { delete c[size]; localStorage.setItem('obyom.cal', JSON.stringify(c)); toast('Калибровка ' + size + ' сброшена'); sync(); };
    sync();
  });
}
function showHelp() {
  sheet(`<h3>Как снимать</h3>
  <ol><li>Положи коврик на стол, предмет — в центр круга. Свет мягкий, рассеянный (у окна днём или две лампы по бокам), без резких теней.</li>
  <li><b>С рук:</b> обходи предмет медленно, держа в кадре весь круг меток. Три круга: низко (~30°), повыше (~55°) и почти сверху (~75°). Купол справа показывает, что уже снято.</li>
  <li><b>Держатель + вертушка:</b> телефон в держателе смотрит на коврик сверху-сбоку с 25–35 см. Нажми ▶, раскрути столик и убери руку: после таймера кадр снимается каждые 8° поворота (настройка «Частота кадров»). Столик замедляется — кадры реже, остановился — съёмка ждёт. Скорость не ограничена: если кадр мутный, приложение подождёт пару кадров порезче. Потом подними держатель выше, ⏸ → ▶ и ещё оборот.</li>
  <li><b>С рук:</b> то же правило — новый кадр через каждые ~10° сдвига ракурса.</li>
  <li>Количество кадров не ограничено. Строка <b>«Не снимаю: …»</b> объясняет, почему кадр не взят; «слежение N к/с» — как быстро телефон успевает искать метки. Кнопка 📷 снимает кадр сразу.</li>
  <li>Когда купол заполнен — «Готово». Форма считается за полминуты, сплэты — несколько минут; можно остановить раньше.</li></ol>
  <p><b>Высота предмета</b> — выбери ближайшую большую. Перед съёмкой подгони верх AR-рамки кнопками ▲▼ справа так, чтобы верхнее кольцо было чуть выше предмета: всё, что выше, обрежется, а пустоту между предметом и верхом рамки программа может принять за предмет (её видно только на фоне стены). Для готового скана высоту можно поправить в «Пересчитать». <b>Ширина</b>: A4 — до 12 см, A3 — до 17 см, A2 — до 24 см.</p>
  <p><b>Форма предмета</b> (можно сменить и потом: ⋯ → Пересчитать):</p>
  <ul><li><b>Обычная</b> — как получилось по силуэтам, любой предмет.</li>
  <li><b>Тело вращения</b> — бутылки, банки, шары, вазы, конусы: каждое сечение — круг.</li>
  <li><b>Гладкая</b> — сильное сглаживание: камни, фрукты, мыло, мягкие игрушки. Мелкие детали и острые рёбра пропадут.</li>
  <li><b>Коробка</b> — точный прямоугольный брусок с острыми рёбрами: упаковки, книги, бруски. Размеры подбираются по сечению.</li>
  <li><b>Призма</b> — одно и то же сечение по всей высоте (любой формы): флакон-брусок, мыло, деталь. Прямые стороны сечения выпрямляются, углы — острые.</li>
  <li><b>Плоские грани</b> — обычная форма, но найденные плоскости становятся ровными, а рёбра между ними — острыми: предметы из граней.</li></ul>
  <p><b>Дно:</b> в обычной съёмке предмет стоит на нём, и снизу модель срезана по столу. Чтобы получить дно — открой модель → ⋯ → <b>«Доснять низ»</b>: положи предмет на бок или вверх дном в центр круга и сними ещё раз. Приложение само найдёт, как он лежал (совместит две формы), и вырежет то, что видно только во второй съёмке: появится настоящее дно, а «колпак» сверху уточнится. Кадры второй съёмки дают и цвет дна.</p>
  <p><b>«Фон» (вертушка):</b> телефон в держателе неподвижен, поэтому стол и стена за ковриком от кадра к кадру одинаковые. Сними их без предмета — кнопка «Фон» в начале (коврик ещё пустой) и после «Готово» (убери предмет, не трогая телефон). Там, где кадр совпал с фоном, над предметом пусто — так вырезается «шапка» над верхом, которую по самому коврику не видно. Фон годится только для того же положения держателя.</p>
  <p><b>Текстура:</b> цвет модели — отдельная картинка-атлас: каждый кусок поверхности берётся из одного лучшего кадра в полном разрешении (а не из цвета вершин). В просмотре — переключатель «Текстура / Вершины». Для большей детальности — ⋯ → <b>«Крупные планы»</b>: предмет не двигать, телефон ближе (15–25 см), в кадре хотя бы 3 метки. Качество «Лучше» снимает в Full HD и считает форму на 960 px.</p>
  <p><b>Что не получится:</b> прозрачные и зеркальные предметы; глубокие впадины (внутренность чашки) — метод видит силуэты. Блестящий бок даёт блики — лучше «Тело вращения» или матовый свет.</p>
  <p>Всё считается на телефоне, без интернета и без нейросетей. Версия ${VERSION}.</p>`);
}

if ('serviceWorker' in navigator && location.protocol === 'https:' && !/ObyomAndroid/.test(navigator.userAgent)) navigator.serviceWorker.register('sw.js').catch(() => {});
renderList();
