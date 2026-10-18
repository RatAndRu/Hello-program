// Сеть в первую очередь (обновления не застревают), кэш — когда нет интернета.
const CACHE = 'reyka-ar-v6';
const ASSETS = ['./', './index.html', './styles.css', './manifest.webmanifest',
  './js/app.js', './js/geom.js', './js/tracker.js', './js/camera.js', './js/guides.js', './js/tracing.js', './js/store.js',
  './js/perspective.js', './js/vanish.js', './js/scan.js', './js/manga.js', './js/colors.js',
  './icons/icon-192.png', './icons/icon-512.png'];
self.addEventListener('install', (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).catch(() => {})); self.skipWaiting(); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))); self.clients.claim(); });
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  e.respondWith(fetch(req).then((res) => {
    const copy = res.clone();
    caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
    return res;
  }).catch(() => caches.match(req).then((r) => r || caches.match('./index.html'))));
});
