// Объём — просмотр 3D: сетка и сплэты (WebGL2). Мир: миллиметры, Z вверх.
import { splatInfo } from './splat.js';

const MESH_VS = `#version 300 es
layout(location=0) in vec3 aPos; layout(location=1) in vec3 aNrm; layout(location=2) in vec3 aCol; layout(location=3) in vec2 aUV; layout(location=4) in vec4 aTan;
uniform mat4 uVP; out vec3 vN; out vec3 vC; out vec3 vP; out vec2 vUV; out vec4 vT;
void main(){ vN=aNrm; vC=aCol; vP=aPos; vUV=aUV; vT=aTan; gl_Position=uVP*vec4(aPos,1.0); }`;
// uMode: 0 — цвет без света, 1 — свет (PBR: GGX, карты нормалей и ORM), 2 — глина (без цвета, с рельефом)
// uMat: −1 — материал из карт (авто), 0 — мат, 1 — глянец, 2 — металл
const MESH_FS = `#version 300 es
precision highp float; in vec3 vN; in vec3 vC; in vec3 vP; in vec2 vUV; in vec4 vT;
uniform int uMode; uniform int uTexOn; uniform sampler2D uTex; uniform vec3 uEye;
uniform int uPbr; uniform sampler2D uNrm; uniform sampler2D uOrm; uniform float uRelief; uniform int uMat; out vec4 o;
uniform int uMap; uniform sampler2D uHgt; // v2.2: показать саму карту (1 нормали, 2 высота, 3 шероховатость, 4 металл, 5 затенение)
const float PI=3.14159265;
vec3 light(vec3 n, vec3 v, vec3 L, vec3 rad, vec3 base, float rough, float metal){
  float NdL=max(dot(n,L),0.0); if(NdL<=0.0) return vec3(0.0);
  vec3 h=normalize(v+L); float NdV=max(dot(n,v),1e-3), NdH=max(dot(n,h),0.0), VdH=max(dot(v,h),0.0);
  float a=rough*rough, a2=a*a, dd=NdH*NdH*(a2-1.0)+1.0, D=a2/(PI*dd*dd);
  float k=(rough+1.0)*(rough+1.0)/8.0, G=NdV/(NdV*(1.0-k)+k)*NdL/(NdL*(1.0-k)+k);
  vec3 F0=mix(vec3(0.04),base,metal), F=F0+(1.0-F0)*pow(1.0-VdH,5.0);
  vec3 spec=D*G*F/(4.0*NdL*NdV+1e-4), kd=(1.0-F)*(1.0-metal);
  return (kd*base/PI+spec)*rad*NdL;
}
// студийное окружение (без файлов): пол — горизонт — небо и софтбокс со стороны основной лампы; шероховатость размывает
vec3 env(vec3 R, vec3 L1, float rg){
  float w=0.08+0.5*rg, z=R.z;
  float g=mix(0.10, 0.62, smoothstep(-0.25-w, 0.02+w, z)); g=mix(g, 1.0, 0.55*smoothstep(0.1, 0.95, z));
  float sb=pow(max(dot(R,L1),0.0), mix(90.0, 2.5, rg))*mix(4.0, 0.5, rg);
  float rim=pow(max(dot(R,normalize(vec3(-0.7,0.6,0.35))),0.0), mix(60.0,2.0,rg))*mix(1.6,0.25,rg);
  return vec3(g*0.95, g*0.98, g*1.04) + sb + rim;
}
vec3 envBRDF(vec3 F0, float rg, float NdV){
  vec4 r=rg*vec4(-1.0,-0.0275,-0.572,0.022)+vec4(1.0,0.0425,1.04,-0.04);
  float a004=min(r.x*r.x, exp2(-9.28*NdV))*r.x+r.y; vec2 AB=vec2(-1.04,1.04)*a004+r.zw; return F0*AB.x+AB.y;
}
void main(){
  vec3 base = uTexOn==1 ? texture(uTex, vUV).rgb : vC;
  vec3 n=normalize(vN); vec3 v=normalize(uEye-vP); if(dot(n,v)<0.0) n=-n;
  float rough=0.85, metal=0.0, ao=1.0;
  if(uPbr==1){
    vec3 t=vT.xyz-n*dot(n,vT.xyz); float tl=length(t);
    if(tl>1e-5 && uRelief>0.0){ t/=tl; vec3 b=cross(n,t)*(vT.w<0.0?-1.0:1.0); vec3 tn=texture(uNrm,vUV).xyz*2.0-1.0; tn.xy*=uRelief; n=normalize(t*tn.x+b*tn.y+n*max(tn.z,0.05)); }
    vec3 orm=texture(uOrm,vUV).rgb; ao=orm.r; rough=orm.g; metal=orm.b;
  }
  if(uMat==0){ rough=0.9; metal=0.0; } else if(uMat==1){ rough=0.22; metal=0.0; } else if(uMat==2){ rough=0.32; metal=1.0; }
  rough=clamp(rough,0.06,1.0);
  vec3 c;
  if(uMode==0) c=base;
  else {
    vec3 alb = uMode==2 ? vec3(0.78,0.74,0.70) : base; float mt = uMode==2 ? 0.0 : metal; float rg = uMode==2 ? max(rough,0.5) : rough;
    vec3 L1=normalize(vec3(0.4,-0.6,0.8)), L2=normalize(v+vec3(0.0,0.0,0.35));
    c = light(n,v,L1,vec3(1.45),alb,rg,mt) + light(n,v,L2,vec3(1.55)*(1.0-0.6*mt),alb,rg,mt);
    // окружение: рассеянное + отражение студии (металл и глянец)
    vec3 F0=mix(vec3(0.04),alb,mt); float NdV=max(dot(n,v),1e-3);
    c += ao*(alb*(1.0-mt)*0.33 + env(reflect(-v,n), L1, rg)*envBRDF(F0, rg, NdV)*mix(0.6, 1.0, mt));
  }
  if(uMap>0 && uPbr==1){
    vec3 orm=texture(uOrm,vUV).rgb;
    if(uMap==1) c=texture(uNrm,vUV).rgb; // как в файле: сиреневый — ровно, оттенки — наклон
    else if(uMap==2){ float hh=texture(uHgt,vUV).r; c=mix(vec3(0.05,0.1,0.35), vec3(1.0,0.95,0.6), hh); c=mix(c, vec3(hh), 0.35); } // синее — впадины, светлое — выпуклости
    else if(uMap==3) c=vec3(orm.g); else if(uMap==4) c=vec3(orm.b); else c=vec3(orm.r);
  }
  o=vec4(c,1.0);
}`;
const SPLAT_VS = `#version 300 es
precision highp float; precision highp usampler2D;
layout(location=0) in vec2 aQuad; layout(location=1) in uint aIdx;
uniform highp sampler2D uData; uniform highp sampler2D uSH; uniform mat4 uV; uniform mat4 uP; uniform vec2 uFocal; uniform vec2 uView; uniform vec3 uEye; uniform int uDeg;
out vec4 vCol; out vec2 vPos;
vec4 fetch(int i){ return texelFetch(uData, ivec2(i%1024, i/1024), 0); }
vec4 fsh(int i){ return texelFetch(uSH, ivec2(i%1024, i/1024), 0); }
// цвет с учётом направления взгляда: сферические гармоники 1–2 степени (как в 3DGS), коэффициенты [k][канал] по 4 в текселе
vec3 shColor(int idx, vec3 base, vec3 p){
  if(uDeg<1) return base;
  vec3 d=normalize(p-uEye); float x=d.x, y=d.y, z=d.z;
  int b=idx*(uDeg>1?6:3); vec4 a0=fsh(b), a1=fsh(b+1), a2=fsh(b+2);
  vec3 s1=a0.xyz, s2=vec3(a0.w,a1.x,a1.y), s3=vec3(a1.z,a1.w,a2.x);
  vec3 c=base - 0.48860251*y*s1 + 0.48860251*z*s2 - 0.48860251*x*s3;
  if(uDeg>1){
    vec4 a3=fsh(b+3), a4=fsh(b+4), a5=fsh(b+5);
    vec3 s4=a2.yzw, s5=a3.xyz, s6=vec3(a3.w,a4.x,a4.y), s7=vec3(a4.z,a4.w,a5.x), s8=a5.yzw;
    c += 1.09254843*x*y*s4 - 1.09254843*y*z*s5 + 0.31539157*(2.0*z*z-x*x-y*y)*s6 - 1.09254843*x*z*s7 + 0.54627422*(x*x-y*y)*s8;
  }
  return max(c, vec3(0.0));
}
void main(){
  int b=int(aIdx)*4; vec4 t0=fetch(b), t1=fetch(b+1), t2=fetch(b+2), t3=fetch(b+3);
  vec4 cam=uV*vec4(t0.xyz,1.0);
  vec4 clip=uP*cam; float bound=1.2*clip.w;
  if(cam.z>-1.0 || clip.x<-bound||clip.x>bound||clip.y<-bound||clip.y>bound){ gl_Position=vec4(0.0,0.0,2.0,1.0); return; }
  mat3 Vrk=mat3(t2.x,t2.y,t2.z, t2.y,t2.w,t3.x, t2.z,t3.x,t3.y);
  float z=-cam.z;
  mat3 J=mat3(uFocal.x/z,0.0,0.0, 0.0,uFocal.y/z,0.0, uFocal.x*cam.x/(z*z), uFocal.y*cam.y/(z*z), 0.0);
  mat3 T=transpose(mat3(uV))*transpose(J); // T = (J·W)ᵀ
  mat3 cov=transpose(T)*Vrk*T;
  float a=cov[0][0]+0.3, bb=cov[0][1], c=cov[1][1]+0.3;
  float mid=0.5*(a+c), rad=length(vec2(0.5*(a-c),bb));
  float l1=mid+rad, l2=max(mid-rad,0.1);
  vec2 dv=normalize(vec2(bb,l1-a)); if(abs(bb)<1e-6) dv = a>=c ? vec2(1.0,0.0) : vec2(0.0,1.0);
  vec2 ax1=min(3.0*sqrt(l1),1024.0)*dv, ax2=min(3.0*sqrt(l2),1024.0)*vec2(dv.y,-dv.x);
  vCol=vec4(shColor(int(aIdx), t1.rgb, t0.xyz), t1.a); vPos=aQuad*3.0;
  vec2 ndc=clip.xy/clip.w;
  gl_Position=vec4(ndc + aQuad.x*ax1*2.0/uView + aQuad.y*ax2*2.0/uView, clip.z/clip.w, 1.0);
}`;
const SPLAT_FS = `#version 300 es
precision highp float; in vec4 vCol; in vec2 vPos; out vec4 o;
void main(){ float r2=dot(vPos,vPos); if(r2>9.0) discard; float B=exp(-0.5*r2)*vCol.a; if(B<1.0/255.0) discard; o=vec4(vCol.rgb*B,B); }`;

function sh(gl, type, src) { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; }
function prog(gl, vs, fs) { const p = gl.createProgram(); gl.attachShader(p, sh(gl, gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl, gl.FRAGMENT_SHADER, fs)); gl.linkProgram(p); if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p)); return p; }

function perspective(fovy, asp, n, f) { const t = 1 / Math.tan(fovy / 2); return [t / asp, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) / (n - f), -1, 0, 0, 2 * f * n / (n - f), 0]; }
function lookAt(e, c, up) {
  let z = [e[0] - c[0], e[1] - c[1], e[2] - c[2]]; let l = Math.hypot(...z); z = z.map(v => v / l);
  let x = [up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0]]; l = Math.hypot(...x); x = x.map(v => v / l);
  const y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]];
  return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -(x[0] * e[0] + x[1] * e[1] + x[2] * e[2]), -(y[0] * e[0] + y[1] * e[1] + y[2] * e[2]), -(z[0] * e[0] + z[1] * e[1] + z[2] * e[2]), 1];
}
function mul4(a, b) { const o = new Array(16); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k]; o[c * 4 + r] = s; } return o; }

export class Viewer3D {
  constructor(canvas) {
    this.cv = canvas;
    const gl = canvas.getContext('webgl2', { antialias: true, premultipliedAlpha: true, preserveDrawingBuffer: true });
    if (!gl) throw new Error('WebGL2 недоступен');
    this.gl = gl;
    this.pm = prog(gl, MESH_VS, MESH_FS); this.ps = prog(gl, SPLAT_VS, SPLAT_FS);
    this.yaw = 0.6; this.pitch = 0.45; this.dist = 250; this.target = [0, 0, 30]; this.fov = 40 * Math.PI / 180;
    this.show = 'mesh'; this.shade = 1; this.auto = false; this.bg = [0.07, 0.08, 0.1];
    this.dirty = true; this._lastSortKey = '';
    this.bindInput();
    const loop = () => { this.frame(); this.raf = requestAnimationFrame(loop); };
    this.raf = requestAnimationFrame(loop);
  }
  destroy() { cancelAnimationFrame(this.raf); }
  fit(mn, mx) {
    this.target = [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2];
    const r = Math.hypot(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]) / 2;
    this.dist = r / Math.sin(this.fov / 2) * 1.08; this.home = { yaw: 0.6, pitch: 0.45, dist: this.dist, target: [...this.target] }; this.dirty = true;
  }
  reset() { if (this.home) { Object.assign(this, { yaw: this.home.yaw, pitch: this.home.pitch, dist: this.home.dist, target: [...this.home.target] }); this.dirty = true; } }
  setMesh(M) {
    const gl = this.gl;
    if (this.mesh) { this.mesh.bufs.forEach(b => gl.deleteBuffer(b)); gl.deleteVertexArray(this.mesh.vao); for (const k of ['tex', 'alb', 'nrm', 'orm', 'hgt']) if (this.mesh[k]) gl.deleteTexture(this.mesh[k]); }
    if (!M) { this.mesh = null; return; }
    const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
    const mk = (data, loc, n, type, norm) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, n, type, norm, 0, 0); return b; };
    const bufs = [mk(M.pos, 0, 3, gl.FLOAT, false), mk(M.nrm, 1, 3, gl.FLOAT, false), mk(M.col instanceof Uint8Array ? M.col : new Uint8Array(M.col), 2, 3, gl.UNSIGNED_BYTE, true)];
    const hasUV = !!(M.uv && M.tex && M.tex.jpg);
    if (hasUV) bufs.push(mk(M.uv instanceof Float32Array ? M.uv : new Float32Array(M.uv), 3, 2, gl.FLOAT, false));
    const hasPbr = hasUV && !!(M.pbr && M.tan && M.pbr.normal && M.pbr.orm);
    if (hasPbr) bufs.push(mk(M.tan instanceof Float32Array ? M.tan : new Float32Array(M.tan), 4, 4, gl.FLOAT, false));
    const ib = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, M.idx instanceof Uint32Array ? M.idx : new Uint32Array(M.idx), gl.STATIC_DRAW); bufs.push(ib);
    gl.bindVertexArray(null);
    const mesh = this.mesh = { vao, bufs, n: M.idx.length, tex: null, hasUV, hasPbr };
    // текстура (JPEG атласа) — раскрываем асинхронно; пока грузится, показываем цвет вершин
    const load = (bytes, type, key) => createImageBitmap(new Blob([bytes], { type }), { colorSpaceConversion: 'none', premultiplyAlpha: 'none' }).then((bmp) => {
      if (this.mesh !== mesh) { bmp.close && bmp.close(); return; }
      const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bmp); bmp.close && bmp.close();
      gl.generateMipmap(gl.TEXTURE_2D);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      mesh[key] = t; this.dirty = true;
    }).catch((e) => console.warn('текстура', key, e));
    // текстура (JPEG атласа) и карты поверхности (альбедо без теней, нормали, ORM) — раскрываем асинхронно
    if (hasUV) load(M.tex.jpg, 'image/jpeg', 'tex');
    if (hasPbr) { if (M.pbr.albedo) load(M.pbr.albedo, 'image/jpeg', 'alb'); load(M.pbr.normal, 'image/png', 'nrm'); load(M.pbr.orm, 'image/png', 'orm'); if (M.pbr.height) load(M.pbr.height, 'image/png', 'hgt'); }
    this.dirty = true;
  }
  // packed: см. splat.js (splatInfo) — v2 с гармониками или старый формат по 14 чисел на каплю
  setSplats(packed) {
    const gl = this.gl, I = splatInfo(packed), n = I.n;
    if (!n) { this.splats = null; return; }
    const rows = Math.ceil(n * 4 / 1024), tex = new Float32Array(1024 * rows * 4);
    const cen = new Float32Array(n * 3);
    const deg = Math.min(2, I.deg), tpS = deg > 1 ? 6 : deg ? 3 : 0, nr = Math.min(I.nb, 9) - 1;
    const shRows = Math.max(1, Math.ceil(n * tpS / 1024)), sh = new Float32Array(1024 * shRows * 4);
    for (let i = 0; i < n; i++) {
      const p = packed.subarray(I.off + i * I.stride, I.off + (i + 1) * I.stride), o = i * 16;
      for (let k = 0; k < 3 * nr; k++) sh[i * tpS * 4 + k] = p[14 + k];
      tex[o] = p[0]; tex[o + 1] = p[1]; tex[o + 2] = p[2]; cen.set(p.subarray(0, 3), i * 3);
      tex[o + 4] = p[11]; tex[o + 5] = p[12]; tex[o + 6] = p[13]; tex[o + 7] = p[10];
      const s = [Math.exp(p[3]), Math.exp(p[4]), Math.exp(p[5])], [w, x, y, z] = [p[6], p[7], p[8], p[9]];
      const R = [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y), 2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x), 2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)];
      const M = [R[0] * s[0], R[1] * s[1], R[2] * s[2], R[3] * s[0], R[4] * s[1], R[5] * s[2], R[6] * s[0], R[7] * s[1], R[8] * s[2]];
      const c = (a, b) => M[a * 3] * M[b * 3] + M[a * 3 + 1] * M[b * 3 + 1] + M[a * 3 + 2] * M[b * 3 + 2];
      tex[o + 8] = c(0, 0); tex[o + 9] = c(0, 1); tex[o + 10] = c(0, 2); tex[o + 11] = c(1, 1); tex[o + 12] = c(1, 2); tex[o + 13] = c(2, 2);
    }
    if (!this.splats) {
      const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
      const qb = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, qb); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, 1, 1, -1, 1]), gl.STATIC_DRAW);
      gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
      const ib = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, ib); gl.enableVertexAttribArray(1); gl.vertexAttribIPointer(1, 1, gl.UNSIGNED_INT, 0, 0); gl.vertexAttribDivisor(1, 1);
      gl.bindVertexArray(null);
      this.splats = { vao, ib, tex: gl.createTexture(), shTex: gl.createTexture() };
    }
    const S = this.splats;
    gl.bindTexture(gl.TEXTURE_2D, S.tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, 1024, rows, 0, gl.RGBA, gl.FLOAT, tex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.bindTexture(gl.TEXTURE_2D, S.shTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, 1024, shRows, 0, gl.RGBA, gl.FLOAT, sh);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    S.deg = tpS ? deg : 0;
    S.n = n; S.cen = cen; S.order = new Uint32Array(n); this._lastSortKey = ''; this.dirty = true;
  }
  sortSplats(V) {
    const S = this.splats, n = S.n, c = S.cen;
    const key = V.slice(2, 11).map(v => v.toFixed(3)).join(',') + n;
    if (key === this._lastSortKey) return; this._lastSortKey = key;
    // глубина = третья строка вида; сортировка подсчётом по 16 битам (дальние первыми)
    const d = new Float32Array(n); let mn = 1e9, mx = -1e9;
    for (let i = 0; i < n; i++) { const z = V[2] * c[i * 3] + V[6] * c[i * 3 + 1] + V[10] * c[i * 3 + 2] + V[14]; d[i] = z; if (z < mn) mn = z; if (z > mx) mx = z; }
    const B = 65536, sc = (B - 1) / Math.max(1e-6, mx - mn), cnt = new Uint32Array(B), key16 = new Uint16Array(n);
    for (let i = 0; i < n; i++) { const k = ((d[i] - mn) * sc) | 0; key16[i] = k; cnt[k]++; }
    for (let i = 1; i < B; i++) cnt[i] += cnt[i - 1];
    for (let i = n - 1; i >= 0; i--) S.order[--cnt[key16[i]]] = i;
    const gl = this.gl; gl.bindBuffer(gl.ARRAY_BUFFER, S.ib); gl.bufferData(gl.ARRAY_BUFFER, S.order, gl.DYNAMIC_DRAW);
  }
  view() {
    const cp = Math.cos(this.pitch), e = [this.target[0] + this.dist * cp * Math.sin(this.yaw), this.target[1] - this.dist * cp * Math.cos(this.yaw), this.target[2] + this.dist * Math.sin(this.pitch)];
    return { e, V: lookAt(e, this.target, [0, 0, 1]) };
  }
  frame() {
    const gl = this.gl, cv = this.cv, dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = Math.round(cv.clientWidth * dpr), H = Math.round(cv.clientHeight * dpr);
    if (!W || !H) return;
    if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; this.dirty = true; }
    if (this.auto) { this.yaw += 0.006; this.dirty = true; }
    if (!this.dirty) return; this.dirty = false;
    const { e, V } = this.view(), P = perspective(this.fov, W / H, Math.max(1, this.dist * 0.05), this.dist * 6), VP = mul4(P, V);
    gl.viewport(0, 0, W, H); gl.clearColor(...this.bg, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (this.show === 'mesh' && this.mesh) {
      gl.enable(gl.DEPTH_TEST); gl.disable(gl.BLEND); gl.useProgram(this.pm);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.pm, 'uVP'), false, VP); gl.uniform1i(gl.getUniformLocation(this.pm, 'uMode'), this.shade); gl.uniform3fv(gl.getUniformLocation(this.pm, 'uEye'), e);
      // текстура: «фото» — атлас как снят, «без теней» — альбедо из карт поверхности
      const M_ = this.mesh, colTex = this.texSrc === 'albedo' && M_.alb ? M_.alb : M_.tex;
      const texOn = colTex && this.useTex !== false ? 1 : 0; gl.uniform1i(gl.getUniformLocation(this.pm, 'uTexOn'), texOn);
      if (texOn) { gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, colTex); gl.uniform1i(gl.getUniformLocation(this.pm, 'uTex'), 0); }
      const pbrOn = M_.hasPbr && M_.nrm && M_.orm ? 1 : 0; gl.uniform1i(gl.getUniformLocation(this.pm, 'uPbr'), pbrOn);
      if (pbrOn) {
        gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, M_.nrm); gl.uniform1i(gl.getUniformLocation(this.pm, 'uNrm'), 1);
        gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, M_.orm); gl.uniform1i(gl.getUniformLocation(this.pm, 'uOrm'), 2); gl.activeTexture(gl.TEXTURE0);
      } else gl.vertexAttrib4f(4, 1, 0, 0, 1);
      const mapOn = pbrOn && this.map > 0 && (this.map !== 2 || M_.hgt) ? this.map : 0; gl.uniform1i(gl.getUniformLocation(this.pm, 'uMap'), mapOn);
      if (mapOn === 2) { gl.activeTexture(gl.TEXTURE3); gl.bindTexture(gl.TEXTURE_2D, M_.hgt); gl.uniform1i(gl.getUniformLocation(this.pm, 'uHgt'), 3); gl.activeTexture(gl.TEXTURE0); }
      gl.uniform1f(gl.getUniformLocation(this.pm, 'uRelief'), this.relief ?? 1); gl.uniform1i(gl.getUniformLocation(this.pm, 'uMat'), this.mat ?? -1);
      gl.bindVertexArray(this.mesh.vao); gl.drawElements(gl.TRIANGLES, this.mesh.n, gl.UNSIGNED_INT, 0);
    } else if (this.show === 'splat' && this.splats) {
      this.sortSplats(V);
      gl.disable(gl.DEPTH_TEST); gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); gl.useProgram(this.ps);
      const f = H / 2 / Math.tan(this.fov / 2);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.ps, 'uV'), false, V); gl.uniformMatrix4fv(gl.getUniformLocation(this.ps, 'uP'), false, P);
      gl.uniform2f(gl.getUniformLocation(this.ps, 'uFocal'), f, f); gl.uniform2f(gl.getUniformLocation(this.ps, 'uView'), W, H);
      gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, this.splats.tex); gl.uniform1i(gl.getUniformLocation(this.ps, 'uData'), 0);
      gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, this.splats.shTex); gl.uniform1i(gl.getUniformLocation(this.ps, 'uSH'), 1); gl.activeTexture(gl.TEXTURE0);
      gl.uniform3fv(gl.getUniformLocation(this.ps, 'uEye'), e); gl.uniform1i(gl.getUniformLocation(this.ps, 'uDeg'), this.splats.deg);
      gl.bindVertexArray(this.splats.vao); gl.drawArraysInstanced(gl.TRIANGLE_FAN, 0, 4, this.splats.n);
    }
    gl.bindVertexArray(null);
  }
  snapshot(w = 256) { this.dirty = true; this.frame(); const c = document.createElement('canvas'); const s = w / Math.max(this.cv.width, this.cv.height); c.width = Math.round(this.cv.width * s); c.height = Math.round(this.cv.height * s); c.getContext('2d').drawImage(this.cv, 0, 0, c.width, c.height); return c.toDataURL('image/jpeg', 0.85); }
  bindInput() {
    const cv = this.cv, pts = new Map(); let last = null, lastTap = 0;
    cv.style.touchAction = 'none';
    const st = () => { const a = [...pts.values()]; if (a.length === 1) return { x: a[0].x, y: a[0].y, d: 0 }; const [p, q] = a; return { x: (p.x + q.x) / 2, y: (p.y + q.y) / 2, d: Math.hypot(p.x - q.x, p.y - q.y) }; };
    cv.addEventListener('pointerdown', (e) => {
      cv.setPointerCapture(e.pointerId); pts.set(e.pointerId, { x: e.clientX, y: e.clientY }); last = st(); this.auto = false; this.onUser && this.onUser();
      const now = Date.now(); if (pts.size === 1 && now - lastTap < 300) this.reset(); lastTap = now;
    });
    cv.addEventListener('pointermove', (e) => {
      if (!pts.has(e.pointerId)) return; pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const s = st(); if (!last || (pts.size === 2) !== (last.d > 0)) { last = s; return; }
      const dx = s.x - last.x, dy = s.y - last.y;
      if (pts.size === 1) { this.yaw -= dx * 0.008; this.pitch = Math.max(-1.45, Math.min(1.45, this.pitch + dy * 0.008)); }
      else {
        if (last.d > 0 && s.d > 0) this.dist = Math.max(10, Math.min(3000, this.dist * last.d / s.d));
        // сдвиг двумя пальцами в плоскости экрана
        const k = this.dist * 2 * Math.tan(this.fov / 2) / cv.clientHeight, cy = Math.cos(this.yaw), sy = Math.sin(this.yaw), sp = Math.sin(this.pitch), cp = Math.cos(this.pitch);
        const right = [cy, sy, 0], up = [-sy * sp, cy * sp, cp];
        for (let i = 0; i < 3; i++) this.target[i] += (-dx * right[i] + dy * up[i]) * k;
      }
      last = s; this.dirty = true;
    });
    const end = (e) => { pts.delete(e.pointerId); last = pts.size ? st() : null; };
    cv.addEventListener('pointerup', end); cv.addEventListener('pointercancel', end);
    cv.addEventListener('wheel', (e) => { e.preventDefault(); this.dist = Math.max(10, Math.min(3000, this.dist * Math.exp(e.deltaY * 0.001))); this.dirty = true; }, { passive: false });
  }
}
