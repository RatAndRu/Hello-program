// ПИКСЕЛЬ v3.4 — любые размеры + ASCII 5×5 + адаптив
const $=id=>document.getElementById(id);
const code=$('code'), gutter=$('gutter'), pc=$('pixelCanvas'), hc=$('hdCanvas'), pctx=pc.getContext('2d'), hctx=hc.getContext('2d');
const PAL={
  pico8:['#000000','#1D2B53','#7E2553','#008751','#AB5236','#5F574F','#C2C3C5','#FFF1E8','#FF004D','#FFA300','#FFEC27','#00E436','#29ADFF','#83769C','#FF77A8','#FFCCAA'],
  gameboy:['#0f380f','#306230','#8bac0f','#9bbc0f'],
  sweet16:['#1a1c2c','#5d275d','#b13e53','#ef7d57','#ffcd75','#a7f070','#38b764','#257179','#29366f','#3b5dc9','#41a6f6','#73eff7','#f4f4f4','#94b0c2','#566c86','#333c57'],
  endesga32:['#000000','#1b1a17','#5a3921','#8a5a44','#a06d3f','#d9a066','#e5c07b','#f2e8b5','#6b8cff','#a0c0ff','#4a9c6d','#7ec8a0','#c94a4a','#ff6b6b','#ff9e9e','#9c4a9c','#d06bff','#e8a0ff','#4a4a6a','#6a6a8a','#8a8aaa','#b0b0c0','#e0e0e0','#ffffff','#2a3a5a','#3a5a8a','#5a8a5a','#8ac68a','#c6a05a','#e8c68a','#ffcc66','#ff9966'],
  n64:['#212121','#424242','#616161','#757575','#9e9e9e','#bdbdbd','#e0e0e0','#fafafa','#b71c1c','#d32f2f','#f44336','#ff5252','#ff8a80','#880e4f','#c2185b','#e91e63','#f48fb1','#4a148c','#7b1fa2','#9c27b0','#e040fb','#ce93d8','#311b92','#512da8','#303f9f','#3f51b5','#7986cb','#0d47a1','#1976d2','#2196f3','#64b5f6','#01579b','#0288d1','#03a9f4','#4fc3f7','#006064','#0097a7','#00bcd4','#4dd0e1','#004d40','#00796b','#009688','#80cbc4','#1b5e20','#388e3c','#4caf50','#a5d6a7','#33691e','#689f38','#8bc34a','#c5e1a5','#827717','#afb42b','#cddc39','#e6ee9c','#f57f17','#ffa000','#ffc107','#ffecb3','#e65100','#ff6f00','#ff9800','#ffe0b2','#bf360c','#ff3d00','#ff5722','#ffab91'],
  lospec32:['#000000','#1b1a17','#5c3a21','#8b5e3c','#c28a46','#e0b07a','#f0d9b5','#ffffff','#3a3a5a','#5a5a8a','#8a8ac0','#a0c0ff','#2a5a3a','#4a8a4a','#7ac07a','#c0ffcc','#8a1a1a','#c72e2e','#ff4a4a','#ff8a8a','#7a1a4a','#c72e6a','#ff6aaa','#ffb0cc','#4a1a8a','#7a2ac7','#a04aff','#d0a0ff','#5a3a0a','#8a5a0a','#c28a0a','#ffd700'],
  rgb: null
};
let S={ w:32, h:32, size:32, pal:PAL.pico8.slice(), palN:'pico8', pix:[], col:4, tool:'brush', grid:true, mode:'pixel', zoom:1, bg:null };

// ===== ASCII 5×5 глифы =====
// макс 5×5 — █ = 25 пикселей, остальные пропорционально в той же сетке
const GLYPH5={
  '█': ["11111","11111","11111","11111","11111"],
  '▓': ["11011","10101","11011","10101","11011"],
  '▒': ["10101","01010","10101","01010","10101"],
  '░': ["10001","00000","00100","00000","10001"],
  '▆': ["00000","00000","11111","11111","11111"],
  '▄': ["00000","00000","00000","11111","11111"],
  '▀': ["11111","11111","00000","00000","00000"],
  ' ': ["00000","00000","00000","00000","00000"],
  'A': ["01110","10001","11111","10001","10001"],
  'B': ["11110","10001","11110","10001","11110"],
  'C': ["01111","10000","10000","10000","01111"],
  'D': ["11100","10010","10001","10010","11100"],
  'E': ["11111","10000","11110","10000","11111"],
  'F': ["11111","10000","11110","10000","10000"],
  'G': ["01111","10000","10111","10001","01110"],
  'H': ["10001","10001","11111","10001","10001"],
  'I': ["01110","00100","00100","00100","01110"],
  'J': ["00111","00010","00010","10010","01100"],
  'K': ["10001","10010","11100","10010","10001"],
  'L': ["10000","10000","10000","10000","11111"],
  'M': ["10001","11011","10101","10001","10001"],
  'N': ["10001","11001","10101","10011","10001"],
  'O': ["01110","10001","10001","10001","01110"],
  'P': ["11110","10001","11110","10000","10000"],
  'Q': ["01110","10001","10001","10011","01111"],
  'R': ["11110","10001","11110","10100","10010"],
  'S': ["01111","10000","01110","00001","11110"],
  'T': ["11111","00100","00100","00100","00100"],
  'U': ["10001","10001","10001","10001","01110"],
  'V': ["10001","10001","10001","01010","00100"],
  'W': ["10001","10001","10101","11011","10001"],
  'X': ["10001","01010","00100","01010","10001"],
  'Y': ["10001","01010","00100","00100","00100"],
  'Z': ["11111","00010","00100","01000","11111"],
  '0': ["01110","10011","10101","11001","01110"],
  '1': ["00100","01100","00100","00100","01110"],
  '2': ["01110","10001","00110","01000","11111"],
  '3': ["11111","00010","01100","00001","11110"],
  '4': ["10001","10001","11111","00001","00001"],
  '5': ["11111","10000","11110","00001","11110"],
  '6': ["01110","10000","11110","10001","01110"],
  '7': ["11111","00001","00010","00100","01000"],
  '8': ["01110","10001","01110","10001","01110"],
  '9': ["01110","10001","01111","00001","01110"],
  '.': ["00000","00000","00000","00000","00100"],
  ',': ["00000","00000","00000","00100","01000"],
  ':': ["00000","00100","00000","00100","00000"],
  ';': ["00000","00100","00000","00100","01000"],
  '!': ["00100","00100","00100","00000","00100"],
  '?': ["01110","10001","00110","00000","00100"],
  '/': ["00001","00010","00100","01000","10000"],
  '\\':["10000","01000","00100","00010","00001"],
  '|': ["00100","00100","00100","00100","00100"],
  '-': ["00000","00000","11111","00000","00000"],
  '_': ["00000","00000","00000","00000","11111"],
  '=': ["00000","11111","00000","11111","00000"],
  '+': ["00000","00100","01110","00100","00000"],
  '*': ["00100","10101","01110","10101","00100"],
  '#': ["01010","11111","01010","11111","01010"],
  '@': ["01110","10001","10111","10101","01110"],
  '(': ["00100","01000","01000","01000","00100"],
  ')': ["00100","00010","00010","00010","00100"],
  '[': ["01110","01000","01000","01000","01110"],
  ']': ["01110","00010","00010","00010","01110"],
  '<': ["00010","00100","01000","00100","00010"],
  '>': ["01000","00100","00010","00100","01000"],
  '^': ["00100","01010","10001","00000","00000"],
  'v': ["00000","00000","10001","01010","00100"],
  'o': ["00000","01110","10001","01110","00000"],
  'x': ["00000","10001","01110","10001","00000"],
};
const GLYPH3={
  '█': ["111","111","111"],
  '▓': ["110","101","011"],
  '▒': ["101","010","101"],
  '░': ["100","000","001"],
  ' ': ["000","000","000"],
  'A': ["010","101","111"],
  'B': ["110","101","110"],
  'o': ["010","101","010"],
};
// генерик: если нет глифа — делаем заполненный 80% блок
function getGlyph(ch, sz){
  const g = sz===3 ? GLYPH3 : GLYPH5;
  if(g[ch]) return g[ch];
  if(g[ch.toUpperCase()]) return g[ch.toUpperCase()];
  // fallback: плотность по коду символа
  const code=ch.charCodeAt(0)%5;
  if(code===0) return sz===3?["111","111","111"]:["11111","11111","11111","11111","11111"];
  if(code===1) return sz===3?["101","010","101"]:["10101","01010","10101","01010","10101"];
  return sz===3?["010","111","010"]:["00100","01110","11111","01110","00100"];
}

function init(){
  S.pix=Array(S.w*S.h).fill(null);
  buildPal();
  fetch('examples/warrior.piksel').then(r=>r.text()).then(t=>{
    if(t && t.includes('размер')){ syncCode(t); parse(true); }
    else throw 0;
  }).catch(()=>{
    syncCode(`размер 32\nпалитра pico8\n# воин — только непустые строки\n4: 12. 4 4 4 4\n5: 11. 4 4 4 4 4 4\n6: 10. 0 4 4 4 4 4 0\n7: 10. 0 4 15 15 15 4 0\n11: 9. 0 6 6 6 6 6 6 6 0\n12: 8. 8 8 0 6 9 6 6 9 6 0\n13: 7. 8 8 8 0 6 6 6 6 6 0\ncheck палитра ≤16\n`);
    parse(true);
  });
  bind();
  updateZoomLabel();
}
function syncCode(v){ code.value=v; updateGutter(); }
function updateGutter(){
  const n=code.value.split('\n').length;
  gutter.innerHTML = Array.from({length:Math.max(10,n)},(_,i)=>i+1).join('<br>');
}
function buildPal(){
  const d=$('palDock'); d.innerHTML='';
  if(S.palN==='rgb'){
    const wrap=document.createElement('div'); wrap.style.cssText='display:flex;align-items:center;gap:8px;flex-wrap:wrap';
    wrap.innerHTML=`<input type="color" id="rgbPick" value="${S.customColor||'#ff7a45'}" style="width:28px;height:28px;padding:0;border:1px solid var(--line);border-radius:999px;overflow:hidden"> <span style="font-size:11px;color:var(--muted)">любой RGB · градиенты</span> <button class="pill" id="addRgb" style="padding:4px 10px;font-size:11px">+ добавить</button>`;
    d.appendChild(wrap);
    if(!S.rgbHistory) S.rgbHistory=['#ff7a45','#ffb347','#7ec8a0','#6b8cff','#ff4a4a','#ffffff'];
    S.rgbHistory.forEach((c,i)=>{
      const b=document.createElement('div'); b.className='sw'; b.style.background=c;
      b.title=c; b.onclick=()=>{ S.customColor=c; S.col=i; toast('цвет '+c); };
      d.appendChild(b);
    });
    setTimeout(()=>{
      const pk=document.getElementById('rgbPick');
      if(pk) pk.oninput=e=>{ S.customColor=e.target.value; };
      const ad=document.getElementById('addRgb');
      if(ad) ad.onclick=()=>{
        const v=document.getElementById('rgbPick')?.value || '#ff0000';
        S.rgbHistory.unshift(v); S.rgbHistory=S.rgbHistory.slice(0,16);
        S.customColor=v; buildPal();
      };
    },0);
  } else {
    S.pal.forEach((c,i)=>{
      const b=document.createElement('div'); b.className='sw'; b.style.background=c;
      if(i===S.col) b.classList.add('active');
      b.title=i+': '+c; b.onclick=()=>{ S.col=i; buildPal(); };
      d.appendChild(b);
    });
    const lbl=document.createElement('span'); lbl.className='pal-label'; lbl.textContent=`цвет ${S.col} · клик по палитре меняет кисть`;
    d.appendChild(lbl);
  }
  const bgWrap=document.createElement('span'); bgWrap.style.cssText='margin-left:12px;display:flex;align-items:center;gap:6px;border-left:1px solid var(--line);padding-left:10px';
  bgWrap.innerHTML=`фон <input type="color" id="bgInput" value="${S.bg||'#0B0E13'}" style="width:26px;height:22px;padding:0;border:1px solid var(--line);border-radius:6px;background:transparent"> <button class="pill" id="bgClear" style="padding:4px 8px;font-size:11px">прозрачно</button>`;
  d.appendChild(bgWrap);
  setTimeout(()=>{
    const inp=document.getElementById('bgInput');
    if(inp){ inp.oninput=e=>{ S.bg=e.target.value; render(); syncBgToCode(); }; inp.value=S.bg||'#0B0E13'; }
    const clr=document.getElementById('bgClear');
    if(clr) clr.onclick=()=>{ S.bg=null; render(); syncBgToCode(); };
  },0);
}
function syncBgToCode(){
  let txt=code.value;
  const bgLine = S.bg ? `фон ${S.bg}` : `фон прозрачно`;
  if(/фон\s+/.test(txt)) txt=txt.replace(/фон\s+[^\n]+/, bgLine);
  else txt=txt.replace(/палитра[^\n]+/, m=>m+'\n'+bgLine);
  if(txt!==code.value){ code.value=txt; updateGutter(); }
}
function parseSize(txt){
  let m=txt.match(/размер\s+(\d+)\s*[x×]\s*(\d+)/i);
  if(m){ S.w = Math.min(256,Math.max(3,parseInt(m[1]))); S.h = Math.min(256,Math.max(3,parseInt(m[2]))); S.size=Math.max(S.w,S.h); return; }
  m=txt.match(/размер\s+(\d+)\s+(\d+)/i);
  if(m){ S.w = Math.min(256,Math.max(3,parseInt(m[1]))); S.h = Math.min(256,Math.max(3,parseInt(m[2]))); S.size=Math.max(S.w,S.h); return; }
  m=txt.match(/размер\s+(\d+)/i);
  if(m){ S.w=S.h=Math.min(256,Math.max(3,parseInt(m[1]))); S.size=S.w; }
}
function parse(showOk=false){
  const txt=code.value;
  parseSize(txt);
  S.pix=Array(S.w*S.h).fill(null);
  let mp=txt.match(/палитра\s+(\w+)/i); if(mp){
    const name=mp[1].toLowerCase();
    if(name==='rgb'){ S.pal=null; S.palN='rgb'; buildPal(); }
    else if(PAL[name]){ S.pal=PAL[name].slice(); S.palN=name; buildPal(); }
  }
  let bgLine = txt.split('\n').find(l=>l.trim().startsWith('фон'));
  if(bgLine){
    let v=bgLine.trim().split(/\s+/)[1]||'';
    if(/прозрачн/i.test(v)) S.bg=null;
    else if(v.startsWith('#')) S.bg=v;
    else if(/^\d+$/.test(v)) S.bg=PAL[S.palN]?.[parseInt(v)]||v;
  }
  let errs=[];
  txt.split('\n').forEach((raw,idx)=>{
    const l=raw.trim(); if(!l||l.startsWith('#')||l.startsWith('размер')||l.startsWith('палитра')||l.startsWith('фон')||l.startsWith('check')) return;
    let mm=l.match(/^(\d+)\s*:\s*(\d+)\s*\.\s*(.+)$/)||l.match(/^(\d+)\s+(\d+)\s*:\s*(.+)$/);
    if(!mm) return;
    let r=parseInt(mm[1]), c=parseInt(mm[2]), rest=mm[3].trim();
    if(r>=S.h||c>=S.w){ errs.push(`стр ${idx+1}: вне ${S.w}×${S.h} (r${r} c${c})`); return; }
    let cc=c;
    rest.split(/\s+/).forEach(t=>{
      if(cc>=S.w) return;
      let rep=1; let mx=t.match(/^(\d+)x(.+)$/); if(mx){ rep=parseInt(mx[1]); t=mx[2]; }
      else { let md=t.match(/^(\d+)-$/); if(md){ rep=parseInt(md[1]); t='-'; } }
      if(t==='-'||t==='—'){ cc+=rep; return; }
      for(let k=0;k<rep;k++){ if(cc>=S.w) break; let col=null; if(t.startsWith('#')) col=t; else if(/^\d+$/.test(t)) col=S.pal? (S.pal[parseInt(t)]||'#fff') : '#fff'; if(col) S.pix[r*S.w+cc]=col; cc++; }
    });
  });
  const used=new Set(S.pix.filter(Boolean));
  const ok = errs.length===0;
  $('dot').className='dot '+(ok? (used.size===0?'warn':'ok'):'bad');
  $('msg').textContent = errs.length? errs[0] : (used.size? `${used.size} цветов · ${S.w}×${S.h} · готово` : `пусто — вставь сценарий · ${S.w}×${S.h}`);
  $('msg').style.color = ok? 'var(--muted)' : 'var(--bad)';
  updateSizeInputs();
  render();
  if(showOk && ok) toast('Собрано');
}
function render(){
  const Nw=S.w, Nh=S.h;
  const stage=document.getElementById('stage');
  const availW = Math.max(280, (stage?.clientWidth||520) - 40);
  const availH = 420;
  const fitPxW = Math.floor(availW / Nw);
  const fitPxH = Math.floor(availH / Nh);
  let basePx = Math.min(fitPxW, fitPxH);
  if(S.mode==='split'){
    const fitSplitW = Math.floor((availW-16) / 2 / Math.max(Nw,1));
    basePx = Math.min(fitPxW, fitPxH, fitSplitW);
  }
  basePx = Math.max(2, Math.min(24, basePx));
  const px = Math.max(1, Math.min(32, Math.round(basePx * S.zoom)));
  const W=Nw*px, H=Nh*px;
  [pc,hc].forEach(c=>{
    c.width=W; c.height=H;
    c.style.width=W+'px';
    c.style.height=H+'px';
    c.style.imageRendering='pixelated';
  });
  pctx.imageSmoothingEnabled=false;
  if(S.bg){ pctx.fillStyle=S.bg; pctx.fillRect(0,0,W,H); }
  else { pctx.fillStyle='#0B0E13'; pctx.fillRect(0,0,W,H); }
  for(let y=0;y<Nh;y++)for(let x=0;x<Nw;x++){ const col=S.pix[y*Nw+x]; if(col){ pctx.fillStyle=col; pctx.fillRect(x*px,y*px,px,px);} }
  if(S.grid && Math.max(Nw,Nh)<=96){
    pctx.strokeStyle='rgba(255,255,255,.055)'; pctx.lineWidth=1;
    for(let i=0;i<=Nw;i++){ const p=i*px+0.5; pctx.beginPath(); pctx.moveTo(p,0); pctx.lineTo(p,H); pctx.stroke(); }
    for(let i=0;i<=Nh;i++){ const p=i*px+0.5; pctx.beginPath(); pctx.moveTo(0,p); pctx.lineTo(W,p); pctx.stroke(); }
  }
  const hdPx = Math.max(1, Math.floor(px/2));
  const tmp=document.createElement('canvas'); tmp.width=Nw; tmp.height=Nh; const tc=tmp.getContext('2d');
  tc.imageSmoothingEnabled=false;
  for(let y=0;y<Nh;y++)for(let x=0;x<Nw;x++){ const c=S.pix[y*Nw+x]; if(c){ tc.fillStyle=c; tc.fillRect(x,y,1,1);} }
  hctx.imageSmoothingEnabled=false;
  hctx.clearRect(0,0,W,H);
  if(S.bg){ hctx.fillStyle=S.bg; hctx.fillRect(0,0,W,H); } else { hctx.fillStyle='#0B0E13'; hctx.fillRect(0,0,W,H); }
  const HDW=Nw*2*hdPx, HDH=Nh*2*hdPx;
  if(HDW<=W && HDH<=H){
    const ox=Math.floor((W-HDW)/2), oy=Math.floor((H-HDH)/2);
    hctx.drawImage(tmp,0,0,Nw,Nh, ox,oy,HDW,HDH);
  } else {
    hctx.drawImage(tmp,0,0,W,H);
  }
  const wrapPixel=document.getElementById('wrapPixel');
  const wrapHD=document.getElementById('wrapHD');
  if(S.mode==='pixel'){ wrapPixel.hidden=false; wrapHD.hidden=true; }
  else if(S.mode==='hd'){ wrapPixel.hidden=true; wrapHD.hidden=false; }
  else { wrapPixel.hidden=false; wrapHD.hidden=false; }
}

function toast(s){ const t=document.createElement('div'); t.textContent=s; t.style.cssText='position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--surface);border:1px solid var(--line);padding:10px 14px;border-radius:999px;box-shadow:var(--shadow);font-size:12.5px'; document.body.appendChild(t); setTimeout(()=>t.remove(),1600); }

function updateSizeInputs(){
  const w=$('sizeW'), h=$('sizeH');
  if(w) w.value=S.w;
  if(h) h.value=S.h;
  const sel=$('sizePreset');
  if(sel){
    const cur=`${S.w}x${S.h}`;
    let found=false;
    for(let o of sel.options) if(o.value===cur){ sel.value=cur; found=true; break; }
    if(!found) sel.value="";
  }
}
function updateZoomLabel(){ const el=document.getElementById('zoomVal'); if(el) el.textContent=Math.round(S.zoom*100)+'%'; }

// ===== ASCII → пиксели =====
function buildAsciiLegend(){
  const txt=$('asciiInput').value;
  if(!txt.trim()){ $('asciiLegend').innerHTML='<span class="muted" style="font-size:11px">вставь ASCII — тут появятся цвета</span>'; return; }
  const uniq=[...new Set([...txt].filter(ch=>ch!=='\n' && ch!=='\r'))].sort();
  const legend=$('asciiLegend'); legend.innerHTML='';
  // палитра по умолчанию — берем из S.pal или rgbHistory
  const defaults = S.pal ? S.pal : (S.rgbHistory||['#ff7a45','#ffb347','#7ec8a0','#6b8cff','#ff4a4a','#ffffff']);
  uniq.forEach((ch,i)=>{
    const wrap=document.createElement('span'); wrap.style.cssText='display:flex;align-items:center;gap:4px;background:var(--surface-3);padding:4px 8px;border-radius:999px;border:1px solid var(--line)';
    const col = defaults[i % defaults.length];
    wrap.innerHTML=`<span style="font-family:var(--mono);font-size:12px;min-width:14px;text-align:center">${ch===' ' ? '␣' : ch}</span><input type="color" data-ch="${ch}" value="${col}" style="width:22px;height:18px;padding:0;border:0;border-radius:4px">`;
    legend.appendChild(wrap);
  });
  legend.querySelectorAll('input[type=color]').forEach(inp=> inp.oninput=e=>{
    // live preview optional
  });
}
function asciiToPiksel(){
  const txt=$('asciiInput').value;
  if(!txt.trim()){ toast('Вставь ASCII'); return; }
  const sz=parseInt($('glyphSize').value)||5;
  const lines=txt.split('\n');
  // убрать пустые строки в конце/начале но сохранить внутренние
  while(lines.length && lines[0].trim()==='') lines.shift();
  while(lines.length && lines[lines.length-1].trim()==='') lines.pop();
  const H = lines.length;
  const Wchars = Math.max(...lines.map(l=>[...l].length));
  const W = Wchars*sz, Hpx = H*sz;
  if(W>256||Hpx>256){ toast(`Слишком большой ${W}×${Hpx} — макс 256, укороти ASCII или выбери 3×3`); return; }
  // цвета из легенды
  const colMap={};
  document.querySelectorAll('#asciiLegend input[type=color]').forEach(inp=> colMap[inp.dataset.ch]=inp.value);
  const defaults = S.pal ? S.pal : (S.rgbHistory||['#ff7a45']);
  // fallback для неизвестных
  // строим пиксели
  const pix=Array(W*Hpx).fill(null);
  lines.forEach((line, ay)=>{
    [...line].forEach((ch, ax)=>{
      if(ch===' '||ch==='\r') return;
      const col = colMap[ch] || defaults[ (ch.charCodeAt(0)%defaults.length) ];
      const glyph=getGlyph(ch, sz);
      for(let dy=0; dy<sz; dy++){
        for(let dx=0; dx<sz; dx++){
          if(glyph[dy][dx]==='1'){
            const px = ax*sz + dx;
            const py = ay*sz + dy;
            if(px<W && py<Hpx) pix[py*W+px]=col;
          }
        }
      }
    });
  });
  // генерируем DSL
  let out=[];
  out.push(`# ASCII ${Wchars}×${H} → ${W}×${Hpx} glyph ${sz}×${sz}`);
  out.push(`размер ${W}x${Hpx}`);
  out.push(`палитра ${S.palN}`);
  out.push(S.bg? `фон ${S.bg}`: `фон прозрачно`);
  for(let y=0;y<Hpx;y++){
    // собрать runs
    let runs=[]; let x=0;
    while(x<W){
      if(!pix[y*W+x]){ // прозрачные скипаем, но нужно через N- или смещать c.
        // считаем пропуск
        let j=x;
        while(j<W && !pix[y*W+j]) j++;
        // пропускаем — не пишем, следующий c будет j
        // но для сохранения позиции нужно начать новую запись? нет, Row-RLE: c — начальный столбец, дальше идут цвета подряд
        // поэтому если есть пропуск в середине, используем N- 
        if(runs.length===0){
          // ведущий пропуск — просто смещаем начальный c
          x=j; continue;
        } else {
          // внутренний пропуск — кодируем как N-
          runs.push(`${j-x}-`);
          x=j;
          continue;
        }
      }
      // цветной run
      let col=pix[y*W+x];
      let j=x;
      while(j<W && pix[y*W+j]===col) j++;
      const cnt=j-x;
      runs.push(cnt===1? col : `${cnt}x${col}`);
      x=j;
    }
    if(runs.length){
      // найти первый цветной x
      let firstX=0;
      // находим первый не-прозрачный
      for(let xi=0; xi<W; xi++) if(pix[y*W+xi]){ firstX=xi; break; }
      out.push(`${y}: ${firstX}. `+runs.join(' '));
    }
  }
  out.push(`check размер ${W}x${Hpx}`);
  const dsl=out.join('\n');
  syncCode(dsl); parse(true);
  // обновить размер инпуты
  S.w=W; S.h=Hpx;
  toast(`ASCII → ${W}×${Hpx} готово`);
}

function bind(){
  let tid=null;
  code.addEventListener('input', ()=>{ updateGutter(); clearTimeout(tid); tid=setTimeout(()=>parse(false),400); });
  code.addEventListener('keydown', e=>{ if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){ e.preventDefault(); parse(true);} });
  $('buildBtn').onclick=()=>parse(true);
  const sizeW=$('sizeW'), sizeH=$('sizeH'), applySize=$('applySize');
  if(applySize) applySize.onclick=()=>{
    const w=Math.min(256,Math.max(3,parseInt(sizeW.value)||32));
    const h=Math.min(256,Math.max(3,parseInt(sizeH.value)||32));
    code.value=code.value.replace(/размер\s+[^\n]+/,`размер ${w}x${h}`);
    parse(true);
  };
  if(sizeW) sizeW.addEventListener('keydown', e=>{ if(e.key==='Enter'){ e.preventDefault(); applySize.click(); }});
  if(sizeH) sizeH.addEventListener('keydown', e=>{ if(e.key==='Enter'){ e.preventDefault(); applySize.click(); }});
  const preset=$('sizePreset');
  if(preset) preset.onchange=e=>{
    const v=e.target.value; if(!v) return;
    code.value=code.value.replace(/размер\s+[^\n]+/,`размер ${v}`);
    parse(true);
  };
  $('palSel').onchange=e=>{ const v=e.target.value; code.value=code.value.replace(/палитра\s+\w+.*/,`палитра ${v}`); parse(true); };
  const bgTop=$('bgTop'); if(bgTop) bgTop.oninput=e=>{ S.bg=e.target.value; render(); syncBgToCode(); };
  document.querySelectorAll('#modeSeg button').forEach(b=> b.onclick=()=>{ document.querySelectorAll('#modeSeg button').forEach(x=>x.classList.remove('active')); b.classList.add('active'); S.mode=b.dataset.m; render(); });
  document.querySelectorAll('#tools .tool').forEach(b=> b.onclick=()=>{ if(b.dataset.t){ document.querySelectorAll('#tools .tool').forEach(x=>x.classList.remove('active')); b.classList.add('active'); S.tool=b.dataset.t; pc.style.cursor=S.tool==='brush'?'crosshair': S.tool==='pick'?'copy':'default'; } });
  $('gridBtn').onclick=()=>{ S.grid=!S.grid; $('gridBtn').classList.toggle('active',S.grid); render(); };
  $('clearBtn').onclick=()=>{ code.value=`размер ${S.w}x${S.h}\nпалитра ${S.palN}\n`; parse(true); };
  $('copyBtn').onclick=()=>{ navigator.clipboard.writeText(code.value); toast('Сценарий скопирован'); };
  $('exportBtn').onclick=()=>{ const a=document.createElement('a'); a.download='piksel.png'; a.href=pc.toDataURL('image/png'); a.click(); toast('PNG сохранён'); };
  $('exBtn').onclick=()=> $('exMenu').classList.toggle('open');
  $('exMenu').querySelectorAll('button').forEach(b=> b.onclick=()=>{
    $('exMenu').classList.remove('open');
    if(b.dataset.ex==='warrior') fetch('examples/warrior.piksel').then(r=>{ if(!r.ok) throw new Error(r.status); return r.text(); }).then(t=>{ if(t.trim().startsWith('<!DOCTYPE')) throw new Error('got html'); syncCode(t); parse(true); toast('Рыцарь загружен'); }).catch(()=>{ toast('Пример не найден'); });
    else if(b.dataset.ex==='landscape') fetch('examples/landscape.piksel').then(r=>{ if(!r.ok) throw new Error(r.status); return r.text(); }).then(t=>{ syncCode(t); parse(true); toast('Пейзаж загружен'); }).catch(()=>toast('нет файла'));
    else if(b.dataset.ex==='rem') fetch('examples/rem.piksel').then(r=>{ if(!r.ok) throw new Error(r.status); return r.text(); }).then(t=>{ syncCode(t); parse(true); toast('Рем загружена'); }).catch(()=>toast('нет файла'));
    else if(b.dataset.ex==='emilia') fetch('examples/emilia.piksel').then(r=>{ if(!r.ok) throw new Error(r.status); return r.text(); }).then(t=>{ syncCode(t); parse(true); toast('Эмилия загружена'); }).catch(()=>toast('нет файла'));
    else if(b.dataset.ex==='rem_face') fetch('examples/rem_face.piksel').then(r=>{ if(!r.ok) throw new Error(r.status); return r.text(); }).then(t=>{ syncCode(t); parse(true); toast('Рем лицо 120 загружено'); }).catch(()=>toast('нет файла'));
    else if(b.dataset.ex==='blank') { syncCode(`размер 32x32\nпалитра pico8\n`); parse(true); }
    else toast('Скоро');
  });
  $('plus').onclick=()=>{ S.zoom=Math.min(2.4,S.zoom*1.15); updateZoomLabel(); render(); };
  $('minus').onclick=()=>{ S.zoom=Math.max(.5,S.zoom/1.15); updateZoomLabel(); render(); };
  // ASCII panel
  const asciiBtn=$('asciiBtn'), asciiPanel=$('asciiPanel'), asciiClose=$('asciiClose');
  if(asciiBtn) asciiBtn.onclick=()=>{ asciiPanel.style.display = asciiPanel.style.display==='none'||!asciiPanel.style.display ? 'flex':'none'; buildAsciiLegend(); };
  if(asciiClose) asciiClose.onclick=()=> asciiPanel.style.display='none';
  const ai=$('asciiInput');
  if(ai) ai.addEventListener('input', ()=>{ clearTimeout(ai._tid); ai._tid=setTimeout(buildAsciiLegend, 400); });
  const conv=$('asciiConvert');
  if(conv) conv.onclick=asciiToPiksel;
  const gs=$('glyphSize');
  if(gs) gs.onchange=buildAsciiLegend;
  pc.addEventListener('click', e=>{
    const rect=pc.getBoundingClientRect(), Nw=S.w, Nh=S.h;
    const x=Math.floor((e.clientX-rect.left)/rect.width*Nw), y=Math.floor((e.clientY-rect.top)/rect.height*Nh);
    if(x<0||y<0||x>=Nw||y>=Nh) return;
    const curCol = S.pix[y*Nw+x];
    if(S.tool==='pick'){
      if(curCol){
        S.customColor=curCol;
        let idx=S.pal ? S.pal.indexOf(curCol) : -1;
        if(idx>=0) S.col=idx;
        buildPal();
        S.tool='brush';
        document.querySelectorAll('#tools .tool').forEach(el=>el.classList.remove('active'));
        const br=document.querySelector('[data-t=brush]'); if(br) br.classList.add('active');
        pc.style.cursor='crosshair';
        toast('Пипетка: '+curCol);
        const inp=document.getElementById('rgbPick'); if(inp) inp.value=curCol;
      } else toast('Прозрачно');
      return;
    }
    if(S.tool==='eraser'){ S.pix[y*Nw+x]=null; } else { const col = S.palN==='rgb' ? (S.customColor||'#ff7a45') : (S.pal?.[S.col]||'#fff'); S.pix[y*Nw+x]=col; }
    render(); updateMsgPicked(x,y,curCol);
  });
}
function updateMsgPicked(x,y,c){ $('msg').textContent=`пиксель ${x},${y} ${c||'прозрачно'} → правь в сценарии`; }

init();
updateGutter();
