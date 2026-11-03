/* Поведенческие минимальные repro playback без WebGL. */
'use strict';
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'web/js/viewer.js'), 'utf8');

function method(name, next) {
  const start = source.indexOf(`  ${name}`);
  const end = source.indexOf(`\n  ${next}`, start + 1);
  if (start < 0 || end < 0) throw new Error(`method not found: ${name}`);
  const text = source.slice(start, end);
  return new Function(`return ({${text}});`)()[name.split('(')[0]];
}

const tick = method('_tickAnimation(dt)', 'playAnimation');
for (const loop of [false, true]) {
  const ctx = {
    manualAdvance: false, playing: true, duration: 2, time: 1.9, speed: 1, loop,
    hasAnimation: () => true,
    applyTime(t) { this.time = t; },
    onEnd() { throw new Error('playback must not end itself'); },
  };
  tick.call(ctx, 0.2);
  if (!ctx.playing || Math.abs(ctx.time - 0.1) > 1e-6) {
    throw new Error(`continuous wrap failed loop=${loop}: ${JSON.stringify(ctx)}`);
  }
}

const setGrid = method('setGrid(visible)', 'setGround');
const gridCtx = {
  gridVisible: true, groundVisible: true,
  grid: { visible: true }, ground: { visible: true }, settings: { ground: true },
};
setGrid.call(gridCtx, false);
if (gridCtx.grid.visible !== false || gridCtx.ground.visible !== true) {
  throw new Error('grid switch changed the independent floor');
}

console.log('Playback: continuous clock, loop=false compatibility, independent grid/floor — OK.');
