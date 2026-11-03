import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const geometry = JSON.parse(readFileSync(new URL('../data/crane.geometry.json',import.meta.url)));
const report = JSON.parse(readFileSync(new URL('../data/crane.validation.json',import.meta.url)));

test('журавлик — одна связанная поверхность с 13 состояниями и 12 операциями', () => {
  assert.equal(geometry.format,'origami-studio-connected-sheet');
  assert.equal(geometry.states.length,13);
  assert.equal(report.engineSteps,12);
  assert.equal(report.allStepsHaveZeroTornFacetPairs,true);
  assert.equal(report.originalAreaConserved,true);
  assert.ok(report.worstRelativeEdgeError < .025);
  assert.ok(geometry.states[12].panels.length >= 100);
});

test('каждая грань хранит полигон на исходном квадратном листе', () => {
  for (const state of geometry.states) for (const panel of state.panels) {
    assert.equal(panel.points.length,panel.uv.length);
    assert.ok(panel.uv.length >= 3);
    for (const [u,v] of panel.uv) {
      assert.ok(u >= -1e-6 && u <= 1.000001);
      assert.ok(v >= -1e-6 && v <= 1.000001);
    }
  }
});
