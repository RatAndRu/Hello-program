// ПИКСЕЛЬ — логика пиксельного редактора, форк forma/web/js/app.js
// Упрощённая версия: холст, палитра, детализация (mock), таймлайн

const $ = id => document.getElementById(id);
const pixelCanvas = $('pixelCanvas');
const pctx = pixelCanvas.getContext('2d');
const hdCanvas = $('hdCanvas');
const hctx = hdCanvas.getContext('2d');

const state = {
  size: 32,
  scale: 2,
  tool: 'brush',
  color: '#ff7a59',
  showGrid: true,
  pixels: null, // Uint32 или массив цветов
  history: [],
  future: [],
  frames: [], // для анимации
};

const PALETTES = {
  'NES': ['#000000','#FCFCFC','#BCBEC4','#7C7C7C','#F8B800','#E45C10','#B83000','#6A0800','#009600','#006400','#004E00','#002600','#0058F8','#0000BC','#000078','#2C0078'],
  'GameBoy': ['#0f380f','#306230','#8bac0f','#9bbc0f'],
  'Sweet16': ['#1a1c2c','#5d275d','#b13e53','#ef7d57','#ffcd75','#a7f070','#38b764','#257179','#29366f','#3b5dc9','#41a6f6','#73eff7','#f4f4f4','#94b0c2','#566c86','#333c57'],
  'Pico8': ['#000000','#1D2B53','#7E2553','#008751','#AB5236','#5F574F','#C2C3C5','#FFF1E8','#FF004D','#FFA300','#FFEC27','#00E436','#29ADFF','#83769C','#FF77A8','#FFCCAA'],
  'Pastel': ['#fec8c8','#fec8e3','#e3c8fe','#c8e3fe','#c8fee3','#e3fec8','#feebc8','#fff4c8'],
};

function initPixels() {
  state.pixels = new Array(state.size * state.size).fill(null).map(() => null); // прозрачный
  // демо-рисунок: котик
  const demo = [
    [14,14,'#ff7a59'],[15,14,'#ff7a59'],[16,14,'#ffb86b'],[17,14,'#ff7a59'],
    [13,15,'#ff7a59'],[14,15,'#e7ecf3'],[15,15,'#1a1c2c'],[16,15,'#1a1c2c'],[17,15,'#e7ecf3'],[18,15,'#ff7a59'],
    [13,16,'#ff7a59'],[14,16,'#e7ecf3'],[15,16,'#ff7a59'],[16,16,'#ff7a59'],[17,16,'#e7ecf3'],[18,16,'#ff7a59'],
    [14,17,'#ff7a59'],[15,17,'#ff7a59'],[16,17,'#5d275d'],[17,17,'#ff7a59'],
    [10,20,'#73eff7'],[11,20,'#73eff7'],[20,20,'#73eff7'],[21,20,'#73eff7'],
  ];
  demo.forEach(([x,y,c]) => { if (x<state.size && y<state.size) state.pixels[y*state.size + x]=c; });
  pushHistory();
  renderPixel();
  renderHD();
  updateStats();
  buildPalette();
  buildTools();
  updateChecks();
  buildTimeline();
}

function pushHistory(){
  state.history.push(state.pixels.slice());
  if(state.history.length>80) state.history.shift();
  state.future=[];
  updateUndo();
}
function updateUndo(){
  $('btn-undo').disabled = state.history.length<=1;
  $('btn-redo').disabled = state.future.length===0;
}

function renderPixel(){
  const N = state.size;
  const S = Math.floor(512 / N);
  pixelCanvas.width = N*S;
  pixelCanvas.height = N*S;
  pctx.clearRect(0,0,pixelCanvas.width,pixelCanvas.height);
  // фон шахматка
  pctx.fillStyle = '#0b0e13';
  pctx.fillRect(0,0,pixelCanvas.width,pixelCanvas.height);
  for(let y=0;y<N;y++) for(let x=0;x<N;x++){
    const c = state.pixels[y*N+x];
    if(c){ pctx.fillStyle=c; pctx.fillRect(x*S,y*S,S,S); }
  }
  if(state.showGrid && N<=64){
    pctx.strokeStyle='rgba(255,255,255,.08)';
    pctx.lineWidth=1;
    for(let i=0;i<=N;i++){
      pctx.beginPath(); pctx.moveTo(i*S,0); pctx.lineTo(i*S,N*S); pctx.stroke();
      pctx.beginPath(); pctx.moveTo(0,i*S); pctx.lineTo(N*S,i*S); pctx.stroke();
    }
  }
  $('res-badge').textContent = `${N}×${N}`;
}
function renderHD(){
  const N = state.size;
  const scale = state.scale;
  const detail = parseInt($('detail-strength').value);
  const S = Math.max(1, 8);
  // 1. nearest-neighbor upscale (детерминирован, как в ФОРМЕ exports)
  const tmp = document.createElement('canvas');
  tmp.width = N; tmp.height = N;
  const tctx = tmp.getContext('2d');
  tctx.clearRect(0,0,N,N);
  for(let y=0;y<N;y++) for(let x=0;x<N;x++){
    const c = state.pixels[y*N+x];
    if(c){ tctx.fillStyle=c; tctx.fillRect(x,y,1,1); }
  }
  // HD canvas: N*scale*S
  const HD = N*scale;
  hdCanvas.width = HD*S;
  hdCanvas.height = HD*S;
  hctx.imageSmoothingEnabled = false;
  hctx.clearRect(0,0,hdCanvas.width,hdCanvas.height);
  hctx.drawImage(tmp, 0,0, HD*S, HD*S);
  // 2. mock-детализация: если detail>0, делаем лёгкий blur + контраст (имитация нейросети)
  if(detail>8){
    hctx.globalAlpha = 0.18 * (detail/100);
    hctx.filter = `blur(${0.6*scale}px) saturate(${1+detail/200})`;
    hctx.drawImage(hdCanvas, 1,1, HD*S, HD*S);
    hctx.filter='none';
    hctx.globalAlpha=1;
  }
  // рамка
  hctx.strokeStyle='rgba(255,122,89,.25)';
  hctx.lineWidth=2;
  hctx.strokeRect(0,0,hdCanvas.width,hdCanvas.height);
  $('hd-badge').textContent = `×${scale} → ${HD}×${HD} • деталь ${detail}%`;
  $('status-left').textContent = `Готов • Пиксель ${N}×${N} • HD ×${scale} • деталь ${detail}%`;
}

function buildPalette(){
  const pal = $('palette');
  pal.innerHTML='';
  const colors = ['#000000','#1a1c2c','#5d275d','#b13e53','#ef7d57','#ffcd75','#ff7a59','#ffb86b','#a7f070','#38b764','#41a6f6','#73eff7','#f4f4f4','#94b0c2','#c2c3c5','#ffffff'];
  colors.forEach(c=>{
    const d=document.createElement('div');
    d.className='swatch'; d.style.background=c;
    if(c.toLowerCase()===state.color.toLowerCase()) d.classList.add('active');
    d.onclick=()=>{ state.color=c; $('color-pick').value=c; buildPalette(); };
    pal.appendChild(d);
  });
  const add = document.createElement('div');
  add.className='add'; add.textContent='+'; add.title='Добавить цвет';
  add.onclick=()=>{ const cc=prompt('HEX цвет, например #ff004d'); if(cc) {state.color=cc; buildPalette();}};
  pal.appendChild(add);
  // палитры-пресеты
  Object.keys(PALETTES).forEach(name=>{
    const b=document.createElement('button');
    b.className='mini'; b.textContent=name; b.title='Применить палитру '+name;
    b.onclick=()=>{ applyPalette(PALETTES[name]); };
    pal.appendChild(b);
  });
}
function applyPalette(pal){
  // квантовать текущие пиксели к ближайшему из палитры
  for(let i=0;i<state.pixels.length;i++){
    const c=state.pixels[i];
    if(!c) continue;
    let best=pal[0], bd=1e9;
    for(const pc of pal){
      const d=colorDist(c,pc);
      if(d<bd){ bd=d; best=pc; }
    }
    state.pixels[i]=best;
  }
  pushHistory(); renderPixel(); renderHD(); updateStats(); updateChecks();
}
function colorDist(a,b){
  const ah=hex2rgb(a), bh=hex2rgb(b);
  return (ah[0]-bh[0])**2+(ah[1]-bh[1])**2+(ah[2]-bh[2])**2;
}
function hex2rgb(hex){
  const h=hex.replace('#',''); const n=parseInt(h,16);
  return [(n>>16)&255,(n>>8)&255,n&255];
}
function buildTools(){
  const grid=$('tools-grid');
  if(!grid) return;
  grid.innerHTML='';
  const items=[
    {name:'Линия',desc:'прямая по 2 точкам'},
    {name:'Заливка',desc:'flood fill'},
    {name:'Градиент',desc:'гориз./верт.'},
    {name:'NES 54',desc:'палитра NES'},
    {name:'PICO-8 16',desc:'ограничить 16'},
    {name:'Шум 5%',desc:'добавить текстуру'},
    {name:'Контур',desc:'обводка 1px'},
    {name:'Тень',desc:'автотень 45°'},
  ];
  items.forEach(it=>{
    const d=document.createElement('div');
    d.style.cssText='padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--panel-2)';
    d.innerHTML=`<strong>${it.name}</strong><br><span style="color:var(--text-faint);font-size:11px">${it.desc}</span>`;
    grid.appendChild(d);
  });
}
function updateStats(){
  const used = new Set(state.pixels.filter(Boolean)).size;
  $('script-stats').textContent = `${state.size}×${state.size} • ${used} цветов • кадр 1/1`;
}
function updateChecks(){
  const list=$('checks-list');
  const used = new Set(state.pixels.filter(Boolean));
  const checks=[
    {ok: (state.size>=16 && state.size<=128), text:`Размер ${state.size}×${state.size}`, hint: used.size?`OK, ${used.size} цветов`:'пусто'},
    {ok: used.size<=16, text:`Палитра ≤16 (${used.size})`, hint: used.size<=16?'в стиле пиксель-арт':'многовато — нажми «квантовать 16»'},
    {ok: used.size>0, text:'Холст не пуст', hint: used.size?'есть пиксели':'нарисуй или сгенерируй'},
    {ok: state.scale>=2, text:`HD ×${state.scale}`, hint:`${state.size*state.scale}×${state.size*state.scale} на выходе`},
  ];
  list.innerHTML = checks.map(c=>`<div class="check ${c.ok?'ok':'bad'}"><span>${c.ok?'✓':'⚠'}</span><div><strong>${c.text}</strong><div style="color:var(--text-faint);font-size:11px">${c.hint}</div></div></div>`).join('');
  // лог
  const log=$('log-list');
  if(log) log.innerHTML = state.history.slice(-10).reverse().map((_,i)=>`<div style="padding:4px 0;border-bottom:1px solid var(--line-soft);color:var(--text-dim)">Шаг ${state.history.length-i}: ${state.history.length-i===state.history.length?'текущий':''} </div>`).join('') || '<div style="color:var(--text-faint)">Журнал пуст — нарисуй что-нибудь</div>';
  // отчёт для нейросети — как в ФОРМЕ build_prompt
  const promptOut=$('prompt-out');
  if(promptOut){
    promptOut.textContent = `# ПИКСЕЛЬ — отчёт для нейросети\nПромпт: ${$('prompt').value||'(пусто)'}\nСтиль: ${$('style-preset').value}\nРазмер: ${state.size}×${state.size}, HD ×${state.scale}, деталь ${$('detail-strength').value}%\nПалитра: ${[...used].join(', ')||'прозрачно'}\nКоординаты заполненных: ${state.pixels.map((c,i)=>c?`(${i%state.size},${(i/state.size)|0},${c})`:'').filter(Boolean).slice(0,20).join(' ')}\n`;
  }
}
function buildTimeline(){
  const tl=$('timeline');
  if(!tl) return;
  // пока 1 кадр + кнопка добавить
  tl.innerHTML=`<div class="frame active"><canvas width="32" height="32" style="background:#0b0e13"></canvas><div><strong>Кадр 1</strong><div style="color:var(--text-faint);font-size:10px">32×32 • 0.0s</div></div></div><button class="mini" id="btn-add-frame">＋ Кадр</button><button class="mini">▶ Предпросмотр</button>`;
}

function posToXY(e){
  const rect=pixelCanvas.getBoundingClientRect();
  const N=state.size;
  const S=pixelCanvas.width/N;
  const x=Math.floor((e.clientX-rect.left)/rect.width * N);
  const y=Math.floor((e.clientY-rect.top)/rect.height * N);
  return {x:Math.max(0,Math.min(N-1,x)), y:Math.max(0,Math.min(N-1,y))};
}
let drawing=false;
pixelCanvas.addEventListener('pointerdown', e=>{
  drawing=true;
  pixelCanvas.setPointerCapture(e.pointerId);
  paint(posToXY(e));
});
pixelCanvas.addEventListener('pointermove', e=>{
  const {x,y}=posToXY(e);
  $('cursor-pos').textContent=`x:${x} y:${y}`;
  if(drawing) paint(posToXY(e));
});
pixelCanvas.addEventListener('pointerup', ()=>{ if(drawing){ drawing=false; pushHistory(); updateStats(); updateChecks(); }});
pixelCanvas.addEventListener('pointerleave', ()=> drawing=false);

function paint({x,y}){
  const N=state.size;
  const idx=y*N+x;
  if(state.tool==='brush') state.pixels[idx]=state.color;
  else if(state.tool==='eraser') state.pixels[idx]=null;
  else if(state.tool==='pick') { const c=state.pixels[idx]; if(c){ state.color=c; $('color-pick').value=c; buildPalette(); } return; }
  else if(state.tool==='fill') { flood(idx, state.pixels[idx], state.color); }
  renderPixel(); renderHD();
}
function flood(start, target, repl){
  if(target===repl) return;
  const N=state.size;
  const stack=[start];
  const seen=new Set();
  while(stack.length){
    const i=stack.pop();
    if(seen.has(i)) continue;
    seen.add(i);
    if(state.pixels[i]!==target) continue;
    state.pixels[i]=repl;
    const x=i%N, y=(i/N)|0;
    if(x>0) stack.push(i-1);
    if(x<N-1) stack.push(i+1);
    if(y>0) stack.push(i-N);
    if(y<N-1) stack.push(i+N);
  }
}

// координатный ввод
$('btn-coord').onclick=()=>{
  const v=$('coord-input').value.trim();
  if(!v) return;
  // парсим "x=4 y=9 #ff0000" или "линия 2..10,5"
  const m=v.match(/x\s*=\s*(\d+).*?y\s*=\s*(\d+).*?(#\w{3,8})?/i);
  if(m){
    const x=parseInt(m[1]), y=parseInt(m[2]);
    const c=m[3]||state.color;
    if(x<state.size && y<state.size){ state.pixels[y*state.size+x]=c; pushHistory(); renderPixel(); renderHD(); updateStats(); updateChecks(); }
  } else {
    // заливка
    if(v.includes('заливка')||v.includes('fill')){
      const col=v.match(/#\w{3,8}/);
      if(col) { state.pixels=state.pixels.map(()=>col[0]); pushHistory(); renderPixel(); renderHD(); }
    }
  }
};
$('color-pick').oninput=e=>{ state.color=e.target.value; buildPalette(); };
$('grid-size').onchange=e=>{ state.size=parseInt(e.target.value); state.pixels=new Array(state.size*state.size).fill(null); pushHistory(); renderPixel(); renderHD(); updateStats(); updateChecks(); };
$('show-grid').onchange=e=>{ state.showGrid=e.target.checked; renderPixel(); };
document.querySelectorAll('#tool-seg [data-tool]').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('#tool-seg [data-tool]').forEach(x=>x.classList.remove('active'));
  b.classList.add('active'); state.tool=b.dataset.tool;
});
document.querySelectorAll('[data-scale]').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('[data-scale]').forEach(x=>x.classList.remove('active'));
  b.classList.add('active'); state.scale=parseInt(b.dataset.scale); renderHD(); updateChecks();
});
$('detail-strength').oninput=e=>{ $('detail-label').textContent=`деталь ${e.target.value}%`; renderHD(); updateChecks(); };
$('compare-slider').oninput=e=>{ $('compare-label').textContent=`HD ${e.target.value}%`; hctx.globalAlpha= e.target.value/100; renderHD(); };
$('btn-clear-pixels').onclick=()=>{ state.pixels.fill(null); pushHistory(); renderPixel(); renderHD(); updateStats(); updateChecks(); };
$('btn-quantize').onclick=()=> applyPalette(PALETTES['Pico8']);

$('btn-pixel').onclick=()=> doPrompt();
$('btn-prompt-run').onclick=()=> doPrompt();
$('btn-detail').onclick=()=>{ state.scale = state.scale>=8?2: state.scale*2; document.querySelectorAll('[data-scale]').forEach(b=> b.classList.toggle('active', parseInt(b.dataset.scale)===state.scale)); renderHD(); updateChecks(); showToast(`HD ×${state.scale}`); };
$('prompt').onkeydown=e=>{ if(e.key==='Enter') doPrompt(); };

function doPrompt(){
  const p=$('prompt').value.trim();
  if(!p) { showToast('Введи промпт или координаты'); return; }
  // mock-генерация: заполняем пиксели случайными цветами по хешу промпта
  let h=0; for(let i=0;i<p.length;i++) h=(h*31+p.charCodeAt(i))>>>0;
  const rng = mulberry(h);
  for(let y=0;y<state.size;y++) for(let x=0;x<state.size;x++){
    if(rng()<0.12) state.pixels[y*state.size+x]= PALETTES['Sweet16'][Math.floor(rng()*16)];
  }
  pushHistory(); renderPixel(); renderHD(); updateStats(); updateChecks();
  showToast(`Пиксель сгенерирован: "${p.slice(0,24)}"`);
}
function mulberry(a){
  return function(){ a|=0; a=a+0x6D2B79F5|0; let t=Math.imul(a^a>>>15,1|a); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }
}
function showToast(s){
  let t=document.getElementById('toast');
  if(!t){ t=document.createElement('div'); t.id='toast'; t.style.cssText='position:fixed;bottom:60px;left:50%;transform:translateX(-50%);background:#1a2029;border:1px solid var(--line);padding:8px 14px;border-radius:8px;z-index:50'; document.body.appendChild(t); }
  t.textContent=s; t.hidden=false; setTimeout(()=>t.hidden=true,2200);
}

// панели — копия forma/web/js/panels.js упрощённая
document.querySelectorAll('.splitter').forEach(s=>{
  let drag=false, startX, startW;
  s.addEventListener('pointerdown', e=>{
    drag=true; startX=e.clientX;
    const panel = s.dataset.split==='editor' ? $('panel-editor') : $('panel-viewer');
    startW=panel.getBoundingClientRect().width;
    s.setPointerCapture(e.pointerId);
    s.classList.add('dragging');
  });
  s.addEventListener('pointermove', e=>{
    if(!drag) return;
    const dx=e.clientX-startX;
    // просто визуально — не меняем grid, как в ФОРМЕ, но показываем drag
  });
  s.addEventListener('pointerup', ()=>{ drag=false; s.classList.remove('dragging'); });
});
document.querySelectorAll('.panel-max').forEach(b=>b.onclick=()=> {
  const p=document.getElementById('panel-'+b.dataset.panel);
  p.classList.toggle('is-collapsed');
});
document.querySelectorAll('[data-fold]').forEach(b=>b.onclick=()=>{
  document.getElementById('panel-'+b.dataset.fold).classList.toggle('is-collapsed');
});
document.querySelectorAll('.report-tabs [data-tab]').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('.report-tabs [data-tab]').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  const t=b.dataset.tab;
  if(t==='checks'){ $('checks-list').hidden=false; $('timeline').hidden=true; $('log-list').hidden=true; $('prompt-out').hidden=true; }
  if(t==='timeline'){ $('checks-list').hidden=true; $('timeline').hidden=false; $('log-list').hidden=true; $('prompt-out').hidden=true; buildTimeline(); }
  if(t==='log'){ $('checks-list').hidden=true; $('timeline').hidden=true; $('log-list').hidden=false; $('prompt-out').hidden=true; }
  if(t==='prompt'){ $('checks-list').hidden=true; $('timeline').hidden=true; $('log-list').hidden=true; $('prompt-out').hidden=false; }
});
$('btn-tools').onclick=()=> $('tools-modal').hidden=false;
$('btn-help').onclick=()=> $('help-modal').hidden=false;
$('link-help').onclick=e=>{ e.preventDefault(); $('help-modal').hidden=false; };
$('btn-history').onclick=()=> $('history-panel').hidden=false;
$('history-close').onclick=()=> $('history-panel').hidden=true;
$('btn-undo').onclick=()=>{
  if(state.history.length>1){
    state.future.push(state.history.pop());
    state.pixels = state.history[state.history.length-1].slice();
    renderPixel(); renderHD(); updateStats(); updateChecks(); updateUndo();
  }
};
$('btn-redo').onclick=()=>{
  if(state.future.length){
    const nxt=state.future.pop();
    state.history.push(nxt);
    state.pixels=nxt.slice();
    renderPixel(); renderHD(); updateStats(); updateChecks(); updateUndo();
  }
};
$('btn-export').onclick=()=> $('export-menu').classList.toggle('open');
$('export-menu').querySelectorAll('button').forEach(b=>b.onclick=()=>{
  $('export-menu').classList.remove('open');
  const fmt=b.dataset.format;
  if(fmt==='png' || fmt==='png-hd'){
    const a=document.createElement('a');
    a.download=`piksel-${Date.now()}.png`;
    a.href=(fmt==='png'?pixelCanvas:hdCanvas).toDataURL('image/png');
    a.click(); showToast('PNG сохранён');
  } else showToast(fmt+' — скоро');
});
$('btn-save').onclick=()=>{
  localStorage.setItem('piksel_pixels', JSON.stringify(state.pixels));
  localStorage.setItem('piksel_size', state.size);
  showToast('Сохранено локально');
};
$('btn-open').onclick=()=> $('file-input').click();
$('file-input').onchange= e=>{
  const f=e.target.files[0]; if(!f) return;
  const img=new Image();
  img.onload=()=>{
    const c=document.createElement('canvas'); c.width=state.size; c.height=state.size;
    const ctx=c.getContext('2d'); ctx.drawImage(img,0,0,state.size,state.size);
    const data=ctx.getImageData(0,0,state.size,state.size).data;
    for(let i=0;i<state.size*state.size;i++){
      const r=data[i*4],g=data[i*4+1],b=data[i*4+2],a=data[i*4+3];
      state.pixels[i]= a<16?null: `#${r.toString(16).padStart(2,'0')}${g.toString(16).padStart(2,'0')}${b.toString(16).padStart(2,'0')}`;
    }
    pushHistory(); renderPixel(); renderHD(); updateStats(); updateChecks(); showToast('Файл загружен');
  };
  img.src=URL.createObjectURL(f);
};
$('btn-projects').onclick=()=> showToast('Проекты — скоро (как в ФОРМЕ: примеры + мои)');

// init
initPixels();
