// Сквозной тест вертушки с кадром фона (1.5): съёмка (камера CAM — сцена STATIC=1 scene.py … spin), «Готово» → лист «Кадр фона» →
// «Снять фон» (снимок подменяется на PLATE — пустой коврик с того же места) → обработка → текстура в просмотре.
// CAM=/tmp/t/camS.y4m PLATE=/tmp/t/spinS/plate.jpg [Q=normal] [MODE=mesh] node e2e_plate.cjs   (сервер obyom/web на :8765)
const puppeteer = require('puppeteer-core'); const chromium = (m => m.default || m)(require('@sparticuz/chromium'));
const fs = require('fs');
const SH = process.env.SH || '/home/user/shots/';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: true, protocolTimeout: 1200000, userDataDir: '/tmp/t/profP',
    args: [...chromium.args.filter((a) => !a.startsWith('--user-data-dir') && a !== '--single-process'), '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-video-capture=${process.env.CAM}`, '--autoplay-policy=no-user-gesture-required', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const page = await browser.newPage(); await page.setViewport({ width: 400, height: 800, deviceScaleFactor: 1 });
  // NATIVE=1 (или угол 0/90/180/270): подставная «своя камера» APK (ObyomNative.camStart/camFrame/camStop) —
  // кадры берутся из фейковой камеры браузера и отдаются повёрнутыми, как с сенсора телефона
  // PORTRAIT=1: телефон стоит вертикально — кадр 720×1280 (так снимают с держателя)
  if (process.env.NATIVE) await page.evaluateOnNewDocument((ROT, PORTRAIT) => {
    let v = null, id = 0, lastT = 0, starting = false; window.__nat = { frames: 0, starts: 0, stops: 0 };
    const c = document.createElement('canvas');
    async function init() { starting = true; const st = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 } }); v = document.createElement('video'); v.muted = true; v.srcObject = st; await v.play(); }
    window.ObyomNative = {
      camStart() { window.__nat.starts++; if (!starting) init(); return 'ok'; },
      camFrame() {
        if (!v || !v.videoWidth) return ''; const now = performance.now(); if (now - lastT < 50) return ''; lastT = now;
        const W = v.videoWidth, H = v.videoHeight, sw = ROT % 180 ? H : W, sh = ROT % 180 ? W : H; c.width = sw; c.height = sh;
        const x = c.getContext('2d'); x.save(); x.translate(sw / 2, sh / 2); x.rotate(-ROT * Math.PI / 180); x.drawImage(v, -W / 2, -H / 2, W, H); x.restore();
        id++; window.__nat.frames++; return `${PORTRAIT ? (ROT + 270) % 360 : ROT}|${id}|${sw}|${sh}|` + c.toDataURL('image/jpeg', 0.9).split(',')[1];
      },
      camStop() { window.__nat.stops++; },
    };
  }, +process.env.NATIVE === 1 ? 90 : +process.env.NATIVE, !!process.env.PORTRAIT);
  const errs = []; page.on('pageerror', (e) => errs.push('PAGEERR ' + e.message)); page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
  await page.goto('http://127.0.0.1:8765/index.html', { waitUntil: 'networkidle0' });
  await page.evaluate((o) => { localStorage.setItem('obyom.settings', JSON.stringify({ mode: o.mode, method: 'turn', size: 'A4', height: '90', quality: o.q, shape: 'normal', delay: '3', step: '8' })); if (o.pool) localStorage.setItem('obyom.pool', o.pool); else localStorage.removeItem('obyom.pool'); }, { q: process.env.Q || 'normal', mode: process.env.MODE || 'mesh', pool: process.env.POOL || '' });
  await page.reload({ waitUntil: 'networkidle0' });
  await page.click('#btnNew'); await sleep(300); await page.click('#btnStart');
  await sleep(1500);
  console.log('кнопка «Фон» видна:', await page.evaluate(() => !document.getElementById('capPlate').classList.contains('hidden')));
  await page.click('#capPause');
  const t0 = Date.now();
  while (Date.now() - t0 < 120000) { await sleep(2000); const d = await page.evaluate(() => document.getElementById('capDone').textContent); if (/· (3[6-9]|[4-9]\d)/.test(d)) break; }
  await page.screenshot({ path: SH + 'ep_cap.png' });
  await page.click('#capDone'); await sleep(600);
  await page.screenshot({ path: SH + 'ep_sheet.png' });
  console.log('лист:', await page.evaluate(() => document.querySelector('#sheetBody h3') && document.querySelector('#sheetBody h3').textContent));
  // подмена снимка фона: пустой коврик с того же места
  const b64 = fs.readFileSync(process.env.PLATE).toString('base64');
  await page.evaluate(async (b) => { const bin = Uint8Array.from(atob(b), (c) => c.charCodeAt(0)); const blob = new Blob([bin], { type: 'image/jpeg' }); window.__obyomCap.grab = async () => blob; }, b64);
  await page.click('[data-a="plate"]');
  const t1 = Date.now();
  while (Date.now() - t1 < 900000) {
    await sleep(4000);
    const s = await page.evaluate(() => ({ act: document.querySelector('.screen.active').id, st: document.getElementById('procStage').textContent }));
    if (s.act === 'view' || /Не получилось/.test(s.st)) break;
  }
  console.log(await page.evaluate(() => document.getElementById('procLog').textContent));
  await sleep(2500);
  await page.evaluate(() => { const b = document.getElementById('vAuto'); if (b.classList.contains('on')) b.click(); });
  await page.evaluate(() => document.querySelector('#vShade button[data-v="0"]').click()); await sleep(1200);
  console.log('переключатель текстуры виден:', await page.evaluate(() => !document.getElementById('vTex').classList.contains('hidden')));
  await page.screenshot({ path: SH + 'ep_viewTex.png' });
  await page.evaluate(() => document.querySelector('#vTex button[data-v="0"]').click()); await sleep(800);
  await page.screenshot({ path: SH + 'ep_viewVert.png' });
  await page.evaluate(() => document.querySelector('#vShade button[data-v="2"]').click()); await sleep(800);
  await page.screenshot({ path: SH + 'ep_viewClay.png' });
  console.log(await page.evaluate(() => document.getElementById('vSize').textContent + ' | ' + document.getElementById('vWarn').textContent));
  // экспорт GLB: проверим, что файл с текстурой собирается
  const glb = await page.evaluate(async () => { const m = await import('./js/export.js'); const s = window.__obyomScan; return s ? m.toGLB(s.mesh, 't').length : -1; });
  console.log('GLB байт:', glb);
  if (process.env.NATIVE) console.log('своя камера:', JSON.stringify(await page.evaluate(() => window.__nat)));
  if (errs.length) console.log(errs.join('\n'));
  await browser.close();
})().catch((e) => { console.log('FAIL', e); process.exit(1); });
