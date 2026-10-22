import fs from 'fs';
import jpeg from 'jpeg-js';
function decode(buf, targetW) {
  const img = jpeg.decode(buf,{useTArray:true,formatAsRGBA:true});
  const sw=img.width, sh=img.height, w=targetW, h=Math.round(sh*w/sw);
  const rgba=new Uint8ClampedArray(w*h*4);
  for(let j=0;j<h;j++){const sy=Math.min(sh-1,Math.floor(j*sh/h)); for(let i=0;i<w;i++){const sx=Math.min(sw-1,Math.floor(i*sw/w)); const s=(sy*sw+sx)*4,o=(j*w+i)*4; for(let k=0;k<4;k++) rgba[o+k]=img.data[s+k];}}
  return {rgba,w,h,srcW:sw,srcH:sh};
}
function blobFrom(path,W){const b=fs.readFileSync(path); return {_raw:{...decode(b,W)}};}
const W=640;
globalThis.ImageData=class{constructor(d,w,h){this.data=d;this.width=w;this.height=h;}};
globalThis.createImageBitmap=async(b)=>({width:b._raw.w,height:b._raw.h,data:b._raw.rgba,close(){}});
globalThis.OffscreenCanvas=class{constructor(w,h){this.buf=new Uint8ClampedArray(w*h*4);this.width=w;this.height=h;} getContext(){const c=this;return{drawImage(bm,x,y,w,h){for(let j=0;j<h;j++)for(let i=0;i<w;i++){const sx=Math.min(bm.width-1,(i*bm.width/w)|0),sy=Math.min(bm.height-1,(j*bm.height/h)|0),s=(sy*bm.width+sx)*4,o=((j+y)*c.width+(i+x))*4;for(let k=0;k<4;k++)c.buf[o+k]=bm.data[s+k];}},getImageData(x,y,w,h){const o=new Uint8ClampedArray(w*h*4);for(let j=0;j<h;j++)for(let i=0;i<w;i++){const s=((j+y)*c.width+(i+x))*4,oo=(j*w+i)*4;for(let k=0;k<4;k++)o[oo+k]=c.buf[s+k];}return {data:o};},putImageData(){} };} async convertToBlob(){return {arrayBuffer:async()=>this.buf.buffer};}};
// повторяем подготовку
const dir='/tmp/u/fig';
const files=fs.readdirSync(dir).filter(f=>/^f\d+\.jpg$/.test(f)).sort();
const blobs=files.map(f=>blobFrom(dir+'/'+f,W));
const {runPipeline}=await import('../web/js/pipeline.js');
// prepSet не экспортируется — запустим runPipeline и вытащим good через progress, но удобнее повторить вызов.
// Скопируем подготовку через pipeline модуль: используем runPipeline с пустой оболочкой, перехватывая prepSet не получается.
// Проще: напрямую вызовем detectMarkers/poseFromMarkers/computeMask/motionMasks.
import {detectMarkers,toGray} from '../web/js/detect.js';
import {poseFromMarkers, focalEqs, focalFromEqs, refineFocal, camAngles} from '../web/js/pose.js';
import {matLayout} from '../web/js/mat.js';
import {matRaster} from '../web/js/mat.js';
import {computeMask, motionMasks} from '../web/js/recon.js';
const L=matLayout('A4','full');
const mr=matRaster(L,'light');
const Rb=55*L.k, Hb=140;
// decode
const frames=[]; let w,h;
for(let i=0;i<blobs.length;i++){const b=blobs[i]._raw; frames.push({rgba:b.rgba,w:b.w,h:b.h}); if(!w){w=b.w;h=b.h;}}
// focal: init guess
let K={fx:0.8*w,fy:0.8*w,cx:w/2,cy:h/2};
// plates decode
const plate=decode(fs.readFileSync(dir+'/plate.jpg'),W);
const dPlate={rgba:plate.rgba,w:plate.w,h:plate.h};
let msP=detectMarkers(toGray(plate.rgba,plate.w,plate.h),plate.w,plate.h);
let pP=poseFromMarkers(msP,L,K);
const eqs=[];
const good=[];
for(let i=0;i<frames.length;i++){
  const f=frames[i];
  const ms=detectMarkers(toGray(f.rgba,f.w,f.h),f.w,f.h);
  let p=poseFromMarkers(ms,L,K);
  if(p && p.n>=2){ eqs.push(...focalEqs(p.H,f.w/2,f.h/2)); good.push({...f,ms,p,idx:i}); }
}
// refine focal
if(eqs.length){const rf=focalFromEqs(eqs,w/2,h/2); if(rf && rf.f) K.fx=K.fy=rf.f;}
let k1=0,rf1={f:K.fx,rms:0};
try { const r=refineFocal(good,K,k1); if(r && Math.abs(r.f/K.fx-1)<0.08 && r.rms<0.75*(good[0].p.rms||1)) K.fx=K.fy=r.f; }catch(e){}
for(const f of good){f.K=K; f.R=f.p.R; f.t=f.p.t; f.rms=f.p.rms; f.ang=camAngles(f.p.R,f.p.t);}
// clean plates: plateEmpty equivalent
let clean=[dPlate.rgba];
// masks
let nTrust=0;
for(let i=0;i<good.length;i++){
  const m=computeMask(good[i],{layout:L,mr,Rb,Hb,cutOnly:true,offMat:false,clean,enclose:true,refOut:true});
  good[i].mask=m.mask; good[i].refOut=m.refOut; good[i].trusted=!!m.stats.enclosed; if(good[i].trusted)nTrust++;
}
// motion masks
const mo=motionMasks(good);
console.log('good',good.length,'nTrust',nTrust,'motion',mo);
const A={good,elMin:Math.min(...good.map(f=>f.ang.el)),elMax:Math.max(...good.map(f=>f.ang.el))};
// сохраним несколько кадров: исходный, маска, движение
const fs_=fs;
for (const idx of [0,40,90,140,200,250,270]) {
  const f=A.good[idx]; if(!f) continue;
  const n=f.w*f.h;
  // mask visualization: 0=bg(white),1=unk(gray),2=obj(black),3=weak(light),4=ignore(yellow)
  const vis=new Uint8ClampedArray(n*4);
  const col={0:[255,255,255],1:[150,150,150],2:[20,20,20],3:[220,220,220],4:[255,255,0]};
  for(let i=0;i<n;i++){const c=col[f.mask[i]]||[255,0,255]; const o=i*4; vis[o]=c[0];vis[o+1]=c[1];vis[o+2]=c[2];vis[o+3]=255;}
  // overlay motion (red) on RGB
  if(f.motion){for(let i=0;i<n;i++) if(f.motion[i]){const o=i*4; vis[o]=255;vis[o+1]=40;vis[o+2]=40;}}
  // write as raw PPM then convert
  let ppm=`P6\n${f.w} ${f.h}\n255\n`;
  fs_.writeFileSync(`/tmp/u/v${idx}.ppm`, Buffer.concat([Buffer.from(ppm), Buffer.from(vis)]));
  // also write original RGB for comparison
  const o2=new Uint8ClampedArray(n*4);
  for(let i=0;i<n;i++){const o=i*4; o2[o]=f.rgba[o]; o2[o+1]=f.rgba[o+1]; o2[o+2]=f.rgba[o+2]; o2[o+3]=255;}
  let ppm2=`P6\n${f.w} ${f.h}\n255\n`;
  fs_.writeFileSync(`/tmp/u/o${idx}.ppm`, Buffer.concat([Buffer.from(ppm2), Buffer.from(o2)]));
}
console.log('good',A.good.length,'els range',A.elMin,A.elMax);
// count motion pixels per frame at high el
for(let i=0;i<A.good.length;i++){const f=A.good[i]; if(!f.motion) continue; let c=0; for(let j=0;j<f.motion.length;j++) if(f.motion[j])c++; if(c>100) console.log(i,'el',f.ang.el.toFixed(1),'motionPx',c,'refMoved',f.refMoved);}
