// ПИКСЕЛЬ v0.2 — парсер row-RLE + ручной режим + HD mock
const $ = id => document.getElementById(id);
const code = $('code'), pc = $('pixelCanvas'), pctx = pc.getContext('2d'), hc = $('hdCanvas'), hctx = hc.getContext('2d');
const PAL = {
  pico8: ['#000000','#1D2B53','#7E2553','#008751','#AB5236','#5F574F','#C2C3C5','#FFF1E8','#FF004D','#FFA300','#FFEC27','#00E436','#29ADFF','#83769C','#FF77A8','#FFCCAA'],
  gameboy: ['#0f380f','#306230','#8bac0f','#9bbc0f'],
  sweet16: ['#1a1c2c','#5d275d','#b13e53','#ef7d57','#ffcd75','#a7f070','#38b764','#257179','#29366f','#3b5dc9','#41a6f6','#73eff7','#f4f4f4','#94b0c2','#566c86','#333c57'],
};
let state = { size:32, pal:PAL.pico8.slice(), palName:'pico8', grid:32, pixels:[] , color:4, manual:false, scale:4 };

function init(){
  state.pixels = Array(state.size*state.size).fill(null);
  buildPalBar();
  // стартовый воин — короткий пример в новом формате
  code.value = `размер 32
палитра pico8
# воин — row-RLE: только непустые строки
4: 12. 4 4 4 4
5: 11. 4 4 4 4 4 4
6: 10. 4 15 15 15 15 4
7: 10. 4 15 1 1 15 4
8: 10. 4 15 1 1 15 4
11: 10. 1 6 6 1 1 6 6 1
12: 9. 1 6 9 6 6 9 6 1
13: 9. 1 6 6 6 6 6 6 1
15: 2. 8 8 8 8
18: 9. 6 6 1 1 6 6
3: 22. 1 7 1
4: 22. 1 6 1
10: 22. 1 9 1
11: 20. 9 9 1 9 1 9 9
check палитра <=16
`;
  parseAndRender();
}
function buildPalBar(){
  const bar=$('palBar'); bar.innerHTML='';
  state.pal.forEach((c,i)=>{
    const d=document.createElement('div'); d.className='sw'; d.style.background=c;
    if(i===state.color) d.classList.add('active');
    d.title=i+': '+c; d.onclick=()=>{ state.color=i; buildPalBar(); };
    bar.appendChild(d);
  });
  const lab=document.createElement('span'); lab.style.cssText='margin-left:8px;color:var(--text-faint);font-size:11px'; lab.textContent='цвет '+state.color;
  bar.appendChild(lab);
  const br=document.createElement('button'); br.className='mini'; br.textContent='🧹 квантовать';
  br.onclick=()=> alert('Квантование — позже');
  bar.appendChild(br);
}

function parseAndRender(){
  const err=$('err'); err.hidden=true; err.textContent='';
  const txt=code.value;
  // размер
  const mSize = txt.match(/размер\s+(\d+)(?:x(\d+))?/i);
  if(mSize){ state.size = parseInt(mSize[1],10); if(state.size<8) state.size=8; if(state.size>64) state.size=64; }
  // палитра
  const mPal = txt.match(/палитра\s+(\w+)/i);
  if(mPal && PAL[mPal[1]]){ state.pal = PAL[mPal[1]].slice(); state.palName=mPal[1]; buildPalBar(); }
  // hex палитра вида 0=#...
  const hexes = [...txt.matchAll(/(\d+)\s*=\s*(\#[0-9a-fA-F]{3,8})/g)];
  if(hexes.length){ hexes.forEach(x=> state.pal[parseInt(x[1])]=x[2]); buildPalBar(); }

  state.pixels = Array(state.size*state.size).fill(null);
  const lines = txt.split('\n');
  let errs=[];
  for(let li=0; li<lines.length; li++){
    let l=lines[li].trim();
    if(!l || l.startsWith('#') || l.startsWith('размер') || l.startsWith('палитра') || l.startsWith('check') || l.startsWith('промпт') || l.startsWith('детализация')) continue;
    // row-RLE: 4: 12. 4 4 4 4   или 4 12: 4 4 4 4
    let m = l.match(/^(\d+)\s*:\s*(\d+)\s*\.\s*(.+)$/) || l.match(/^(\d+)\s+(\d+)\s*:\s*(.+)$/);
    if(!m) continue;
    let row=parseInt(m[1],10), col=parseInt(m[2],10), rest=m[3].trim();
    if(row<0 || row>=state.size){ errs.push(`стр ${li+1}: строка ${row} вне 0..${state.size-1}`); continue; }
    if(col<0 || col>=state.size){ errs.push(`стр ${li+1}: столбец ${col} вне`); continue; }
    // токены: "10x -" "10-" "5x 2" "-" "2"
    const toks = rest.split(/\s+/).filter(Boolean);
    let c=col;
    for(let t of toks){
      if(c>=state.size) break;
      let rep=1, val=null;
      // 10x -  или 10-  или 10x2
      let mm = t.match(/^(\d+)[x\-]?$/); // не точно
      // разбор: [число][x][-]
      let mx = t.match(/^(\d+)x(.+)$/); // 10x2  10x-
      if(mx){ rep=parseInt(mx[1],10); t=mx[2]; }
      else {
        let md = t.match(/^(\d+)-$/); // 10-
        if(md){ rep=parseInt(md[1],10); t='-'; }
      }
      if(t==='-' || t==='—'){ // прозрачный
        c+=rep; continue;
      }
      // цвет: 0..15 или #hex
      let colorIdx=null;
      if(t.startsWith('#')){ colorIdx=t; }
      else if(/^\d+$/.test(t)){ colorIdx=parseInt(t,10); }
      else continue;
      for(let k=0;k<rep;k++){
        if(c>=state.size) break;
        if(colorIdx!==null){
          let colVal = (typeof colorIdx==='number') ? (state.pal[colorIdx]||'#fff') : colorIdx;
          state.pixels[row*state.size + c] = colVal;
        }
        c++;
      }
    }
  }
  if(errs.length){ err.hidden=false; err.textContent=errs.join(' · '); }
  renderPix();
  renderHD();
  updateChecks();
  updateReport(txt);
}

function renderPix(){
  const N=state.size, S=Math.max(2, Math.floor(420/N));
  const show = $('chkGrid').checked;
  pc.width=N*S; pc.height=N*S;
  const dim=S;
  pctx.clearRect(0,0,pc.width,pc.height);
  pctx.fillStyle='#0b0e13'; pctx.fillRect(0,0,pc.width,pc.height);
  for(let y=0;y<N;y++) for(let x=0;x<N;x++){
    const c=state.pixels[y*N+x];
    if(c){ pctx.fillStyle=c; pctx.fillRect(x*S,y*S,S,S); }
  }
  if(show && N<=64){
    pctx.strokeStyle='rgba(255,255,255,.07)'; pctx.lineWidth=1;
    for(let i=0;i<=N;i++){ pctx.beginPath(); pctx.moveTo(i*S,0); pctx.lineTo(i*S,N*S); pctx.stroke(); pctx.beginPath(); pctx.moveTo(0,i*S); pctx.lineTo(N*S,i*S); pctx.stroke(); }
  }
  $('pixInfo').textContent = `${N}×${N} • ${new Set(state.pixels.filter(Boolean)).size} цветов`;
}
function renderHD(){
  const N=state.size, scale=4;
  const pow=parseInt($('hdPow').value,10);
  $('hdPct').textContent=pow+'%';
  // nearest upscale to N*scale
  const tmp=document.createElement('canvas'); tmp.width=N; tmp.height=N;
  const tc=tmp.getContext('2d');
  for(let y=0;y<N;y++) for(let x=0;x<N;x++){ const c=state.pixels[y*N+x]; if(c){ tc.fillStyle=c; tc.fillRect(x,y,1,1); } }
  const HD=N*scale; const S=Math.max(2, Math.floor(420/HD));
  hc.width=HD*S; hc.height=HD*S;
  hctx.imageSmoothingEnabled=false;
  hctx.clearRect(0,0,hc.width,hc.height);
  hctx.drawImage(tmp,0,0,HD*S,HD*S);
  if(pow>10){
    hctx.globalAlpha=0.18*(pow/100);
    hctx.filter=`blur(${0.7*scale}px) saturate(${1+pow/180})`;
    hctx.drawImage(hc, 0.8*scale,0.8*scale,HD*S,HD*S);
    hctx.filter='none'; hctx.globalAlpha=1;
  }
  hctx.strokeStyle='rgba(255,122,89,.22)'; hctx.lineWidth=2; hctx.strokeRect(0,0,hc.width,hc.height);
  $('hdInfo').textContent=`${HD}×${HD}`;
}

function updateChecks(){
  const box=$('checks');
  const used=new Set(state.pixels.filter(Boolean));
  const fillPct = (state.pixels.filter(Boolean).length / state.pixels.length *100)|0;
  const checks=[
    {ok: used.size<=16, text:`Палитра ${used.size}/16`, hint: used.size<=16?'в норме (PICO-8)':'много — квантуй'},
    {ok: fillPct>=5 && fillPct<=92, text:`Заполнение ${fillPct}%`, hint: fillPct<5?'почти пусто': fillPct>92?'фон переполнен':'ок — фон пропускаем, как ты просил'},
    {ok: hasNoOrphans(), text:'Кластеры', hint: hasNoOrphans()?'нет одиночек-шума':'есть孤立 пиксели — проверь'},
    {ok: state.size>=16 && state.size<=64, text:`Размер ${state.size}×${state.size}`, hint:'сильуэт читается? сделай скрин в 1×'},
  ];
  box.innerHTML=checks.map(c=>`<div class="check ${c.ok?'ok':'bad'}"><span>${c.ok?'✓':'⚠'}</span><div><strong>${c.text}</strong><div style="color:var(--text-faint)">${c.hint}</div></div></div>`).join('');
}
function hasNoOrphans(){
  const N=state.size;
  for(let y=0;y<N;y++) for(let x=0;x<N;x++){
    const c=state.pixels[y*N+x];
    if(!c) continue;
    let neigh=0;
    for(let dy=-1;dy<=1;dy++) for(let dx=-1;dx<=1;dx++){
      if(!dx&&!dy) continue;
      let nx=x+dx, ny=y+dy;
      if(nx<0||ny<0||nx>=N||ny>=N) continue;
      if(state.pixels[ny*N+nx]===c) neigh++;
    }
    if(neigh===0) return false;
  }
  return true;
}
function updateReport(txt){
  const used=[...new Set(state.pixels.filter(Boolean))];
  const fill = state.pixels.map((c,i)=> c ? `(${i%state.size},${(i/state.size)|0}:${c})` : '').filter(Boolean).slice(0,12).join(' ');
  $('report').textContent = `# Отчёт для нейросети (скопируй → вставь в чат)\nПалитра: ${state.palName} (${used.join(', ')||'прозрачно'})\nРазмер: ${state.size}×${state.size}, заполнено ${used.length? ((state.pixels.filter(Boolean).length/state.pixels.length*100)|0)+'%':''}\nЗанятых строк: ${linesUsed()}\nПример координат: ${fill||'пусто'}\nОшибок: ${$('err').hidden? 'нет' : $('err').textContent}\n---\nИсходник:\n${txt.slice(0,700)}\n`;
  const tok=txt.split(/\s+/).filter(Boolean).length;
  const rows=(txt.match(/^\d+\s*:/gm)||[]).length;
  $('tokInfo').textContent=`строк ${rows} • токенов ~${tok}`;
}
function linesUsed(){
  const s=new Set();
  for(let i=0;i<state.pixels.length;i++) if(state.pixels[i]) s.add((i/state.size)|0);
  return s.size;
}

// события
$('btnBuild').onclick=parseAndRender;
code.addEventListener('keydown', e=>{ if((e.ctrlKey||e.metaKey) && e.key==='Enter'){ e.preventDefault(); parseAndRender(); } });
$('sizeSel').onchange=e=>{ const v=parseInt(e.target.value); state.size=v; code.value=code.value.replace(/размер\s+\d+/,`размер ${v}`); parseAndRender(); };
$('palSel').onchange=e=>{ const v=e.target.value; if(PAL[v]){ state.pal=PAL[v].slice(); state.palName=v; code.value=code.value.replace(/палитра\s+\w+.*/,`палитра ${v}`); parseAndRender(); } };
$('chkGrid').onchange=renderPix;
$('hdPow').oninput=renderHD;
$('btnSave').onclick=()=>{ localStorage.setItem('piksel_code', code.value); alert('Сохранено локально'); };
$('btnClear').onclick=()=>{ code.value=`размер ${state.size}\nпалитра ${state.palName}\n`; parseAndRender(); };
$('btnWarrior').onclick=async()=>{
  try{ const txt=await (await fetch('../examples/warrior.piksel')).text(); code.value=txt; parseAndRender(); }catch{ alert('warrior.piksel не найден'); }
};
$('btnManual').onclick=()=>{ state.manual=!state.manual; $('btnManual').classList.toggle('active', state.manual); $('btnManual').textContent = state.manual? '✎ ручной ВКЛ' : '🖌 ручной'; pc.style.cursor = state.manual? 'crosshair':'default'; };
pc.addEventListener('click', e=>{
  if(!state.manual) return;
  const rect=pc.getBoundingClientRect(), N=state.size;
  const S=pc.width/N;
  const x=Math.floor((e.clientX-rect.left)/rect.width * N);
  const y=Math.floor((e.clientY-rect.top)/rect.height * N);
  const col=state.pal[state.color]||'#fff';
  state.pixels[y*N+x]=col;
  // дописать в код
  const rowLine = findRowLine(y);
  if(rowLine>=0){
    // просто обновить рендер, код не трогаем в MVP — позже синхронизация
  }
  renderPix(); renderHD(); updateChecks();
});
function findRowLine(row){ const ls=code.value.split('\n'); for(let i=0;i<ls.length;i++) if(ls[i].match(new RegExp(`^${row}\\s*:`))) return i; return -1; }
$('btnCmd').onclick=()=>{ const v=$('cmd').value.trim(); if(!v) return; if(v.match(/^\d+\s*:/)){ code.value+='\n'+v; parseAndRender(); $('cmd').value=''; } else code.value+='\n'+v, parseAndRender(); };
$('cmd').onkeydown=e=>{ if(e.key==='Enter') $('btnCmd').click(); };
$('btnHD').onclick=()=>{ $('hdPow').value=55; renderHD(); alert('HD детализация: пока mock (blur), реальная — через Replicate Tile на Fly.io'); };
$('btnCopyReport').onclick=()=>{ navigator.clipboard.writeText($('report').textContent); alert('Отчёт скопирован — отдай нейросети'); };
$('btnExport').onclick=()=> $('expMenu').classList.toggle('open');
$('expMenu').querySelectorAll('button').forEach(b=> b.onclick=()=>{
  $('expMenu').classList.remove('open');
  if(b.dataset.f==='png'){ const a=document.createElement('a'); a.download='piksel.png'; a.href=pc.toDataURL('image/png'); a.click(); }
  if(b.dataset.f==='hd'){ const a=document.createElement('a'); a.download='piksel-hd.png'; a.href=hc.toDataURL('image/png'); a.click(); }
  if(b.dataset.f==='copy'){ navigator.clipboard.writeText(code.value); alert('Сценарий скопирован'); }
});

init();
window.addEventListener('resize', ()=>{ renderPix(); renderHD(); });
