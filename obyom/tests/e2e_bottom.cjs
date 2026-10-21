// Сквозной тест «Доснять низ»: PHASE=A — обычная съёмка (камера CAM), PHASE=B — открыть скан → ⋯ → «Доснять низ» → вторая съёмка.
// Профиль браузера общий (/tmp/t/prof), чтобы скан из фазы A сохранился. Нужен сервер obyom/web на :8765.
// PHASE=A CAM=/tmp/t/camA.y4m node e2e_bottom.cjs; PHASE=B CAM=/tmp/t/camB.y4m SHAPE=normal node e2e_bottom.cjs
const puppeteer = require('puppeteer-core'); const chromium = (m => m.default || m)(require('@sparticuz/chromium'));
const SH = process.env.SH || '/home/user/shots/', PH = process.env.PHASE || 'A';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: true, userDataDir: '/tmp/t/prof',
    args: [...chromium.args.filter((a) => !a.startsWith('--user-data-dir') && a !== '--single-process'), '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-video-capture=${process.env.CAM}`, '--autoplay-policy=no-user-gesture-required', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const page = await browser.newPage(); await page.setViewport({ width: 400, height: 800, deviceScaleFactor: 1 });
  const errs = []; page.on('pageerror', (e) => errs.push('PAGEERR ' + e.message)); page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
  await page.goto('http://127.0.0.1:8765/index.html', { waitUntil: 'networkidle0' });
  const capture = async () => {
    await sleep(1500); await page.click('#capPause');
    const t0 = Date.now();
    while (Date.now() - t0 < 80000) { await sleep(2000); const d = await page.evaluate(() => document.getElementById('capDone').textContent); if (/· (2[6-9]|[3-9]\d)/.test(d)) break; }
    await page.screenshot({ path: SH + `eb_cap${PH}.png` });
    await page.click('#capDone');
    const t1 = Date.now();
    while (Date.now() - t1 < 500000) {
      await sleep(4000);
      const s = await page.evaluate(() => ({ act: document.querySelector('.screen.active').id, st: document.getElementById('procStage').textContent }));
      if (s.act === 'view' || /Не получилось/.test(s.st)) break;
    }
    console.log(await page.evaluate(() => document.getElementById('procLog').textContent));
    await sleep(1500);
  };
  if (PH === 'A') {
    await page.evaluate((o) => { localStorage.setItem('obyom.settings', JSON.stringify({ mode: 'mesh', method: 'walk', size: 'A4', height: '90', quality: 'fast', shape: o.shape, delay: '3', step: '10' })); }, { shape: process.env.SHAPE || 'normal' });
    await page.reload({ waitUntil: 'networkidle0' });
    await page.click('#btnNew'); await sleep(300); await page.screenshot({ path: SH + 'eb_setup.png' }); await page.click('#btnStart');
    await capture();
  } else {
    await page.click('#scanList button.card'); await sleep(1500);
    await page.click('#vMore'); await sleep(800); await page.screenshot({ path: SH + 'eb_more.png' });
    await page.click('[data-a="bottom"]'); await sleep(500);
    console.log('экран:', await page.evaluate(() => document.querySelector('.screen.active').id), '| сообщение:', await page.evaluate(() => document.getElementById('capMsg').className));
    await capture();
  }
  await page.evaluate(() => { const b = document.getElementById('vAuto'); if (b.classList.contains('on')) b.click(); });
  await page.evaluate(() => document.querySelector('#vShade button[data-v="2"]').click()); await sleep(600);
  await page.screenshot({ path: SH + `eb_view${PH}.png` });
  console.log(await page.evaluate(() => document.getElementById('vSize').textContent + ' | ' + document.getElementById('vWarn').textContent));
  if (errs.length) console.log(errs.join('\n'));
  await browser.close();
})().catch((e) => { console.log('FAIL', e); process.exit(1); });
