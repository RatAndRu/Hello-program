// ЗакрепФото: в браузере фото хранятся в IndexedDB, а в Android-приложении —
// в нативных файлах приложения через мост PinPhotosNative (надёжнее для WebView).
const DB = 'pinphotos-db', STORE = 'photos';
const nativeMode = !!(window.PinPhotosNative && PinPhotosNative.listPhotos);
let photos = [], current = null, urls = new Map(), deferredInstall = null;
const $ = id => document.getElementById(id);
const metaOf = p => ({id: p.id, name: p.name, album: p.album, tags: p.tags || [], note: p.note || '', pinned: !!p.pinned, widget: !!p.widget, createdAt: p.createdAt});

// ---------- Отладочный журнал: виден прямо в приложении ----------
let debugLines = [];
try { debugLines = JSON.parse(localStorage.getItem('pinphotos_debug') || '[]'); } catch (e) {}
function dbg(stage, details = '') {
  const line = `[${new Date().toLocaleTimeString()}] ${stage}${details ? ' — ' + details : ''}`;
  debugLines.push(line); debugLines = debugLines.slice(-160);
  try { localStorage.setItem('pinphotos_debug', JSON.stringify(debugLines)); } catch (e) {}
  const el = $('debugLog'); if (el) { el.textContent = debugLines.join('\n'); el.scrollTop = el.scrollHeight; }
  console.log(line);
}
function dbgErr(stage, err) { dbg('❌ ' + stage, (err && (err.stack || err.message || String(err))) || String(err)); }
window.addEventListener('error', e => dbg('❌ window.error', e.message || String(e.error || e)));
window.addEventListener('unhandledrejection', e => dbg('❌ unhandledrejection', String(e.reason && (e.reason.stack || e.reason.message || e.reason))));
function renderDebugLog() { const el = $('debugLog'); if (el) el.textContent = debugLines.length ? debugLines.join('\n') : 'Журнал пуст.'; }
function storageInfoLog(stage) {
  if (nativeMode && PinPhotosNative.getStorageInfo) dbg(stage + ': storage', PinPhotosNative.getStorageInfo());
  else dbg(stage + ': storage', `browser mode, photos in memory=${photos.length}`);
}

function db() { return new Promise((res, rej) => { const r = indexedDB.open(DB, 1); r.onupgradeneeded = () => r.result.createObjectStore(STORE, {keyPath: 'id'}); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); }); }
async function tx(mode, fn) { const d = await db(); return new Promise((res, rej) => { const t = d.transaction(STORE, mode); const out = fn(t.objectStore(STORE)); t.oncomplete = () => res(out && out.result); t.onerror = () => rej(t.error); }); }
const loadAll = async () => {
  dbg('loadAll start', `nativeMode=${nativeMode}, bridge=${typeof window.PinPhotosNative}, listPhotos=${typeof (window.PinPhotosNative || {}).listPhotos}`);
  if (nativeMode) {
    const raw = PinPhotosNative.listPhotos() || '[]';
    dbg('loadAll native raw', `length=${raw.length}, lastError=${PinPhotosNative.getLastError ? PinPhotosNative.getLastError() : 'n/a'}`);
    const list = JSON.parse(raw);
    for (const p of list) { p.blob = await (await fetch(p.dataUrl)).blob(); p._stored = true; }
    dbg('loadAll native done', `photos=${list.length}`);
    return list;
  }
  return tx('readonly', s => s.getAll());
};
const put = async p => {
  if (nativeMode) {
    if (!p._stored) {
      dbg('put→savePhoto start', `name=${p.name}, blobType=${p.blob && p.blob.type}, blobSize=${p.blob && p.blob.size}`);
      const dataUrl = p.dataUrl || await blobToB64(p.blob);
      dbg('put→savePhoto encoded', `dataUrlLength=${dataUrl.length}, prefix=${dataUrl.slice(0, 40)}`);
      const raw = PinPhotosNative.savePhoto(dataUrl, p.name);
      dbg('put→savePhoto returned', String(raw).slice(0, 500));
      const saved = JSON.parse(raw);
      if (!saved.ok) throw new Error(saved.error || 'savePhoto вернул ok=false');
      Object.assign(p, saved); delete p.dataUrl; p._stored = true;
      storageInfoLog('put→savePhoto verified');
    } else {
      const result = PinPhotosNative.updatePhoto(JSON.stringify(metaOf(p)));
      dbg('put→updatePhoto', String(result));
      if (String(result).startsWith('ERROR')) throw new Error(result);
    }
    return;
  }
  const clean = metaOf(p); clean.blob = p.blob; return tx('readwrite', s => s.put(clean));
};
const del = async id => {
  if (nativeMode) { const r = PinPhotosNative.deletePhoto(id); dbg('deletePhoto', String(r)); if (String(r).startsWith('ERROR')) throw new Error(r); return; }
  return tx('readwrite', s => s.delete(id));
};
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
function urlFor(p) { if (!urls.has(p.id)) urls.set(p.id, URL.createObjectURL(p.blob)); return urls.get(p.id); }

async function addFiles(files) {
  dbg('addFiles start', `count=${files.length}`);
  for (const f of files) {
    dbg('file from picker', `name=${f.name || '(без имени)'}, type=${f.type || '(пустой MIME)'}, size=${f.size}, lastModified=${f.lastModified || 'n/a'}`);
    if (!f.type.startsWith('image/')) { dbg('⚠️ file skipped', 'MIME не начинается с image/ — это возможная причина, если фото не добавляется'); continue; }
    if (!f.size) dbg('⚠️ file size = 0', 'WebView получил пустой файл; используй нативный способ');
    // Ужимаем очень большие фото, чтобы не раздуть хранилище телефона
    let blob = f;
    try {
      const bmp = await createImageBitmap(f);
      dbg('createImageBitmap ok', `${bmp.width}×${bmp.height}`);
      const max = 2048; if (Math.max(bmp.width, bmp.height) > max) { const k = max / Math.max(bmp.width, bmp.height); const c = document.createElement('canvas'); c.width = bmp.width * k; c.height = bmp.height * k; c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height); blob = await new Promise(r => c.toBlob(r, 'image/jpeg', 0.85)); dbg('resize ok', `blobSize=${blob && blob.size}, blobType=${blob && blob.type}`); }
    } catch (e) { dbg('⚠️ createImageBitmap failed, беру оригинал', e.message || String(e)); }
    const p = {id: uid(), name: (f.name || 'Фото').replace(/\.[^.]+$/, ''), album: 'Разное', tags: [], note: '', pinned: false, widget: false, createdAt: Date.now(), blob};
    try { await put(p); photos.unshift(p); dbg('✅ photo saved and added to list', `id=${p.id}, total=${photos.length}`); }
    catch (e) { dbgErr('photo save failed', e); throw e; }
  }
  render(); dbg('render after addFiles', `photos=${photos.length}, pinned=${photos.filter(p => p.pinned).length}`);
}

function card(p, container) {
  const el = document.createElement('article'); el.className = 'card';
  el.innerHTML = `<img loading="lazy" alt=""><div class="meta"><div class="name"></div><div class="tags"></div></div>`;
  el.querySelector('img').src = urlFor(p);
  el.querySelector('.name').textContent = (p.widget ? '📱 ' : '') + (p.pinned ? '📌 ' : '') + p.name;
  el.querySelector('.tags').textContent = [p.album, ...(p.tags || []).map(t => '#' + t)].join(' · ');
  el.onclick = () => openViewer(p); container.appendChild(el);
}

function render() {
  const q = $('search').value.trim().toLowerCase(), alb = $('albumFilter').value;
  const match = p => (!alb || p.album === alb) && (!q || (p.name + ' ' + (p.tags || []).join(' ') + ' ' + p.album + ' ' + (p.note || '')).toLowerCase().includes(q));
  const list = photos.filter(match);
  const pinned = list.filter(p => p.pinned), rest = list;
  $('pinnedGrid').innerHTML = ''; $('grid').innerHTML = '';
  pinned.forEach(p => card(p, $('pinnedGrid'))); rest.forEach(p => card(p, $('grid')));
  $('pinnedEmpty').style.display = pinned.length ? 'none' : ''; $('empty').style.display = rest.length ? 'none' : '';
  const w = photos.find(p => p.widget) || photos.find(p => p.pinned) || photos[0];
  if (w) { $('widgetImg').src = urlFor(w); $('widgetTitle').textContent = w.name; $('widgetSub').textContent = [w.album, ...(w.tags || []).map(t => '#' + t)].join(' · ') || 'Закреплённое фото'; }
  // Бейдж на иконке приложения (там, где поддерживается: Chromium/Android)
  if ('setAppBadge' in navigator) navigator.setAppBadge(photos.filter(p => p.pinned).length).catch(() => {});
}

function openViewer(p) {
  current = p; $('viewer').classList.remove('hidden'); $('viewerImg').src = urlFor(p);
  $('editName').value = p.name; $('editAlbum').value = p.album; $('editTags').value = (p.tags || []).join(', '); $('editNote').value = p.note || '';
}
async function saveCurrent() {
  if (!current) return;
  Object.assign(current, {name: $('editName').value || current.name, album: $('editAlbum').value, tags: $('editTags').value.split(',').map(s => s.trim().replace(/^#/, '')).filter(Boolean), note: $('editNote').value});
  await put(current); render();
}
['editName', 'editAlbum', 'editTags', 'editNote'].forEach(id => $(id).addEventListener('change', saveCurrent));

$('fileInput').addEventListener('change', async e => {
  const count = e.target.files.length;
  dbg('fileInput change', `files=${count}`);
  try { await addFiles(e.target.files); if (count) alert(`Сохранено фото: ${count}. Режим хранения: ${nativeMode ? 'файлы Android-приложения' : 'IndexedDB браузера'}. Подробности — в журнале отладки.`); }
  catch (err) { dbgErr('fileInput add failed', err); alert('Не удалось сохранить фото. Открой журнал отладки, скопируй его и пришли мне. Ошибка: ' + (err.message || err)); }
  e.target.value = '';
});
$('fileInput').addEventListener('click', () => dbg('fileInput click', 'открываю системный выбор фото'));
$('nativeAddBtn').onclick = () => {
  dbg('nativeAdd click', `bridge=${typeof window.PinPhotosNative}, pickPhotosNative=${typeof (window.PinPhotosNative || {}).pickPhotosNative}`);
  if (nativeMode && PinPhotosNative.pickPhotosNative) PinPhotosNative.pickPhotosNative();
  else alert('Нативный способ работает только в установленном Android-приложении.');
};
window.onNativePhotosImported = async (saved, message) => {
  dbg('onNativePhotosImported', `saved=${saved}, message=${message}`);
  try { photos = (await loadAll() || []).sort((a, b) => b.createdAt - a.createdAt); render(); storageInfoLog('native import reload'); }
  catch (e) { dbgErr('native import reload failed', e); }
};
$('debugStorageBtn').onclick = () => storageInfoLog('manual check');
$('debugClearBtn').onclick = () => { debugLines = []; try { localStorage.removeItem('pinphotos_debug'); } catch (e) {} renderDebugLog(); };
$('debugCopyBtn').onclick = async () => {
  const text = debugLines.join('\n');
  try { await navigator.clipboard.writeText(text); alert('Журнал скопирован. Вставь его мне в чат.'); }
  catch (e) {
    const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); alert('Журнал скопирован. Вставь его мне в чат.'); } catch (_) { alert('Не удалось скопировать автоматически. Сделай скрин журнала.'); }
    ta.remove();
  }
};
$('search').addEventListener('input', render); $('albumFilter').addEventListener('change', render);
$('closeViewer').onclick = () => { saveCurrent(); $('viewer').classList.add('hidden'); };
$('pinBtn').onclick = async () => { await saveCurrent(); current.pinned = !current.pinned; await put(current); render(); openViewer(current); };
$('widgetBtn').onclick = async () => {
  await saveCurrent(); photos.forEach(p => p.widget = false); current.widget = true; current.pinned = true; await Promise.all(photos.map(put)); render();
  if (window.PinPhotosNative && PinPhotosNative.setWidgetPhoto) {
    // Единое Android-приложение: передаём фото через JS-мост, Kotlin обновит настоящий виджет 3×2.
    PinPhotosNative.setWidgetPhoto(await blobToB64(current.blob), current.name);
    alert('Готово: фото отправлено в виджет рабочего стола (3×2).');
  } else {
    alert('Фото поставлено на виджет (превью вверху). В Android-приложении оно обновит настоящий виджет рабочего стола.');
  }
};
document.querySelectorAll('.icon-state').forEach(btn => btn.addEventListener('click', () => {
  if (window.PinPhotosNative && PinPhotosNative.setIcon) PinPhotosNative.setIcon(btn.dataset.icon);
  else alert('Смена иконки работает в установленном Android-приложении «ЗакрепФото», а не в браузере.');
}));
$('deleteBtn').onclick = async () => { if (!confirm('Удалить копию фото из приложения? Оригинал в галерее не тронем.')) return; await del(current.id); URL.revokeObjectURL(urlFor(current)); urls.delete(current.id); photos = photos.filter(p => p !== current); $('viewer').classList.add('hidden'); render(); };
$('shareBtn').onclick = async () => { try { const f = new File([current.blob], current.name + '.jpg', {type: current.blob.type || 'image/jpeg'}); if (navigator.canShare && navigator.canShare({files: [f]})) await navigator.share({files: [f], title: current.name}); else alert('Браузер не умеет делиться файлами'); } catch (e) {} };
$('addWidgetBtn').onclick = () => {
  if (window.PinPhotosNative && PinPhotosNative.requestPinWidget) PinPhotosNative.requestPinWidget();
  else alert('Кнопка работает в установленном Android-приложении «ЗакрепФото». В браузере виджет добавить нельзя.');
};
$('widgetCard').onclick = () => { const w = photos.find(p => p.widget) || photos.find(p => p.pinned) || photos[0]; if (w) openViewer(w); };

const blobToB64 = b => new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(b); });
$('exportBtn').onclick = async () => {
  const data = []; for (const p of photos) data.push({...p, blob: undefined, dataUrl: await blobToB64(p.blob)});
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify({app: 'pinphotos', version: 1, photos: data})], {type: 'application/json'})); a.download = 'pinphotos-backup.json'; a.click();
};
$('importInput').addEventListener('change', async e => {
  try { const j = JSON.parse(await e.target.files[0].text()); for (const p of j.photos) { p.blob = await (await fetch(p.dataUrl)).blob(); delete p.dataUrl; p.id = uid(); await put(p); photos.unshift(p); } render(); } catch (err) { alert('Не удалось восстановить бэкап'); } e.target.value = '';
});

window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); deferredInstall = e; $('installBtn').classList.remove('hidden'); });
$('installBtn').onclick = async () => { if (deferredInstall) { deferredInstall.prompt(); await deferredInstall.userChoice; deferredInstall = null; $('installBtn').classList.add('hidden'); } };
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});

renderDebugLog();
dbg('app start', `nativeMode=${nativeMode}, userAgent=${navigator.userAgent}`);
storageInfoLog('app start');
loadAll().then(list => { photos = (list || []).sort((a, b) => b.createdAt - a.createdAt); render(); dbg('initial load done', `photos=${photos.length}`); }).catch(e => { dbgErr('initial load failed', e); render(); });
