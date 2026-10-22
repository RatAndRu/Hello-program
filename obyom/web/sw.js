// Сеть в первую очередь (обновления не застревают), кэш — когда нет интернета.
const CACHE = 'obyom-v19';
const ASSETS = ['./', './index.html', './styles.css', './manifest.webmanifest',
  './js/app.js', './js/mat.js', './js/detect.js', './js/pose.js', './js/recon.js', './js/splat.js', './js/pipeline.js', './js/worker.js', './js/procclient.js', './js/wasmcarve.js', './js/sam.js',
  './js/capture.js', './js/viewer.js', './js/export.js', './js/store.js', './js/matprint.js', './js/align.js', './js/shapes.js', './js/texture.js', './js/surface.js', './js/nativecam.js', './js/retopo.js', './js/splatpool.js', './js/splatworker.js', './js/zip.js',
  './icons/icon-192.png', './icons/icon-512.png'];
self.addEventListener('install', (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).catch(() => {})); self.skipWaiting(); });
// v2.8: WASM-модуль добавляется в кэш в фоне при install — без этого в APK при оффлайне
// с первого запуска carve.mjs может не подтянуться.
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all([
    c.add(new Request('./js/wasm/carve.mjs', { cache: 'no-cache' })).catch(()=>{}),
    c.add(new Request('./js/wasm/carve.wasm', { cache: 'no-cache' })).catch(()=>{}),
  ])));
});
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))); self.clients.claim(); });
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  e.respondWith(fetch(req).then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {}); return res; })
    .catch(() => caches.match(req).then((r) => r || caches.match('./index.html'))));
});
