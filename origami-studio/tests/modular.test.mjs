import test from 'node:test';
import assert from 'node:assert/strict';
import { buildModulePlan, modulePlanSvg, moduleBomHtml } from '../js/modular.js';

test('планировщик считает детали, радиус, смену ориентации и смещение', () => {
  const plan = buildModulePlan({count:12,rows:3,pitch:18,paperWidth:40,paperHeight:60});
  assert.equal(plan.totals.units,36);
  assert.equal(plan.totals.plannedTabInsertions,72);
  assert.ok(Math.abs(plan.totals.baseRadiusMm - 12*18/(2*Math.PI)) < 1e-9);
  assert.equal(plan.rows[1].phase,.5);
  assert.equal(plan.rows[1].orientation,'перевёрнутый');
  assert.match(modulePlanSvg(plan),/схема позиций/);
  assert.match(moduleBomHtml(plan),/Вставлять выступы/);
  assert.match(plan.verification,/not verified/);
});

test('планировщик отклоняет некорректные параметры', () => {
  assert.throws(()=>buildModulePlan({count:2}),/от 6 до 48/);
  assert.throws(()=>buildModulePlan({rows:0}),/Рядов/);
});
