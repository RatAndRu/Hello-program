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

// Демо: стол, лист A4 в лёгкой перспективе, который чуть «гуляет», и рука с карандашом.
export function createDemoStream(portrait = false) {
  const W = portrait ? 720 : 1280, H = portrait ? 1280 : 720;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const g = c.getContext('2d');

  // Текстура стола один раз.
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

  let raf = 0, t0 = performance.now();
  const draw = () => {
    const t = (performance.now() - t0) / 1000;
    g.drawImage(table, 0, 0);
    const cx = W / 2 + Math.sin(t * 0.25) * 30, cy = H / 2 + Math.cos(t * 0.2) * 14;
    const ang = -0.09 + Math.sin(t * 0.18) * 0.06;
    const pw = (portrait ? 210 : 297) * 1.6, ph = (portrait ? 297 : 210) * 1.6; // A4
    const pers = 0.06;
    const pts = [[-pw / 2 * (1 - pers), -ph / 2], [pw / 2 * (1 - pers), -ph / 2], [pw / 2, ph / 2], [-pw / 2, ph / 2]]
      .map(([x, y]) => [cx + x * Math.cos(ang) - y * Math.sin(ang), cy + x * Math.sin(ang) + y * Math.cos(ang)]);
    // тень
    g.fillStyle = 'rgba(0,0,0,0.35)';
    g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(x + 8, y + 10) : g.moveTo(x + 8, y + 10)); g.closePath(); g.fill();
    // лист
    const pg = g.createLinearGradient(pts[0][0], pts[0][1], pts[2][0], pts[2][1]);
    pg.addColorStop(0, '#f4f2ec'); pg.addColorStop(1, '#dcd8cf');
    g.fillStyle = pg;
    g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); g.closePath(); g.fill();
    // карандашный набросок
    g.save();
    g.translate(cx, cy); g.rotate(ang); if (portrait) g.scale(0.8, 0.8);
    g.strokeStyle = 'rgba(60,60,70,0.55)'; g.lineWidth = 1.6;
    g.beginPath(); g.ellipse(-60, 10, 70, 46, 0.2, 0, Math.PI * 2); g.stroke();
    g.beginPath(); g.moveTo(-180, 90); g.lineTo(60, -40); g.lineTo(170, 70); g.stroke();
    g.restore();
    // рука с карандашом
    const hx = cx + 120 + Math.sin(t * 0.9) * 90, hy = cy + 40 + Math.cos(t * 0.7) * 50;
    g.save();
    g.translate(hx, hy); g.rotate(0.7);
    g.fillStyle = '#5c4632';
    g.fillRect(-14, -6, 160, 12); // карандаш
    g.fillStyle = '#c69c7d';
    g.beginPath(); g.ellipse(120, 30, 70, 48, 0.3, 0, Math.PI * 2); g.fill();
    g.fillRect(150, 30, 400, 90); // предплечье уходит за кадр
    g.restore();
    raf = requestAnimationFrame(draw);
  };
  draw();
  const stream = c.captureStream(30);
  return { stream, track: stream.getVideoTracks()[0], stop: () => { cancelAnimationFrame(raf); stream.getTracks().forEach(t => t.stop()); }, demo: true };
}
