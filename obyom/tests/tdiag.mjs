import fs from 'fs';
import jpeg from 'jpeg-js';
function decode(buf,W){const img=jpeg.decode(buf,{useTArray:true,formatAsRGBA:true});const sw=img.width,sh=img.height,w=W,h=Math.round(sh*w/sw);const rgba=new Uint8ClampedArray(w*h*4);for(let j=0;j<h;j++){const sy=Math.min(sh-1,Math.floor(j*sh/h));for(let i=0;i<w;i++){const sx=Math.min(sw-1,Math.floor(i*sw/w));const s=(sy*sw+sx)*4,o=(j*w+i)*4;for(let k=0;k<4;k++)rgba[o+k]=img.data[s+k];}}return {rgba,w,h};}
function blob(path,W){const b=fs.readFileSync(path);return decode(b,W);}
const W=640;
globalThis.ImageData=class{constructor(d,w,h){this.data=d;this.width=w;this.height=h;}};
globalThis.createImageBitmap=async(b)=>({width:b.w,height:b.h,data:b.rgba,close(){}});
globalThis.OffscreenCanvas=class{constructor(w,h){this.buf=new Uint8ClampedArray(w*h*4);this.width=w;this.height=h;} getContext(){const c=this;return{drawImage(bm,x,y,w,h){for(let j=0;j<h;j++)for(let i=0;i<w;i++){const sx=Math.min(bm.width-1,(i*bm.width/w)|0),sy=Math.min(bm.height-1,(j*bm.height/h)|0),s=(sy*bm.width+sx)*4,o=((j+y)*c.width+(i+x))*4;for(let k=0;k<4;k++)c.buf[o+k]=bm.data[s+k];}},getImageData(x,y,w,h){const o=new Uint8ClampedArray(w*h*4);for(let j=0;j<h;j++)for(let i=0;i<w;i++){const s=((j+y)*c.width+(i+x))*4,oo=(j*w+i)*4;for(let k=0;k<4;k++)o[oo+k]=c.buf[s+k];}return {data:o};},putImageData(){}};} async convertToBlob(){return {arrayBuffer:async()=>this.buf.buffer};}};
const dir='/tmp/u/fig';
const files=fs.readdirSync(dir).filter(f=>/^f\d+\.jpg$/.test(f)).sort();
// decode all frames
const frames=[]; let w0,h0;
for(const f of files){const d=blob(dir+'/'+f,W); frames.push(d); if(!w0){w0=d.w;h0=d.h;}}
import {detectMarkers,toGray} from '../web/js/detect.js';
import {poseFromMarkers,focalEqs,focalFromEqs,refineFocal,camAngles} from '../web/js/pose.js';
import {matLayout,matRaster} from '../web/js/mat.js';
import {computeMask,motionMasks,carveHull,MOTION_OPT} from '../web/js/recon.js';
const L=matLayout('A4','full');
const mr=matRaster(L,'light',2);
const Hb=140;
const Rb=55*L.k;
// plates
const plates=[];
for(let i=0;i<4;i++){const d=blob(`/tmp/u/meta/plate/p00${i}.jpg`,W); plates.push(d);}
let K={fx:0.8*w0,fy:0.8*w0,cx:w0/2,cy:h0/2};
const good=[];const eqs=[];
for(let i=0;i<frames.length;i++){const d=frames[i]; const ms=detectMarkers(toGray(d.rgba,d.w,d.h),d.w,d.h); let p=poseFromMarkers(ms,L,K); if(p&&p.n>=2){eqs.push(...focalEqs(p.H,d.w/2,d.h/2)); good.push({...d,ms,p,idx:i});}}
if(eqs.length){const rf=focalFromEqs(eqs,w0/2,h0/2); if(rf&&rf.f){K.fx=K.fy=rf.f;}}
// refine focal using all poses
try { const r=refineFocal(good,K,0); if(r && Math.abs(r.f/K.fx-1)<0.08) K.fx=K.fy=r.f; }catch(e){}
// recompute poses with refined focal for better accuracy
for(const f of good){ const p=poseFromMarkers(f.ms,L,K); if(p&&p.n>=2){f.p=p;f.R=p.R;f.t=p.t;f.rms=p.rms;f.ang=camAngles(p.R,p.t);} }
for(const f of good){f.K=K;f.R=f.p.R;f.t=f.p.t;f.rms=f.p.rms;f.ang=camAngles(f.p.R,f.p.t);}
// plates (after focal refine)
function plateCheckRaw(pd){const ms=detectMarkers(toGray(pd.rgba,pd.w,pd.h),pd.w,pd.h);const p=poseFromMarkers(ms,L,K);if(!p||p.n<2)return null;return {R:p.R,t:p.t,rms:p.rms,ms};}
let platePoses=plates.map(pd=>({pd,ps:plateCheckRaw(pd)}));
// refine focal together with frames to reduce plate rms
for(let it=0;it<3;it++){
  const all=[...good.map(g=>({ms:g.ms})),...platePoses.filter(x=>x.ps).map(x=>({ms:x.ps.ms}))];
  try { const r=refineFocal(all.map(a=>({...a,K,R:poseFromMarkers(a.ms,L,K).R,t:poseFromMarkers(a.ms,L,K).t})),K,0); if(r && Math.abs(r.f/K.fx-1)<0.08) K.fx=K.fy=r.f; }catch(e){}
}
for(const pp of platePoses){const p=pp.ps&&poseFromMarkers(pp.ps.ms,L,K); pp.ps=p&&p.n>=2&&p.rms<2.5?{R:p.R,t:p.t,rms:p.rms,K}:null;}
platePoses=platePoses.filter(x=>x.ps);
console.log('plates detected:',platePoses.length,'/',plates.length);
// group frames by camera position (matches motionMasks grouping)
// Build clean array per frame: match each frame to its closest plate by camera position
function closestPlate(f){
  let best=null,bd=1e9;
  for(const pp of platePoses){const dt=Math.hypot(f.t[0]-pp.ps.t[0],f.t[1]-pp.ps.t[1],f.t[2]-pp.ps.t[2]); if(dt<bd){bd=dt;best=pp;}}
  return bd<25?best:null; // within 25 mm
}
// mask with plate matched per frame
let nTrust=0,plUsed=0;
for(const f of good){
  const pp=closestPlate(f);
  const clean=pp?[pp.pd.rgba]:[];
  const m=computeMask(f,{layout:L,mr,Rb,Hb,cutOnly:true,offMat:false,clean,enclose:true,refOut:true});
  f.mask=m.mask;f.refOut=m.refOut;f.trusted=!!m.stats.enclosed;if(f.trusted)nTrust++;
  if(pp)plUsed++;
}
console.log('frames with plate match:',plUsed,'/',good.length,'  trusted:',nTrust);
// motion masks — lower minG threshold
const mo=motionMasks(good,{minG:4});
console.log('motion groups:',mo);
// carve
const G=carveHull(good,{Rb,Hb},128,()=>{},{motion:true,photo:false,frac:0.08});
// measure
function measure(G){
  const {nx,ny,nz,vs,origin:[ox,oy,oz],occ}=G;
  let xmin=1e9,xmax=-1e9,ymin=1e9,ymax=-1e9,zmin=1e9,zmax=-1e9,n=0,vol=0;
  for(let z=0,vo=0;z<nz;z++)for(let y=0;y<ny;y++)for(let x=0;x<nx;x++){const i=(z*ny+y)*nx+x;if(occ[i]>0.5){const X=ox+(x+0.5)*vs,Y=oy+(y+0.5)*vs,Z=oz+z*vs;if(X<xmin)xmin=X;if(X>xmax)xmax=X;if(Y<ymin)ymin=Y;if(Y>ymax)ymax=Y;if(Z<zmin)zmin=Z;if(Z>zmax)zmax=Z;n++;}}
  return {dx:xmax-xmin,dy:ymax-ymin,dz:zmax-zmin,vol:n*vs**3/1000,n};
}
console.log('base vs=%.2f mm',2*Rb/128);
console.log('mesh:',measure(G));
console.log('capTrim mm:',G.capTrim,'capExt mm:',G.capExt,'bridge mm:',G.capBridge,'motion vol cm3:',G.motionCut);
