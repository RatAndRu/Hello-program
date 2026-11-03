import test from 'node:test';
import assert from 'node:assert/strict';
import { craneSteps, projects, moduleTemplates, notation } from '../js/data.js';
import { stepDiagram, creasePattern, projectIcon, operationIcon } from '../js/diagrams.js';

test('журавлик содержит 10 уникальных, полностью описанных шагов', () => {
  assert.equal(craneSteps.length, 10);
  assert.equal(new Set(craneSteps.map(step => step.id)).size, 10);
  for (const step of craneSteps) {
    for (const key of ['title','short','type','typeLabel','description','tip','result','diagram','camera']) {
      assert.ok(step[key], `${step.id}: missing ${key}`);
    }
    assert.ok(step.description.length > 70);
    assert.ok(step.tip.length > 40);
  }
});

test('каждый шаг имеет самостоятельную SVG-схему с доступным именем', () => {
  for (const step of craneSteps) {
    const diagram = stepDiagram(step.diagram);
    assert.match(diagram, /^<svg /);
    assert.match(diagram, /aria-label="Схема шага оригами"/);
    assert.ok(diagram.length > 900, step.id);
    assert.ok(!diagram.includes('undefined'), step.id);
  }
});

test('карта складок различает гору и долину', () => {
  const cp = creasePattern();
  assert.match(cp, /class="valley"/);
  assert.match(cp, /class="mountain"/);
  assert.match(cp, /Учебная схема/);
});

test('библиотека содержит модульные и прикладные техники', () => {
  assert.ok(moduleTemplates.length >= 5);
  assert.ok(moduleTemplates.some(item => item.id === 'golden-venture'));
  assert.ok(moduleTemplates.some(item => item.id === 'sonobe'));
  assert.ok(moduleTemplates.some(item => item.id === 'applied'));
  assert.ok(projects.some(item => item.id === 'crane' && item.status === 'ready'));
});

test('обозначения включают рез, клей и вспомогательную складку', () => {
  for (const id of ['valley','mountain','crease','reverse','turn','cut','glue','repeat']) {
    assert.ok(notation.some(item => item.id === id), id);
    assert.match(operationIcon(id), /^<svg/);
  }
});

test('иконки проектов создаются для всех карточек', () => {
  for (const project of projects) assert.match(projectIcon(project.icon), /^<svg/);
});
