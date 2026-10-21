const puppeteer = require('puppeteer-core'); const chromium = (m => m.default || m)(require('@sparticuz/chromium'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms)); const SH = '/home/user/shots/';
(async () => {
  const W = +(process.env.VW || 360), H = +(process.env.VH || 720);
  const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: true, userDataDir: '/tmp/t/profU',
    args: [...chromium.args.filter((a) => !a.startsWith('--user-data-dir') && a !== '--single-process'), '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const page = await browser.newPage(); await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
  const errs = []; page.on('pageerror', (e) => errs.push('PAGEERR ' + e.message));
  await page.goto('http://127.0.0.1:8765/index.html', { waitUntil: 'networkidle0' });
  await page.evaluate(() => localStorage.setItem('obyom.settings', JSON.stringify({ mode: 'mesh', method: 'turn', size: 'A4', height: '90', quality: 'best', shape: 'normal', delay: '3', step: '8' })));
  // фальшивый скан: куб
  await page.evaluate(async () => { const st = await import('./js/store.js');
    const P = [], N = [], C = [], I = []; const v = [[-20,-20,0],[20,-20,0],[20,20,0],[-20,20,0],[-20,-20,40],[20,-20,40],[20,20,40],[-20,20,40]];
    v.forEach((p) => { P.push(...p); N.push(0,0,1); C.push(200,120,60); }); [[0,1,2],[0,2,3],[4,6,5],[4,7,6],[0,4,5],[0,5,1],[1,5,6],[1,6,2],[2,6,7],[2,7,3],[3,7,4],[3,4,0]].forEach((t) => I.push(...t));
    await st.putScan({ id: 'scan-1', name: 'Тест куб', date: Date.now(), settings: { mode: 'mesh', method: 'turn', size: 'A4', height: '90', quality: 'normal' }, mode: 'mesh', hasMesh: true, mesh: { pos: new Float32Array(P), nrm: new Float32Array(N), col: new Uint8Array(C), idx: new Uint32Array(I), uv: new Float32Array(16), tex: { w: 4, h: 4, jpg: new Uint8Array([1]) } }, stats: { used: 30, frames: 30, size: [40, 40, 40], volume: 64000, t: 10 } });
    await st.putFrames('scan-1', [new Blob([new Uint8Array(10)])]); });
  await page.reload({ waitUntil: 'networkidle0' });
  await page.screenshot({ path: SH + 'u_home.png' });
  await page.click('#scanList button.card'); await sleep(1500);
  await page.screenshot({ path: SH + 'u_view.png' });
  const r = await page.evaluate(() => { const o = {}; for (const id of ['vMore', 'vExp', 'vTex', 'vShade']) { const b = document.getElementById(id).getBoundingClientRect(); o[id] = [Math.round(b.left), Math.round(b.top), Math.round(b.right), Math.round(b.bottom)]; } o.H = innerHeight; o.W = innerWidth; return o; });
  console.log('view rects', JSON.stringify(r));
  await page.click('#vMore'); await sleep(800); await page.screenshot({ path: SH + 'u_more.png' });
  await page.evaluate(() => document.getElementById('sheetClose').click()); await sleep(300);
  await page.evaluate(() => history.back()); await sleep(500);
  await page.click('#btnNew'); await sleep(300); await page.screenshot({ path: SH + 'u_setup.png' });
  await page.click('#btnStart'); await sleep(3000); await page.screenshot({ path: SH + 'u_cap.png' });
  const c = await page.evaluate(() => { const o = {}; for (const id of ['capCancel', 'capPause', 'capShot', 'capPlate', 'capDone']) { const b = document.getElementById(id).getBoundingClientRect(); o[id] = [Math.round(b.left), Math.round(b.right)]; } return o; });
  console.log('cap rects', JSON.stringify(c));
  console.log(errs.join('\n'));
  await browser.close();
})().catch((e) => { console.log('FAIL', e); process.exit(1); });
