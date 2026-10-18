// Камера и демо-источник (нарисованный стол с листом, если камеры нет).

export async function startCamera(deviceId) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new Error('Браузер не даёт доступ к камере (нужен HTTPS или приложение).');
  }
  const video = {
    width: { ideal: 1920 },
    height: { ideal: 1080 },
    frameRate: { ideal: 30 },
  };
  if (deviceId) video.deviceId = { exact: deviceId };
  else video.facingMode = { ideal: 'environment' };
  const stream = await navigator.mediaDevices.getUserMedia({ audio: false, video });
  const track = stream.getVideoTracks()[0];
  // Непрерывная автофокусировка, если камера умеет.
  try {
    const caps = track.getCapabilities ? track.getCapabilities() : {};
    if (caps.focusMode && caps.focusMode.includes('continuous')) {
      await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
    }
  } catch { /* не критично */ }
  return { stream, track, stop: () => stream.getTracks().forEach(t => t.stop()) };
}

export async function listCameras() {
  try {
    const devs = await navigator.mediaDevices.enumerateDevices();
    return devs.filter(d => d.kind === 'videoinput');
  } catch { return []; }
}

export function trackCaps(track) {
  try { return track && track.getCapabilities ? track.getCapabilities() : {}; } catch { return {}; }
}

export async function setTorch(track, on) {
  await track.applyConstraints({ advanced: [{ torch: !!on }] });
}

export async function setZoom(track, z) {
  await track.applyConstraints({ advanced: [{ zoom: z }] });
}

// Демо: стол, лист A4 в настоящей перспективе (наклон камеры tilt°), цветной рисунок
// и рука с карандашом. Лист чуть «гуляет», чтобы было видно слежение.
export function createDemoStream(portrait = false, tilt = 0) {
  const W = portrait ? 720 : 1280, H = portrait ? 1280 : 720;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const g = c.getContext('2d');
  let handOn = true;

  const table = document.createElement('canvas');
  table.width = W; table.height = H;
  const tg = table.getContext('2d');
  const grad = tg.createLinearGradient(0, 0, W, H);
  grad.addColorStop(0, '#4a3020'); grad.addColorStop(1, '#2b1a10');
  tg.fillStyle = grad; tg.fillRect(0, 0, W, H);
  for (let i = 0; i < 140; i++) {
    tg.strokeStyle = `rgba(${20 + Math.random() * 40},${10 + Math.random() * 20},0,${0.15 + Math.random() * 0.2})`;
    tg.lineWidth = 1 + Math.random() * 3;
    tg.beginPath();
    const y = Math.random() * H;
    tg.moveTo(0, y);
    for (let x = 0; x <= W; x += 80) tg.lineTo(x, y + Math.sin(x / 140 + i) * 6);
    tg.stroke();
  }

  // Рисунок на листе — в мм листа (книжный A4 210×297).
  const pw = 210, ph = 297;
  const f = 0.78 * Math.max(W, H);
  const t = tilt * Math.PI / 180;
  let raf = 0; const t0 = performance.now();
  const draw = () => {
    const tm = (performance.now() - t0) / 1000;
    g.drawImage(table, 0, 0);
    const yaw = (portrait ? 0 : Math.PI / 2) + 0.08 + Math.sin(tm * 0.18) * 0.05;
    const size = (portrait ? 2.55 : 2.0);
    const d = f / size;
    const cx = W / 2 + Math.sin(tm * 0.25) * 20, cy = H / 2 + Math.cos(tm * 0.2) * 10;
    // проекция точки листа (мм) в кадр
    const P = (x, y) => {
      const X0 = x - pw / 2, Y0 = y - ph / 2;
      const X = X0 * Math.cos(yaw) - Y0 * Math.sin(yaw), Y = X0 * Math.sin(yaw) + Y0 * Math.cos(yaw);
      const Z = d - Y * Math.sin(t);
      return [cx + f * X / Z, cy + f * Y * Math.cos(t) / Z];
    };
    const path = (pts, close) => { g.beginPath(); pts.forEach(([x, y], i) => { const [u, v] = P(x, y); i ? g.lineTo(u, v) : g.moveTo(u, v); }); if (close) g.closePath(); };
    const circ = (x0, y0, r, n = 48) => { const a = []; for (let i = 0; i < n; i++) a.push([x0 + Math.cos(i / n * 6.283) * r, y0 + Math.sin(i / n * 6.283) * r]); return a; };
    const corners = [[0, 0], [pw, 0], [pw, ph], [0, ph]];
    g.fillStyle = 'rgba(0,0,0,0.35)';
    g.beginPath(); corners.forEach(([x, y], i) => { const [u, v] = P(x, y); i ? g.lineTo(u + 7, v + 9) : g.moveTo(u + 7, v + 9); }); g.closePath(); g.fill();
    const [ax, ay] = P(0, 0), [bx, by] = P(pw, ph);
    const pg = g.createLinearGradient(ax, ay, bx, by);
    pg.addColorStop(0, '#f4f2ec'); pg.addColorStop(1, '#d8d4ca');
    g.fillStyle = pg; path(corners, true); g.fill();
    // краска
    g.fillStyle = '#f2c230'; path(circ(160, 55, 22), true); g.fill();           // солнце
    g.fillStyle = '#d9483b'; path([[40, 140], [105, 85], [170, 140]], true); g.fill(); // крыша
    g.fillStyle = '#4f9ad6'; path([[85, 170], [125, 170], [125, 200], [85, 200]], true); g.fill(); // окно
    g.fillStyle = '#5bb34a'; path([[10, 245], [200, 238], [200, 285], [10, 285]], true); g.fill(); // трава
    // карандашные линии
    g.strokeStyle = 'rgba(45,45,55,0.9)'; g.lineWidth = 2.2; g.lineJoin = 'round';
    path([[40, 140], [105, 85], [170, 140]], false); g.stroke();
    path([[55, 140], [155, 140], [155, 240], [55, 240]], true); g.stroke();
    path([[85, 170], [125, 170], [125, 200], [85, 200]], true); g.stroke();
    path([[95, 240], [95, 205], [115, 205], [115, 240]], false); g.stroke();
    path(circ(160, 55, 22), true); g.stroke();
    for (let i = 0; i < 8; i++) { const a = i / 8 * 6.283; path([[160 + Math.cos(a) * 28, 55 + Math.sin(a) * 28], [160 + Math.cos(a) * 38, 55 + Math.sin(a) * 38]]); g.stroke(); }
    path([[10, 245], [60, 240], [120, 246], [200, 238]]); g.stroke();
    if (handOn) {
      const [hx0, hy0] = P(150 + Math.sin(tm * 0.9) * 30, 200 + Math.cos(tm * 0.7) * 30);
      g.save(); g.translate(hx0, hy0); g.rotate(0.7);
      g.fillStyle = '#5c4632'; g.fillRect(-14, -6, 160, 12);
      g.fillStyle = '#c69c7d'; g.beginPath(); g.ellipse(120, 30, 70, 48, 0.3, 0, Math.PI * 2); g.fill();
      g.fillRect(150, 30, 400, 90);
      g.restore();
    }
    raf = requestAnimationFrame(draw);
  };
  draw();
  const stream = c.captureStream(30);
  return { stream, track: stream.getVideoTracks()[0], stop: () => { cancelAnimationFrame(raf); stream.getTracks().forEach(tr => tr.stop()); }, demo: true, setHand: (v) => { handOn = v; } };
}
