/**
 * A small position-based solver that turns the rigid walk of `placePanels`
 * into a sheet that holds together: every facet keeps its shape, facets
 * joined at a crease share their edge, and each crease is pulled towards
 * its target dihedral angle. Where the targets contradict each other (the
 * wings and the body of a crane form a loop) the sheet settles on a
 * compromise, the way paper gives a little, instead of showing a gap.
 */
import {
  type Mat,
  type Polygon,
  type Vec,
  apply,
  applyToPolygon,
  centroid,
  containsPoint,
  cross,
  distance,
  intersectConvex,
  invert,
  signedArea,
  sub,
} from './geometry';
import { type Facet, type PaperState, currentPolygon, isFlipped } from './paper';
import {
  type ContactMemory,
  type Hinge,
  type Panel,
  type PoseOptions,
  type Vec3,
  anchorFacet,
  placePanels,
} from './rigid';

export interface SolveOptions extends PoseOptions {
  /** Gauss-Seidel sweeps over all constraints. */
  readonly iterations?: number;
  /** Stop early when no vertex moved more than this in a sweep, in sheet units. */
  readonly tolerance?: number;
  /** How hard creases pull towards their angle, 0 to 1. */
  readonly bendStiffness?: number;
  /**
   * Thickness of the paper, in sheet units. Where one facet lies on another
   * in the flat model it is kept at least this far above it, in that order;
   * zero still keeps the order.
   */
  readonly thickness?: number;
  /** Sweeps at the end with the creases free, so that facets are rigid and layers in order. */
  readonly settle?: number;
  /** Vertex positions to start from (a previous solution), by facet id and vertex index. */
  readonly warm?: ReadonlyMap<number, readonly Vec3[]>;
  /**
   * Keep the root facet (the one the rigid walk started from) exactly where
   * the walk put it, so the sheet does not drift or turn while it settles.
   * On by default.
   */
  readonly anchor?: boolean;
}

export interface Solved {
  readonly panels: Panel[];
  /** Largest remaining violation of a length or layer-order constraint, in sheet units. */
  readonly residual: number;
  /** Positions to warm-start the next solve from. */
  readonly positions: ReadonlyMap<number, readonly Vec3[]>;
}

interface Mesh {
  /** Every facet's polygon with hinge endpoints inserted as extra (collinear) vertices. */
  readonly polys: Map<number, Vec[]>;
  /** Index into `vertices` for each facet vertex. */
  readonly index: Map<number, number[]>;
  /** Rest length pairs within facets. */
  readonly lengths: { i: number; j: number; rest: number }[];
  /** Crease constraints: edge (i, j), one off-edge vertex on each side. */
  readonly bends: { i: number; j: number; k: number; l: number; hinge: Hinge }[];
  /** Flatness constraints across the diagonals of each facet's triangles. */
  readonly flats: { i: number; j: number; k: number; l: number }[];
  /** Layer constraints: where one facet lies directly on another in the flat model. */
  readonly overlaps: Overlap[];
  readonly count: number;
}

/**
 * A point of the sheet where facet `over` lies directly on facet `under`:
 * the same spot on each, as weights on three of the facet's mesh vertices
 * (a non-degenerate triangle of it, in the polygon's winding).
 */
interface Overlap {
  readonly underId: number;
  readonly overId: number;
  readonly under: readonly [number, number, number];
  readonly underW: readonly [number, number, number];
  readonly underFlipped: boolean;
  readonly over: readonly [number, number, number];
  readonly overW: readonly [number, number, number];
  readonly overFlipped: boolean;
}

/** The point as weights on a non-degenerate fan triangle of the polygon, if it lies inside. */
function onTriangle(
  poly: readonly Vec[],
  ids: readonly number[],
  p: Vec,
  tolerance: number,
): { tri: [number, number, number]; w: [number, number, number] } | null {
  const o = poly[0] as Vec;
  for (let k = 1; k + 1 < poly.length; k++) {
    const a = poly[k] as Vec;
    const b = poly[k + 1] as Vec;
    const area = cross(sub(a, o), sub(b, o));
    if (Math.abs(area) < tolerance * tolerance) continue;
    const w1 = cross(sub(p, o), sub(b, o)) / area;
    const w2 = cross(sub(a, o), sub(p, o)) / area;
    const w0 = 1 - w1 - w2;
    const slack = -1e-6;
    if (w0 < slack || w1 < slack || w2 < slack) continue;
    const clamp = (w: number): number => Math.max(0, w);
    const sum = clamp(w0) + clamp(w1) + clamp(w2);
    return {
      tri: [ids[0] as number, ids[k] as number, ids[k + 1] as number],
      w: [clamp(w0) / sum, clamp(w1) / sum, clamp(w2) / sum],
    };
  }
  return null;
}

/** Whether `p` lies inside the polygon by more than `margin` (not on its edge). */
function wellInside(poly: Polygon, p: Vec, margin: number): boolean {
  if (poly.length < 3) return false;
  const sign = signedArea(poly) >= 0 ? 1 : -1;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i] as Vec;
    const b = poly[(i + 1) % poly.length] as Vec;
    const len = distance(a, b);
    if (len < 1e-12) continue;
    if ((sign * cross(sub(b, a), sub(p, a))) / len <= margin) return false;
  }
  return true;
}

/**
 * Where facets lie on one another in the flat model: for every pair that
 * overlaps, the corners and centre of the overlap, each kept only where no
 * third facet lies between the two there, so that each layer is tied to
 * the one directly beneath it.
 */
function findOverlaps(state: PaperState, mesh: Omit<Mesh, 'overlaps'>): Overlap[] {
  const tolerance = 1e-6 * state.size;
  const facets = [...state.facets].sort((a, b) => a.z - b.z);
  const folded = facets.map((f) => currentPolygon(f));
  const inverse = facets.map((f) => invert(f.transform));
  const flipped = facets.map((f) => isFlipped(f));
  const overlaps: Overlap[] = [];
  for (let i = 0; i < facets.length; i++) {
    for (let j = i + 1; j < facets.length; j++) {
      const region = intersectConvex(folded[i] as Polygon, folded[j] as Polygon);
      if (Math.abs(signedArea(region)) < tolerance * tolerance * 100) continue;
      const under = facets[i] as Facet;
      const over = facets[j] as Facet;
      const samples = [...region, centroid(region)];
      for (const s of samples) {
        // A facet between the two at this spot ties each of them to itself instead.
        let between = false;
        for (let k = i + 1; k < j && !between; k++) {
          between = wellInside(folded[k] as Polygon, s, -tolerance);
        }
        if (between) continue;
        const onUnder = onTriangle(
          mesh.polys.get(under.id) as Vec[],
          mesh.index.get(under.id) as number[],
          apply(inverse[i] as Mat, s),
          tolerance,
        );
        const onOver = onTriangle(
          mesh.polys.get(over.id) as Vec[],
          mesh.index.get(over.id) as number[],
          apply(inverse[j] as Mat, s),
          tolerance,
        );
        if (!onUnder || !onOver) continue;
        // The same welded vertices on both sides (a shared crease): nothing to keep apart.
        const used = (t: readonly number[], w: readonly number[]): string =>
          t
            .filter((_, n) => (w[n] as number) > 1e-9)
            .sort((a, b) => a - b)
            .join(',');
        if (used(onUnder.tri, onUnder.w) === used(onOver.tri, onOver.w)) continue;
        overlaps.push({
          underId: under.id,
          overId: over.id,
          under: onUnder.tri,
          underW: onUnder.w,
          underFlipped: flipped[i] as boolean,
          over: onOver.tri,
          overW: onOver.w,
          overFlipped: flipped[j] as boolean,
        });
      }
    }
  }
  return overlaps;
}

/**
 * Tuning of the sweeps, exported through `solverInternals` so that tests
 * can measure the effect of each knob.
 */
export const solverTuning = {
  /** How much softer a crease folded flat pulls than one folded to a given angle. */
  flatCreaseGive: 0.3,
  /** How hard a facet pulls itself flat across its diagonals: paper bends a little, before a crease gives. */
  facetStiffness: 0.6,
  /**
   * How hard layers are pushed apart to the paper's thickness, 0 to 1. The
   * order of layers is kept hard; the thickness is a preference, since
   * layers welded at a crease or a tip cannot be a thickness apart there.
   */
  thicknessStiffness: 0.3,
};
/** Triangles thinner than this share of their facet get no flatness constraint. */
const THIN_TRIANGLE = 1e-3;
/** Sweeps at the end with the creases free, so that facets are rigid and layers in order. */
const SETTLE_SWEEPS = 100;
/** How close (as a share of the sheet) a vertex must come to a facet to be held off it. */
const CONTACT_REACH = 0.25;

/**
 * A vertex of moving paper near a facet of still paper (or the other way
 * round) in the frame being solved: the facet's triangle under it, where
 * on that triangle, and the side it is to stay on.
 */
interface Contact {
  readonly vertex: number;
  /** The facet the vertex is held off. */
  readonly facet: number;
  readonly tri: readonly [number, number, number];
  readonly w: readonly [number, number, number];
  readonly side: 1 | -1;
}

const sub3 = (a: Vec3, b: Vec3): Vec3 => ({ x: a.x - b.x, y: a.y - b.y, z: a.z - b.z });
const add3 = (a: Vec3, b: Vec3): Vec3 => ({ x: a.x + b.x, y: a.y + b.y, z: a.z + b.z });
const mul3 = (a: Vec3, s: number): Vec3 => ({ x: a.x * s, y: a.y * s, z: a.z * s });
const dot3 = (a: Vec3, b: Vec3): number => a.x * b.x + a.y * b.y + a.z * b.z;
const cross3 = (a: Vec3, b: Vec3): Vec3 => ({
  x: a.y * b.z - a.z * b.y,
  y: a.z * b.x - a.x * b.z,
  z: a.x * b.y - a.y * b.x,
});
const len3 = (a: Vec3): number => Math.hypot(a.x, a.y, a.z);
const norm3 = (a: Vec3): Vec3 => {
  const l = len3(a) || 1;
  return { x: a.x / l, y: a.y / l, z: a.z / l };
};

/** Insert `p` into the polygon if it lies on an edge and is not a vertex yet. */
function insertOnEdge(poly: Vec[], p: Vec, tolerance: number): void {
  if (poly.some((v) => distance(v, p) < tolerance)) return;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i] as Vec;
    const b = poly[(i + 1) % poly.length] as Vec;
    const ab = { x: b.x - a.x, y: b.y - a.y };
    const len = Math.hypot(ab.x, ab.y);
    if (len < tolerance) continue;
    const t = ((p.x - a.x) * ab.x + (p.y - a.y) * ab.y) / (len * len);
    if (t <= 0 || t >= 1) continue;
    const foot = { x: a.x + ab.x * t, y: a.y + ab.y * t };
    if (distance(foot, p) < tolerance) {
      poly.splice(i + 1, 0, p);
      return;
    }
  }
}

class Welds {
  private readonly parent: number[] = [];
  make(): number {
    this.parent.push(this.parent.length);
    return this.parent.length - 1;
  }
  find(i: number): number {
    let r = i;
    while (this.parent[r] !== r) r = this.parent[r] as number;
    let c = i;
    while (this.parent[c] !== r) {
      const next = this.parent[c] as number;
      this.parent[c] = r;
      c = next;
    }
    return r;
  }
  union(a: number, b: number): void {
    const ra = this.find(a);
    const rb = this.find(b);
    if (ra !== rb) this.parent[rb] = ra;
  }
}

// States are immutable, so a mesh built for one can be kept with it.
const meshCache = new WeakMap<PaperState, { hinges: readonly Hinge[]; mesh: Mesh }>();

/** The constraint mesh of a sheet: facets with hinge endpoints as vertices, welded along hinges. */
function buildMesh(state: PaperState, hinges: readonly Hinge[]): Mesh {
  const cached = meshCache.get(state);
  if (cached && cached.hinges === hinges) return cached.mesh;
  const mesh = buildMeshUncached(state, hinges);
  meshCache.set(state, { hinges, mesh });
  return mesh;
}

function buildMeshUncached(state: PaperState, hinges: readonly Hinge[]): Mesh {
  const tolerance = 1e-6 * state.size;
  const polys = new Map<number, Vec[]>();
  for (const f of state.facets)
    polys.set(
      f.id,
      f.poly.map((p) => ({ ...p })),
    );
  for (const h of hinges) {
    for (const id of [h.p, h.q]) {
      const poly = polys.get(id);
      if (!poly) continue;
      insertOnEdge(poly, h.a, tolerance);
      insertOnEdge(poly, h.b, tolerance);
    }
  }
  const welds = new Welds();
  const index = new Map<number, number[]>();
  for (const [id, poly] of polys)
    index.set(
      id,
      poly.map(() => welds.make()),
    );
  const vertexAt = (id: number, p: Vec): number => {
    const poly = polys.get(id) as Vec[];
    const ids = index.get(id) as number[];
    const i = poly.findIndex((v) => distance(v, p) < tolerance);
    return i >= 0 ? (ids[i] as number) : -1;
  };
  for (const h of hinges) {
    for (const end of [h.a, h.b]) {
      const vp = vertexAt(h.p, end);
      const vq = vertexAt(h.q, end);
      if (vp >= 0 && vq >= 0) welds.union(vp, vq);
    }
  }
  // Compact vertex ids.
  const compact = new Map<number, number>();
  for (const ids of index.values()) {
    for (let i = 0; i < ids.length; i++) {
      const root = welds.find(ids[i] as number);
      let c = compact.get(root);
      if (c === undefined) {
        c = compact.size;
        compact.set(root, c);
      }
      ids[i] = c;
    }
  }
  // Each facet is a fan of triangles from one corner: the triangles' edges
  // keep their lengths (so each triangle is rigid and the sheet does not
  // stretch), the facet may bend a little across the diagonals, and every
  // run of vertices along one straight edge keeps all its distances so the
  // edge stays straight.
  const lengths: Mesh['lengths'] = [];
  const flats: Mesh['flats'] = [];
  const seen = new Set<string>();
  const addLength = (a: number, b: number, rest: number): void => {
    if (a === b) return;
    const key = a < b ? `${a}:${b}` : `${b}:${a}`;
    if (seen.has(key)) return;
    seen.add(key);
    lengths.push({ i: a, j: b, rest });
  };
  const facetById = new Map(state.facets.map((f) => [f.id, f]));
  for (const [id, poly] of polys) {
    const ids = index.get(id) as number[];
    const facet = facetById.get(id);
    const corners = facet ? facet.poly : poly;
    // Straight edges of the original facet, with every mesh vertex on them.
    for (let e = 0; e < corners.length; e++) {
      const a = corners[e] as Vec;
      const b = corners[(e + 1) % corners.length] as Vec;
      const len = distance(a, b);
      if (len < tolerance) continue;
      const on = poly
        .map((v, i) => ({ v, i }))
        .filter(({ v }) => {
          const t = ((v.x - a.x) * (b.x - a.x) + (v.y - a.y) * (b.y - a.y)) / (len * len);
          if (t < -1e-9 || t > 1 + 1e-9) return false;
          const foot = { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t };
          return distance(foot, v) < tolerance;
        });
      for (let m = 0; m < on.length; m++) {
        for (let n = m + 1; n < on.length; n++) {
          const p = on[m] as { v: Vec; i: number };
          const q = on[n] as { v: Vec; i: number };
          addLength(ids[p.i] as number, ids[q.i] as number, distance(p.v, q.v));
        }
      }
    }
    const area2 = (a: Vec, b: Vec, c: Vec): number => Math.abs(cross(sub(b, a), sub(c, a)));
    let facetArea = 0;
    for (let k = 1; k + 1 < poly.length; k++) {
      facetArea += area2(poly[0] as Vec, poly[k] as Vec, poly[k + 1] as Vec);
    }
    const thin = (k: number): boolean =>
      area2(poly[0] as Vec, poly[k] as Vec, poly[k + 1] as Vec) < THIN_TRIANGLE * facetArea;
    for (let k = 1; k + 1 < poly.length; k++) {
      const [a, b, c] = [ids[0] as number, ids[k] as number, ids[k + 1] as number];
      addLength(a, b, distance(poly[0] as Vec, poly[k] as Vec));
      addLength(b, c, distance(poly[k] as Vec, poly[k + 1] as Vec));
      addLength(a, c, distance(poly[0] as Vec, poly[k + 1] as Vec));
      // Across the diagonal (0, k+1) to the next triangle of the fan.
      if (k + 2 < poly.length && !thin(k) && !thin(k + 1)) {
        flats.push({ i: a, j: c, k: b, l: ids[k + 2] as number });
      }
    }
  }
  const bends: Mesh['bends'] = [];
  const offEdge = (id: number, a: Vec, b: Vec): number => {
    const poly = polys.get(id) as Vec[];
    const ids = index.get(id) as number[];
    let best = -1;
    let bestDist = 0;
    const ab = { x: b.x - a.x, y: b.y - a.y };
    const len = Math.hypot(ab.x, ab.y) || 1;
    poly.forEach((v, i) => {
      const d = Math.abs((ab.x * (v.y - a.y) - ab.y * (v.x - a.x)) / len);
      if (d > bestDist) {
        bestDist = d;
        best = ids[i] as number;
      }
    });
    return best;
  };
  for (const h of hinges) {
    const i = vertexAt(h.p, h.a);
    const j = vertexAt(h.p, h.b);
    const k = offEdge(h.p, h.a, h.b);
    const l = offEdge(h.q, h.a, h.b);
    if (i < 0 || j < 0 || k < 0 || l < 0 || i === j) continue;
    bends.push({ i, j, k, l, hinge: h });
  }
  const partial = { polys, index, lengths, bends, flats, count: compact.size };
  return { ...partial, overlaps: findOverlaps(state, partial) };
}

/** The facet's current unit normal, from all its vertices (Newell's method). */
function currentNormal(pos: readonly Vec3[], ids: readonly number[]): Vec3 {
  let n: Vec3 = { x: 0, y: 0, z: 0 };
  for (let i = 0; i < ids.length; i++) {
    const a = pos[ids[i] as number] as Vec3;
    const b = pos[ids[(i + 1) % ids.length] as number] as Vec3;
    n = add3(n, cross3(a, b));
  }
  return norm3(n);
}

/**
 * Where a point projects onto a facet in space, as weights on one of its fan
 * triangles, if it lands inside the facet.
 */
function onFacet(
  pos: readonly Vec3[],
  ids: readonly number[],
  normal: Vec3,
  q: Vec3,
): { tri: [number, number, number]; w: [number, number, number] } | null {
  const o = pos[ids[0] as number] as Vec3;
  for (let k = 1; k + 1 < ids.length; k++) {
    const a = pos[ids[k] as number] as Vec3;
    const b = pos[ids[k + 1] as number] as Vec3;
    const area = dot3(cross3(sub3(a, o), sub3(b, o)), normal);
    if (Math.abs(area) < 1e-12) continue;
    const w1 = dot3(cross3(sub3(q, o), sub3(b, o)), normal) / area;
    const w2 = dot3(cross3(sub3(a, o), sub3(q, o)), normal) / area;
    const w0 = 1 - w1 - w2;
    const slack = -1e-6;
    if (w0 < slack || w1 < slack || w2 < slack) continue;
    const clamp = (w: number): number => Math.max(0, w);
    const sum = clamp(w0) + clamp(w1) + clamp(w2);
    return {
      tri: [ids[0] as number, ids[k] as number, ids[k + 1] as number],
      w: [clamp(w0) / sum, clamp(w1) / sum, clamp(w2) / sum],
    };
  }
  return null;
}

/**
 * At the start of a step the moving paper lies flat in the stack, so
 * geometry alone cannot say which side of a still facet it is on. The
 * stack order the step lands in says: a vertex that lay on another facet
 * then keeps that side from the first frame.
 */
function seedSides(
  state: PaperState,
  mesh: Mesh,
  moving: ReadonlySet<number>,
  memory: ContactMemory,
): void {
  memory.seeded = true;
  const before = memory.before;
  const parentOf = (f: Facet): Facet | undefined =>
    before.facets.find((g) => containsPoint(g.poly, centroid(f.poly)));
  const flying = state.facets.filter((f) => moving.has(f.id));
  const still = state.facets.filter((f) => !moving.has(f.id));
  const margin = 1e-6 * state.size;
  for (const m of flying) {
    const pm = parentOf(m);
    if (!pm) continue;
    const mThen = applyToPolygon(pm.transform, m.poly);
    for (const s of still) {
      const ps = parentOf(s);
      if (!ps) continue;
      const sThen = applyToPolygon(ps.transform, s.poly);
      const tiny = 1e-9 * state.size * state.size;
      if (Math.abs(signedArea(intersectConvex(mThen, sThen))) < tiny) continue;
      // The order is only known where the two still lie on one another at
      // the end: paper that unfolds away from a layer leaves it from the
      // side the first frame shows.
      const mNow = applyToPolygon(m.transform, m.poly);
      const sNow = applyToPolygon(s.transform, s.poly);
      if (Math.abs(signedArea(intersectConvex(mNow, sNow))) < tiny) continue;
      // Below in the stack means on the back side of a facet whose front
      // faces up. A side is kept against the facet's own front, which turns
      // over with the moving paper: against moving paper it is read on the
      // facet as it set off.
      const mBelow = m.z < s.z;
      const againstStill: 1 | -1 = (mBelow ? -1 : 1) * (isFlipped(s) ? -1 : 1) === 1 ? 1 : -1;
      const againstMoving: 1 | -1 = (mBelow ? 1 : -1) * (isFlipped(pm) ? -1 : 1) === 1 ? 1 : -1;
      // Only the vertices that lay on the other facet (its edge included)
      // keep that side: a vertex beyond the fold line, where the moving
      // paper is to land, is on the other side of it once it swings past,
      // and the geometry of the frame that first sees it says which.
      const seed = (owner: Facet, over: Polygon, other: Facet, side: 1 | -1): void => {
        const poly = mesh.polys.get(owner.id) ?? [];
        const ids = mesh.index.get(owner.id) ?? [];
        const parent = parentOf(owner);
        if (!parent) return;
        poly.forEach((v, i) => {
          const then = apply(parent.transform, v);
          if (wellInside(over, then, -margin)) memory.sides.set(`${ids[i]}:${other.id}`, side);
        });
      };
      seed(m, sThen, s, againstStill);
      seed(s, mThen, m, againstMoving);
    }
  }
}

/**
 * The contacts of this frame: every vertex of moving paper within reach of
 * a still facet, and every still vertex within reach of a moving facet,
 * each with the side it was first seen on (remembered across frames).
 */
function findContacts(
  state: PaperState,
  mesh: Mesh,
  pos: readonly Vec3[],
  moving: ReadonlySet<number>,
  memory: ContactMemory,
  reach: number,
): Contact[] {
  if (!memory.seeded) seedSides(state, mesh, moving, memory);
  interface Body {
    readonly id: number;
    readonly ids: readonly number[];
    readonly centre: Vec3;
    readonly radius: number;
    readonly normal: Vec3;
  }
  const bodies: Body[] = [];
  for (const [id, ids] of mesh.index) {
    if (ids.length < 3) continue;
    let centre: Vec3 = { x: 0, y: 0, z: 0 };
    for (const vi of ids) centre = add3(centre, pos[vi] as Vec3);
    centre = mul3(centre, 1 / ids.length);
    let radius = 0;
    for (const vi of ids) radius = Math.max(radius, len3(sub3(pos[vi] as Vec3, centre)));
    bodies.push({ id, ids, centre, radius, normal: currentNormal(pos, ids) });
  }
  const flying = bodies.filter((b) => moving.has(b.id));
  const still = bodies.filter((b) => !moving.has(b.id));
  const contacts: Contact[] = [];
  // A vertex is shared by every facet that meets at it, so a pair can come
  // up more than once; each is held once.
  const listed = new Set<string>();
  const near = (vertex: number, facet: Body): void => {
    if (facet.ids.includes(vertex)) return;
    const key = `${vertex}:${facet.id}`;
    if (listed.has(key)) return;
    const p = pos[vertex] as Vec3;
    const d = dot3(sub3(p, pos[facet.ids[0] as number] as Vec3), facet.normal);
    if (Math.abs(d) > reach) return;
    const found = onFacet(pos, facet.ids, facet.normal, sub3(p, mul3(facet.normal, d)));
    if (!found) return;
    let side = memory.sides.get(key);
    if (side === undefined) {
      side = d >= 0 ? 1 : -1;
      memory.sides.set(key, side);
    }
    listed.add(key);
    contacts.push({ vertex, facet: facet.id, tri: found.tri, w: found.w, side });
  };
  for (const a of flying) {
    for (const b of still) {
      if (len3(sub3(a.centre, b.centre)) > a.radius + b.radius + reach) continue;
      for (const vi of a.ids) near(vi, b);
      for (const vi of b.ids) near(vi, a);
    }
  }
  return contacts;
}

/** Hold a vertex on its side of a facet's triangle, `thickness` away. Returns the correction. */
function contactConstraint(
  pos: Vec3[],
  c: Contact,
  thickness: number,
  pinned: ReadonlySet<number>,
): number {
  const a = pos[c.tri[0]] as Vec3;
  const b = pos[c.tri[1]] as Vec3;
  const d = pos[c.tri[2]] as Vec3;
  const n = mul3(norm3(cross3(sub3(b, a), sub3(d, a))), c.side);
  const on = add3(add3(mul3(a, c.w[0]), mul3(b, c.w[1])), mul3(d, c.w[2]));
  const p = pos[c.vertex] as Vec3;
  const gap = dot3(sub3(p, on), n);
  if (gap >= thickness) return 0;
  const wp = pinned.has(c.vertex) ? 0 : 1;
  let sum = wp;
  for (let k = 0; k < 3; k++) {
    const w = c.w[k] as number;
    if (!pinned.has(c.tri[k] as number)) sum += w * w;
  }
  if (sum < 1e-12) return 0;
  const hard = Math.max(0, -gap);
  const soft = (thickness - Math.max(gap, 0)) * solverTuning.thicknessStiffness;
  const lambda = (hard + soft) / sum;
  if (wp) pos[c.vertex] = add3(p, mul3(n, lambda));
  for (let k = 0; k < 3; k++) {
    const vi = c.tri[k] as number;
    if (!pinned.has(vi)) pos[vi] = sub3(pos[vi] as Vec3, mul3(n, lambda * (c.w[k] as number)));
  }
  return hard;
}

/**
 * Keep the point where `over` lies on `under` at least `thickness` above
 * it, along the stack's up direction there. Returns the correction applied.
 */
function separationConstraint(
  pos: Vec3[],
  c: Overlap,
  thickness: number,
  pinned: ReadonlySet<number>,
): number {
  const at = (tri: readonly [number, number, number], w: readonly [number, number, number]): Vec3 =>
    add3(
      add3(mul3(pos[tri[0]] as Vec3, w[0]), mul3(pos[tri[1]] as Vec3, w[1])),
      mul3(pos[tri[2]] as Vec3, w[2]),
    );
  const upOf = (tri: readonly [number, number, number], flipped: boolean): Vec3 => {
    const o = pos[tri[0]] as Vec3;
    const n = cross3(sub3(pos[tri[1]] as Vec3, o), sub3(pos[tri[2]] as Vec3, o));
    return flipped ? mul3(n, -1) : n;
  };
  const p = at(c.under, c.underW);
  const q = at(c.over, c.overW);
  let up = add3(norm3(upOf(c.under, c.underFlipped)), norm3(upOf(c.over, c.overFlipped)));
  if (len3(up) < 1e-9) up = upOf(c.under, c.underFlipped);
  up = norm3(up);
  const gap = dot3(sub3(q, p), up);
  if (gap >= thickness) return 0;
  let sum = 0;
  for (let n = 0; n < 3; n++) {
    const wu = c.underW[n] as number;
    const wo = c.overW[n] as number;
    if (!pinned.has(c.under[n] as number)) sum += wu * wu;
    if (!pinned.has(c.over[n] as number)) sum += wo * wo;
  }
  if (sum < 1e-12) return 0;
  // Through to the other side is corrected in full; short of the thickness, in part.
  const hard = Math.max(0, -gap);
  const soft = (thickness - Math.max(gap, 0)) * solverTuning.thicknessStiffness;
  const lambda = (hard + soft) / sum;
  for (let n = 0; n < 3; n++) {
    const o = c.over[n] as number;
    const u = c.under[n] as number;
    if (!pinned.has(o)) pos[o] = add3(pos[o] as Vec3, mul3(up, lambda * (c.overW[n] as number)));
    if (!pinned.has(u)) pos[u] = sub3(pos[u] as Vec3, mul3(up, lambda * (c.underW[n] as number)));
  }
  return hard;
}

/**
 * Solve the sheet for the given hinge angles. Starts from the rigid walk (or
 * a warm start) and relaxes lengths and crease angles together.
 */
export function solveSheet(
  state: PaperState,
  hinges: readonly Hinge[],
  options: SolveOptions = {},
): Solved {
  const mesh = buildMesh(state, hinges);
  const angleOf = options.angleOf ?? ((h: Hinge): number => h.shown);
  const iterations = options.iterations ?? 60;
  const tolerance = options.tolerance ?? 1e-5 * state.size;
  const bendStiffness = options.bendStiffness ?? 0.5;
  const thickness = options.thickness ?? 0;
  const settle = options.settle ?? SETTLE_SWEEPS;
  const inFlight = options.moved;

  // Initial positions: the rigid walk, averaged where welded vertices disagree.
  const start = placePanels(state, hinges, options);
  const byId = new Map(start.map((p) => [p.facet.id, p]));
  // The anchored facet: the walk's root, or the lowest largest facet it chose.
  const rootId = options.rootId ?? anchorFacet(state)?.id;
  // Nothing is pinned while the sheet settles: a facet held fast in the
  // middle of a stack jams the layers on both sides of it against the loop
  // error. The anchor is put back where the walk had it afterwards, moving
  // the whole sheet as one, which keeps it as still.
  const pinned = new Set<number>();
  const pos: Vec3[] = Array.from({ length: mesh.count }, () => ({ x: 0, y: 0, z: 0 }));
  const weight = new Array<number>(mesh.count).fill(0);
  for (const [id, poly] of mesh.polys) {
    const ids = mesh.index.get(id) as number[];
    const warm = options.warm?.get(id);
    const panel = byId.get(id);
    poly.forEach((v, i) => {
      const vi = ids[i] as number;
      let p: Vec3 | undefined = warm?.[i];
      if (!p && panel) p = pointOnPanel(panel, v);
      if (!p) return;
      pos[vi] = add3(pos[vi] as Vec3, p);
      weight[vi] = (weight[vi] as number) + 1;
    });
  }
  for (let i = 0; i < mesh.count; i++) {
    const w = weight[i] as number;
    if (w > 0) pos[i] = mul3(pos[i] as Vec3, 1 / w);
  }

  const lengthSweep = (): number => {
    let moved = 0;
    for (const c of mesh.lengths) {
      const a = pos[c.i] as Vec3;
      const b = pos[c.j] as Vec3;
      const d = sub3(b, a);
      const l = len3(d);
      if (l < 1e-12) continue;
      const wa = pinned.has(c.i) ? 0 : 1;
      const wb = pinned.has(c.j) ? 0 : 1;
      if (wa + wb === 0) continue;
      const corr = mul3(d, (l - c.rest) / l / (wa + wb));
      pos[c.i] = add3(a, mul3(corr, wa));
      pos[c.j] = sub3(b, mul3(corr, wb));
      moved = Math.max(moved, len3(corr));
    }
    return moved;
  };
  // While a step plays, moving paper is held off the still paper it comes near.
  const contacts =
    inFlight && options.contact
      ? findContacts(state, mesh, pos, inFlight, options.contact, CONTACT_REACH * state.size)
      : [];
  const separationSweep = (apart: number): number => {
    let moved = 0;
    for (const c of mesh.overlaps) {
      // A flap in flight has no settled order against the rest of the sheet.
      if (inFlight && inFlight.has(c.underId) !== inFlight.has(c.overId)) continue;
      moved = Math.max(moved, separationConstraint(pos, c, apart, pinned));
    }
    for (const c of contacts) moved = Math.max(moved, contactConstraint(pos, c, apart, pinned));
    return moved;
  };

  // Creases pull towards their angles while lengths and layer order are kept;
  // a crease folded flat is a soft preference (its opening is a guess), a
  // crease given an angle is firmer.
  for (let sweep = 0; sweep < iterations; sweep++) {
    let moved = lengthSweep();
    for (const c of mesh.bends) {
      if (options.released?.has(c.hinge)) continue;
      const shown = angleOf(c.hinge);
      const target = Math.PI - Math.abs(shown);
      const firm = Math.abs(c.hinge.shown) < Math.PI - 1e-9;
      const stiffness = firm ? bendStiffness : bendStiffness * solverTuning.flatCreaseGive;
      moved = Math.max(moved, bendConstraint(pos, c.i, c.j, c.k, c.l, target, stiffness, pinned));
    }
    for (const c of mesh.flats) {
      moved = Math.max(
        moved,
        bendConstraint(pos, c.i, c.j, c.k, c.l, Math.PI, solverTuning.facetStiffness, pinned),
      );
    }
    moved = Math.max(moved, separationSweep(thickness));
    if (moved < tolerance) break;
  }
  // Then let the sheet settle with its creases free and the thickness no
  // longer asked for: facets rigid, layers in order, which is a state that
  // exists, so the sweeps converge.
  let residual = 0;
  for (let sweep = 0; sweep < settle; sweep++) {
    residual = Math.max(lengthSweep(), separationSweep(0));
    if (residual < tolerance) break;
  }

  if (rootId !== undefined && options.anchor !== false) {
    const root = byId.get(rootId);
    const poly = mesh.polys.get(rootId);
    const ids = mesh.index.get(rootId);
    if (root && poly && ids) {
      registerTo(
        pos,
        ids.map((vi) => pos[vi] as Vec3),
        poly.map((v) => pointOnPanel(root, v)),
      );
    }
  }

  const positions = new Map<number, Vec3[]>();
  const panels: Panel[] = [];
  for (const f of state.facets) {
    const poly = mesh.polys.get(f.id) as Vec[];
    const ids = mesh.index.get(f.id) as number[];
    const solved = ids.map((vi) => pos[vi] as Vec3);
    positions.set(f.id, solved);
    // Report the facet's own corners (not the inserted hinge endpoints).
    const points = f.poly.map((corner) => {
      const i = poly.findIndex((v) => distance(v, corner) < 1e-9);
      return solved[i >= 0 ? i : 0] as Vec3;
    });
    panels.push({ facet: f, points, normal: facetNormal(points) });
  }
  return { panels, residual, positions };
}

/**
 * Move every position as one rigid body so that the `from` points (a
 * facet's corners as solved) land on the `to` points (the same corners
 * where the walk had them), as nearly as a rigid motion can.
 */
function registerTo(pos: Vec3[], from: readonly Vec3[], to: readonly Vec3[]): void {
  const centreOf = (pts: readonly Vec3[]): Vec3 =>
    mul3(
      pts.reduce((s, q) => add3(s, q), { x: 0, y: 0, z: 0 }),
      1 / pts.length,
    );
  // The corner farthest from the centre gives the first axis: the same
  // corner of both, chosen on the exact one.
  const toCentre = centreOf(to);
  let k = 0;
  to.forEach((q, i) => {
    if (len3(sub3(q, toCentre)) > len3(sub3(to[k] as Vec3, toCentre))) k = i;
  });
  const frame = (pts: readonly Vec3[]): [Vec3, Vec3, Vec3, Vec3] | null => {
    const c = centreOf(pts);
    const n = facetNormal(pts);
    const u = sub3(pts[k] as Vec3, c);
    if (len3(u) < 1e-9 || len3(n) < 1e-9) return null;
    const e1 = norm3(u);
    const e3 = norm3(sub3(n, mul3(e1, dot3(n, e1))));
    return [c, e1, cross3(e3, e1), e3];
  };
  const f = frame(from);
  const g = frame(to);
  if (!f || !g) return;
  for (let i = 0; i < pos.length; i++) {
    const d = sub3(pos[i] as Vec3, f[0]);
    const a = dot3(d, f[1]);
    const b = dot3(d, f[2]);
    const c = dot3(d, f[3]);
    pos[i] = add3(g[0], add3(add3(mul3(g[1], a), mul3(g[2], b)), mul3(g[3], c)));
  }
}

/** Where a point of the facet's unfolded polygon sits on the placed panel. */
function pointOnPanel(panel: Panel, p: Vec): Vec3 {
  const poly = panel.facet.poly;
  // Barycentric-free: express p in the frame of the first corner and two edges.
  const o = poly[0] as Vec;
  const u = { x: (poly[1] as Vec).x - o.x, y: (poly[1] as Vec).y - o.y };
  const c = centroid(poly);
  const v = { x: c.x - o.x, y: c.y - o.y };
  const det = u.x * v.y - u.y * v.x;
  const O = panel.points[0] as Vec3;
  const U = sub3(panel.points[1] as Vec3, O);
  const C = panel.points.reduce((s, q) => add3(s, q), { x: 0, y: 0, z: 0 });
  const V = sub3(mul3(C, 1 / panel.points.length), O);
  if (Math.abs(det) < 1e-12) return O;
  const d = { x: p.x - o.x, y: p.y - o.y };
  const s = (d.x * v.y - d.y * v.x) / det;
  const t = (u.x * d.y - u.y * d.x) / det;
  return add3(O, add3(mul3(U, s), mul3(V, t)));
}

function facetNormal(points: readonly Vec3[]): Vec3 {
  let n: Vec3 = { x: 0, y: 0, z: 0 };
  for (let i = 0; i < points.length; i++) {
    const a = points[i] as Vec3;
    const b = points[(i + 1) % points.length] as Vec3;
    n = add3(n, cross3(a, b));
  }
  return norm3(n);
}

/**
 * The bending constraint of Müller et al. (2007) on the edge (i, j) with
 * off-edge vertices k and l: the angle between the two triangle normals is
 * driven towards `target` (π when the two lie flat in one plane, 0 when
 * folded onto each other). Returns the largest correction applied.
 */
function bendConstraint(
  pos: Vec3[],
  i: number,
  j: number,
  k: number,
  l: number,
  target: number,
  stiffness: number,
  pinned: ReadonlySet<number>,
): number {
  const p1 = pos[i] as Vec3;
  const p2 = sub3(pos[j] as Vec3, p1);
  const p3 = sub3(pos[k] as Vec3, p1);
  const p4 = sub3(pos[l] as Vec3, p1);
  const n1raw = cross3(p2, p3);
  const n2raw = cross3(p2, p4);
  const l1 = len3(n1raw);
  const l2 = len3(n2raw);
  if (l1 < 1e-12 || l2 < 1e-12) return 0;
  const n1 = mul3(n1raw, 1 / l1);
  const n2 = mul3(n2raw, 1 / l2);
  const d = Math.max(-1, Math.min(1, dot3(n1, n2)));
  const q3 = mul3(add3(cross3(p2, n2), mul3(cross3(n1, p2), d)), 1 / l1);
  const q4 = mul3(add3(cross3(p2, n1), mul3(cross3(n2, p2), d)), 1 / l2);
  const q2 = add3(
    mul3(add3(cross3(p3, n2), mul3(cross3(n1, p3), d)), -1 / l1),
    mul3(add3(cross3(p4, n1), mul3(cross3(n2, p4), d)), -1 / l2),
  );
  const q1 = mul3(add3(add3(q2, q3), q4), -1);
  const w = [i, j, k, l].map((v) => (pinned.has(v) ? 0 : 1)) as [number, number, number, number];
  const sum = w[0] * dot3(q1, q1) + w[1] * dot3(q2, q2) + w[2] * dot3(q3, q3) + w[3] * dot3(q4, q4);
  if (sum < 1e-12) return 0;
  const sinD = Math.sqrt(Math.max(0, 1 - d * d));
  if (sinD < 1e-9) {
    // Normals (anti)parallel: the gradient vanishes; nudge the off-edge vertex instead.
    const want = Math.cos(target);
    if (Math.abs(want - d) < 1e-6) return 0;
    const push = mul3(n1, (want > d ? -1 : 1) * 1e-3 * stiffness);
    if (pinned.has(l)) return 0;
    pos[l] = add3(pos[l] as Vec3, push);
    return len3(push);
  }
  const scale = (-(Math.acos(d) - target) * sinD) / sum;
  const s = stiffness * scale;
  pos[i] = add3(pos[i] as Vec3, mul3(q1, s * w[0]));
  pos[j] = add3(pos[j] as Vec3, mul3(q2, s * w[1]));
  pos[k] = add3(pos[k] as Vec3, mul3(q3, s * w[2]));
  pos[l] = add3(pos[l] as Vec3, mul3(q4, s * w[3]));
  return Math.abs(s) * Math.sqrt(sum);
}

export const solverInternals = { buildMesh, tuning: solverTuning };
export type { Facet };
