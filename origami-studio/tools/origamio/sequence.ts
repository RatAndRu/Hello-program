/**
 * Fold sequences as data. A sequence is a list of folds that can be replayed
 * on a fresh sheet: presets ship in this format, and anything folded by hand
 * can be exported to it. The JSON form is documented in the README.
 */
import {
  type Line,
  type Polygon,
  type Side,
  type Vec,
  apply,
  centroid,
  containsPoint,
  distance,
  line,
  vec,
} from './geometry';
import {
  type FoldOptions,
  type FoldResult,
  type LayerSelection,
  type PaperState,
  type Placement,
  ALL_LAYERS,
  bottomLayers,
  fold,
  topLayers,
} from './paper';

/** One fold: a line in the folded coordinates of that moment, the side that flips, and its options. */
export interface FoldPart {
  readonly line: Line;
  readonly side: Side;
  readonly options: FoldOptions;
}

export interface FoldStep extends FoldPart {
  /**
   * Further folds that happen in the same step, applied in order after the
   * first. A collapse or a petal fold is several creases forming at once;
   * grouping them keeps every state between steps one that real paper can
   * take, and plays them together.
   */
  readonly also?: readonly FoldPart[];
  /** Short name shown on the timeline, such as "Petal fold". */
  readonly label?: string;
}

/**
 * Apply a whole step. The moved facets are those of the final sheet that
 * lie somewhere else than the part of the previous sheet they came from.
 */
export function applyStep(state: PaperState, step: FoldStep): FoldResult {
  const first = fold(state, step.line, step.side, step.options);
  let current = first.state;
  let takenAlong = first.takenAlong;
  for (const part of step.also ?? []) {
    const next = fold(current, part.line, part.side, part.options);
    current = next.state;
    takenAlong += next.takenAlong;
  }
  return { state: current, movedIds: movedBetween(state, current), line: step.line, takenAlong };
}

/** Ids of the facets of `after` whose paper moved since `before`. */
export function movedBetween(before: PaperState, after: PaperState): number[] {
  const probe = { x: 0.37, y: 0.61 };
  const moved: number[] = [];
  for (const facet of after.facets) {
    const c = centroid(facet.poly);
    const origin = before.facets.find((f) => containsPoint(f.poly, c));
    if (!origin) continue;
    const here = apply(facet.transform, probe);
    const there = apply(origin.transform, probe);
    if (distance(here, there) > 1e-7) moved.push(facet.id);
  }
  return moved;
}

/**
 * The sheet a sequence is folded from. Sides are in sheet units (the longer
 * side is usually 1); the colours are CSS hex colours of the two faces.
 */
export interface Paper {
  readonly width: number;
  readonly height: number;
  readonly front: string;
  readonly back: string;
}

export const DEFAULT_FRONT = '#e8923a';
export const DEFAULT_BACK = '#7a3f12';
export const DEFAULT_PAPER: Paper = {
  width: 1,
  height: 1,
  front: DEFAULT_FRONT,
  back: DEFAULT_BACK,
};

const HEX_COLOUR = /^#[0-9a-f]{6}$/i;
export const isHexColour = (value: unknown): value is string =>
  typeof value === 'string' && HEX_COLOUR.test(value);

/**
 * How the finished model stands, for the fixed views of the 3D card: two
 * directions in the folded coordinates of the final state. `front` points
 * at the viewer of the front view (for a crane, out of its beak), `top` at
 * the viewer of the top view (up its back). Absent means the sheet's own
 * axes: front along +x, top along +y.
 */
export interface ViewFrame {
  readonly front: Vec;
  readonly top: Vec;
}

export interface Sequence {
  readonly name: string;
  readonly description?: string;
  /** Omitted in files means the unit square. */
  readonly paper?: Paper;
  readonly view?: ViewFrame;
  readonly steps: readonly FoldStep[];
}

export const SEQUENCE_FORMAT = 'origamio-sequence';
export const SEQUENCE_VERSION = 1;

/** A point as `[x, y]`. */
export type PointJson = readonly [number, number];

export interface StepJson {
  /** Two points on the fold line, in the folded coordinates of that moment. */
  readonly line: readonly [PointJson, PointJson];
  /** Which side of the directed line flips over: +1 is to its left. */
  readonly side: 1 | -1;
  readonly layers?: 'all' | { readonly top: number } | { readonly bottom: number };
  readonly region?: readonly PointJson[];
  readonly window?: readonly PointJson[];
  readonly placement?: Placement;
  /** Take attached facets along so the paper never tears; omitted means false. */
  readonly attached?: boolean;
  /** Fold angle for display in degrees, (0, 180]; omitted means folded flat. */
  readonly angle?: number;
  /** Further folds of the same step: the same fields without `also` and `label`. */
  readonly also?: readonly StepPartJson[];
  readonly label?: string;
}

export type StepPartJson = Omit<StepJson, 'also' | 'label'>;

export interface SequenceJson {
  readonly format: typeof SEQUENCE_FORMAT;
  readonly version: typeof SEQUENCE_VERSION;
  readonly name: string;
  readonly description?: string;
  readonly paper?: {
    readonly width: number;
    readonly height: number;
    readonly front?: string;
    readonly back?: string;
  };
  readonly view?: { readonly front: PointJson; readonly top: PointJson };
  readonly steps: readonly StepJson[];
}

/** Largest side length accepted for a sheet, in sheet units. */
export const MAX_PAPER_SIDE = 10;

const PLACEMENTS: readonly Placement[] = ['top', 'bottom', 'inside'];

const round = (n: number): number => Math.round(n * 1e9) / 1e9;
const pointJson = (p: Vec): PointJson => [round(p.x), round(p.y)];

function layersJson(layers: LayerSelection | undefined): StepJson['layers'] | undefined {
  if (!layers || layers.kind === 'all') return undefined;
  return layers.kind === 'top' ? { top: layers.count } : { bottom: layers.count };
}

function partToJson(part: FoldPart): StepPartJson {
  const { options } = part;
  const layers = layersJson(options.layers);
  return {
    line: [pointJson(part.line.a), pointJson(part.line.b)],
    side: part.side,
    ...(layers ? { layers } : {}),
    ...(options.region ? { region: options.region.map(pointJson) } : {}),
    ...(options.window ? { window: options.window.map(pointJson) } : {}),
    ...(options.placement && options.placement !== 'top' ? { placement: options.placement } : {}),
    ...(options.attached ? { attached: true } : {}),
    ...(options.angle !== undefined && options.angle < 180 ? { angle: options.angle } : {}),
  };
}

export function stepToJson(step: FoldStep): StepJson {
  return {
    ...partToJson(step),
    ...(step.also && step.also.length > 0 ? { also: step.also.map(partToJson) } : {}),
    ...(step.label ? { label: step.label } : {}),
  };
}

export function sequenceToJson(sequence: Sequence): SequenceJson {
  return {
    format: SEQUENCE_FORMAT,
    version: SEQUENCE_VERSION,
    name: sequence.name,
    ...(sequence.description ? { description: sequence.description } : {}),
    ...(sequence.paper
      ? {
          paper: {
            width: round(sequence.paper.width),
            height: round(sequence.paper.height),
            front: sequence.paper.front.toLowerCase(),
            back: sequence.paper.back.toLowerCase(),
          },
        }
      : {}),
    ...(sequence.view
      ? { view: { front: pointJson(sequence.view.front), top: pointJson(sequence.view.top) } }
      : {}),
    steps: sequence.steps.map(stepToJson),
  };
}

/** The JSON text of a sequence, indented for reading and diffing, points on one line. */
export const serializeSequence = (sequence: Sequence): string =>
  `${compactPoints(JSON.stringify(sequenceToJson(sequence), null, 2))}\n`;

/** Every two-number array outside a string on one line: `[x, y]`. */
function compactPoints(text: string): string {
  const point = /^\[\s*(-?[\d.e+-]+),\s*(-?[\d.e+-]+)\s*\]/;
  let out = '';
  let i = 0;
  while (i < text.length) {
    const c = text[i] as string;
    if (c === '"') {
      // Copy the string literal whole, escapes included.
      let j = i + 1;
      while (j < text.length && text[j] !== '"') j += text[j] === '\\' ? 2 : 1;
      out += text.slice(i, j + 1);
      i = j + 1;
    } else if (c === '[') {
      const m = point.exec(text.slice(i, i + 80));
      if (m) {
        out += `[${m[1]}, ${m[2]}]`;
        i += m[0].length;
      } else {
        out += c;
        i++;
      }
    } else {
      out += c;
      i++;
    }
  }
  return out;
}

// --- Parsing -------------------------------------------------------------------

export class SequenceError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SequenceError';
  }
}

const fail = (where: string, what: string): never => {
  throw new SequenceError(`${where}: ${what}`);
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/** Bounds for a file from anywhere: generous for any real model, small enough to replay. */
const MAX_COORDINATE = 1e6;
const MAX_POLYGON_POINTS = 64;
const MAX_FOLDS_PER_STEP = 256;
const MAX_STEPS = 10000;

function parsePoint(value: unknown, where: string): Vec {
  if (
    !Array.isArray(value) ||
    value.length !== 2 ||
    !value.every((n) => typeof n === 'number' && Number.isFinite(n))
  ) {
    return fail(where, 'expected a point as [x, y]');
  }
  if (!value.every((n) => Math.abs(n as number) <= MAX_COORDINATE)) {
    return fail(where, `expected coordinates within ±${MAX_COORDINATE}`);
  }
  return vec(value[0] as number, value[1] as number);
}

function parsePolygon(value: unknown, where: string): Polygon {
  if (!Array.isArray(value) || value.length < 3) {
    return fail(where, 'expected a polygon with at least three points');
  }
  if (value.length > MAX_POLYGON_POINTS) {
    return fail(where, `expected at most ${MAX_POLYGON_POINTS} points`);
  }
  return value.map((p, i) => parsePoint(p, `${where}[${i}]`));
}

function parseLayers(value: unknown, where: string): LayerSelection {
  if (value === undefined || value === 'all') return ALL_LAYERS;
  if (isRecord(value)) {
    const count = value['top'] ?? value['bottom'];
    const kind = 'top' in value ? 'top' : 'bottom' in value ? 'bottom' : null;
    if (kind && typeof count === 'number' && Number.isInteger(count) && count >= 1) {
      return kind === 'top' ? topLayers(count) : bottomLayers(count);
    }
  }
  return fail(where, 'expected "all", { "top": n } or { "bottom": n } with n ≥ 1');
}

export function parseStep(value: unknown, where = 'step'): FoldStep {
  const part = parsePart(value, where);
  if (!isRecord(value)) return fail(where, 'expected an object');
  const options: FoldOptions = part.options;
  const alsoValue = value['also'];
  let also: FoldPart[] | undefined;
  if (alsoValue !== undefined) {
    if (!Array.isArray(alsoValue)) return fail(`${where}.also`, 'expected a list of folds');
    if (alsoValue.length > MAX_FOLDS_PER_STEP) {
      return fail(`${where}.also`, `expected at most ${MAX_FOLDS_PER_STEP} folds`);
    }
    also = alsoValue.map((v, i) => parsePart(v, `${where}.also[${i}]`));
  }
  const label = value['label'];
  if (label !== undefined && typeof label !== 'string') {
    return fail(`${where}.label`, 'expected a string');
  }
  return {
    line: part.line,
    side: part.side,
    options,
    ...(also && also.length > 0 ? { also } : {}),
    ...(typeof label === 'string' && label ? { label } : {}),
  };
}

function parsePart(value: unknown, where: string): FoldPart {
  if (!isRecord(value)) return fail(where, 'expected an object');
  const lineValue = value['line'];
  if (!Array.isArray(lineValue) || lineValue.length !== 2) {
    return fail(`${where}.line`, 'expected two points');
  }
  const a = parsePoint(lineValue[0], `${where}.line[0]`);
  const b = parsePoint(lineValue[1], `${where}.line[1]`);
  if (distance(a, b) < 1e-9) return fail(`${where}.line`, 'the two points coincide');
  const side = value['side'];
  if (side !== 1 && side !== -1) return fail(`${where}.side`, 'expected 1 or -1');
  const options: {
    layers?: LayerSelection;
    region?: Polygon;
    window?: Polygon;
    placement?: Placement;
    attached?: boolean;
    angle?: number;
  } = {};
  const layers = parseLayers(value['layers'], `${where}.layers`);
  if (layers.kind !== 'all') options.layers = layers;
  if (value['region'] !== undefined) {
    options.region = parsePolygon(value['region'], `${where}.region`);
  }
  if (value['window'] !== undefined) {
    options.window = parsePolygon(value['window'], `${where}.window`);
  }
  const placement = value['placement'];
  if (placement !== undefined) {
    if (!PLACEMENTS.includes(placement as Placement)) {
      return fail(`${where}.placement`, `expected one of ${PLACEMENTS.join(', ')}`);
    }
    if (placement !== 'top') options.placement = placement as Placement;
  }
  const attached = value['attached'];
  if (attached !== undefined) {
    if (typeof attached !== 'boolean') return fail(`${where}.attached`, 'expected true or false');
    if (attached) options.attached = true;
  }
  const angle = value['angle'];
  if (angle !== undefined) {
    if (typeof angle !== 'number' || !(angle > 0 && angle <= 180)) {
      return fail(`${where}.angle`, 'expected a number in (0, 180]');
    }
    if (angle < 180) options.angle = angle;
  }
  return { line: line(a, b), side, options };
}

/** Parse a sequence from its JSON form (an object or JSON text); throws SequenceError. */
export function parseSequence(input: unknown): Sequence {
  let value: unknown = input;
  if (typeof input === 'string') {
    try {
      value = JSON.parse(input);
    } catch (error) {
      return fail('sequence', `not valid JSON (${(error as Error).message})`);
    }
  }
  if (!isRecord(value)) return fail('sequence', 'expected an object');
  if (value['format'] !== SEQUENCE_FORMAT) {
    return fail('sequence.format', `expected "${SEQUENCE_FORMAT}"`);
  }
  if (value['version'] !== SEQUENCE_VERSION) {
    return fail('sequence.version', `expected ${SEQUENCE_VERSION}`);
  }
  const name = value['name'];
  if (typeof name !== 'string' || !name.trim()) return fail('sequence.name', 'expected a name');
  const description = value['description'];
  if (description !== undefined && typeof description !== 'string') {
    return fail('sequence.description', 'expected a string');
  }
  const steps = value['steps'];
  if (!Array.isArray(steps)) return fail('sequence.steps', 'expected an array');
  if (steps.length > MAX_STEPS)
    return fail('sequence.steps', `expected at most ${MAX_STEPS} steps`);
  const paperValue = value['paper'];
  let paper: Paper | undefined;
  if (paperValue !== undefined) {
    if (!isRecord(paperValue)) return fail('sequence.paper', 'expected { width, height }');
    const width = paperValue['width'];
    const height = paperValue['height'];
    const side = (n: unknown): n is number =>
      typeof n === 'number' && Number.isFinite(n) && n > 0 && n <= MAX_PAPER_SIDE;
    if (!side(width) || !side(height)) {
      return fail('sequence.paper', `expected sides between 0 and ${MAX_PAPER_SIDE}`);
    }
    const front = paperValue['front'] ?? DEFAULT_FRONT;
    const back = paperValue['back'] ?? DEFAULT_BACK;
    if (!isHexColour(front) || !isHexColour(back)) {
      return fail('sequence.paper', 'expected front and back as hex colours like #e8923a');
    }
    paper = { width, height, front: front.toLowerCase(), back: back.toLowerCase() };
  }
  const viewValue = value['view'];
  let view: ViewFrame | undefined;
  if (viewValue !== undefined) {
    if (!isRecord(viewValue)) return fail('sequence.view', 'expected { front, top }');
    const front = parsePoint(viewValue['front'], 'sequence.view.front');
    const top = parsePoint(viewValue['top'], 'sequence.view.top');
    const cross = front.x * top.y - front.y * top.x;
    if (Math.hypot(front.x, front.y) < 1e-9 || Math.hypot(top.x, top.y) < 1e-9) {
      return fail('sequence.view', 'expected two non-zero directions');
    }
    if (Math.abs(cross) < 1e-9) return fail('sequence.view', 'front and top must not be parallel');
    view = { front, top };
  }
  return {
    name: name.trim(),
    ...(typeof description === 'string' && description ? { description } : {}),
    ...(paper ? { paper } : {}),
    ...(view ? { view } : {}),
    steps: steps.map((s, i) => parseStep(s, `steps[${i}]`)),
  };
}
