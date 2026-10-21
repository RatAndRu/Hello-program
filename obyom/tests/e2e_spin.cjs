// Автосъёмка на «вертушке»: поддельная камера крутит сцену с затуханием (scene.py spin + FPS=10 mkcam.py).
// Проверяем: таймер старта, кадры по углу поворота, реже при замедлении, без ограничения количества.
const puppeteer = require('puppeteer-core'); const chromium = (m => m.default || m)(require('@sparticuz/chromium'));
(async () => {
  const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: true,
    args: [...chromium.args, '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--use-file-for-fake-video-capture=/tmp/t/cam.y4m', '--autoplay-policy=no-user-gesture-required'] });
  const page = await browser.newPage(); await page.setViewport({ width: 400, height: 800 });
  const logs = []; page.on('pageerror', e => logs.push('PAGEERR ' + e.message));
  await page.goto('http://127.0.0.1:8765/index.html', { waitUntil: 'networkidle0' });
  await page.evaluate(() => localStorage.setItem('obyom.settings', JSON.stringify({ mode: 'mesh', method: 'turn', size: 'A4', height: '90', quality: 'fast', delay: '3', step: '8' })));
  await page.reload({ waitUntil: 'networkidle0' });
  await page.click('#btnNew'); await new Promise(r => setTimeout(r, 300)); await page.click('#btnStart');
  await new Promise(r => setTimeout(r, 1500)); await page.click('#capPause');
  const t0 = Date.now();
  while (Date.now() - t0 < 14000) {
    await new Promise(r => setTimeout(r, 700));
    const s = await page.evaluate(() => ({ msg: document.getElementById('capMsg').textContent, info: document.getElementById('capInfo').textContent.replace(/\n/g, ' | '), done: document.getElementById('capDone').textContent }));
    console.log(((Date.now() - t0) / 1000).toFixed(1), s.done, '|', s.msg, '|', s.info);
  }
  const shots = await page.evaluate(() => window.__obyomCap ? window.__obyomCap.shots.map(s => [s.az == null ? null : +s.az.toFixed(0), s.blind ? 'b' : '']) : null);
  console.log('SHOTS', JSON.stringify(shots));
  console.log(logs.join('\n'));
  await browser.close();
})().catch(e => { console.error('FAIL', e); process.exit(1); });
