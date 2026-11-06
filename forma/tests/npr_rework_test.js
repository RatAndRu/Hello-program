/* Статический контракт живого NPR-прохода: буферы и overlay не смешиваются. */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const source = fs.readFileSync(path.resolve(__dirname, '../web/js/viewer.js'), 'utf8')
  .replace(/\r\n?/g, '\n');

for (const token of [
  'this._albedoRT = new THREE.WebGLRenderTarget',
  '_renderAlbedoPass();',
  '_albedoMaterial(source)',
  'uniform sampler2D tAlbedo;',
  'albedoSample.a',
  'materialBlack',
  'materialValue',
  'linearToSrgb',
  'vec3 alb = linearToSrgb',
  'bgShadow',
  'this._hideForGBuffer();',
  'this._restoreGBufferVisibility(hidden);',
  'for (int i = 0; i < 16; i++)',
  'gl_FragColor = vec4(edge * visible, silhouette * visible, feature * visible, 1.0);',
  'this._applyAnimeLook();',
]) assert(source.includes(token), `NPR не подключён: ${token}`);

assert(!source.includes('float bright = step(0.97'),
  'Обычный specular больше не должен определяться как emissive по белому порогу');
assert(source.includes('this._overlays.forEach((overlay) => { overlay.visible = false; });'),
  'Полигонаж должен отключаться в художественном режиме');
assert(source.includes('vec3 under = alb * 0.78 + vec3(albedoL) * 0.22;'),
  'Sketch должен сохранять цветной подмалёвок');
// Штриховка ведёт форму, а не рисует ровную диагональ по всему предмету.
assert(!source.includes('float warp = 12.0 * formN.x + 4.0 * sin(p.y * 0.035'),
  'Скачок warp на ребре давал «пружинки» и пунктир вместо штриховки');
assert(source.includes('float bend = clamp(formN.x * 0.55 + formN.y * 0.22'),
  'Направление штриха должно следовать форме плавно и ограниченно');
assert(source.includes('across += (bandSeed - 0.5) * stepPx * 0.42;'),
  'Шаг штриховки должен дышать, а не быть линейкой');
assert(source.includes('float segLen = 26.0 + 58.0 * bandSeed;'),
  'Штрих должен быть коротким сегментом своей длины, а не линией через грань');
assert(source.includes('h *= 1.0 - smoothstep(0.20, 0.80, edge);'),
  'Штриховка не должна налезать на контур');
// Падающая тень на полу: узкий круг ловил только кромку.
assert(source.includes('vec2 widePx = 42.0 * uPixelRatio / uResolution;'),
  'Фоновая тень должна читаться широкой пробой, иначе большая тень исчезает');
assert(source.includes('float reference = max(max(local, wideRef), value);'),
  'Опорой тени должен быть самый светлый участок фона');
// Манга: материал и тень — разные растры, чёрное в тени — заливка.
assert(source.includes('float cellPx = 4.4 * uPixelRatio;'),
  'Скринтон манги должен быть мелким, а не «горохом» 7 px');
assert(source.includes('float ink = shadowScreen > 0.5 ? dots : lines;'),
  'Две сетки нельзя смешивать: на границе получается муар и «верёвка»');
assert(source.includes('h *= smoothstep(0.58, 0.86, normalCoherence(vUv));'),
  'На изломе нормалей штриховка должна гаснуть, а не двоиться');
assert(source.includes('float shadowScreen = step(0.92, shadowDensity / max(materialDensity, 0.035));'),
  'Тень и собственный тон материала должны различаться растром');
assert(source.includes('if (deep || blackDeep > 0.62) sheet = uInk;'),
  'Чёрный предмет в тени должен уходить в заливку, а на свету — в тон');
assert(source.includes('float celShade = clamp(1.0 - celLight, 0.0, 1.0);'),
  'Тень рисунка должна задаваться формой, а не яркостью beauty-пикселя');
assert(source.includes('float shadeSignal = max(celShade, darkness * 0.95);'),
  'Сигнал тени обязан учитывать и форму, и фактическую освещённость');
assert(source.includes('float shadowDensity = smoothstep(0.26, 0.60, shadeSignal) * 0.30;'),
  'Тон манги обязан появляться в тени, а не на освещённой грани');
// Аниме: цвет из альбедо, без спекулярного выбеливания.
assert(source.includes('vec3 celN = formNormal(vUv);'),
  'Cel-ступени должны считаться по сглаженной нормали, иначе на сфере звёздчатые пятна');
assert(source.includes('float litMass = smoothstep(0.44, 0.52, celNdl);'),
  'Cel-тень должна быть плоской массой собственного цвета материала');
assert(!source.includes('vec3 cel = clamp(mix(cool, warm, q) * tone * 1.08'),
  'Фотореалистичный тон/блик не должен возвращаться в аниме');
assert(source.includes('float q = clamp(floor(celLight * (steps - 1.0) + 0.20)'),
  'Cel-ступени должны идти по normal/key light, а не по белому блеску');
for (const token of [
  'float ndl = max(dot(nvC, normalize(uLightDir)), 0.0);',
  'float localBackgroundShadow(vec2 uv, float paperL)',
  'float lineTone(vec2 uv, float cell, float dark)',
  'vec3 bridgedEdge(vec2 uv)',
  'vec2 wideOff = off * 1.85;',
  "import { FXAAShader } from 'three/addons/shaders/FXAAShader.js';",
  'composer.addPass(fxaa);',
  'bool deep = (materialBlack > 0.80 && shadeSignal > 0.88 && beautyL < 0.10)',
  'edge *= step(0.001, uLine);',
]) assert(source.includes(token), `Новый NPR-контракт не подключён: ${token}`);
assert(!source.includes('if (materialBlack > 0.80 || (darkness > 0.96'),
  'Чёрный материал на свету не должен автоматически становиться глубокой тенью');
assert(fs.statSync(path.resolve(__dirname, '../web/vendor/shaders/FXAAShader.js')).size > 4000,
  'Финальный FXAA должен поставляться локально вместе с Studio');
const composerMethod = source.slice(source.indexOf('  _ensureComposer() {'),
  source.indexOf('  _animeBufferScale(size)'));
assert(composerMethod.indexOf('composer.addPass(pass)') < composerMethod.indexOf('composer.addPass(fxaa)'),
  'FXAA должен идти после NPR, а не размывать cel-ступени до их построения');

// Минимальный shader-contract: предыдущая замена могла случайно вставить
// fragment-код в vertexShader; node --check этого не замечает, а WebGL падает.
const edgeMethod = source.slice(source.indexOf('  _edgeShader() {'),
  source.indexOf('  /** Цвет, тон и растр;', source.indexOf('  _edgeShader() {')));
const vertex = edgeMethod.slice(edgeMethod.indexOf('vertexShader:'),
  edgeMethod.indexOf('fragmentShader:'));
const fragment = edgeMethod.slice(edgeMethod.indexOf('fragmentShader:'));
assert(vertex.includes('vUv = uv;'), 'edge vertex должен передавать UV');
assert(!vertex.includes('gl_FragColor') && !vertex.includes('texture2D'),
  'fragment-only код не должен попадать в edge vertexShader');
assert(fragment.includes('for (int i = 0; i < 16; i++)'),
  '16-направленный поиск должен быть именно в fragmentShader');
assert(fragment.includes('float linearDepth(float d)'),
  'edge fragment должен объявлять linearDepth');

console.log('NPR: albedo/emissive, тень, классы линий и скрытие полигонажа подключены.');
