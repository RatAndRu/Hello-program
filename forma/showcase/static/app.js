const content = document.querySelector('#content');
const versionNav = document.querySelector('#version-nav');
const dialog = document.querySelector('#viewer-dialog');
const stage = document.querySelector('#viewer-stage');
const progress = document.querySelector('#viewer-progress');
const progressTitle = document.querySelector('#viewer-progress-title');
const progressDetail = document.querySelector('#viewer-progress-detail');
const progressBar = document.querySelector('#viewer-progress-bar');

const numberFormat = new Intl.NumberFormat('ru-RU');
let catalog = null;
let activeVersion = null;
let viewer = null;
let viewerModule = null;
let viewerGeneration = 0;
const modelIndex = new Map();

function esc(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[char]);
}

function formatNumber(value) {
  return numberFormat.format(Number(value) || 0);
}

function formatBytes(bytes) {
  const value = Number(bytes) || 0;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 1 : 2)} МБ`;
  return `${Math.max(1, Math.round(value / 1000))} КБ`;
}

function versionFromUrl() {
  return new URLSearchParams(location.search).get('v');
}

function setRevision() {
  const link = document.querySelector('#revision-link');
  const revision = catalog.revision || 'local';
  link.textContent = `revision ${revision.slice(0, 10)}`;
  if (/^[0-9a-f]{40}$/i.test(revision)) {
    link.href = `https://github.com/RatAndRu/Hello-program/commit/${revision}`;
  }
}

function renderNav() {
  versionNav.innerHTML = catalog.versions.map((version) => `
    <button class="version-button ${version.id === activeVersion ? 'active' : ''}"
      type="button" data-version="${esc(version.id)}" aria-current="${version.id === activeVersion ? 'page' : 'false'}">
      <strong>${esc(version.label)}</strong>
      <small>${esc(version.kicker)} · ${version.models.length}</small>
    </button>`).join('');
}

function changeCard(change) {
  const image = change.image
    ? `<a class="change-image-link" href="${esc(change.image)}" target="_blank" rel="noreferrer" aria-label="${esc(change.title)} — открыть сравнение полностью"><img class="change-image" src="${esc(change.image)}" alt="${esc(change.title)} — сравнение до и после" loading="lazy" decoding="async"></a>`
    : '';
  return `<article class="change"><h3>${esc(change.title)}</h3><p>${esc(change.text)}</p>${image}</article>`;
}

function posterTabs(model) {
  if (model.posters.length < 2) return '';
  return `<div class="poster-tabs" aria-label="Ракурсы модели">${model.posters.map((poster, index) => `
    <button type="button" class="poster-tab ${index === 0 ? 'active' : ''}"
      data-poster-model="${esc(model.id)}" data-poster-view="${esc(poster.view)}"
      aria-pressed="${index === 0 ? 'true' : 'false'}">${esc(poster.label)}</button>`).join('')}</div>`;
}

function modelCard(model) {
  const stats = model.stats;
  const firstPoster = model.posters[0];
  const drawLabel = stats.optimized ? 'пакетов в 3D' : 'узлов в 3D';
  const optimization = model.preview_kind === 'subset'
    ? `Лёгкий интерактивный preview: ${formatNumber(stats.preview_triangles)} треугольников вместо ${formatNumber(stats.triangles)}. Полный GLB и исходник содержат все детали; ничего не загружается до нажатия кнопки.`
    : stats.optimized
      ? `Быстрый просмотр: ${formatNumber(stats.preview_draw_calls)} пакетов материалов вместо ${formatNumber(stats.objects)} узлов. Треугольники, нормали и габариты совпадают с полным GLB.`
      : 'Для этой сцены используется исходный GLB без пакетирования, чтобы полностью сохранить покраску или текстуры.';
  return `<article class="model-card" id="model-${esc(model.id)}">
    <div class="model-main">
      <div class="poster-panel">
        <div class="poster-frame">
          <img id="poster-${esc(model.id)}" src="${esc(firstPoster.url)}" alt="${esc(model.title)} — ${esc(firstPoster.label)}"
            width="${firstPoster.width}" height="${firstPoster.height}" loading="lazy" decoding="async">
        </div>
        ${posterTabs(model)}
      </div>
      <div class="model-info">
        <h3>${esc(model.title)}</h3>
        <p class="model-description">${esc(model.description)}</p>
        <div class="tag-list">${model.tags.map((tag) => `<span class="pill">${esc(tag)}</span>`).join('')}</div>
        <div class="model-stats">
          <div class="stat"><strong>${formatNumber(stats.objects)}</strong><span>деталей в исходнике</span></div>
          <div class="stat"><strong>${formatNumber(stats.triangles)}</strong><span>треугольников</span></div>
          <div class="stat"><strong>${formatNumber(stats.preview_draw_calls)}</strong><span>${drawLabel}</span></div>
        </div>
        <div class="model-actions">
          <button class="button primary" type="button" data-open-model="${esc(model.id)}">Смотреть в 3D <small>${formatBytes(model.preview_glb.bytes)}</small></button>
          <a class="button secondary" href="${esc(model.full_glb.url)}" download="${esc(model.full_glb.file_name)}">Скачать .glb <small>${formatBytes(model.full_glb.bytes)}</small></a>
          <a class="button file" href="${esc(model.forma.url)}" download="${esc(model.forma.file_name)}">Исходник .forma <small>${formatBytes(model.forma.bytes)}</small></a>
        </div>
        <p class="optimization-note">${esc(optimization)}</p>
      </div>
    </div>
  </article>`;
}

function renderVersion(id, updateUrl = true) {
  const version = catalog.versions.find((item) => item.id === id) || catalog.versions[0];
  activeVersion = version.id;
  renderNav();
  document.title = `${version.label} — Forma`;
  content.innerHTML = `
    <header class="release-header">
      <div class="release-meta">
        <span class="pill accent">${esc(version.kicker)}</span>
        <span class="pill">${esc(version.date)}</span>
        <span class="pill">${version.models.length} ${version.models.length === 1 ? 'готовая модель' : 'готовые модели'}</span>
      </div>
      <h1>${esc(version.title)}</h1>
      <p class="release-summary">${esc(version.summary)}</p>
    </header>
    <section aria-labelledby="changes-title">
      <div class="section-heading"><h2 id="changes-title">Что в этой версии</h2><span>${version.changes.length} изменений</span></div>
      <div class="changes">${version.changes.map(changeCard).join('')}</div>
    </section>
    <section aria-labelledby="models-title">
      <div class="section-heading"><h2 id="models-title">Готовый результат</h2><span>просмотр по требованию · файлы всегда доступны</span></div>
      <div class="models">${version.models.map(modelCard).join('')}</div>
    </section>`;
  if (updateUrl) {
    const url = new URL(location.href);
    url.searchParams.set('v', version.id);
    history.replaceState(null, '', url);
  }
}

function setPoster(modelId, view, button) {
  const model = modelIndex.get(modelId);
  const poster = model?.posters.find((item) => item.view === view);
  const image = document.querySelector(`#poster-${CSS.escape(modelId)}`);
  if (!poster || !image) return;
  image.src = poster.url;
  image.alt = `${model.title} — ${poster.label}`;
  image.closest('.poster-panel').querySelectorAll('.poster-tab').forEach((item) => {
    const active = item === button;
    item.classList.toggle('active', active);
    item.setAttribute('aria-pressed', String(active));
  });
}

versionNav.addEventListener('click', (event) => {
  const button = event.target.closest('[data-version]');
  if (!button) return;
  closeViewer();
  renderVersion(button.dataset.version);
  scrollTo({ top: 0, behavior: 'smooth' });
});

content.addEventListener('click', (event) => {
  const open = event.target.closest('[data-open-model]');
  if (open) {
    openModel(open.dataset.openModel);
    return;
  }
  const poster = event.target.closest('[data-poster-model]');
  if (poster) setPoster(poster.dataset.posterModel, poster.dataset.posterView, poster);
});

function updateProgress(loaded, total, expected) {
  const denominator = total || expected || 0;
  const fraction = denominator ? Math.min(0.98, loaded / denominator) : 0.1;
  progressBar.style.width = `${Math.max(4, fraction * 100)}%`;
  progressDetail.textContent = denominator
    ? `${formatBytes(loaded)} из ${formatBytes(denominator)}`
    : `${formatBytes(loaded)} загружено`;
}

function resetViewerUi(model) {
  document.querySelector('#viewer-title').textContent = model.title;
  document.querySelector('#viewer-stats').textContent =
    `${formatNumber(model.stats.preview_triangles ?? model.stats.triangles)} треугольников · ${formatNumber(model.stats.preview_draw_calls)} пакетов`;
  for (const [selector, asset] of [['#viewer-forma', model.forma], ['#viewer-glb', model.full_glb]]) {
    const link = document.querySelector(selector);
    link.href = asset.url;
    link.download = asset.file_name;
  }
  for (const selector of ['#viewer-wire', '#viewer-spin']) {
    document.querySelector(selector).setAttribute('aria-pressed', 'false');
  }
  progress.hidden = false;
  progress.querySelector('.loader').hidden = false;
  progressTitle.textContent = 'Подготовка просмотра…';
  progressDetail.textContent = `${formatBytes(model.preview_glb.bytes)} · загрузка только по вашей команде`;
  progressBar.style.width = '4%';
}

async function openModel(modelId) {
  const model = modelIndex.get(modelId);
  if (!model) return;
  closeViewer();
  const generation = ++viewerGeneration;
  resetViewerUi(model);
  if (!dialog.open) dialog.showModal();
  try {
    progressTitle.textContent = 'Загружаю лёгкий 3D-просмотрщик…';
    viewerModule ||= import('./viewer.js');
    const { ShowcaseViewer } = await viewerModule;
    if (generation !== viewerGeneration || !dialog.open) return;
    const currentViewer = new ShowcaseViewer(stage, {
      onProgress: (loaded, total) => {
        if (generation === viewerGeneration) updateProgress(loaded, total, model.preview_glb.bytes);
      },
    });
    viewer = currentViewer;
    progressTitle.textContent = 'Загружаю готовую модель…';
    await currentViewer.load(model.preview_glb.url);
    if (generation !== viewerGeneration || viewer !== currentViewer || !dialog.open) return;
    progressBar.style.width = '100%';
    progress.hidden = true;
  } catch (error) {
    if (generation !== viewerGeneration || !dialog.open) return;
    viewerModule = null;
    console.error(error);
    progress.hidden = false;
    progress.querySelector('.loader').hidden = true;
    progressTitle.textContent = 'Не удалось открыть интерактивный просмотр';
    progressDetail.textContent = 'Готовые .glb и .forma всё равно можно скачать кнопками ниже.';
  }
}

function closeViewer() {
  viewerGeneration += 1;
  if (viewer) {
    viewer.dispose();
    viewer = null;
  }
  stage.querySelectorAll('canvas').forEach((canvas) => canvas.remove());
  if (dialog.open) dialog.close();
}

document.querySelector('#viewer-close').addEventListener('click', closeViewer);
dialog.addEventListener('cancel', (event) => {
  event.preventDefault();
  closeViewer();
});
dialog.addEventListener('click', (event) => {
  if (event.target === dialog) closeViewer();
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden && viewer) viewer.pause();
  if (!document.hidden && viewer) viewer.resume();
});
document.querySelector('.viewer-toolbar').addEventListener('click', (event) => {
  const view = event.target.closest('[data-view]');
  if (view && viewer) viewer.setView(view.dataset.view);
  if (event.target.id === 'viewer-wire' && viewer) {
    const enabled = event.target.getAttribute('aria-pressed') !== 'true';
    event.target.setAttribute('aria-pressed', String(enabled));
    viewer.setWireframe(enabled);
  }
  if (event.target.id === 'viewer-spin' && viewer) {
    const enabled = event.target.getAttribute('aria-pressed') !== 'true';
    event.target.setAttribute('aria-pressed', String(enabled));
    viewer.setSpin(enabled);
  }
});

async function init() {
  try {
    const response = await fetch('./assets/catalog.json', { cache: 'no-cache' });
    if (!response.ok) throw new Error(`Каталог: HTTP ${response.status}`);
    catalog = await response.json();
    for (const version of catalog.versions) {
      for (const model of version.models) modelIndex.set(model.id, model);
    }
    setRevision();
    renderVersion(versionFromUrl(), false);
  } catch (error) {
    console.error(error);
    content.innerHTML = `<div class="error-page"><h1>Каталог не загрузился</h1><p>${esc(error.message)}</p><p><a href="./">Повторить открытие стенда</a></p></div>`;
  }
}

init();
