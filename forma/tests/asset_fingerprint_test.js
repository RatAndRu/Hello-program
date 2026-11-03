/* Static contract: stale GLB cannot masquerade as the current build. */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const viewer = fs.readFileSync(path.join(root, 'web/js/viewer.js'), 'utf8');
const app = fs.readFileSync(path.join(root, 'web/js/app.js'), 'utf8');
const webui = fs.readFileSync(path.join(root, 'forma/webui.py'), 'utf8');

assert(viewer.includes('async load(url, animation = null, expectedVariant = null)'),
  'Viewer.load должен получать ожидаемый variant');
assert(viewer.includes('gltf.parser?.json?.asset?.extras?.forma_variant'),
  'Fingerprint нужно читать из фактически загруженного GLB');
assert(viewer.includes('actualVariant !== expectedVariant'),
  'Несовпадающий GLB должен отклоняться');
const loadStart = viewer.indexOf('async load(url, animation = null, expectedVariant = null)');
const check = viewer.indexOf('actualVariant !== expectedVariant', loadStart);
const install = viewer.indexOf('this.disposeModel();', loadStart);
assert(check >= 0 && install > check, 'Проверка обязана завершиться до установки модели в сцену');
assert(app.includes('animation, state.payload?.variant_hash || null'),
  'UI должен передавать variant текущего payload');
assert(webui.includes('payload["glb_url"] = f"/api/model.glb?v={b.variant_hash}"'),
  'URL основного GLB должен содержать variant');
assert(webui.includes('self.send_header("Cache-Control", "no-store")'),
  'API не должен полагаться на устаревший browser cache');

console.log('Asset fingerprint: source, payload, URL и загруженный GLB связаны.');
