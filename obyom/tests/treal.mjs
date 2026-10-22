// Прогон реальных JPG через конвейер
import fs from 'fs';
import jpeg from 'jpeg-js';

function decode(buf, targetW) {
  const img = jpeg.decode(buf, { useTArray: true, formatAsRGBA: true });
  const sw = img.width, sh = img.height;
  const w = targetW, h = Math.round(sh * w / sw);
  // билинейное уменьшение через canvas-имитацию: простейшее ближайшее
  const src = img.data;
  const rgba = new Uint8ClampedArray(w * h * 4);
  for (let j = 0; j < h; j++) {
    const sy = Math.min(sh - 1, Math.floor(j * sh / h));
    for (let i = 0; i < w; i++) {
      const sx = Math.min(sw - 1, Math.floor(i * sw / w));
      const s = (sy * sw + sx) * 4, o = (j * w + i) * 4;
      for (let k = 0; k < 4; k++) rgba[o + k] = src[s + k];
    }
  }
  return { rgba, w, h, srcW: sw, srcH: sh };
}
function blobFrom(path, targetW) {
  const buf = fs.readFileSync(path);
  const d = decode(buf, targetW);
  return { _raw: { rgba: d.rgba, w: d.w, h: d.h, srcW: d.srcW, srcH: d.h } };
}
function blobFromBuf(buf, targetW) {
  const d = decode(buf, targetW);
  return { _raw: { rgba: d.rgba, w: d.w, h: d.h, srcW: d.srcW, srcH: d.h } };
}

const W = 640; // PROC_W
globalThis.ImageData = class { constructor(d,w,h){this.data=d;this.width=w;this.height=h;} };
globalThis.createImageBitmap = async (b) => { const r=b._raw; return { width:r.w, height:r.h, data:r.rgba, close(){} }; };
globalThis.OffscreenCanvas = class {
  constructor(w,h){ this.buf=new Uint8ClampedArray(w*h*4); this.width=w; this.height=h; }
  getContext(){ const c=this; return {
    drawImage(bm,x,y,w,h){ for(let j=0;j<h;j++)for(let i=0;i<w;i++){const sx=Math.min(bm.width-1,(i*bm.width/w)|0),sy=Math.min(bm.height-1,(j*bm.height/h)|0),s=(sy*bm.width+sx)*4,o=((j+y)*c.width+(i+x))*4;for(let k=0;k<4;k++)c.buf[o+k]=bm.data[s+k];} },
    getImageData(x,y,w,h){ const out=new Uint8ClampedArray(w*h*4); for(let j=0;j<h;j++)for(let i=0;i<w;i++){const s=((j+y)*c.width+(i+x))*4,o=(j*w+i)*4;for(let k=0;k<4;k++)out[o+k]=c.buf[s+k];} return {data:out}; },
    putImageData(id){ const d=id.data,w=id.width,h=id.height,x=0,y=0; for(let j=0;j<h;j++)for(let i=0;i<w;i++){const s=(j*w+i)*4,o=((j+y)*c.width+(i+x))*4;for(let k=0;k<4;k++)c.buf[o+k]=d[s+k];} }
  }; }
  async convertToBlob(){ const u=new Uint8Array(this.buf.buffer.slice(0)); return {arrayBuffer:async()=>u.buffer}; }
};
// encodeJPEG внутри pipeline использует OffscreenCanvas.convertToBlob — пригодно, просто не сохраняем текстуру
const dir = process.argv[2];
const method = process.argv[3] || 'turn';
const Hb = +(process.env.HB || process.argv[4] || 140);
const quality = process.env.QUALITY || 'normal';
const PW = quality === 'best' ? 960 : 640;
const files = fs.readdirSync(dir).filter(f=>/^f\d+\.jpg$/.test(f)).sort();
console.log(`frames: ${files.length}, PW=${PW}, quality=${quality}, Hb=${Hb}`);
const blobs = files.map(f => blobFrom(dir+'/'+f, PW));
const { runPipeline } = await import('../web/js/pipeline.js');
const job = { blobs, mode:'mesh', quality, size:'A4', theme:'light', Hb, method, shape:process.env.SHAPE||'normal', pool:false };
if (fs.existsSync(dir+'/plate.jpg')) {
  job.plates = [blobFrom(dir+'/plate.jpg', PW)];
  console.log('plate: yes');
}
const t0=Date.now(); let last='';
const cb={ progress:(t,p,s)=>{const k=t;if(k!==last){last=k;console.log(`  · ${t} ${Math.round(p*100)}% ${s||''}`);}}, log:m=>console.log('LOG',m), partial:(r)=>{ console.log('PARTIAL stats:', JSON.stringify(r.stats)); fs.writeFileSync('/tmp/u/mesh_partial.json', JSON.stringify({pos:[...r.mesh.pos], idx:[...r.mesh.idx], col:[...r.mesh.col]})); }, preview:()=>{} };
let r; try { r = await runPipeline(job,cb); } catch(e){ console.error('CRASH',e); process.exit(1); }
console.log('STATS', JSON.stringify(r.stats));
fs.writeFileSync('/tmp/u/mesh_real.json', JSON.stringify({pos:[...r.mesh.pos], idx:[...r.mesh.idx], col:[...r.mesh.col]}));
console.log('done, t=', (Date.now()-t0)/1000);
