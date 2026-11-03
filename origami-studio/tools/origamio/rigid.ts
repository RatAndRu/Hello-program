/**
 * Rigid origami on top of the flat-fold model: the facets are rigid panels
 * joined along creases, each crease has a fold angle, and the position of
 * every panel in space follows from walking the facet graph from a root.
 *
 * A flat-folded state is the special case where every crease is folded by
 * ±π (or by 0, for a crease that was folded and unfolded again). Opening the
 * creases a little from there shows the sheet as folded paper rather than as
 * a stack of coincident layers; interpolating a step's new creases from 0 to
 * ±π animates that step.
 */
import {
  type Mat,
  type Polygon,
  type Vec,
  EPS,
  apply,
  applyToLine,
  centroid,
  compose,
  cross,
  determinant,
  distance,
  dot,
  line,
  reflection,
  sub,
} from './geometry';
import { type Facet, type PaperState, isFlipped, layersAt } from './paper';

export interface Vec3 {
  readonly x: number;
  readonly y: number;
  readonly z: number;
}

/** A crease edge shared by two facets, in unfolded-sheet coordinates. */
export interface Hinge {
  readonly a: Vec;
  readonly b: Vec;
  /** Facet ids on either side of the crease. */
  readonly p: number;
  readonly q: number;
  /**
   * Fold angle in the flat-folded state: +π when `q` lies toward the front
   * face of `p`, −π when it lies behind it, 0 when the two are coplanar
   * (a crease that was folded and unfolded again).
   */
  readonly angle: number;
  /**
   * The angle to show: the flat angle, unless the crease was folded with a
   * display angle below 180°, in which case that angle with the same sign.
   */
  readonly shown: number;
  /** How many layers of the folded sheet lie at this crease (at least 2 when folded). */
  readonly cover: number;
}

/** A rigid transform in space: `rotate` is a row-major 3×3 rotation, then `move`. */
export interface Pose {
  readonly rotate: readonly [Vec3, Vec3, Vec3];
  readonly move: Vec3;
}

/** A facet placed in space. */
export interface Panel {
  readonly facet: Facet;
  readonly points: readonly Vec3[];
  /** Unit normal of the facet's front face. */
  readonly normal: Vec3;
}

export const applyPose = (pose: Pose, p: Vec3): Vec3 => {
  const [r0, r1, r2] = pose.rotate;
  return {
    x: r0.x * p.x + r0.y * p.y + r0.z * p.z + pose.move.x,
    y: r1.x * p.x + r1.y * p.y + r1.z * p.z + pose.move.y,
    z: r2.x * p.x + r2.y * p.y + r2.z * p.z + pose.move.z,
  };
};

const rotateVec = (pose: Pose, v: Vec3): Vec3 => {
  const [r0, r1, r2] = pose.rotate;
  return {
    x: r0.x * v.x + r0.y * v.y + r0.z * v.z,
    y: r1.x * v.x + r1.y * v.y + r1.z * v.z,
    z: r2.x * v.x + r2.y * v.y + r2.z * v.z,
  };
};

/** `composePose(outer, inner)` applies `inner` first. */
export function composePose(outer: Pose, inner: Pose): Pose {
  const [i0, i1, i2] = inner.rotate;
  // Columns of the inner rotation, each rotated by the outer one.
  const c0 = rotateVec(outer, { x: i0.x, y: i1.x, z: i2.x });
  const c1 = rotateVec(outer, { x: i0.y, y: i1.y, z: i2.y });
  const c2 = rotateVec(outer, { x: i0.z, y: i1.z, z: i2.z });
  const rotate: [Vec3, Vec3, Vec3] = [
    { x: c0.x, y: c1.x, z: c2.x },
    { x: c0.y, y: c1.y, z: c2.y },
    { x: c0.z, y: c1.z, z: c2.z },
  ];
  return { rotate, move: applyPose(outer, inner.move) };
}

/** Rotation by `angle` about the axis through `a` towards `b` lying in the plane z = 0 (right-hand rule). */
export function rotationAbout(a: Vec, b: Vec, angle: number): Pose {
  const len = distance(a, b);
  const ux = (b.x - a.x) / len;
  const uy = (b.y - a.y) / len;
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  const t = 1 - c;
  // Rodrigues' formula for a unit axis (ux, uy, 0).
  const rotate: [Vec3, Vec3, Vec3] = [
    { x: c + ux * ux * t, y: ux * uy * t, z: uy * s },
    { x: ux * uy * t, y: c + uy * uy * t, z: -ux * s },
    { x: -uy * s, y: ux * s, z: c },
  ];
  // Rotate about a point of the axis rather than the origin.
  const origin: Vec3 = { x: a.x, y: a.y, z: 0 };
  const turned = applyPose({ rotate, move: { x: 0, y: 0, z: 0 } }, origin);
  return { rotate, move: sub3(origin, turned) };
}

const sub3 = (p: Vec3, q: Vec3): Vec3 => ({ x: p.x - q.x, y: p.y - q.y, z: p.z - q.z });

/**
 * A flat transform of the sheet as a pose in space: a reflection is a half
 * turn about its line, so z flips with the determinant and the result is
 * always a proper rotation.
 */
export function embedFlat(m: Mat): Pose {
  const det = determinant(m) < 0 ? -1 : 1;
  return {
    rotate: [
      { x: m.a, y: m.c, z: 0 },
      { x: m.b, y: m.d, z: 0 },
      { x: 0, y: 0, z: det },
    ],
    move: { x: m.e, y: m.f, z: 0 },
  };
}

/** The part of segment ab that segment cd covers, if the two are collinear and overlap. */
function sharedSegment(a: Vec, b: Vec, c: Vec, d: Vec, tolerance: number): [Vec, Vec] | null {
  const ab = sub(b, a);
  const len = Math.hypot(ab.x, ab.y);
  if (len < tolerance) return null;
  const dir = { x: ab.x / len, y: ab.y / len };
  if (Math.abs(cross(dir, sub(c, a))) > tolerance || Math.abs(cross(dir, sub(d, a))) > tolerance) {
    return null;
  }
  const tc = dot(dir, sub(c, a));
  const td = dot(dir, sub(d, a));
  const lo = Math.max(0, Math.min(tc, td));
  const hi = Math.min(len, Math.max(tc, td));
  if (hi - lo < tolerance) return null;
  return [
    { x: a.x + dir.x * lo, y: a.y + dir.y * lo },
    { x: a.x + dir.x * hi, y: a.y + dir.y * hi },
  ];
}

/** Whether two flat transforms move the sheet the same way. */
const sameTransform = (m: Mat, n: Mat, tolerance: number): boolean =>
  distance(apply(m, { x: 0.37, y: 0.61 }), apply(n, { x: 0.37, y: 0.61 })) < tolerance &&
  distance(apply(m, { x: 0.83, y: 0.29 }), apply(n, { x: 0.83, y: 0.29 })) < tolerance;

/**
 * The creases between neighbouring facets with their fold angles in the
 * current flat-folded state. Facets are neighbours when their unfolded
 * polygons share part of an edge and the fold model kept them attached:
 * one lies where the other is, or where its reflection across the shared
 * edge is. A fold limited to a region can move a facet away from a
 * neighbour it is attached to (real paper would tear there); such pairs are
 * no hinge, and the panels on either side are placed by the flat model.
 */
export function hinges(state: PaperState): Hinge[] {
  return neighbours(state).hinges;
}

/**
 * Neighbouring facet pairs that the fold model pulled apart: real paper
 * would have torn there. Zero means every state between steps is one a
 * sheet of paper can take.
 */
export function tears(state: PaperState): number {
  return neighbours(state).torn.length;
}

interface Neighbours {
  hinges: Hinge[];
  torn: { a: Vec; b: Vec; p: number; q: number }[];
}

// States are immutable, so what is derived from one can be kept with it.
const neighbourCache = new WeakMap<PaperState, Neighbours>();

function neighbours(state: PaperState): Neighbours {
  const cached = neighbourCache.get(state);
  if (cached) return cached;
  const found = findNeighbours(state);
  neighbourCache.set(state, found);
  return found;
}

function findNeighbours(state: PaperState): Neighbours {
  const tolerance = EPS * 1e3 * state.size;
  const result: Hinge[] = [];
  const torn: { a: Vec; b: Vec; p: number; q: number }[] = [];
  const facets = state.facets;
  for (let i = 0; i < facets.length; i++) {
    const p = facets[i] as Facet;
    for (let j = i + 1; j < facets.length; j++) {
      const q = facets[j] as Facet;
      const shared = sharedEdge(p.poly, q.poly, tolerance);
      if (!shared) continue;
      let angle: number;
      if (sameTransform(p.transform, q.transform, tolerance)) {
        angle = 0;
      } else {
        const folded = compose(
          reflection(applyToLine(p.transform, line(shared[0], shared[1]))),
          p.transform,
        );
        if (!sameTransform(folded, q.transform, tolerance)) {
          torn.push({ a: shared[0], b: shared[1], p: p.id, q: q.id });
          continue;
        }
        angle = q.z > p.z === !isFlipped(p) ? Math.PI : -Math.PI;
      }
      const degrees = creaseAngle(state, shared, tolerance);
      const shown =
        angle === 0 || degrees === undefined ? angle : Math.sign(angle) * degrees * (Math.PI / 180);
      // Layers stacked where the crease lies, just inside facet p.
      const mid = { x: (shared[0].x + shared[1].x) / 2, y: (shared[0].y + shared[1].y) / 2 };
      const inward = centroid(p.poly);
      const probe = apply(p.transform, {
        x: mid.x + (inward.x - mid.x) * 0.02,
        y: mid.y + (inward.y - mid.y) * 0.02,
      });
      const cover = Math.max(1, layersAt(state, probe));
      result.push({ a: shared[0], b: shared[1], p: p.id, q: q.id, angle, shown, cover });
    }
  }
  return { hinges: result, torn };
}

/** The display angle of the latest recorded crease that covers the segment, if any. */
function creaseAngle(
  state: PaperState,
  segment: [Vec, Vec],
  tolerance: number,
): number | undefined {
  const mid = { x: (segment[0].x + segment[1].x) / 2, y: (segment[0].y + segment[1].y) / 2 };
  for (let i = state.creases.length - 1; i >= 0; i--) {
    const c = state.creases[i];
    if (!c || sharedSegment(c.a, c.b, segment[0], segment[1], tolerance) === null) continue;
    // The crease must cover the hinge, not just touch it.
    const d = sub(c.b, c.a);
    const len = Math.hypot(d.x, d.y);
    const t = dot({ x: d.x / len, y: d.y / len }, sub(mid, c.a));
    if (t < -tolerance || t > len + tolerance) continue;
    return c.angle;
  }
  return undefined;
}

function sharedEdge(p: Polygon, q: Polygon, tolerance: number): [Vec, Vec] | null {
  for (let i = 0; i < p.length; i++) {
    const a = p[i] as Vec;
    const b = p[(i + 1) % p.length] as Vec;
    for (let j = 0; j < q.length; j++) {
      const c = q[j] as Vec;
      const d = q[(j + 1) % q.length] as Vec;
      const s = sharedSegment(a, b, c, d, tolerance);
      if (s) return s;
    }
  }
  return null;
}

/** A step in progress: the creases it makes swing from their old angle to the new. */
export interface StepAnimation {
  /** The sheet before the step. */
  readonly previous: PaperState;
  /** Facets (of the current sheet) that the step moved. */
  readonly movedIds: ReadonlySet<number>;
  /** 0 at the start of the step, 1 at its end. */
  readonly progress: number;
  /** Which side of each facet the moving paper is on, carried from frame to frame. */
  readonly contact?: ContactMemory;
}

/**
 * What the solver remembers between the frames of one step: for every
 * vertex that came close to a facet, the side of that facet it was on. The
 * paper then cannot pass through: it is held, and pushes the facet aside.
 */
export interface ContactMemory {
  /** The sheet before the step: where the moving paper lay in the stack when it set off. */
  readonly before: PaperState;
  readonly sides: Map<string, 1 | -1>;
  /** Whether `sides` has been seeded from `before`; the solver does that on first use. */
  seeded: boolean;
}

/** A folded crease opened by `opening`, keeping its direction; a flat crease stays flat. */
export const openedAngle = (angle: number, opening: number): number =>
  angle === 0 ? 0 : Math.sign(angle) * Math.max(0, Math.abs(angle) - opening);

/**
 * How far a hinge opens for a requested opening: a crease on the outside of
 * the stack opens fully, one buried under many layers barely at all, so the
 * sheet reads as pressed paper rather than as fanned-out layers. A crease
 * folded to a chosen angle keeps that angle.
 */
export const hingeOpening = (hinge: Hinge, opening: number): number =>
  Math.abs(hinge.shown) < Math.PI - 1e-9 ? 0 : (opening * 2) / Math.max(2, hinge.cover);

/**
 * The angle a hinge had before the current step. A hinge crossing the step's
 * fold (one facet moved, the other not) is new, or was folded flat before an
 * unfold; every other hinge kept its angle.
 */
function angleBefore(hinge: Hinge, animation: StepAnimation): number {
  const crosses = animation.movedIds.has(hinge.p) !== animation.movedIds.has(hinge.q);
  if (!crosses) return hinge.shown;
  if (hinge.angle !== 0) return 0;
  // Folded and now unfolded: it came from whichever side it lay on before.
  const before = animation.previous.facets;
  const p = before.find((f) => f.id === hinge.p);
  const q = before.find((f) => f.id === hinge.q);
  if (!p || !q) return 0;
  return q.z > p.z === !isFlipped(p) ? Math.PI : -Math.PI;
}

/**
 * How many layers lay at a hinge before the current step: the cover of the
 * crease of the previous sheet that this hinge is part of, or its own
 * cover if the crease is new. A step that stacks more paper on a crease
 * closes it a little; interpolating from the old cover keeps that smooth.
 */
function coverBefore(hinge: Hinge, previous: PaperState): number {
  const tolerance = 1e-6 * previous.size;
  const length = distance(hinge.a, hinge.b);
  for (const h of hinges(previous)) {
    const shared = sharedSegment(h.a, h.b, hinge.a, hinge.b, tolerance);
    if (shared && distance(shared[0], shared[1]) > length - tolerance) return h.cover;
  }
  return hinge.cover;
}

/**
 * Pose options for a sheet shown with its creases opened by `opening`, and,
 * while a step plays, with that step's creases part way between their old
 * and new angles. The facets that stay put anchor the walk.
 */
export function stepPose(
  state: PaperState,
  opening: number,
  animation?: StepAnimation,
): PoseOptions {
  const t = animation ? Math.min(1, Math.max(0, animation.progress)) : 1;
  const byId = new Map(state.facets.map((f) => [f.id, f]));
  // The way the moving paper swings at a crease the step crosses: over the
  // top of the still paper when the moved facet lands above it in the
  // stack, under it otherwise. The crease's angle reads that in the still
  // facet's own sense: a positive angle lifts the neighbour towards its front.
  const swingOf = (h: Hinge): { side: 1 | -1; sense: 1 | -1 } | undefined => {
    const pMoved = animation?.movedIds.has(h.p) ?? false;
    if (!animation || pMoved === animation.movedIds.has(h.q)) return undefined;
    const still = byId.get(pMoved ? h.q : h.p);
    const moved = byId.get(pMoved ? h.p : h.q);
    if (!still || !moved) return undefined;
    return { side: moved.z > still.z ? 1 : -1, sense: isFlipped(still) ? -1 : 1 };
  };
  // Paper folded inside, between layers, is hinged to still paper on both
  // sides of it and cannot swing rigidly either way: it goes the way most
  // of its creases say, and the creases that disagree are released for the
  // step, so the layers in its way bend out of it as paper does.
  const released = new Set<Hinge>();
  if (animation && t < 1) {
    const crossing: [Hinge, 1 | -1][] = [];
    for (const h of hinges(state)) {
      const swing = swingOf(h);
      if (swing) crossing.push([h, swing.side]);
    }
    const over = crossing.filter(([, side]) => side === 1).length;
    const minority = over >= crossing.length - over ? -1 : 1;
    for (const [h, side] of crossing) if (side === minority) released.add(h);
  }
  const angleOf = (h: Hinge): number => {
    const open = hingeOpening(h, opening);
    const target = openedAngle(h.shown, open);
    if (!animation || t >= 1) return target;
    const openBefore = hingeOpening({ ...h, cover: coverBefore(h, animation.previous) }, opening);
    const from = openedAngle(angleBefore(h, animation), openBefore);
    const swing = swingOf(h);
    if (swing === undefined) return from + (target - from) * t;
    // A crease the step folds or unfolds: the moving paper swings on the
    // side it lands on, whatever the crease's own sign says mid-way.
    const magnitude = Math.abs(from) + (Math.abs(target) - Math.abs(from)) * t;
    return swing.side * swing.sense * magnitude;
  };
  const still = animation
    ? new Set(state.facets.filter((f) => !animation.movedIds.has(f.id)).map((f) => f.id))
    : undefined;
  const anchor = anchorFacet(state, still);
  return {
    angleOf,
    ...(anchor ? { rootId: anchor.id } : {}),
    ...(released.size > 0 ? { released } : {}),
    ...(animation && t < 1
      ? { moved: animation.movedIds, ...(animation.contact ? { contact: animation.contact } : {}) }
      : {}),
  };
}

/**
 * The facet to hold still: the largest one lying deepest inside the stack,
 * so that wings and points swing while the body stays where it is.
 */
export function anchorFacet(state: PaperState, among?: ReadonlySet<number>): Facet | undefined {
  let best: Facet | undefined;
  let bestKey = -1;
  for (const f of state.facets) {
    if (among && !among.has(f.id)) continue;
    const c = apply(f.transform, centroid(f.poly));
    // Deep first, but a facet of some size beats a sliver a few layers
    // deeper: pinning a tiny piece inside a head would let the whole body
    // swing about an extremity.
    const key = layersAt(state, c) + ANCHOR_AREA_WEIGHT * polygonArea(f.poly);
    if (key > bestKey) {
      bestKey = key;
      best = f;
    }
  }
  return best;
}

/** How many layers of depth one unit of facet area is worth when choosing the anchor. */
const ANCHOR_AREA_WEIGHT = 50;

export interface PoseOptions {
  /**
   * Fold angle to use for each hinge; defaults to the hinge's flat-folded
   * angle. Lets a caller open creases or animate them.
   */
  readonly angleOf?: (hinge: Hinge) => number;
  /** Facet to place first; defaults to the lowest layer with the largest area. */
  readonly rootId?: number;
  /**
   * While a step plays, the facets it moves: their order against the rest
   * of the sheet is not settled until they land, so the solver keeps layers
   * apart only within the moving group and within the group that stays.
   */
  readonly moved?: ReadonlySet<number>;
  /** With `moved`: the sides remembered so far, kept up to date by the solver. */
  readonly contact?: ContactMemory;
  /**
   * Creases that hold no angle for now: the walk does not cross them and
   * the solver does not bend them, the paper stays joined along them.
   */
  readonly released?: ReadonlySet<Hinge>;
}

/**
 * Every facet placed in space by walking the hinges from the root. With the
 * flat-folded angles this reproduces the folded sheet (z = 0 everywhere);
 * with other angles the panels swing about their creases.
 */
export function placePanels(
  state: PaperState,
  all: readonly Hinge[],
  options: PoseOptions = {},
): Panel[] {
  const byId = new Map(state.facets.map((f) => [f.id, f]));
  if (byId.size === 0) return [];
  const chosen = options.rootId !== undefined ? byId.get(options.rootId) : undefined;
  const root = chosen ?? anchorFacet(state);
  if (!root) return [];
  const angleOf = options.angleOf ?? ((h: Hinge): number => h.angle);
  // The root sits where the flat model puts it, so the two agree.
  const poses = new Map<number, Pose>([[root.id, embedFlat(root.transform)]]);
  const queue = [root.id];
  while (queue.length > 0) {
    const id = queue.shift() as number;
    const pose = poses.get(id) as Pose;
    for (const h of all) {
      if (options.released?.has(h)) continue;
      const other = h.p === id ? h.q : h.q === id ? h.p : null;
      if (other === null || poses.has(other)) continue;
      const neighbour = byId.get(other);
      if (!neighbour) continue;
      // Orient the axis so that the neighbour lies on its left in the sheet:
      // a positive angle then lifts it toward the front of this facet.
      const c = centroid(neighbour.poly);
      const [a, b] = cross(sub(h.b, h.a), sub(c, h.a)) >= 0 ? [h.a, h.b] : [h.b, h.a];
      // The dihedral angle is the same from either side; the axis orientation
      // above is what makes it lift the neighbour toward this facet's front.
      const angle = angleOf(h);
      poses.set(other, composePose(pose, rotationAbout(a, b, angle)));
      queue.push(other);
    }
  }
  return state.facets.map((facet) => {
    const pose = poses.get(facet.id) ?? embedFlat(facet.transform);
    return {
      facet,
      points: facet.poly.map((p) => applyPose(pose, { x: p.x, y: p.y, z: 0 })),
      normal: rotateVec(pose, { x: 0, y: 0, z: 1 }),
    };
  });
}

const polygonArea = (poly: Polygon): number => {
  let sum = 0;
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i] as Vec;
    const q = poly[(i + 1) % poly.length] as Vec;
    sum += p.x * q.y - q.x * p.y;
  }
  return Math.abs(sum) / 2;
};
