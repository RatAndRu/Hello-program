// доля кадров слежения с найденной позой: подставная своя камера, PORTRAIT=1 — вертикальный кадр
const chromium = (m => m.default || m)(require('@sparticuz/chromium'));
const puppeteer = require('puppeteer-core');
(async () => {
  const b = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: true,
    args: [...chromium.args, '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--use-file-for-fake-video-capture=' + process.env.CAM, '--user-data-dir=/tmp/t/profF'] });
  const p = await b.newPage(); p.on('pageerror', e => console.log('ERR', e.message));
  await p.evaluateOnNewDocument((PORTRAIT) => {
    let v = null, id = 0, lastT = 0, starting = false; const c = document.createElement('canvas'), ROT = 90;
    async function init() { starting = true; const st = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 } }); v = document.createElement('video'); v.muted = true; v.srcObject = st; await v.play(); }
    window.ObyomNative = {
      camStart() { if (!starting) init(); return 'ok'; },
      camFrame() {
        if (!v || !v.videoWidth) return ''; const now = performance.now(); if (now - lastT < 50) return ''; lastT = now;
        const W = v.videoWidth, H = v.videoHeight, sw = H, sh = W; c.width = sw; c.height = sh;
        const x = c.getContext('2d'); x.save(); x.translate(sw / 2, sh / 2); x.rotate(-ROT * Math.PI / 180); x.drawImage(v, -W / 2, -H / 2, W, H); x.restore();
        id++; return `${PORTRAIT ? 0 : 90}|${id}|${sw}|${sh}|` + c.toDataURL('image/jpeg', 0.9).split(',')[1];
      },
      camStop() {},
    };
  }, !!process.env.PORTRAIT);
  await p.goto('http://localhost:8765/index.html');
  const out = await p.evaluate(async (method) => {
    const { Capture } = await import('./js/capture.js');
    const v = document.createElement('video'), ov = document.createElement('canvas'); document.body.append(v, ov);
    const log = [];
    const c = new Capture(v, ov, { size: 'A4', method, onState: (st) => log.push(st) });
    await c.start(); c.arm(0);
    await new Promise(r => setTimeout(r, 15000)); c.stop();
    const withM = log.filter(s => s.markers >= 2), found = log.filter(s => s.found);
    const rms = withM.map(s => s.poseRms).filter(x => x != null).sort((a, b) => a - b);
    return { states: log.length, withMarkers: withM.length, found: found.length, shots: c.shots.length, medRms: rms[rms.length >> 1], f: c.f && Math.round(c.f), w: log.at(-1).w, h: log.at(-1).h, why: log.at(-1).why };
  }, process.env.METHOD || 'turn');
  console.log(JSON.stringify(out)); await b.close();
})();
