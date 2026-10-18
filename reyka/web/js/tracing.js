// «Калька»: обработка картинки без ИИ и вывод её на лист через WebGL с перспективой.
//  - Контур: детектор границ Кэнни (размытие → Собель → утончение → гистерезис).
//  - Тона: постеризация яркости на 2–6 уровней (видно, где светлое/тёмное).
//  - Ч/Б: просто яркость.

const MAX_SIDE = 1400;

export function imageToCanvas(img) {
  const w0 = img.naturalWidth || img.videoWidth || img.width;
  const h0 = img.naturalHeight || img.videoHeight || img.height;
  const k = Math.min(1, MAX_SIDE / Math.max(w0, h0));
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(w0 * k)); c.height = Math.max(1, Math.round(h0 * k));
  c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
  return c;
}

function grayOf(src) {
  const w = src.width, h = src.height;
  const d = src.getContext('2d').getImageData(0, 0, w, h).data;
  const g = new Float32Array(w * h), a = new Uint8Array(w * h);
  for (let i = 0, j = 0; i < w * h; i++, j += 4) {
    // прозрачные пиксели считаем белыми
    const al = d[j + 3] / 255;
    g[i] = (0.299 * d[j] + 0.587 * d[j + 1] + 0.114 * d[j + 2]) * al + 255 * (1 - al);
    a[i] = d[j + 3];
  }
  return { g, a, w, h };
}

function gaussian(src, w, h, sigma) {
  if (sigma < 0.3) return src.slice();
  const r = Math.ceil(sigma * 2.5), k = [];
  let s = 0;
  for (let i = -r; i <= r; i++) { const v = Math.exp(-(i * i) / (2 * sigma * sigma)); k.push(v); s += v; }
  for (let i = 0; i < k.length; i++) k[i] /= s;
  const tmp = new Float32Array(w * h), out = new Float32Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let acc = 0;
    for (let i = -r; i <= r; i++) { const xx = Math.min(w - 1, Math.max(0, x + i)); acc += src[y * w + xx] * k[i + r]; }
    tmp[y * w + x] = acc;
  }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let acc = 0;
    for (let i = -r; i <= r; i++) { const yy = Math.min(h - 1, Math.max(0, y + i)); acc += tmp[yy * w + x] * k[i + r]; }
    out[y * w + x] = acc;
  }
  return out;
}

function hexToRgb(hex) {
  const v = parseInt(hex.replace('#', ''), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

// detail 0..1 — сколько линий оставить; thick 1..4 — толщина; smooth — сглаживание.
export function edgesCanvas(src, { detail = 0.5, thick = 2, smooth = 1.4, color = '#ff2fd6' } = {}) {
  const { g, w, h } = grayOf(src);
  const b = gaussian(g, w, h, smooth);
  const mag = new Float32Array(w * h), dir = new Uint8Array(w * h);
  for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
    const i = y * w + x;
    const gx = -b[i - w - 1] - 2 * b[i - 1] - b[i + w - 1] + b[i - w + 1] + 2 * b[i + 1] + b[i + w + 1];
    const gy = -b[i - w - 1] - 2 * b[i - w] - b[i - w + 1] + b[i + w - 1] + 2 * b[i + w] + b[i + w + 1];
    mag[i] = Math.hypot(gx, gy);
    let a = Math.atan2(gy, gx) * 180 / Math.PI; if (a < 0) a += 180;
    dir[i] = a < 22.5 || a >= 157.5 ? 0 : a < 67.5 ? 1 : a < 112.5 ? 2 : 3;
  }
  // утончение (non-maximum suppression)
  const nms = new Float32Array(w * h);
  const vals = [];
  for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
    const i = y * w + x, m = mag[i];
    if (m < 4) continue;
    let a, c;
    switch (dir[i]) {
      case 0: a = mag[i - 1]; c = mag[i + 1]; break;
      case 1: a = mag[i - w - 1]; c = mag[i + w + 1]; break;
      case 2: a = mag[i - w]; c = mag[i + w]; break;
      default: a = mag[i - w + 1]; c = mag[i + w - 1];
    }
    if (m >= a && m >= c) { nms[i] = m; vals.push(m); }
  }
  const out = document.createElement('canvas');
  out.width = w; out.height = h;
  if (!vals.length) return out;
  vals.sort((p, q) => p - q);
  const keep = 0.04 + 0.42 * Math.max(0, Math.min(1, detail));
  const hi = vals[Math.min(vals.length - 1, Math.floor(vals.length * (1 - keep)))];
  const lo = hi * 0.45;
  // гистерезис
  const edge = new Uint8Array(w * h), stack = [];
  for (let i = 0; i < w * h; i++) if (nms[i] >= hi) { edge[i] = 1; stack.push(i); }
  while (stack.length) {
    const i = stack.pop(), y = (i / w) | 0, x = i - y * w;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      if (!dx && !dy) continue;
      const xx = x + dx, yy = y + dy;
      if (xx < 0 || yy < 0 || xx >= w || yy >= h) continue;
      const j = yy * w + xx;
      if (!edge[j] && nms[j] >= lo) { edge[j] = 1; stack.push(j); }
    }
  }
  // толщина
  const r = Math.max(0, Math.round(thick) - 1);
  const ctx = out.getContext('2d');
  const id = ctx.createImageData(w, h);
  const [cr, cg, cb] = hexToRgb(color);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let on = edge[y * w + x];
    if (!on && r) {
      for (let dy = -r; dy <= r && !on; dy++) for (let dx = -r; dx <= r; dx++) {
        if (dx * dx + dy * dy > r * r + r) continue;
        const xx = x + dx, yy = y + dy;
        if (xx >= 0 && yy >= 0 && xx < w && yy < h && edge[yy * w + xx]) { on = 1; break; }
      }
    }
    if (on) { const j = (y * w + x) * 4; id.data[j] = cr; id.data[j + 1] = cg; id.data[j + 2] = cb; id.data[j + 3] = 255; }
  }
  ctx.putImageData(id, 0, 0);
  return out;
}

export function tonesCanvas(src, { levels = 3, smooth = 1.6 } = {}) {
  const { g, a, w, h } = grayOf(src);
  const b = gaussian(g, w, h, smooth);
  const out = document.createElement('canvas');
  out.width = w; out.height = h;
  const ctx = out.getContext('2d');
  const id = ctx.createImageData(w, h);
  const L = Math.max(2, levels);
  for (let i = 0; i < w * h; i++) {
    const q = Math.min(L - 1, Math.floor(b[i] / 256 * L));
    const v = Math.round(q / (L - 1) * 255);
    const j = i * 4;
    id.data[j] = id.data[j + 1] = id.data[j + 2] = v; id.data[j + 3] = a[i];
  }
  ctx.putImageData(id, 0, 0);
  return out;
}

export function grayCanvas(src) {
  const { g, a, w, h } = grayOf(src);
  const out = document.createElement('canvas');
  out.width = w; out.height = h;
  const ctx = out.getContext('2d');
  const id = ctx.createImageData(w, h);
  for (let i = 0; i < w * h; i++) { const j = i * 4; id.data[j] = id.data[j + 1] = id.data[j + 2] = g[i]; id.data[j + 3] = a[i]; }
  ctx.putImageData(id, 0, 0);
  return out;
}

// --- WebGL-слой: рисует картинку с произвольной гомографией (честная перспектива) ---
export class KalkaLayer {
  constructor(canvas) {
    this.canvas = canvas;
    const gl = canvas.getContext('webgl', { premultipliedAlpha: true, alpha: true, antialias: false });
    this.gl = gl;
    this.ok = !!gl;
    if (!gl) return;
    const vs = `attribute vec2 p; void main(){ gl_Position = vec4(p, 0.0, 1.0); }`;
    const fs = `precision highp float;
      uniform mat3 uInv; uniform sampler2D uTex; uniform float uAlpha; uniform vec4 uCrop;
      void main(){
        vec3 q = uInv * vec3(gl_FragCoord.xy, 1.0);
        if (q.z <= 0.0) discard;
        vec2 uv = q.xy / q.z;
        if (uv.x < uCrop.x || uv.y < uCrop.y || uv.x > uCrop.z || uv.y > uCrop.w) discard;
        vec4 c = texture2D(uTex, uv);
        float a = c.a * uAlpha;
        gl_FragColor = vec4(c.rgb * a, a);
      }`;
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
    const pr = gl.createProgram();
    gl.attachShader(pr, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(pr);
    this.pr = pr;
    gl.useProgram(pr);
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(pr, 'p');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    this.uInv = gl.getUniformLocation(pr, 'uInv');
    this.uAlpha = gl.getUniformLocation(pr, 'uAlpha');
    this.uCrop = gl.getUniformLocation(pr, 'uCrop');
    this.tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    this.hasTex = false;
  }

  setImage(canvas) {
    if (!this.ok) return;
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
    this.hasTex = true;
  }

  clear() {
    if (!this.ok) return;
    const gl = this.gl;
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
  }

  // inv — матрица (row-major) «пиксель WebGL → uv картинки».
  draw(inv, alpha, crop = [0, 0, 1, 1]) {
    this.clear();
    if (!this.ok || !this.hasTex || !inv) return;
    const gl = this.gl;
    gl.useProgram(this.pr);
    // GLSL ждёт column-major → транспонируем
    const m = inv;
    gl.uniformMatrix3fv(this.uInv, false, new Float32Array([m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8]]));
    gl.uniform1f(this.uAlpha, alpha);
    gl.uniform4f(this.uCrop, crop[0], crop[1], crop[2], crop[3]);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
}
