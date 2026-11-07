// ПИКСЕЛЬ v3 — живой парсер row-RLE + один канвас + HD таб
const $=id=>document.getElementById(id);
const code=$('code'), gutter=$('gutter'), pc=$('pixelCanvas'), hc=$('hdCanvas'), pctx=pc.getContext('2d'), hctx=hc.getContext('2d');
const PAL={
  pico8:['#000000','#1D2B53','#7E2553','#008751','#AB5236','#5F574F','#C2C3C5','#FFF1E8','#FF004D','#FFA300','#FFEC27','#00E436','#29ADFF','#83769C','#FF77A8','#FFCCAA'],
  gameboy:['#0f380f','#306230','#8bac0f','#9bbc0f'],
  sweet16:['#1a1c2c','#5d275d','#b13e53','#ef7d57','#ffcd75','#a7f070','#38b764','#257179','#29366f','#3b5dc9','#41a6f6','#73eff7','#f4f4f4','#94b0c2','#566c86','#333c57'],
  // пошире — 32 и 48 цветов (популярные Lospec)
  endesga32:['#000000','#1b1a17','#5a3921','#8a5a44','#a06d3f','#d9a066','#e5c07b','#f2e8b5','#6b8cff','#a0c0ff','#4a9c6d','#7ec8a0','#c94a4a','#ff6b6b','#ff9e9e','#9c4a9c','#d06bff','#e8a0ff','#4a4a6a','#6a6a8a','#8a8aaa','#b0b0c0','#e0e0e0','#ffffff','#2a3a5a','#3a5a8a','#5a8a5a','#8ac68a','#c6a05a','#e8c68a','#ffcc66','#ff9966'],
  n64:['#212121','#424242','#616161','#757575','#9e9e9e','#bdbdbd','#e0e0e0','#fafafa','#b71c1c','#d32f2f','#f44336','#ff5252','#ff8a80','#880e4f','#c2185b','#e91e63','#f48fb1','#4a148c','#7b1fa2','#9c27b0','#e040fb','#ce93d8','#311b92','#512da8','#303f9f','#3f51b5','#7986cb','#0d47a1','#1976d2','#2196f3','#64b5f6','#01579b','#0288d1','#03a9f4','#4fc3f7','#006064','#0097a7','#00bcd4','#4dd0e1','#004d40','#00796b','#009688','#80cbc4','#1b5e20','#388e3c','#4caf50','#a5d6a7','#33691e','#689f38','#8bc34a','#c5e1a5','#827717','#afb42b','#cddc39','#e6ee9c','#f57f17','#ffa000','#ffc107','#ffecb3','#e65100','#ff6f00','#ff9800','#ffe0b2','#bf360c','#ff3d00','#ff5722','#ffab91'],
  lospec32:['#000000','#1b1a17','#5c3a21','#8b5e3c','#c28a46','#e0b07a','#f0d9b5','#ffffff','#3a3a5a','#5a5a8a','#8a8ac0','#a0c0ff','#2a5a3a','#4a8a4a','#7ac07a','#c0ffcc','#8a1a1a','#c72e2e','#ff4a4a','#ff8a8a','#7a1a4a','#c72e6a','#ff6aaa','#ffb0cc','#4a1a8a','#7a2ac7','#a04aff','#d0a0ff','#5a3a0a','#8a5a0a','#c28a0a','#ffd700'],
  // полный RGB — без ограничений, для градиентов
  rgb: null
};
let S={ size:32, pal:PAL.pico8.slice(), palN:'pico8', pix:[], col:4, tool:'brush', grid:true, mode:'pixel', zoom:1.6, bg:null };

function init(){
  S.pix=Array(S.size*S.size).fill(null);
  buildPal();
  // грузим настоящего воина из файла, если есть
  fetch('examples/warrior.piksel').then(r=>r.text()).then(t=>{
    if(t && t.includes('размер')){ syncCode(t); parse(true); }
    else throw 0;
  }).catch(()=>{
    syncCode(`размер 32\nпалитра pico8\n# воин — только непустые строки\n4: 12. 4 4 4 4\n5: 11. 4 4 4 4 4 4\n6: 10. 0 4 4 4 4 4 0\n7: 10. 0 4 15 15 15 4 0\n11: 9. 0 6 6 6 6 6 6 6 0\n12: 8. 8 8 0 6 9 6 6 9 6 0\n13: 7. 8 8 8 0 6 6 6 6 6 0\ncheck палитра ≤16\n`);
    parse(true);
  });
  bind();
}
function syncCode(v){ code.value=v; updateGutter(); }
function updateGutter(){
  const n=code.value.split('\n').length;
  gutter.innerHTML = Array.from({length:Math.max(10,n)},(_,i)=>i+1).join('<br>');
}
function buildPal(){
  const d=$('palDock'); d.innerHTML='';
  if(S.palN==='rgb'){
    // полный RGB — палитра без лимита + пипетка
    const wrap=document.createElement('div'); wrap.style.cssText='display:flex;align-items:center;gap:8px;flex-wrap:wrap';
    wrap.innerHTML=`<input type="color" id="rgbPick" value="${S.pal?.[S.col]||'#ff7a45'}" style="width:28px;height:28px;padding:0;border:1px solid var(--line);border-radius:999px;overflow:hidden"> <span style="font-size:11px;color:var(--muted)">любой RGB · градиенты</span> <button class="pill" id="addRgb" style="padding:4px 10px;font-size:11px">+ добавить</button>`;
    d.appendChild(wrap);
    // недавние цвета
    if(!S.rgbHistory) S.rgbHistory=['#ff7a45','#ffb347','#7ec8a0','#6b8cff','#ff4a4a','#ffffff'];
    S.rgbHistory.forEach((c,i)=>{
      const b=document.createElement('div'); b.className='sw'; b.style.background=c;
      b.title=c; b.onclick=()=>{ S.customColor=c; S.col=i; buildPal(); };
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
  // фон всегда
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
function parse(showOk=false){
  const txt=code.value;
  let m=txt.match(/размер\s+(\d+)/i); if(m){ S.size=Math.min(64,Math.max(8,parseInt(m[1]))); S.pix=Array(S.size*S.size).fill(null); }
  let mp=txt.match(/палитра\s+(\w+)/i); if(mp){
    const name=mp[1].toLowerCase();
    if(name==='rgb'){ S.pal=null; S.palN='rgb'; buildPal(); }
    else if(PAL[name]){ S.pal=PAL[name].slice(); S.palN=name; buildPal(); }
  }
  // фон: фон #RRGGBB или фон 3 (индекс) или фон прозрачно
  let mb=txt.match(/фон\s+([^\n#]+#[0-9a-fA-F]{3,8}|фон\s+\d+|фон\s+прозрачно)/i);
  // более просто: ищем строку фон ...
  let bgLine = txt.split('\n').find(l=>l.trim().startsWith('фон'));
  if(bgLine){
    let v=bgLine.trim().split(/\s+/)[1]||'';
    if(/прозрачн/i.test(v)) S.bg=null;
    else if(v.startsWith('#')) S.bg=v;
    else if(/^\d+$/.test(v)) S.bg=PAL[S.palN]?.[parseInt(v)]||v;
    else if(v.startsWith('#')) S.bg=v;
  }
  S.pix=Array(S.size*S.size).fill(null);
  let errs=[];
  txt.split('\n').forEach((raw,idx)=>{
    const l=raw.trim(); if(!l||l.startsWith('#')||l.startsWith('размер')||l.startsWith('палитра')||l.startsWith('check')) return;
    let mm=l.match(/^(\d+)\s*:\s*(\d+)\s*\.\s*(.+)$/)||l.match(/^(\d+)\s+(\d+)\s*:\s*(.+)$/);
    if(!mm) return;
    let r=parseInt(mm[1]), c=parseInt(mm[2]), rest=mm[3].trim();
    if(r>=S.size||c>=S.size){ errs.push(`стр ${idx+1}: вне ${S.size}`); return; }
    let cc=c;
    rest.split(/\s+/).forEach(t=>{
      if(cc>=S.size) return;
      let rep=1; let mx=t.match(/^(\d+)x(.+)$/); if(mx){ rep=parseInt(mx[1]); t=mx[2]; }
      else { let md=t.match(/^(\d+)-$/); if(md){ rep=parseInt(md[1]); t='-'; } }
      if(t==='-'||t==='—'){ cc+=rep; return; }
      for(let k=0;k<rep;k++){ if(cc>=S.size) break; let col=null; if(t.startsWith('#')) col=t; else if(/^\d+$/.test(t)) col=S.pal[parseInt(t)]||'#fff'; if(col) S.pix[r*S.size+cc]=col; cc++; }
    });
  });
  const used=new Set(S.pix.filter(Boolean));
  const ok = errs.length===0;
  $('dot').className='dot '+(ok? (used.size===0?'warn':'ok'):'bad');
  $('msg').textContent = errs.length? errs[0] : (used.size? `${used.size} цветов · ${S.size}×${S.size} · готово` : 'пусто — вставь сценарий');
  $('msg').style.color = ok? 'var(--muted)' : 'var(--bad)';
  // живой ререндер
  render();
  if(showOk && ok) toast('Собрано');
  // gutter error line highlight could be added
}
function render(){
  const N=S.size;
  // НОРМАЛИЗОВАННЫЙ КВАДРАТ: один px = одинаков по X и Y, без растягивания
  const basePx = 10; // базовый размер пикселя для 32x32 → 320px квадрат
  const px = Math.max(6, Math.min(18, Math.round(basePx * S.zoom)));
  const W=N*px, H=N*px; // строго квадрат!
  [pc,hc].forEach(c=>{
    c.width=W; c.height=H;
    // CSS размер — тоже квадрат, вписан в контейнер 380px
    c.style.width=W+'px';
    c.style.height=H+'px';
    c.style.imageRendering='pixelated';
  });
  // пиксель — чёткий (фон любой)
  pctx.imageSmoothingEnabled=false;
  if(S.bg){ pctx.fillStyle=S.bg; pctx.fillRect(0,0,W,H); }
  else { // прозрачно — тёмный
    pctx.fillStyle='#0B0E13'; pctx.fillRect(0,0,W,H);
  }
  for(let y=0;y<N;y++)for(let x=0;x<N;x++){ const col=S.pix[y*N+x]; if(col){ pctx.fillStyle=col; pctx.fillRect(x*px,y*px,px,px);} }
  if(S.grid && N<=64){
    pctx.strokeStyle='rgba(255,255,255,.055)'; pctx.lineWidth=1;
    for(let i=0;i<=N;i++){
      const p=i*px+0.5;
      pctx.beginPath(); pctx.moveTo(p,0); pctx.lineTo(p,H); pctx.stroke();
      pctx.beginPath(); pctx.moveTo(0,p); pctx.lineTo(W,p); pctx.stroke();
    }
  }
  // HD — тот же квадрат, nearest
  const scale=4, HD=N*scale;
  // для HD тот же px/2 чтобы влез в тот же W,H (визуально крупнее, но квадрат)
  const hdPx = Math.max(2, Math.floor(px/2));
  const tmp=document.createElement('canvas'); tmp.width=N; tmp.height=N; const tc=tmp.getContext('2d');
  tc.imageSmoothingEnabled=false;
  for(let y=0;y<N;y++)for(let x=0;x<N;x++){ const c=S.pix[y*N+x]; if(c){ tc.fillStyle=c; tc.fillRect(x,y,1,1);} }
  hctx.imageSmoothingEnabled=false;
  hctx.clearRect(0,0,W,H);
  // рисуем HD ровно в центр квадрата, без растягивания
  const HDW=HD*hdPx, HDH=HD*hdPx;
  const ox=Math.floor((W-HDW)/2), oy=Math.floor((H-HDH)/2);
  if(HDW<=W) hctx.drawImage(tmp,0,0,N,N, ox,oy,HDW,HDH);
  else hctx.drawImage(tmp,0,0,W,H);
  // сравнение: пиксель / HD / рядом
  const wrapPixel=document.getElementById('wrapPixel');
  const wrapHD=document.getElementById('wrapHD');
  if(S.mode==='pixel'){ wrapPixel.hidden=false; wrapHD.hidden=true; }
  else if(S.mode==='hd'){ wrapPixel.hidden=true; wrapHD.hidden=false; }
  else { // Сравн. — показываем оба рядом
    wrapPixel.hidden=false; wrapHD.hidden=false;
  }
}

function toast(s){ const t=document.createElement('div'); t.textContent=s; t.style.cssText='position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--surface);border:1px solid var(--line);padding:10px 14px;border-radius:999px;box-shadow:var(--shadow);font-size:12.5px'; document.body.appendChild(t); setTimeout(()=>t.remove(),1600); }

function bind(){
  let tid=null;
  code.addEventListener('input', ()=>{ updateGutter(); clearTimeout(tid); tid=setTimeout(()=>parse(false),400); });
  code.addEventListener('keydown', e=>{ if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){ e.preventDefault(); parse(true);} });
  $('buildBtn').onclick=()=>parse(true);
  $('sizeSel').onchange=e=>{ const v=parseInt(e.target.value); code.value=code.value.replace(/размер\s+\d+/,`размер ${v}`); parse(true); };
  $('palSel').onchange=e=>{ const v=e.target.value; code.value=code.value.replace(/палитра\s+\w+.*/,`палитра ${v}`); parse(true); };
  const bgTop=$('bgTop'); if(bgTop) bgTop.oninput=e=>{ S.bg=e.target.value; render(); syncBgToCode(); };
  document.querySelectorAll('#modeSeg button').forEach(b=> b.onclick=()=>{ document.querySelectorAll('#modeSeg button').forEach(x=>x.classList.remove('active')); b.classList.add('active'); S.mode=b.dataset.m; render(); });
  document.querySelectorAll('#tools .tool').forEach(b=> b.onclick=()=>{ if(b.dataset.t){ document.querySelectorAll('#tools .tool').forEach(x=>x.classList.remove('active')); b.classList.add('active'); S.tool=b.dataset.t; pc.style.cursor=S.tool==='brush'?'crosshair':'default'; } });
  $('gridBtn').onclick=()=>{ S.grid=!S.grid; $('gridBtn').classList.toggle('active',S.grid); render(); };
  $('clearBtn').onclick=()=>{ code.value=`размер ${S.size}\nпалитра ${S.palN}\n`; parse(true); };
  $('copyBtn').onclick=()=>{ navigator.clipboard.writeText(code.value); toast('Сценарий скопирован'); };
  $('exportBtn').onclick=()=>{ const a=document.createElement('a'); a.download='piksel.png'; a.href=pc.toDataURL('image/png'); a.click(); toast('PNG сохранён'); };
  $('exBtn').onclick=()=> $('exMenu').classList.toggle('open');
  $('exMenu').querySelectorAll('button').forEach(b=> b.onclick=()=>{
    $('exMenu').classList.remove('open');
    if(b.dataset.ex==='warrior') fetch('examples/warrior.piksel').then(r=>{
      if(!r.ok) throw new Error(r.status);
      return r.text();
    }).then(t=>{
      if(t.trim().startsWith('<!DOCTYPE')) throw new Error('got html');
      syncCode(t); parse(true); toast('Воин загружен');
    }).catch(()=>{ toast('Пример не найден — вставлен локальный'); syncCode(warriorFallback()); parse(true); });
    else if(b.dataset.ex==='blank') { syncCode(`размер 32\nпалитра pico8\n`); parse(true); }
    else toast('Скоро');
  });
function warriorFallback(){ return `размер 32\nпалитра pico8\n# воин — fallback\n4: 12. 4 4 4 4\n5: 11. 4 4 4 4 4 4\n6: 10. 0 4 4 4 4 4 0\n7: 10. 0 4 15 15 15 4 0\n11: 9. 0 6 6 6 6 6 6 6 0\n12: 8. 8 8 0 6 9 6 6 9 6 0\n`; }
  const updZoom=()=>{ const el=document.getElementById('zoomVal'); if(el) el.textContent=Math.round(S.zoom*100)+'%'; };
  $('plus').onclick=()=>{ S.zoom=Math.min(2.4,S.zoom*1.15); updZoom(); render(); };
  $('minus').onclick=()=>{ S.zoom=Math.max(.7,S.zoom/1.15); updZoom(); render(); }; updZoom();
  // ручной
  pc.addEventListener('click', e=>{
    const rect=pc.getBoundingClientRect(), N=S.size;
    const x=Math.floor((e.clientX-rect.left)/rect.width*N), y=Math.floor((e.clientY-rect.top)/rect.height*N);
    if(S.tool==='pick'){
      const c=S.pix[y*N+x];
      if(c){
        // ставим пипетку: найти ближайший цвет в палитре или запомнить как custom
        S.customColor=c;
        // попробовать найти индекс в палитре
        let idx=S.pal ? S.pal.indexOf(c) : -1;
        if(idx>=0) S.col=idx;
        else { S.col=0; }
        buildPal();
        // переключаем на кисть
        S.tool='brush';
        document.querySelectorAll('#tools .tool').forEach(x=>x.classList.remove('active'));
        const br=document.querySelector('[data-t=brush]'); if(br) br.classList.add('active');
        toast('Пипетка: '+c);
        const inp=document.getElementById('rgbPick'); if(inp) inp.value=c;
      } else toast('Прозрачно');
      return;
    }

    if(S.tool==='eraser'){ S.pix[y*N+x]=null; } else { const col = S.palN==='rgb' ? (S.customColor||'#ff7a45') : (S.pal?.[S.col]||'#fff'); S.pix[y*N+x]=col; }
    // обратно в код — добавляем/обновляем строку row-RLE (упрощённо: перегенерим все строки)
    // для MVP — не трогаем код, только холст + счётчик
    render(); updateMsgPicked(x,y,c);
  });
  // клик по палитре уже в buildPal
}
function updateMsgPicked(x,y,c){ $('msg').textContent=`пиксель ${x},${y} ${c||'прозрачно'} → правь в сценарии`; }

init();
updateGutter();
