// Same as tz but dumps per-layer silhouette stats from high-elevation trusted frames
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
const plBlobs=[];for(let i=0;i<4;i++)plBlobs.push(blobFrom(`/tmp/u/meta/plate/p00${i}.jpg`,W));
// patch pipeline to add a hook after prepSet
const pipeline=await import('../web/js/pipeline.js');
const orig = pipeline.runPipeline.toString; // can't easily hook — reimplement minimal
const recon=await import('../web/js/recon.js');
const detect=await import('../web/js/detect.js');
const poseMod=await import('../web/js/pose.js');
const matMod=await import('../web/js/mat.js');
// We'll use prepSet indirectly by running runPipeline up to hull — easier: patch carveHull
const carveOrig = recon.carveHull;
recon.carveHull = function(frames,box,N,onProgress,opt){
  const G = carveOrig(frames,box,N,onProgress,opt);
  // project frames onto grid, count per layer what silhouettes say
  const {nx,ny,nz,vs,origin:[ox,oy,oz]}=G;
  // high frames
  const highF=frames.filter(f=>f.ang && f.ang.el>50*Math.PI/180);
  console.log('high-el frames (>50°):',highF.length);
  // For each layer, in each cell of the base ring, count bg/seen from high frames and mask==2
  for(let z=nz-1;z>=Math.max(0,nz-80);z-=2){
    const Z=oz+z*vs;
    let occN=0,objByHigh=0,seenByHigh=0;
    for(let y=0;y<ny;y+=2)for(let x=0;x<nx;x+=2){
      const i=(z*ny+y)*nx+x; if(G.occ[i]<0.5) continue;
      occN++;
      const X=ox+(x+0.5)*vs,Y=oy+(y+0.5)*vs;
      let so=0,sbg=0,s2=0,sn=0;
      for(const f of highF){
        const R=f.R,t=f.t,K=f.K,cz=R[6]*X+R[7]*Y+R[8]*Z+t[2]; if(cz<=1) continue;
        const u=(K.fx*(R[0]*X+R[1]*Y+R[2]*Z+t[0])/cz+K.cx)|0;
        const v=(K.fy*(R[3]*X+R[4]*Y+R[5]*Z+t[1])/cz+K.cy)|0;
        if(u<0||v<0||u>=f.w||v>=f.h) continue;
        sn++;
        const m=f.mask[v*f.w+u];
        if(m===0) sbg++;
        else if(m===2) s2++;
        else if(m===1||m===3) so++;
      }
      if(sn>=2){seenByHigh++; if(s2>=Math.max(2,0.1*sn)) objByHigh++;}
    }
    console.log(`z=${Z.toFixed(0)} mm occ(x4)=${occN*4} seenHigh=${seenByHigh*4} objHigh=${objByHigh*4}`);
  }
  return G;
};
const {runPipeline}=pipeline;
const job={blobs,mode:'mesh',quality:'normal',size:'A4',theme:'light',Hb:140,method:'turn',shape:'normal',pool:false,plates:plBlobs};
const t0=Date.now();let last='';
try{
  const r=await runPipeline(job,{progress:(t,p,s)=>{if(t!==last){last=t;console.log('·',t);}},log:m=>console.log('LOG',m),partial:()=>{},preview:()=>{}});
  console.log('STATS',JSON.stringify(r.stats));
  const p=r.mesh.pos;let xmin=1e9,xmax=-1e9,ymin=1e9,ymax=-1e9,zmin=1e9,zmax=-1e9;
  for(let i=0;i<p.length;i+=3){xmin=Math.min(xmin,p[i]);xmax=Math.max(xmax,p[i]);ymin=Math.min(ymin,p[i+1]);ymax=Math.max(ymax,p[i+1]);zmin=Math.min(zmin,p[i+2]);zmax=Math.max(zmax,p[i+2]);}
  console.log('DX/DY/DZ mm:',xmax-xmin,ymax-ymin,zmax-zmin);
}catch(e){console.error('CRASH',e);process.exit(1);}
