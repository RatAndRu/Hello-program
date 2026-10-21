// Объём — печать коврика: PDF ровно A4/A3/A2 (картинка 300/250/180 dpi внутри) и PNG.
// Разрешение для больших листов ниже — иначе холст не помещается в память телефона.
import { matLayout, drawMatCanvas } from './mat.js';

const DPI = { A4: 300, A3: 250, A2: 180 };
export function matCanvas(size = 'A4', theme = 'light', dpi = DPI[size] || 300, variant = 'full') {
  const L = matLayout(size, variant), ppm = dpi / 25.4;
  const c = document.createElement('canvas'); c.width = Math.round(L.W * ppm); c.height = Math.round(L.H * ppm);
  drawMatCanvas(c.getContext('2d'), L, theme, ppm);
  return { canvas: c, L };
}
const blobOf = (c, type, q) => new Promise((r) => c.toBlob(r, type, q));

export async function matPDF(size = 'A4', theme = 'light', variant = 'full') {
  const { canvas, L } = matCanvas(size, theme, undefined, variant);
  const jpg = new Uint8Array(await (await blobOf(canvas, 'image/jpeg', 0.95)).arrayBuffer());
  const Wpt = L.W / 25.4 * 72, Hpt = L.H / 25.4 * 72;
  const enc = new TextEncoder(), parts = [], offs = [];
  let len = 0; const push = (b) => { if (typeof b === 'string') b = enc.encode(b); parts.push(b); len += b.length; };
  push('%PDF-1.4\n%\xE2\xE3\xCF\xD3\n');
  const obj = (n, body) => { offs[n] = len; push(`${n} 0 obj\n`); for (const b of body) push(b); push('\nendobj\n'); };
  const content = `q ${Wpt.toFixed(2)} 0 0 ${Hpt.toFixed(2)} 0 0 cm /Im0 Do Q`;
  obj(1, ['<< /Type /Catalog /Pages 2 0 R /ViewerPreferences << /PrintScaling /None >> >>']);
  obj(2, ['<< /Type /Pages /Kids [3 0 R] /Count 1 >>']);
  obj(3, [`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${Wpt.toFixed(2)} ${Hpt.toFixed(2)}] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>`]);
  obj(4, [`<< /Type /XObject /Subtype /Image /Width ${canvas.width} /Height ${canvas.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpg.length} >>\nstream\n`, jpg, '\nendstream']);
  obj(5, [`<< /Length ${content.length} >>\nstream\n${content}\nendstream`]);
  const xref = len;
  let x = `xref\n0 6\n0000000000 65535 f \n`; for (let i = 1; i <= 5; i++) x += String(offs[i]).padStart(10, '0') + ' 00000 n \n';
  push(x + `trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
  const out = new Uint8Array(len); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}
export async function matPNG(size = 'A4', theme = 'light', variant = 'full') {
  const { canvas } = matCanvas(size, theme, undefined, variant);
  return new Uint8Array(await (await blobOf(canvas, 'image/png')).arrayBuffer());
}
