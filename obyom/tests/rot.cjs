const chromium = (m => m.default || m)(require('@sparticuz/chromium'));
const puppeteer = require('puppeteer-core');
(async () => {
  const b = await puppeteer.launch({ executablePath: await chromium.executablePath(), headless: true, args: [...chromium.args, '--user-data-dir=/tmp/t/profR'] });
  const p = await b.newPage(); p.on('pageerror', e => console.log('ERR', e.message)); p.on('console', m => console.log('LOG', m.text()));
  await p.evaluateOnNewDocument(() => {
    // подставная нативная камера: «сенсорный» кадр = вертикальная картинка, повёрнутая против часовой на ROT
    let id = 0; window.__ROT = 90;
    const up = document.createElement('canvas'); up.width = 1280; up.height = 720;
    window.ObyomNative = {
      camStart() { const x = up.getContext('2d'); x.fillStyle = '#00f'; x.fillRect(0, 0, 1280, 720); x.fillStyle = '#f00'; x.fillRect(0, 0, 200, 150); x.fillStyle = '#0f0'; x.fillRect(1080, 570, 200, 150); return 'ok'; },
      camFrame(last) {
        const R = window.__ROT, sw = R % 180 ? 720 : 1280, sh = R % 180 ? 1280 : 720, c = document.createElement('canvas'); c.width = sw; c.height = sh;
        const x = c.getContext('2d'); x.translate(sw / 2, sh / 2); x.rotate(-R * Math.PI / 180); x.drawImage(up, -640, -360); id++;
        return `${R}|${id}|${sw}|${sh}|` + c.toDataURL('image/jpeg', 0.95).split(',')[1];
      },
      camStop() {},
    };
  });
  await p.goto('http://localhost:8765/index.html');
  const out = await p.evaluate(async () => {
    const { NativeCam } = await import('./js/nativecam.js'), res = {};
    for (const R of [0, 90, 180, 270]) {
      window.__ROT = R; const cam = new NativeCam(null); await cam.open(); await new Promise(r => setTimeout(r, 200));
      const c = document.createElement('canvas'); c.width = cam.videoWidth; c.height = cam.videoHeight; const x = c.getContext('2d'); cam.drawTo(x, c.width, c.height);
      const px = (X, Y) => Array.from(x.getImageData(X, Y, 1, 1).data.slice(0, 3)).map(v => v > 128 ? 1 : 0).join('');
      res[R] = { w: cam.videoWidth, h: cam.videoHeight, tl: px(50, 50), br: px(1230, 670), mid: px(640, 360), fps: +cam.fps.toFixed(0) }; cam.close();
    }
    return res;
  });
  console.log(JSON.stringify(out)); await b.close();
})();
