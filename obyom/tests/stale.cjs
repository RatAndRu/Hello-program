const chromium = (m => m.default || m)(require('@sparticuz/chromium'));
const puppeteer = require('puppeteer-core');
(async () => {
  const b = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: true,
    args: [...chromium.args, '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--use-file-for-fake-video-capture=' + process.env.CAM, '--user-data-dir=/tmp/t/profS'] });
  const p = await b.newPage(); p.on('pageerror', e => console.log('ERR', e.message));
  await p.goto('http://localhost:8765/index.html');
  const out = await p.evaluate(async () => {
    const { Capture } = await import('./js/capture.js');
    const v = document.createElement('video'), ov = document.createElement('canvas'); document.body.append(v, ov);
    const log = []; let opens = 0;
    const gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = (c) => { opens++; return gum(c); };
    const c = new Capture(v, ov, { size: 'A4', method: 'turn', onState: (st) => log.push([Math.round(performance.now()), st.stale || 0, st.markers, st.found]) });
    await c.start(); c.arm(0);
    await new Promise(r => setTimeout(r, 11000)); c.stop();
    return { opens, n: log.length, stale: log.filter(x => x[1]).length, maxStale: Math.max(...log.map(x => x[1])), last: log.slice(-3), first: log.slice(0, 3), vw: v.videoWidth };
  });
  console.log(JSON.stringify(out)); await b.close();
})();
