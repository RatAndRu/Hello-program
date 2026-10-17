(() => {
'use strict';

const video = document.getElementById('camera');
const canvas = document.getElementById('game');
const ctx = canvas.getContext('2d', { alpha: false });
const startPanel = document.getElementById('startPanel');
const endPanel = document.getElementById('endPanel');
const topHud = document.getElementById('topHud');
const radar = document.getElementById('radar');
const radarCanvas = document.getElementById('radarCanvas');
const rctx = radarCanvas.getContext('2d');
const startBtn = document.getElementById('startBtn');
const restartBtn = document.getElementById('restartBtn');
const permissionBtn = document.getElementById('permissionBtn');
const timeText = document.getElementById('timeText');
const livesText = document.getElementById('livesText');
const scoreText = document.getElementById('scoreText');
const endTitle = document.getElementById('endTitle');
const endStats = document.getElementById('endStats');
const toast = document.getElementById('toast');

const analysis = document.createElement('canvas');
const actx = analysis.getContext('2d', { willReadFrequently: true });

const CFG = {
  duration: 300,
  lives: 3,
  hFov: 160,
  vFov: 90,
  spawnYaw: 80,
  spawnPitch: 38,
  maxMonsters: 7,
  spawnEveryMin: 1.8,
  spawnEveryMax: 3.6,
  flashlightThreshold: 218,
  flashlightMinArea: 35,
  laserMinSat: 105,
  laserMinValue: 210,
  laserMaxArea: 42,
  slashMinLen: 18,
  damageCooldown: 0.32,
};

let W = 1, H = 1, DPR = 1;
let running = false;
let lastT = 0;
let elapsed = 0;
let lives = CFG.lives;
let score = 0;
let monsters = [];
let nextSpawn = 0;
let monsterId = 1;
let cameraReady = false;

let rawYaw = 0, rawPitch = 0, baseYaw = null;
let smoothYaw = 0, smoothPitch = 0;
let orientationOk = false;
let manualYaw = 0, manualPitch = 0;
let dragging = false, dragX = 0, dragY = 0;

let light = { active:false, x:0, y:0, radius:0, area:0, rising:false, prev:false, hold:0 };
let laser = { active:false, x:0, y:0, px:null, py:null, color:'red', area:0 };
let lastLaserCandidate = null;
let laserCandidateStreak = 0;

const clamp = (v,a,b)=>Math.max(a,Math.min(b,v));
const rand = (a,b)=>a+Math.random()*(b-a);
const pick = arr => arr[(Math.random()*arr.length)|0];
function deltaAngle(a,b){ let d=a-b; while(d>180)d-=360; while(d<-180)d+=360; return d; }
function lerp(a,b,t){ return a+(b-a)*t; }
function lerpAngle(a,b,t){ return a + deltaAngle(b,a)*t; }
function showToast(s, ms=2500){ toast.textContent=s; toast.classList.remove('hidden'); clearTimeout(showToast._t); showToast._t=setTimeout(()=>toast.classList.add('hidden'),ms); }

function resize(){
  DPR = Math.min(2, window.devicePixelRatio || 1);
  W = Math.floor(innerWidth * DPR); H = Math.floor(innerHeight * DPR);
  canvas.width = W; canvas.height = H;
  radarCanvas.width = Math.floor(126*DPR); radarCanvas.height = Math.floor(126*DPR);
  analysis.width = 160; analysis.height = 90;
}
addEventListener('resize', resize); resize();

async function requestOrientation(){
  try{
    if (typeof DeviceOrientationEvent !== 'undefined' && typeof DeviceOrientationEvent.requestPermission === 'function') {
      const res = await DeviceOrientationEvent.requestPermission();
      orientationOk = res === 'granted';
    } else {
      orientationOk = true;
    }
    showToast(orientationOk ? 'Датчики движения разрешены' : 'Датчики не разрешены');
  }catch(e){ showToast('Не удалось запросить датчики'); }
}
permissionBtn.addEventListener('click', requestOrientation);

window.addEventListener('deviceorientation', e => {
  if (e.alpha == null) return;
  orientationOk = true;
  rawYaw = 360 - e.alpha; // удобнее: вправо = плюс
  rawPitch = clamp((e.beta || 0) - 65, -80, 80); // примерная поправка под портретный хват
  if (baseYaw === null) baseYaw = rawYaw;
});

canvas.addEventListener('pointerdown', e=>{ dragging=true; dragX=e.clientX; dragY=e.clientY; });
canvas.addEventListener('pointermove', e=>{
  if(!dragging) return;
  manualYaw += (e.clientX-dragX)*0.18;
  manualPitch = clamp(manualPitch - (e.clientY-dragY)*0.12, -45, 45);
  dragX=e.clientX; dragY=e.clientY;
});
canvas.addEventListener('pointerup', ()=>dragging=false);
canvas.addEventListener('pointercancel', ()=>dragging=false);

async function startCamera(){
  const constraints = {
    video: {
      facingMode: { ideal: 'environment' },
      width: { ideal: 1280 }, height: { ideal: 720 },
      frameRate: { ideal: 30, max: 60 }
    },
    audio: false
  };
  const stream = await navigator.mediaDevices.getUserMedia(constraints);
  video.srcObject = stream;
  await video.play();
  cameraReady = true;
}

function startGame(){
  running = true; lastT = performance.now(); elapsed = 0; lives = CFG.lives; score = 0; monsters = []; nextSpawn = 0.5; monsterId = 1;
  baseYaw = rawYaw || null; smoothYaw = 0; smoothPitch = 0;
  startPanel.classList.add('hidden'); endPanel.classList.add('hidden'); topHud.classList.remove('hidden'); radar.classList.remove('hidden');
  requestAnimationFrame(loop);
}

startBtn.addEventListener('click', async ()=>{
  try{
    if(!cameraReady) await startCamera();
    if(!orientationOk) await requestOrientation();
    startGame();
  }catch(e){ console.error(e); showToast('Камера не запустилась. Нужен HTTPS и разрешение камеры.', 5000); }
});
restartBtn.addEventListener('click', startGame);

function spawnMonster(){
  const type = Math.random() < 0.58 ? 'flash' : 'laser';
  const hp = type === 'flash' ? pick([2,3,3,4]) : pick([2,2,3]);
  const sideBias = Math.random()<.55 ? pick([-1,1]) * rand(42, CFG.spawnYaw) : rand(-CFG.spawnYaw, CFG.spawnYaw);
  monsters.push({
    id: monsterId++, type, hp, maxHp: hp,
    yaw: smoothYaw + sideBias,
    pitch: smoothPitch + rand(-CFG.spawnPitch, CFG.spawnPitch),
    dist: rand(0.82, 1.0),
    speed: type === 'flash' ? rand(0.030,0.050) : rand(0.040,0.065),
    phase: rand(0,Math.PI*2),
    wobble: rand(0.6,1.4),
    lastHit: -99,
  });
}

function updateOrientation(dt){
  let targetYaw, targetPitch;
  if (orientationOk && baseYaw !== null) {
    targetYaw = deltaAngle(rawYaw, baseYaw);
    targetPitch = rawPitch;
  } else {
    targetYaw = manualYaw;
    targetPitch = manualPitch;
  }
  smoothYaw = lerpAngle(smoothYaw, targetYaw, 1-Math.pow(0.001, dt));
  smoothPitch = lerp(smoothPitch, targetPitch, 1-Math.pow(0.001, dt));
}

function analyzeLight(){
  if(!cameraReady || video.videoWidth === 0) return;
  const aw = analysis.width, ah = analysis.height;
  actx.drawImage(video, 0, 0, aw, ah);
  const img = actx.getImageData(0,0,aw,ah);
  const data = img.data;

  let brightCount=0, brightX=0, brightY=0;

  // Для лазера делаем более строгий детектор:
  // 1) очень яркая и насыщенная красная/зелёная точка;
  // 2) маленький компактный объект;
  // 3) подтверждение хотя бы 2 кадра подряд, чтобы случайные цветные блики не считались лазером.
  const laserMask = new Uint8Array(aw * ah);

  for(let y=0; y<ah; y++){
    for(let x=0; x<aw; x++){
      const idx = y*aw+x;
      const i=idx*4, r=data[i], g=data[i+1], b=data[i+2];
      const max=Math.max(r,g,b), min=Math.min(r,g,b);
      const sat=max-min;
      const bright=(r+g+b)/3;

      // большой белый/желтый фонарик. Сильно цветные точки исключаем, чтобы лазер не считался фонарём.
      if(bright > CFG.flashlightThreshold && !(sat>95 && (r>g*1.35 || g>r*1.35))){
        brightCount++; brightX+=x; brightY+=y;
      }

      // Красный/зелёный лазер. Порог сделан жёстким специально против ложных срабатываний.
      const isRedLaser = r > CFG.laserMinValue && sat > CFG.laserMinSat && r > g*1.75 && r > b*1.75 && g < 175 && b < 175;
      const isGreenLaser = g > CFG.laserMinValue && sat > CFG.laserMinSat && g > r*1.55 && g > b*1.55 && r < 190 && b < 190;
      if(isRedLaser || isGreenLaser) laserMask[idx] = isRedLaser ? 1 : 2;
    }
  }

  const prevLight = light.active;
  if(brightCount > CFG.flashlightMinArea){
    const x = brightX/brightCount/aw*W;
    const y = brightY/brightCount/ah*H;
    light.x = light.active ? lerp(light.x,x,.35) : x;
    light.y = light.active ? lerp(light.y,y,.35) : y;
    light.radius = clamp(Math.sqrt(brightCount)*DPR*7, 32*DPR, 150*DPR);
    light.area = brightCount;
    light.active = true;
    light.hold += 1;
  } else {
    light.active = false; light.hold = 0;
  }
  light.rising = light.active && !prevLight;
  light.prev = light.active;

  // Поиск самого подходящего компактного пятна лазера через flood fill.
  const visited = new Uint8Array(aw * ah);
  let best = null;
  const stack = [];
  for(let i=0; i<aw*ah; i++){
    if(!laserMask[i] || visited[i]) continue;
    const colorKind = laserMask[i];
    let area=0, sx=0, sy=0, minX=999, minY=999, maxX=-1, maxY=-1;
    stack.length = 0; stack.push(i); visited[i]=1;
    while(stack.length){
      const cur=stack.pop();
      const x=cur%aw, y=(cur/aw)|0;
      area++; sx+=x; sy+=y; if(x<minX)minX=x; if(x>maxX)maxX=x; if(y<minY)minY=y; if(y>maxY)maxY=y;
      const neigh = [cur-1, cur+1, cur-aw, cur+aw];
      for(const n of neigh){
        if(n<0 || n>=aw*ah || visited[n] || laserMask[n]!==colorKind) continue;
        const nx=n%aw;
        // не соединяем края строк через -1/+1
        if((n===cur-1 || n===cur+1) && Math.abs(nx-x)!==1) continue;
        visited[n]=1; stack.push(n);
      }
    }
    const bw=maxX-minX+1, bh=maxY-minY+1;
    const compact = bw <= 8 && bh <= 8;
    const areaOk = area >= 1 && area <= CFG.laserMaxArea;
    if(areaOk && compact){
      const score = area / Math.max(1, bw*bh);
      if(!best || score > best.score || area > best.area){
        best = { x:sx/area, y:sy/area, area, kind:colorKind, score, bw, bh };
      }
    }
  }

  const prevLaserActive = laser.active;
  const oldX = laser.x, oldY = laser.y;
  if(best){
    const sx = best.x/aw*W;
    const sy = best.y/ah*H;
    if(lastLaserCandidate){
      const jump = Math.hypot(sx-lastLaserCandidate.x, sy-lastLaserCandidate.y);
      // подтверждаем либо близкую точку в соседних кадрах, либо уже активный лазер
      if(jump < 170*DPR || prevLaserActive) laserCandidateStreak++;
      else laserCandidateStreak = 1;
    } else laserCandidateStreak = 1;
    lastLaserCandidate = { x:sx, y:sy };

    if(laserCandidateStreak >= 2 || prevLaserActive){
      laser.px = prevLaserActive ? oldX : null;
      laser.py = prevLaserActive ? oldY : null;
      laser.x = prevLaserActive ? lerp(oldX,sx,.65) : sx;
      laser.y = prevLaserActive ? lerp(oldY,sy,.65) : sy;
      laser.color = best.kind === 1 ? 'red' : 'green';
      laser.area = best.area;
      laser.active = true;
    } else {
      laser.active = false; laser.px = null; laser.py = null;
    }
  } else {
    laserCandidateStreak = 0; lastLaserCandidate = null;
    laser.active = false; laser.px = null; laser.py = null;
  }
}

function monsterScreen(m){
  const dy = deltaAngle(m.yaw, smoothYaw);
  const dp = m.pitch - smoothPitch;
  if(Math.abs(dy) > CFG.hFov/2 || Math.abs(dp) > CFG.vFov/2) return null;
  const nx = dy / (CFG.hFov/2);
  const ny = dp / (CFG.vFov/2);
  const wobX = Math.sin(elapsed*m.wobble*2 + m.phase) * 10 * DPR * (1-m.dist);
  const wobY = Math.cos(elapsed*m.wobble*1.7 + m.phase) * 7 * DPR * (1-m.dist);
  return {
    x: W/2 + nx*W/2 + wobX,
    y: H/2 - ny*H/2 + wobY,
    scale: lerp(0.45, 1.85, 1-m.dist),
    alpha: clamp(lerp(.30, .96, 1-m.dist), .25, 1),
    dy, dp
  };
}

function distPointSegment(px,py,x1,y1,x2,y2){
  const vx=x2-x1, vy=y2-y1, wx=px-x1, wy=py-y1;
  const c1=vx*wx+vy*wy;
  if(c1<=0) return Math.hypot(px-x1,py-y1);
  const c2=vx*vx+vy*vy;
  if(c2<=c1) return Math.hypot(px-x2,py-y2);
  const t=c1/c2;
  return Math.hypot(px-(x1+t*vx), py-(y1+t*vy));
}

function updateMonsters(dt){
  nextSpawn -= dt;
  const desiredSpawn = clamp(lerp(CFG.spawnEveryMax, CFG.spawnEveryMin, elapsed/CFG.duration), CFG.spawnEveryMin, CFG.spawnEveryMax);
  if(nextSpawn <= 0 && monsters.length < CFG.maxMonsters){ spawnMonster(); nextSpawn = rand(desiredSpawn*.75, desiredSpawn*1.25); }

  for(const m of monsters){
    m.dist -= m.speed * dt;
    // тени немного «плывут» по направлению, чтобы жили вне кадра
    m.yaw += Math.sin(elapsed*.55 + m.phase) * dt * 1.2;
    m.pitch += Math.cos(elapsed*.45 + m.phase) * dt * 0.45;
    const s = monsterScreen(m);

    if(s){
      const radius = (m.type === 'flash' ? 58 : 48) * s.scale * DPR;
      if(m.type === 'flash' && light.rising && performance.now()/1000 - m.lastHit > CFG.damageCooldown){
        const d = Math.hypot(s.x-light.x, s.y-light.y);
        if(light.active && d < radius + light.radius*.65){ hitMonster(m, 1); }
      }
      if(m.type === 'laser' && laser.active && laser.px !== null && performance.now()/1000 - m.lastHit > CFG.damageCooldown){
        const len = Math.hypot(laser.x-laser.px, laser.y-laser.py);
        if(len > CFG.slashMinLen * DPR){
          const d = distPointSegment(s.x, s.y, laser.px, laser.py, laser.x, laser.y);
          if(d < radius*.78){ hitMonster(m, 1); }
        }
      }
    }
  }

  for(const m of monsters){
    if(m.dist <= 0){ lives--; m.dead = true; showToast('Монстр добрался! -1 жизнь'); }
  }
  monsters = monsters.filter(m=>!m.dead);
  if(lives <= 0) endGame(false);
}

function hitMonster(m, dmg){
  m.hp -= dmg; m.lastHit = performance.now()/1000; m.hitFlash = 0.18;
  if(m.hp <= 0){ m.dead = true; score++; showToast(m.type==='flash' ? 'Тень рассеяна вспышкой!' : 'Паук рассечён лазером!'); }
}

function drawCamera(){
  if(cameraReady && video.videoWidth){
    const vw=video.videoWidth, vh=video.videoHeight;
    const scale = Math.max(W/vw, H/vh);
    const dw=vw*scale, dh=vh*scale;
    // Не зеркалим изображение: картинка совпадает с реальным направлением камеры.
    ctx.drawImage(video, (W-dw)/2, (H-dh)/2, dw, dh);
  } else { ctx.fillStyle='#070914'; ctx.fillRect(0,0,W,H); }
  // хоррор-затемнение + виньетка
  ctx.fillStyle='rgba(0,0,12,.46)'; ctx.fillRect(0,0,W,H);
  const g=ctx.createRadialGradient(W/2,H/2,Math.min(W,H)*.05,W/2,H/2,Math.max(W,H)*.72);
  g.addColorStop(0,'rgba(0,0,0,0)'); g.addColorStop(.56,'rgba(0,0,20,.22)'); g.addColorStop(1,'rgba(0,0,0,.78)');
  ctx.fillStyle=g; ctx.fillRect(0,0,W,H);
}

function drawFlashlightBlob(){
  if(light.active){
    const g=ctx.createRadialGradient(light.x,light.y,0,light.x,light.y,light.radius*1.6);
    g.addColorStop(0,'rgba(255,246,180,.34)'); g.addColorStop(.45,'rgba(255,220,110,.16)'); g.addColorStop(1,'rgba(255,220,90,0)');
    ctx.fillStyle=g; ctx.beginPath(); ctx.arc(light.x,light.y,light.radius*1.6,0,Math.PI*2); ctx.fill();
    ctx.strokeStyle=light.rising?'rgba(255,255,220,.95)':'rgba(255,230,120,.55)'; ctx.lineWidth=2*DPR; ctx.beginPath(); ctx.arc(light.x,light.y,light.radius*.65,0,Math.PI*2); ctx.stroke();
  }
  if(laser.active){
    ctx.strokeStyle = laser.color === 'red' ? 'rgba(255,45,55,.95)' : 'rgba(70,255,100,.95)';
    ctx.fillStyle = ctx.strokeStyle;
    ctx.lineWidth = 2*DPR;
    if(laser.px!==null){ ctx.beginPath(); ctx.moveTo(laser.px,laser.py); ctx.lineTo(laser.x,laser.y); ctx.stroke(); }
    ctx.beginPath(); ctx.arc(laser.x,laser.y,5*DPR,0,Math.PI*2); ctx.fill();
  }
}

function drawMonster(m){
  const s = monsterScreen(m);
  if(!s) return;
  const base = (m.type==='flash'? 72:62) * s.scale * DPR;
  const x=s.x,y=s.y;
  const alpha = s.alpha;
  ctx.save(); ctx.globalAlpha=alpha;
  if(m.hitFlash && m.hitFlash>0){ ctx.shadowColor='rgba(255,255,255,.9)'; ctx.shadowBlur=30*DPR; m.hitFlash-=1/60; }
  if(m.type==='flash') drawWraith(x,y,base,m); else drawSpider(x,y,base,m);
  drawHp(x,y-base*1.05,base,m);
  ctx.restore();
}

function drawHp(x,y,base,m){
  const w=base*1.25,h=7*DPR;
  ctx.fillStyle='rgba(0,0,0,.55)'; ctx.fillRect(x-w/2,y,w,h);
  ctx.fillStyle=m.type==='flash'?'rgba(255,225,120,.95)':'rgba(255,70,85,.95)'; ctx.fillRect(x-w/2,y,w*(m.hp/m.maxHp),h);
}

function drawWraith(x,y,r,m){
  const t=elapsed*4+m.phase;
  ctx.shadowColor='rgba(70,90,255,.45)'; ctx.shadowBlur=18*DPR;
  const g=ctx.createRadialGradient(x,y-r*.15,r*.1,x,y,r*1.1);
  g.addColorStop(0,'rgba(95,110,150,.82)'); g.addColorStop(.55,'rgba(25,28,45,.84)'); g.addColorStop(1,'rgba(0,0,0,.05)');
  ctx.fillStyle=g;
  ctx.beginPath();
  ctx.moveTo(x, y-r*.95);
  ctx.bezierCurveTo(x-r*.75,y-r*.72,x-r*.78,y-r*.05,x-r*.48,y+r*.35);
  for(let i=0;i<5;i++){
    const px=x-r*.48+i*r*.24; const py=y+r*.35+Math.sin(t+i)*r*.12;
    ctx.quadraticCurveTo(px+r*.09,py+r*.25,px+r*.20,py);
  }
  ctx.bezierCurveTo(x+r*.78,y-r*.05,x+r*.75,y-r*.72,x,y-r*.95);
  ctx.fill();
  ctx.fillStyle='rgba(255,245,190,.95)';
  ctx.beginPath(); ctx.ellipse(x-r*.22,y-r*.28,r*.10,r*.055,0,0,Math.PI*2); ctx.fill();
  ctx.beginPath(); ctx.ellipse(x+r*.22,y-r*.28,r*.10,r*.055,0,0,Math.PI*2); ctx.fill();
  ctx.strokeStyle='rgba(255,245,190,.55)'; ctx.lineWidth=2*DPR;
  ctx.beginPath(); ctx.arc(x,y-r*.08,r*.28,0.15*Math.PI,0.85*Math.PI); ctx.stroke();
  ctx.fillStyle='rgba(255,255,255,.75)'; ctx.font=`${Math.max(12, r*.18)}px system-ui`; ctx.textAlign='center';
  ctx.fillText(`вспышек: ${m.hp}`, x, y+r*.78);
}

function drawSpider(x,y,r,m){
  const t=elapsed*5+m.phase;
  ctx.shadowColor='rgba(255,40,70,.38)'; ctx.shadowBlur=15*DPR;
  ctx.strokeStyle='rgba(2,2,7,.92)'; ctx.lineWidth=Math.max(2, r*.055);
  for(let side of [-1,1]){
    for(let i=0;i<4;i++){
      const yy=y-r*.26+i*r*.17;
      const bend=Math.sin(t+i)*r*.08;
      ctx.beginPath();
      ctx.moveTo(x+side*r*.28, yy);
      ctx.lineTo(x+side*(r*.70+bend), yy-r*.20+Math.sin(t+i)*r*.04);
      ctx.lineTo(x+side*(r*1.02), yy+r*.12);
      ctx.stroke();
    }
  }
  const g=ctx.createRadialGradient(x,y-r*.1,r*.1,x,y,r*.75);
  g.addColorStop(0,'rgba(60,5,14,.98)'); g.addColorStop(1,'rgba(0,0,0,.92)'); ctx.fillStyle=g;
  ctx.beginPath(); ctx.ellipse(x,y,r*.43,r*.58,0,0,Math.PI*2); ctx.fill();
  ctx.beginPath(); ctx.ellipse(x,y-r*.54,r*.30,r*.25,0,0,Math.PI*2); ctx.fill();
  ctx.fillStyle='rgba(255,65,70,.95)';
  ctx.beginPath(); ctx.arc(x-r*.12,y-r*.58,r*.045,0,Math.PI*2); ctx.fill();
  ctx.beginPath(); ctx.arc(x+r*.12,y-r*.58,r*.045,0,Math.PI*2); ctx.fill();
  ctx.fillStyle='rgba(255,255,255,.75)'; ctx.font=`${Math.max(12, r*.18)}px system-ui`; ctx.textAlign='center';
  ctx.fillText(`разрезов: ${m.hp}`, x, y+r*.86);
}

function drawReticle(){
  ctx.save(); ctx.strokeStyle='rgba(210,230,255,.22)'; ctx.lineWidth=1.5*DPR;
  ctx.beginPath(); ctx.moveTo(W/2-18*DPR,H/2); ctx.lineTo(W/2+18*DPR,H/2); ctx.moveTo(W/2,H/2-18*DPR); ctx.lineTo(W/2,H/2+18*DPR); ctx.stroke();
  ctx.restore();
}

function drawRadar(){
  const rw=radarCanvas.width, rh=radarCanvas.height, cx=rw/2, cy=rh/2, rr=Math.min(rw,rh)/2-8*DPR;
  rctx.clearRect(0,0,rw,rh);
  rctx.fillStyle='rgba(0,0,0,.20)'; rctx.beginPath(); rctx.arc(cx,cy,rr,0,Math.PI*2); rctx.fill();
  rctx.strokeStyle='rgba(180,210,255,.25)'; rctx.lineWidth=1*DPR; rctx.beginPath(); rctx.arc(cx,cy,rr,0,Math.PI*2); rctx.stroke();
  rctx.strokeStyle='rgba(120,230,255,.45)'; rctx.beginPath(); rctx.moveTo(cx,cy); rctx.arc(cx,cy,rr,-Math.PI*0.25,-Math.PI*0.75,true); rctx.closePath(); rctx.stroke();
  for(const m of monsters){
    const a = deltaAngle(m.yaw, smoothYaw) * Math.PI/180 - Math.PI/2;
    const d = rr * clamp(m.dist,0,1);
    rctx.fillStyle=m.type==='flash'?'rgba(255,220,110,.9)':'rgba(255,60,80,.9)';
    rctx.beginPath(); rctx.arc(cx+Math.cos(a)*d, cy+Math.sin(a)*d, 4*DPR,0,Math.PI*2); rctx.fill();
  }
}

function updateHud(){
  const remain=Math.max(0, CFG.duration-elapsed);
  const mm=String(Math.floor(remain/60)).padStart(2,'0'); const ss=String(Math.floor(remain%60)).padStart(2,'0');
  timeText.textContent=`${mm}:${ss}`; livesText.textContent=lives; scoreText.textContent=score;
}

function endGame(win){
  if(!running) return;
  running=false; topHud.classList.add('hidden'); radar.classList.add('hidden'); endPanel.classList.remove('hidden');
  endTitle.textContent = win ? 'Ты выжил!' : 'Тьма добралась до тебя';
  endStats.textContent = `Уничтожено монстров: ${score}. Время: ${Math.floor(elapsed)} сек.`;
}

function loop(t){
  if(!running) return;
  const dt=Math.min(0.05,(t-lastT)/1000 || 0.016); lastT=t; elapsed += dt;
  updateOrientation(dt); analyzeLight(); updateMonsters(dt);
  drawCamera();
  const sorted = [...monsters].sort((a,b)=>b.dist-a.dist);
  for(const m of sorted) drawMonster(m);
  drawFlashlightBlob(); drawReticle(); drawRadar(); updateHud();
  if(elapsed >= CFG.duration) endGame(true);
  else requestAnimationFrame(loop);
}

if('serviceWorker' in navigator){ navigator.serviceWorker.register('./service-worker.js').catch(()=>{}); }
})();
