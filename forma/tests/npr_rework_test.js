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
assert(source.includes('float q = clamp(floor(light * (steps - 1.0) + 0.35)'),
  'Cel-ступени должны идти по illumination, а не по белому блеску');

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
