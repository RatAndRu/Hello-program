const puppeteer = require('puppeteer-core'); const chromium = (m => m.default || m)(require('@sparticuz/chromium'));
const fs = require('fs'); const SH = process.env.SH || '/home/user/Hello-program/.cache/shots/';
(async () => {
  const browser = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: true,
    args: [...chromium.args, '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--use-file-for-fake-video-capture=/tmp/t/cam.y4m', '--autoplay-policy=no-user-gesture-required', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const page = await browser.newPage(); await page.setViewport({ width: 400, height: 800, deviceScaleFactor: 1 });
  const logs = []; page.on('console', m => logs.push(m.type() + ': ' + m.text())); page.on('pageerror', e => logs.push('PAGEERR ' + e.message));
  const cdp = await page.target().createCDPSession(); await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: '/tmp/t/dl' }).catch(async () => { await cdp.send('Page.setDownloadBehavior', { behavior: 'allow', downloadPath: '/tmp/t/dl' }); });
  await page.goto('http://127.0.0.1:8765/index.html', { waitUntil: 'networkidle0' });
  await page.evaluate((shape) => { localStorage.setItem('obyom.settings', JSON.stringify({ mode: 'both', method: 'walk', size: 'A4', height: '90', quality: 'fast', shape })); localStorage.setItem('obyom.cal', JSON.stringify({ A4: { sx: 1.02, sy: 1.0 } })); }, process.env.SHAPE || 'normal');
  await page.reload({ waitUntil: 'networkidle0' });
  await page.screenshot({ path: SH + 'e_home.png' });
  await page.click('#btnNew'); await new Promise(r => setTimeout(r, 300)); await page.screenshot({ path: SH + 'e_setup.png' });
  await page.click('#btnStart');
  const t0 = Date.now(); let shot = false;
  while (Date.now() - t0 < 70000) {
    await new Promise(r => setTimeout(r, 2000));
    const s = await page.evaluate(() => ({ msg: document.getElementById('capMsg').textContent, info: document.getElementById('capInfo').textContent, done: document.getElementById('capDone').textContent }));
    console.log(((Date.now() - t0) / 1000).toFixed(0), s.done, '|', s.msg, '|', s.info);
    if (!shot && /· (1[2-9]|[2-9]\d)/.test(s.done)) { await page.screenshot({ path: SH + 'e_cap.png' }); shot = true; }
    if (/· (2[6-9]|[3-9]\d)/.test(s.done)) break;
  }
  await page.screenshot({ path: SH + 'e_cap2.png' });
  await page.click('#capDone');
  const t1 = Date.now(); let pshot = false;
  while (Date.now() - t1 < 400000) {
    await new Promise(r => setTimeout(r, 5000));
    const s = await page.evaluate(() => ({ act: document.querySelector('.screen.active').id, st: document.getElementById('procStage').textContent, tx: document.getElementById('procText').textContent }));
    console.log('P', ((Date.now() - t1) / 1000).toFixed(0), s.act, s.st, s.tx);
    if (!pshot && /сплэты/.test(s.st)) { await new Promise(r => setTimeout(r, 15000)); await page.screenshot({ path: SH + 'e_proc.png' }); pshot = true; }
    if (s.act === 'view' || /Не получилось/.test(s.st)) break;
  }
  console.log((await page.evaluate(() => document.getElementById('procLog').textContent)));
  await new Promise(r => setTimeout(r, 1500));
  await page.evaluate(() => { document.getElementById('vAuto').click(); });
  await page.screenshot({ path: SH + 'e_view_mesh.png' });
  await page.evaluate(() => document.querySelector('#vShade button[data-v="2"]').click()); await new Promise(r => setTimeout(r, 500)); await page.screenshot({ path: SH + 'e_view_clay.png' });
  await page.evaluate(() => document.querySelector('#vShow button[data-v="splat"]').click()); await new Promise(r => setTimeout(r, 1500)); await page.screenshot({ path: SH + 'e_view_splat.png' });
  // экспорт всех форматов
  await page.click('#vExp'); await new Promise(r => setTimeout(r, 400)); await page.screenshot({ path: SH + 'e_export.png' });
  for (const k of ['glb', 'obj', 'ply', 'stl', 'splat']) { await page.evaluate((k) => document.querySelector(`#sheetBody button[data-k="${k}"]`).click(), k); await new Promise(r => setTimeout(r, 1500)); }
  await page.click('#sheetClose');
  // коврик PDF
  await page.evaluate(() => { history.back(); }); await new Promise(r => setTimeout(r, 800));
  await page.click('#btnMat'); await new Promise(r => setTimeout(r, 300));
  await page.screenshot({ path: SH + 'e_mat.png' });
  await page.evaluate(() => document.querySelector('#sheetBody button[data-m="pdf:A4:full"]').click()); await new Promise(r => setTimeout(r, 6000));
  await page.evaluate(() => document.getElementById('btnCal').click()); await new Promise(r => setTimeout(r, 300));
  await page.screenshot({ path: SH + 'e_cal.png' });
  await page.click('#sheetClose'); await new Promise(r => setTimeout(r, 500));
  await page.screenshot({ path: SH + 'e_home2.png' });
  console.log('DL', fs.readdirSync('/tmp/t/dl').map(f => f + ' ' + fs.statSync('/tmp/t/dl/' + f).size).join(', '));
  console.log(logs.slice(-25).join('\n'));
  await browser.close();
})().catch(e => { console.error('FAIL', e); process.exit(1); });
