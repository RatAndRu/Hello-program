/**
 * Generates the connected single-sheet crane used by Origami Studio.
 * Geometry and fold sequence: Origamio by Hannes Gao, MIT license.
 * Run: npm run generate:crane
 */
import { writeFileSync } from 'node:fs';
import { createPaper, fold, isFlipped, maxLayers, type PaperState } from './origamio/paper';
import { PRESETS, presetToSequence } from './origamio/presets';
import { applyStep, type FoldPart, type FoldStep } from './origamio/sequence';
import { hinges, tears } from './origamio/rigid';
import { solvedScene, type SolvedScene } from './origamio/view3d';
import { signedArea } from './origamio/geometry';

const OUT = new URL('../data/', import.meta.url);
const OPENING = (6 * Math.PI) / 180;
const THICKNESS = 0.07 / 150;
const SCALE = 3;
const INV_SQRT2 = Math.SQRT1_2;
const round = (n: number) => Math.round(n * 100000) / 100000;
// Origamio's named isometric basis for the crane's diagonal view frame.
// Keeping that basis avoids an arbitrary, misleading presentation of the sheet.
const FRONT_BLEND = 0.64;
const point = (p: { x: number; y: number; z: number }) => {
  const along = p.x + p.y - 1;
  const isoX = -0.5 * along - INV_SQRT2 * p.z;
  const isoZ = 0.5 * along - INV_SQRT2 * p.z;
  const frontX = -p.z;
  const frontZ = INV_SQRT2 * along;
  return [
    round((isoX * (1 - FRONT_BLEND) + frontX * FRONT_BLEND) * SCALE),
    round(INV_SQRT2 * (p.y - p.x) * SCALE),
    round((isoZ * (1 - FRONT_BLEND) + frontZ * FRONT_BLEND) * SCALE),
  ];
};
const sceneAt = (state: PaperState, animation?: any) => solvedScene(state, {
  opening: OPENING,
  thickness: THICKNESS,
  ...(animation ? { animation } : {}),
});

function packScene(scene: SolvedScene) {
  return {
    panels: scene.panels.map(panel => ({
      id: panel.facet.id,
      flipped: isFlipped(panel.facet),
      uv: panel.facet.poly.map(p => [round(p.x), round(p.y)]),
      points: panel.points.map(point),
    })),
    edges: scene.edges.map(edge => [point(edge.a), point(edge.b)]),
  };
}

function maxEdgeError(state: PaperState, scene: SolvedScene): number {
  let worst = 0;
  for (const panel of scene.panels) {
    const uv = panel.facet.poly;
    for (let i = 0; i < uv.length; i++) {
      const j = (i + 1) % uv.length;
      const a = uv[i]!, b = uv[j]!;
      const rest = Math.hypot(a.x - b.x, a.y - b.y);
      const p = panel.points[i]!, q = panel.points[j]!;
      const current = Math.hypot(p.x - q.x, p.y - q.y, p.z - q.z);
      if (rest > 1e-7) worst = Math.max(worst, Math.abs(current - rest) / rest);
    }
  }
  return worst;
}

const preset = PRESETS.find(item => item.id === 'crane');
if (!preset) throw new Error('Origamio crane preset not found');
const sequence = presetToSequence(preset);
let state = createPaper();
const states = [packScene(sceneAt(state))];
const animations: any[] = [];
const validationSteps: any[] = [];
let worstEdgeError = 0;

for (let index = 0; index < sequence.steps.length; index++) {
  const step = sequence.steps[index] as FoldStep;
  const stepStart = state;
  let before = state;
  const segments: any[] = [];
  const parts = [step, ...(step.also ?? [])] as FoldPart[];
  for (const part of parts) {
    const result = fold(before, part.line, part.side, part.options);
    const movedIds = new Set(result.movedIds);
    const frames: any[] = [];
    if (movedIds.size > 0) {
      for (const progress of [0, 0.2, 0.4, 0.6, 0.8, 1]) {
        frames.push(packScene(sceneAt(result.state, {
          previous: before,
          movedIds,
          progress,
        })));
      }
      segments.push({ label: step.label ?? `Fold ${index + 1}`, frames });
    }
    before = result.state;
  }
  state = applyStep(stepStart, step).state;
  const torn = tears(state);
  if (torn !== 0) throw new Error(`Sheet tore after engine step ${index + 1}: ${torn}`);
  const solved = sceneAt(state);
  const edgeError = maxEdgeError(state, solved);
  worstEdgeError = Math.max(worstEdgeError, edgeError);
  const area = state.facets.reduce((sum, facet) => sum + Math.abs(signedArea(facet.poly)), 0);
  if (Math.abs(area - 1) > 1e-6) throw new Error(`Sheet area changed at step ${index + 1}: ${area}`);
  if (edgeError > 0.025) throw new Error(`Edge strain exceeded 2.5% at step ${index + 1}: ${edgeError}`);
  states.push(packScene(solved));
  animations.push({ label: step.label, segments, endState: index + 1 });
  validationSteps.push({
    engineStep: index + 1,
    label: step.label,
    tornFacetPairs: torn,
    facets: state.facets.length,
    maxLayers: maxLayers(state),
    originalArea: area,
    maxRelativeEdgeError: edgeError,
  });
  console.log(`${index + 1}/12 ${step.label}: ${state.facets.length} facets, tears=0, edge error=${(edgeError * 100).toFixed(3)}%`);
}

// UI groups follow familiar instruction-book steps; engine operations remain intact inside them.
const trackMap = [[0], [1], [2], [3], [4], [5, 6], [7, 8, 9], [10], [11], []];
const tracks = trackMap.map((engineIndices, uiIndex) => ({
  uiIndex,
  engineSteps: engineIndices.map(index => index + 1),
  startState: engineIndices.length ? animations[engineIndices[0]!].endState - 1 : 12,
  endState: engineIndices.length ? animations[engineIndices.at(-1)!].endState : 12,
  animations: engineIndices.map(index => animations[index]),
}));

const payload = {
  format: 'origami-studio-connected-sheet',
  version: 1,
  model: 'traditional-crane',
  source: {
    name: 'Origamio',
    author: 'Hannes Gao',
    license: 'MIT',
    repository: 'https://github.com/hannesgao/Origamio',
    revision: 'c28937855e8d4b08cd10c83b66689f3e94b924b2',
  },
  sheet: { width: 1, height: 1, physicalSizeMm: 150, thicknessMm: 0.07 },
  creasePattern: hinges(state).map(hinge => ({
    a: [round(hinge.a.x), round(hinge.a.y)],
    b: [round(hinge.b.x), round(hinge.b.y)],
    angle: round(hinge.angle * 180 / Math.PI),
  })),
  coordinateTransform: 'Origamio named isometric basis, diagonal crane view frame, scale=3',
  states,
  tracks,
};
writeFileSync(new URL('crane.geometry.json', OUT), JSON.stringify(payload));
writeFileSync(new URL('crane.validation.json', OUT), JSON.stringify({
  model: 'traditional-crane',
  engineSteps: sequence.steps.length,
  connectedSingleSheet: true,
  originalAreaConserved: true,
  allStepsHaveZeroTornFacetPairs: true,
  worstRelativeEdgeError: worstEdgeError,
  steps: validationSteps,
}, null, 2));
console.log(`Done: ${states.length} states, worst edge error ${(worstEdgeError * 100).toFixed(3)}%`);
