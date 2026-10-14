// ЗакрепФото: офлайн-PWA. Фото хранятся копиями в IndexedDB (браузер не даёт сканировать галерею напрямую).
const DB = 'pinphotos-db', STORE = 'photos';
let photos = [], current = null, urls = new Map(), deferredInstall = null;
const $ = id => document.getElementById(id);

function db() { return new Promise((res, rej) => { const r = indexedDB.open(DB, 1); r.onupgradeneeded = () => r.result.createObjectStore(STORE, {keyPath: 'id'}); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); }); }
async function tx(mode, fn) { const d = await db(); return new Promise((res, rej) => { const t = d.transaction(STORE, mode); const out = fn(t.objectStore(STORE)); t.oncomplete = () => res(out && out.result); t.onerror = () => rej(t.error); }); }
const loadAll = () => tx('readonly', s => s.getAll());
const put = p => tx('readwrite', s => s.put(p));
const del = id => tx('readwrite', s => s.delete(id));
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
function urlFor(p) { if (!urls.has(p.id)) urls.set(p.id, URL.createObjectURL(p.blob)); return urls.get(p.id); }

async function addFiles(files) {
  for (const f of files) {
    if (!f.type.startsWith('image/')) continue;
    // Ужимаем очень большие фото, чтобы не раздуть хранилище телефона
    let blob = f;
    try { const bmp = await createImageBitmap(f); const max = 2048; if (Math.max(bmp.width, bmp.height) > max) { const k = max / Math.max(bmp.width, bmp.height); const c = document.createElement('canvas'); c.width = bmp.width * k; c.height = bmp.height * k; c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height); blob = await new Promise(r => c.toBlob(r, 'image/jpeg', 0.85)); } } catch (e) { /* оставим оригинал */ }
    const p = {id: uid(), name: f.name.replace(/\.[^.]+$/, ''), album: 'Разное', tags: [], note: '', pinned: false, widget: false, createdAt: Date.now(), blob};
    await put(p); photos.unshift(p);
  }
  render();
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

$('fileInput').addEventListener('change', async e => { await addFiles(e.target.files); e.target.value = ''; });
$('search').addEventListener('input', render); $('albumFilter').addEventListener('change', render);
$('closeViewer').onclick = () => { saveCurrent(); $('viewer').classList.add('hidden'); };
$('pinBtn').onclick = async () => { await saveCurrent(); current.pinned = !current.pinned; await put(current); render(); openViewer(current); };
$('widgetBtn').onclick = async () => { await saveCurrent(); photos.forEach(p => p.widget = false); current.widget = true; current.pinned = true; await Promise.all(photos.map(put)); render(); alert('Фото поставлено на виджет (превью вверху). В нативной Android-версии оно обновит виджет рабочего стола.'); };
$('deleteBtn').onclick = async () => { if (!confirm('Удалить копию фото из приложения? Оригинал в галерее не тронем.')) return; await del(current.id); URL.revokeObjectURL(urlFor(current)); urls.delete(current.id); photos = photos.filter(p => p !== current); $('viewer').classList.add('hidden'); render(); };
$('shareBtn').onclick = async () => { try { const f = new File([current.blob], current.name + '.jpg', {type: current.blob.type || 'image/jpeg'}); if (navigator.canShare && navigator.canShare({files: [f]})) await navigator.share({files: [f], title: current.name}); else alert('Браузер не умеет делиться файлами'); } catch (e) {} };
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

loadAll().then(list => { photos = (list || []).sort((a, b) => b.createdAt - a.createdAt); render(); }).catch(() => render());
