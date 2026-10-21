// v2.1: обработка прервалась (приложение закрыли / выгрузили) → при запуске лист «Обработка прервалась» с продолжением.
// node tresume.cjs   (сервер obyom/web на :8765)
const puppeteer = require('puppeteer-core'); const chromium = (m => m.default || m)(require('@sparticuz/chromium'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: true, args: chromium.args.filter((a) => !a.startsWith('--user-data-dir') && a !== '--single-process') });
  const page = await browser.newPage(); await page.setViewport({ width: 400, height: 800 });
  const errs = []; page.on('pageerror', (e) => errs.push(e.message));
  await page.goto('http://127.0.0.1:8765/index.html', { waitUntil: 'networkidle0' });
  await page.evaluate(async () => {
    const st = await import('/js/store.js');
    const settings = { mode: 'mesh', method: 'turn', size: 'A4', height: '90', quality: 'fast', shape: 'normal', delay: '3', step: '8', torch: 'off' };
    const jpg = await new Promise((r) => { const c = document.createElement('canvas'); c.width = 8; c.height = 8; c.toBlob(r, 'image/jpeg'); }); await st.putFrames('scan-t1', [jpg, jpg]);
    await st.putScan({ id: 'scan-t1', name: 'Тест прерывания', date: Date.now(), settings, failed: 'Обработка не закончилась', hasMesh: false, hasSplats: false });
    localStorage.setItem('obyom.pending', JSON.stringify({ id: 'scan-t1', name: 'Тест прерывания', settings, noB: true, t: Date.now() }));
  });
  await page.reload({ waitUntil: 'networkidle0' }); await sleep(1200);
  const h = await page.evaluate(() => { const e = document.querySelector('#sheetBody h3'); return e && e.textContent; });
  const p = await page.evaluate(() => { const e = document.querySelector('#sheetBody p'); return e && e.textContent; });
  console.log('лист:', h, '|', p);
  const pend = await page.evaluate(() => localStorage.getItem('obyom.pending'));
  console.log('пометка снята:', pend === null);
  // «Продолжить»: два пустых кадра → обработка запускается и честно говорит, что не вышло
  await page.click('#sheetBody [data-a="go"]'); await sleep(4000);
  console.log('после «Продолжить»:', await page.evaluate(() => document.querySelector('.screen.active').id + ': ' + document.getElementById('procStage').textContent));
  await page.reload({ waitUntil: 'networkidle0' }); await sleep(800);
  console.log('повторно лист не показан:', await page.evaluate(() => document.getElementById('sheet').classList.contains('hidden')));
  console.log(errs.length ? 'ОШИБКИ: ' + errs.join('; ') : 'ошибок нет');
  await browser.close();
  if (h !== 'Обработка прервалась' || pend !== null || errs.length) process.exit(1);
})();
