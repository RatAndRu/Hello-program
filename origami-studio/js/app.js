import { craneSteps, projects, moduleTemplates, notation } from './data.js';
import { stepDiagram, creasePattern, projectIcon, operationIcon } from './diagrams.js';
import { OrigamiScene } from './scene.js';
import { buildModulePlan, modulePlanSvg, moduleBomHtml } from './modular.js';

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const state = {
  step: 9,
  viewed: new Set(craneSteps.map((_, i) => i)),
  view: '3d',
  playing: false,
  pose: 9,
  filter: 'all',
  exporting: false
};

let scene;
let playbackFrame = null;
let playbackStart = 0;
let playbackFrom = 0;
let toastTimer;

try {
  scene = new OrigamiScene($('#scene-container'));
} catch (error) {
  console.error('3D renderer could not start:', error);
  $('#scene-container').innerHTML = '<div style="display:grid;place-items:center;height:100%;padding:40px;text-align:center;color:#748077">3D-просмотр недоступен в этом браузере.<br>Схемы шагов и печатная инструкция продолжают работать.</div>';
}

function icon(id) { return `<svg><use href="#${id}"/></svg>`; }

function renderProjects() {
  const query = $('#project-search').value.trim().toLowerCase();
  const filtered = projects.filter(project =>
    (state.filter === 'all' || project.category === state.filter) &&
    `${project.title} ${project.category}`.toLowerCase().includes(query)
  );
  $('#project-list').innerHTML = filtered.map(project => `
    <button class="project-card ${project.id === 'crane' ? 'active' : ''} ${project.status === 'soon' ? 'soon' : ''}" data-project="${project.id}">
      <span class="project-thumb">${projectIcon(project.icon)}</span>
      <span class="project-card-text"><strong>${project.title}</strong><small>${project.description}</small></span>
      ${project.status === 'soon' ? '<span class="project-status">СКОРО</span>' : project.status === 'concept' ? '<span class="project-status">3D</span>' : ''}
    </button>`).join('') || '<p style="font-size:11px;color:#92998f;padding:12px">Ничего не найдено</p>';
  $$('[data-project]').forEach(button => button.addEventListener('click', () => {
    const id = button.dataset.project;
    if (id === 'crane') {
      selectStep(9);
      showToast('Журавлик открыт · 10 интерактивных шагов');
    } else if (id === 'ring') {
      openModulePlanner();
    } else showToast('Эта заготовка показана в дорожной карте прототипа', '○');
  }));
}

function renderStepStrip() {
  $('#step-strip').innerHTML = craneSteps.map((step, i) => `
    <button class="step-card ${i === state.step ? 'active' : ''} ${state.viewed.has(i) ? 'viewed' : ''}" data-step="${i}" title="${i + 1}. ${step.title}">
      <span class="step-preview">${stepDiagram(step.diagram)}</span>
      <span class="step-card-label"><b>${String(i + 1).padStart(2, '0')}</b><span>${step.short}</span></span>
    </button>`).join('');
  $$('[data-step]').forEach(button => button.addEventListener('click', () => selectStep(Number(button.dataset.step))));
}

function updateStepUI() {
  const step = craneSteps[state.step];
  $('#instruction-number').textContent = `ШАГ ${state.step + 1}`;
  $('#operation-badge').textContent = step.typeLabel;
  $('#instruction-title').textContent = step.title;
  $('#instruction-description').textContent = step.description;
  $('#instruction-tip').textContent = step.tip;
  $('#instruction-result').textContent = step.result;
  $('#instruction-diagram').innerHTML = stepDiagram(step.diagram);
  $('#step-current').textContent = state.step + 1;
  $('#time-left').textContent = state.step === 9 ? 'Готово' : `≈ ${Math.max(1, Math.ceil((9 - state.step) * .65))} мин`;
  $('#model-badge-text').textContent = state.step === 9 ? 'Один лист · 144 грани' : `Лист после шага ${state.step + 1}`;
  $('#progress-label').textContent = `${state.viewed.size} из 10 просмотрено`;
  $('#instruction-prev').disabled = state.step === 0;
  $('#prev-step').disabled = state.step === 0;
  $('#instruction-next').disabled = state.step === 9;
  $('#next-step').disabled = state.step === 9;
  $('#instruction-next').innerHTML = state.step === 9 ? `Модель готова ${icon('i-check')}` : `Следующий шаг ${icon('i-chevron')}`;
  $$('.step-card').forEach((card, i) => {
    card.classList.toggle('active', i === state.step);
    card.classList.toggle('viewed', state.viewed.has(i));
  });
  $$('.timeline-ticks button').forEach((tick, i) => tick.classList.toggle('active', i === state.step));
  if (state.view === 'diagram') $('#diagram-container').innerHTML = stepDiagram(step.diagram);
  document.title = `${state.step + 1}/10 · ${step.title} — Origami Studio`;
}

function updateTimeline(pose) {
  state.pose = Math.max(0, Math.min(9, pose));
  $('#timeline').value = state.pose;
  $('#timeline').style.setProperty('--progress', `${state.pose / 9 * 100}%`);
}

function selectStep(index, options = {}) {
  if (!options.keepPlaying) stopPlayback();
  const next = Math.max(0, Math.min(9, Math.round(index)));
  state.step = next;
  state.viewed.add(next);
  updateTimeline(next);
  if (scene && !options.noPose) {
    scene.showStep(next);
  }
  updateStepUI();
}

function switchView(view) {
  state.view = view;
  $$('.view-tab').forEach(tab => tab.classList.toggle('active', tab.dataset.view === view));
  $('#scene-container').hidden = view !== '3d';
  $('#diagram-container').hidden = view !== 'diagram';
  $('#pattern-container').hidden = view !== 'pattern';
  $('#view-hint').hidden = view !== '3d';
  $('#reset-camera').hidden = view !== '3d';
  $('#model-badge-text').textContent = view === 'pattern' ? 'Основные складки' : state.step === 9 ? 'Один лист · 144 грани' : `Лист после шага ${state.step + 1}`;
  if (view === 'diagram') $('#diagram-container').innerHTML = stepDiagram(craneSteps[state.step].diagram);
  if (view === 'pattern') $('#pattern-container').innerHTML = creasePattern(scene?.data);
  if (view === '3d' && scene) scene.cameraPreset(craneSteps[state.step].camera);
}

function stopPlayback() {
  state.playing = false;
  if (playbackFrame) cancelAnimationFrame(playbackFrame);
  playbackFrame = null;
  $('#play-button').classList.remove('playing');
  $('#play-button').innerHTML = icon('i-play');
  $('#play-button').setAttribute('aria-label', 'Запустить анимацию');
  $('#playback-status').hidden = true;
}

function startPlayback() {
  if (!scene || state.exporting) return;
  if (state.pose >= 8.99) selectStep(0);
  state.playing = true;
  playbackFrom = state.pose;
  playbackStart = performance.now();
  $('#play-button').classList.add('playing');
  $('#play-button').innerHTML = icon('i-pause');
  $('#play-button').setAttribute('aria-label', 'Пауза');
  $('#playback-status').hidden = false;
  if (state.view !== '3d') switchView('3d');
  const speed = Number($('#playback-speed').value);
  const duration = (9 - playbackFrom) * 1750 / speed;
  const frame = now => {
    if (!state.playing) return;
    const t = Math.min(1, (now - playbackStart) / duration);
    const pose = playbackFrom + (9 - playbackFrom) * t;
    scene.setPose(pose);
    updateTimeline(pose);
    const instructionStep = Math.min(9, Math.floor(pose + .35));
    if (instructionStep !== state.step) selectStep(instructionStep, { keepPlaying: true, noPose: true });
    if (t < 1) playbackFrame = requestAnimationFrame(frame);
    else {
      stopPlayback();
      selectStep(9);
      showToast('Журавлик готов! Можно распечатать инструкцию.');
    }
  };
  playbackFrame = requestAnimationFrame(frame);
}

function showToast(message, symbol = '✓') {
  clearTimeout(toastTimer);
  $('#toast-text').textContent = message;
  $('#toast-icon').textContent = symbol;
  $('#toast').hidden = false;
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 3600);
}

function openDialog(id) { const dialog = document.getElementById(id); if (dialog && !dialog.open) dialog.showModal(); }

function currentModulePlan() {
  return buildModulePlan({
    count: $('#planner-count').value,
    rows: $('#planner-rows').value,
    paperWidth: $('#planner-paper-width').value,
    paperHeight: $('#planner-paper-height').value,
    pitch: $('#planner-pitch').value,
  });
}

function renderModulePlanner() {
  try {
    const plan = currentModulePlan();
    $('#planner-preview').innerHTML = modulePlanSvg(plan);
    $('#planner-bom').innerHTML = moduleBomHtml(plan);
    $('#planner-stats').innerHTML = [
      [plan.totals.units, 'бумажных деталей'],
      [`Ø ${plan.totals.baseDiameterMm.toFixed(1)}`, 'мм · первый ряд'],
      [plan.totals.paperAreaCm2.toFixed(0), 'см² бумаги всего'],
    ].map(([value,label]) => `<div class="planner-stat"><b>${value}</b><span>${label}</span></div>`).join('');
  } catch (error) {
    $('#planner-preview').innerHTML = `<p style="color:#a56850;font-size:11px">${error.message}</p>`;
  }
}

function openModulePlanner() {
  renderModulePlanner();
  openDialog('module-dialog');
}

function renderLibraries() {
  $('#module-grid').innerHTML = moduleTemplates.map(module => `
    <article class="module-card" style="--module-color:${module.color}">
      <div class="module-card-top"><div><span class="module-family">${module.family}</span><h3>${module.name}</h3></div><span class="module-subtitle">${module.subtitle}</span></div>
      <p class="module-description">${module.description}</p>
      <div class="module-joints">${module.joints.map(joint => `<span>${joint}</span>`).join('')}</div>
      <div class="module-meta"><div><small>ПОДХОДИТ ДЛЯ</small><b>${module.best}</b></div><div><small>КОЛИЧЕСТВО</small><b>${module.units}</b></div></div>
      <button class="module-use" data-use-module="${module.id}" ${module.id === 'golden-venture' ? '' : 'disabled'}>${module.id === 'golden-venture' ? 'Открыть планировщик →' : 'Только справка · не реализовано'}</button>
    </article>`).join('');
  $('[data-use-module="golden-venture"]').addEventListener('click', () => {
    $('#library-dialog').close();
    openModulePlanner();
  });
  $('#notation-grid').innerHTML = notation.map(item => `
    <article class="notation-item" style="--notation-color:${item.color}">
      <span class="notation-icon" style="color:${item.color}">${operationIcon(item.id)}</span>
      <div><strong>${item.name}</strong><span class="notation-symbol">${item.symbol}</span></div>
      <p>${item.description}</p>
    </article>`).join('');
}

function buildPrintSheet() {
  $('#print-sheet').innerHTML = `
    <header class="print-header"><div><h1>Классический журавлик</h1><p>Origami Studio · один квадратный лист 15 × 15 см · без клея и ножниц</p></div><span>10 шагов</span></header>
    <div class="print-grid">${craneSteps.map((step, i) => `
      <article class="print-step">${stepDiagram(step.diagram)}<div><small>ШАГ ${i + 1} · ${step.typeLabel.toUpperCase()}</small><h3>${step.title}</h3><p>${step.description}</p></div></article>`).join('')}</div>
    <footer class="print-footer"><span>Пунктир — долина · штрих-пунктир — гора · стрелка — направление движения</span><span>origami-studio.local</span></footer>`;
}

const exportDiagramCSS = `
  .paper{fill:#fffdf7;stroke:#68776e;stroke-width:1.35;stroke-linejoin:round}.paper-back{fill:#f4d5c6}.paper-front{fill:#f4bda6;stroke:#8d6e5f;stroke-width:1}
  .valley,.mountain,.old-crease,.center-crease,.crease{fill:none;stroke-linecap:round}.valley{stroke:#ce7254;stroke-width:1.6;stroke-dasharray:7 5}.mountain{stroke:#537b8e;stroke-width:1.5;stroke-dasharray:10 4 2 4}.old-crease{stroke:#b9b9ae;stroke-width:1.2;stroke-dasharray:4 5}.center-crease{stroke:#b2b5aa;stroke-width:1;stroke-dasharray:3 4}
  .fold-arrow,.unfold-arrow{fill:none;stroke:#cf704f;stroke-width:2.1;stroke-linecap:round}.fold-arrow.green,.unfold-arrow{stroke:#527766}.diagram-label{fill:#58675e;font-family:Arial,sans-serif;font-size:12px}.diagram-note{fill:#8b9187;font-family:Arial,sans-serif;font-size:9px;letter-spacing:.4px}.step-badge{fill:#fffaf0;stroke:#b8bbae;stroke-width:1}.badge-text{fill:#778177;font-family:Arial,sans-serif;font-size:11px;font-weight:700}.turn-disc{fill:#eef1e9}.turn-icon{fill:none;stroke:#527766;stroke-width:2}.ghost-fold{fill:#edd5c9;fill-opacity:.35;stroke:#bda99d;stroke-width:1.1;stroke-dasharray:4 3}.paper-fold-back{fill:#f1c5b2;stroke:#9e7d6e;stroke-width:1}.leader{fill:none;stroke:#adb3a8;stroke-width:1}.crane-paper{fill:#f9d6c4;stroke:#8d7569;stroke-width:1;stroke-linejoin:round}.crane-paper-dark{fill:#e7ad92;stroke:#8d7569;stroke-width:1;stroke-linejoin:round}.crane-body{fill:#f2c0a8;stroke:#8d7569;stroke-width:1}`;

function standaloneDiagram(id) {
  return stepDiagram(id).replace('<defs>', `<style>${exportDiagramCSS}</style><defs>`);
}

function loadSvgImage(markup) {
  return new Promise((resolve, reject) => {
    const blob = new Blob([markup], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => { URL.revokeObjectURL(url); resolve(image); };
    image.onerror = error => { URL.revokeObjectURL(url); reject(error); };
    image.src = url;
  });
}

function roundedRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

function wrapText(ctx, text, x, y, maxWidth, lineHeight, maxLines = 8) {
  const words = text.split(' ');
  let line = '', lineNumber = 0;
  for (let n = 0; n < words.length; n++) {
    const test = line + words[n] + ' ';
    if (ctx.measureText(test).width > maxWidth && n > 0) {
      ctx.fillText(line.trim(), x, y + lineNumber * lineHeight);
      line = words[n] + ' ';
      lineNumber++;
      if (lineNumber >= maxLines - 1) break;
    } else line = test;
  }
  ctx.fillText(line.trim(), x, y + lineNumber * lineHeight);
  return lineNumber + 1;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

async function exportPNG() {
  if (state.exporting) return;
  state.exporting = true;
  $('#export-menu').hidden = true;
  $('#export-progress').hidden = false;
  $('#export-progress-title').textContent = 'Собираем лист инструкций…';
  $('#export-progress-text').textContent = '10 схем · формат PNG';
  try {
    const canvas = document.createElement('canvas');
    canvas.width = 1800;
    canvas.height = 2720;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#f7f5ee';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#294036';
    ctx.font = '52px Georgia, serif';
    ctx.fillText('Классический журавлик', 70, 100);
    ctx.fillStyle = '#7a857c';
    ctx.font = '22px Arial, sans-serif';
    ctx.fillText('Origami Studio  ·  один лист 15 × 15 см  ·  без клея и ножниц', 72, 145);
    ctx.strokeStyle = '#4d7060'; ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(70,180); ctx.lineTo(1730,180); ctx.stroke();
    const images = await Promise.all(craneSteps.map(step => loadSvgImage(standaloneDiagram(step.diagram))));
    images.forEach((image, i) => {
      const col = i % 2, row = Math.floor(i / 2);
      const x = 65 + col * 855, y = 215 + row * 480, w = 815, h = 445;
      ctx.fillStyle = '#fffdf8'; roundedRect(ctx,x,y,w,h,16); ctx.fill();
      ctx.strokeStyle = '#dce0d7'; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = '#eef0e8'; roundedRect(ctx,x+18,y+55,350,330,10); ctx.fill();
      ctx.drawImage(image,x+20,y+65,345,310);
      ctx.fillStyle = '#ca7153'; ctx.font = 'bold 17px Arial, sans-serif';
      ctx.fillText(`ШАГ ${i+1}`,x+395,y+66);
      ctx.fillStyle = '#2d4036'; ctx.font = 'bold 26px Georgia, serif';
      wrapText(ctx,craneSteps[i].title,x+395,y+108,385,31,2);
      ctx.fillStyle = '#69756c'; ctx.font = '19px Arial, sans-serif';
      wrapText(ctx,craneSteps[i].description,x+395,y+177,380,27,7);
      ctx.fillStyle = '#8b7a5c'; ctx.font = 'italic 16px Arial, sans-serif';
      wrapText(ctx,craneSteps[i].tip,x+395,y+367,380,21,3);
      $('#export-progress-bar').style.width = `${(i + 1) * 10}%`;
    });
    ctx.fillStyle = '#899188'; ctx.font = '17px Arial, sans-serif';
    ctx.fillText('Пунктир — долина  ·  штрих-пунктир — гора  ·  стрелка — движение бумаги',70,2670);
    const blob = await new Promise(resolve => canvas.toBlob(resolve,'image/png'));
    if (!blob) throw new Error('PNG export returned no data');
    downloadBlob(blob,'origami-crane-instructions.png');
    showToast('Лист инструкций PNG сохранён');
  } catch (error) {
    console.error(error);
    showToast('Не удалось создать PNG. Попробуй печать / PDF.', '!');
  } finally {
    state.exporting = false;
    $('#export-progress').hidden = true;
    $('#export-progress-bar').style.width = '0';
  }
}

async function exportVideo() {
  if (state.exporting) return;
  if (!scene || !window.MediaRecorder || !HTMLCanvasElement.prototype.captureStream) {
    showToast('Этот браузер не поддерживает запись WebM. Доступны PNG и PDF.', '!');
    return;
  }
  state.exporting = true;
  stopPlayback();
  switchView('3d');
  $('#export-menu').hidden = true;
  $('#export-progress').hidden = false;
  $('#export-progress-title').textContent = 'Создаём видео сборки…';
  $('#export-progress-text').textContent = '16 секунд · WebM · без звука';
  const previousStep = state.step;
  const canvas = $('#video-canvas');
  const ctx = canvas.getContext('2d');
  const stream = canvas.captureStream(30);
  const mimeType = ['video/webm;codecs=vp9','video/webm;codecs=vp8','video/webm'].find(type => MediaRecorder.isTypeSupported(type));
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType, videoBitsPerSecond: 5_000_000 } : undefined);
  const chunks = [];
  recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
  const completed = new Promise(resolve => { recorder.onstop = resolve; });
  recorder.start(250);
  const started = performance.now();
  const duration = 16000;
  await new Promise(resolve => {
    const draw = now => {
      const t = Math.min(1,(now-started)/duration);
      const pose = t * 9;
      scene.setPose(pose);
      const stepIndex = Math.min(9,Math.floor(pose + .35));
      ctx.fillStyle = '#eef0e8'; ctx.fillRect(0,0,1280,720);
      ctx.fillStyle = '#2b4035'; ctx.font = '34px Georgia, serif'; ctx.fillText('Классический журавлик',45,52);
      ctx.fillStyle = '#7b877d'; ctx.font = '16px Arial, sans-serif'; ctx.fillText('ORIGAMI STUDIO',1020,48);
      ctx.drawImage(scene.canvas,0,78,1280,515);
      ctx.fillStyle = '#fffdf8'; ctx.fillRect(0,593,1280,127);
      ctx.fillStyle = '#ca7153'; ctx.font = 'bold 15px Arial, sans-serif'; ctx.fillText(`ШАГ ${stepIndex+1} / 10`,45,630);
      ctx.fillStyle = '#2c4035'; ctx.font = '26px Georgia, serif'; ctx.fillText(craneSteps[stepIndex].title,45,671);
      ctx.fillStyle = '#d9ded6'; ctx.fillRect(45,693,1190,4);
      ctx.fillStyle = '#4d7060'; ctx.fillRect(45,693,1190*t,4);
      $('#export-progress-bar').style.width = `${t*100}%`;
      if (t < 1) requestAnimationFrame(draw); else resolve();
    };
    requestAnimationFrame(draw);
  });
  recorder.stop();
  await completed;
  stream.getTracks().forEach(track => track.stop());
  const blob = new Blob(chunks,{type:'video/webm'});
  downloadBlob(blob,'origami-crane.webm');
  scene.setPose(previousStep);
  selectStep(previousStep);
  state.exporting = false;
  $('#export-progress').hidden = true;
  $('#export-progress-bar').style.width = '0';
  showToast('Видео WebM сохранено');
}

function bindEvents() {
  $$('.view-tab').forEach(tab => tab.addEventListener('click', () => switchView(tab.dataset.view)));
  $('#prev-step').addEventListener('click', () => selectStep(state.step - 1));
  $('#next-step').addEventListener('click', () => selectStep(state.step + 1));
  $('#instruction-prev').addEventListener('click', () => selectStep(state.step - 1));
  $('#instruction-next').addEventListener('click', () => selectStep(state.step + 1));
  $('#play-button').addEventListener('click', () => state.playing ? stopPlayback() : startPlayback());
  $('#timeline').addEventListener('input', event => {
    stopPlayback();
    const pose = Number(event.target.value);
    if (scene) scene.setPose(pose);
    updateTimeline(pose);
    const step = Math.min(9,Math.floor(pose + .35));
    if (step !== state.step) selectStep(step,{noPose:true});
  });
  $('#reset-camera').addEventListener('click', () => scene?.resetCamera());
  $('#viewer-info').addEventListener('click', () => openDialog('info-dialog'));
  $('#open-library').addEventListener('click', () => openDialog('library-dialog'));
  $('#open-modules').addEventListener('click', () => openDialog('library-dialog'));
  $('#open-notation').addEventListener('click', () => openDialog('notation-dialog'));
  ['#planner-count','#planner-rows','#planner-paper-width','#planner-paper-height','#planner-pitch'].forEach(id => $(id).addEventListener('input', renderModulePlanner));
  $('#planner-export').addEventListener('click', () => {
    try {
      const plan = currentModulePlan();
      downloadBlob(new Blob([JSON.stringify(plan,null,2)],{type:'application/json'}),'golden-venture-layout.json');
      showToast('План компоновки сохранён · это не сертификат собираемости');
    } catch (error) { showToast(error.message,'!'); }
  });
  $('#new-project').addEventListener('click', () => openDialog('new-dialog'));
  $('#sidebar-add').addEventListener('click', () => openDialog('new-dialog'));
  $$('.modal-close').forEach(button => button.addEventListener('click', () => document.getElementById(button.dataset.close).close()));
  $$('dialog').forEach(dialog => dialog.addEventListener('click', event => {
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  }));
  $$('[data-route]').forEach(button => button.addEventListener('click', () => {
    const route = button.dataset.route;
    $('#new-dialog').close();
    if (route === 'template') { selectStep(0); showToast('Начни с первого шага журавлика'); }
    else if (route === 'module') openModulePlanner();
    else showToast('Маршрут заложен в концепцию; редактор появится на следующем этапе', '○');
  }));
  $('#project-search').addEventListener('input', renderProjects);
  $$('[data-filter]').forEach(button => button.addEventListener('click', () => {
    state.filter = button.dataset.filter;
    $$('[data-filter]').forEach(chip => chip.classList.toggle('active',chip === button));
    renderProjects();
  }));
  $('#export-toggle').addEventListener('click', event => {
    event.stopPropagation();
    const menu = $('#export-menu');
    menu.hidden = !menu.hidden;
    $('#export-toggle').setAttribute('aria-expanded',String(!menu.hidden));
  });
  document.addEventListener('click', event => {
    if (!event.target.closest('.export-wrap')) { $('#export-menu').hidden = true; $('#export-toggle').setAttribute('aria-expanded','false'); }
  });
  $('#export-png').addEventListener('click', exportPNG);
  $('#export-video').addEventListener('click', exportVideo);
  $('#download-source').addEventListener('click', () => {
    $('#export-menu').hidden = true;
    const link = document.createElement('a');
    link.href = './downloads/origami-studio.zip';
    link.download = 'origami-studio.zip';
    document.body.appendChild(link);
    link.click();
    link.remove();
  });
  $('#export-print').addEventListener('click', () => {
    $('#export-menu').hidden = true;
    buildPrintSheet();
    document.title = 'Классический журавлик — инструкция';
    window.print();
    setTimeout(() => { document.title = `${state.step+1}/10 · ${craneSteps[state.step].title} — Origami Studio`; },500);
  });
  document.addEventListener('keydown', event => {
    if (['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName) || $('dialog[open]') || state.exporting) return;
    if (event.key === 'ArrowRight') selectStep(state.step+1);
    if (event.key === 'ArrowLeft') selectStep(state.step-1);
    if (event.code === 'Space') { event.preventDefault(); state.playing ? stopPlayback() : startPlayback(); }
  });
}

renderProjects();
renderStepStrip();
renderLibraries();
bindEvents();
$('#timeline-ticks').innerHTML = craneSteps.map((_,i) => `<button data-tick="${i}" aria-label="Шаг ${i+1}">${i+1}</button>`).join('');
$$('[data-tick]').forEach(button => button.addEventListener('click',() => selectStep(Number(button.dataset.tick))));
$('#pattern-container').innerHTML = creasePattern(scene?.data);
selectStep(9);
buildPrintSheet();

// Small, read-only hook for smoke tests and future project importers.
window.origamiStudio = {
  getState: () => ({ step: state.step, pose: state.pose, view: state.view, playing: state.playing, steps: craneSteps.length }),
  selectStep,
  switchView
};
