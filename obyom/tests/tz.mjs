import fs from 'fs';
import jpeg from 'jpeg-js';
function decode(buf,W){const img=jpeg.decode(buf,{useTArray:true,formatAsRGBA:true});const sw=img.width,sh=img.height,w=W,h=Math.round(sh*w/sw);const rgba=new Uint8ClampedArray(w*h*4);for(let j=0;j<h;j++){const sy=Math.min(sh-1,Math.floor(j*sh/h));for(let i=0;i<w;i++){const sx=Math.min(sw-1,Math.floor(i*sw/w));const s=(sy*sw+sx)*4,o=(j*w+i)*4;for(let k=0;k<4;k++)rgba[o+k]=img.data[s+k];}}return {rgba,w,h};}
function blobFrom(path,W){const b=fs.readFileSync(path); const d=decode(b,W); return {_raw:{...d}};}
const W=640;
globalThis.ImageData=class{constructor(d,w,h){this.data=d;this.width=w;this.height=h;}};
globalThis.createImageBitmap=async(b)=>({width:b._raw.w,height:b._raw.h,data:b._raw.rgba,close(){}});
globalThis.OffscreenCanvas=class{constructor(w,h){this.buf=new Uint8ClampedArray(w*h*4);this.width=w;this.height=h;} getContext(){const c=this;return{drawImage(bm,x,y,w,h){for(let j=0;j<h;j++)for(let i=0;i<w;i++){const sx=Math.min(bm.width-1,(i*bm.width/w)|0),sy=Math.min(bm.height-1,(j*bm.height/h)|0),s=(sy*bm.width+sx)*4,o=((j+y)*c.width+(i+x))*4;for(let k=0;k<4;k++)c.buf[o+k]=bm.data[s+k];}},getImageData(x,y,w,h){const o=new Uint8ClampedArray(w*h*4);for(let j=0;j<h;j++)for(let i=0;i<w;i++){const s=((j+y)*c.width+(i+x))*4,oo=(j*w+i)*4;for(let k=0;k<4;k++)o[oo+k]=c.buf[s+k];}return{data:o};},putImageData(){}};} async convertToBlob(){return {arrayBuffer:async()=>this.buf.buffer};}};
const dir='/tmp/u/fig';
const files=fs.readdirSync(dir).filter(f=>/^f\d+\.jpg$/.test(f)).sort();
const blobs=files.map(f=>blobFrom(dir+'/'+f,W));
const plBlobs=[];
for(let i=0;i<4;i++) plBlobs.push(blobFrom(`/tmp/u/meta/plate/p00${i}.jpg`,W));
const {runPipeline}=await import('../web/js/pipeline.js');
const job={blobs,mode:'mesh',quality:'normal',size:'A4',theme:'light',Hb:140,method:'turn',shape:'normal',pool:false,plates:plBlobs};
const t0=Date.now();let last='';
const cb={progress:(t,p,s)=>{if(t!==last){last=t;console.log(`· ${t} ${Math.round(p*100)}% ${s||''}`);}},log:m=>console.log('LOG',m),partial:()=>{},preview:()=>{}};
const r=await runPipeline(job,cb);
console.log('STATS',JSON.stringify(r.stats));
const p=r.mesh.pos;let xmin=1e9,xmax=-1e9,ymin=1e9,ymax=-1e9,zmin=1e9,zmax=-1e9;
for(let i=0;i<p.length;i+=3){xmin=Math.min(xmin,p[i]);xmax=Math.max(xmax,p[i]);ymin=Math.min(ymin,p[i+1]);ymax=Math.max(ymax,p[i+1]);zmin=Math.min(zmin,p[i+2]);zmax=Math.max(zmax,p[i+2]);}
console.log('DX/DY/DZ mm:',xmax-xmin,ymax-ymin,zmax-zmin);
console.log('t=',(Date.now()-t0)/1000);
