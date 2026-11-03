/**
 * Pure 2D geometry helpers: vectors, lines, affine transforms (reflections),
 * and convex polygon clipping. Nothing in here knows about paper or layers.
 */

export interface Vec {
  readonly x: number;
  readonly y: number;
}

/** A convex polygon given by its vertices in order (no repeated closing vertex). */
export type Polygon = readonly Vec[];

/** An infinite line through two distinct points `a` and `b`. */
export interface Line {
  readonly a: Vec;
  readonly b: Vec;
}

/**
 * A 2D affine transform in SVG matrix convention:
 * x' = a·x + c·y + e, y' = b·x + d·y + f.
 */
export interface Mat {
  readonly a: number;
  readonly b: number;
  readonly c: number;
  readonly d: number;
  readonly e: number;
  readonly f: number;
}

/** Which side of a directed line (a → b) a point lies on. +1 is the left side. */
export type Side = 1 | -1;

export const EPS = 1e-9;
/** Polygon pieces with an area below this are treated as empty. */
export const AREA_EPS = 1e-10;
/**
 * How close to a fold line a vertex may lie and still count as on it. Wider
 * than EPS because fold lines read from files carry nine decimals, and a
 * vertex meant to sit on the line would otherwise split off a sliver facet.
 */
export const ON_LINE_EPS = 1e-7;

export const vec = (x: number, y: number): Vec => ({ x, y });
export const add = (p: Vec, q: Vec): Vec => ({ x: p.x + q.x, y: p.y + q.y });
export const sub = (p: Vec, q: Vec): Vec => ({ x: p.x - q.x, y: p.y - q.y });
export const scale = (p: Vec, s: number): Vec => ({ x: p.x * s, y: p.y * s });
export const dot = (p: Vec, q: Vec): number => p.x * q.x + p.y * q.y;
export const cross = (p: Vec, q: Vec): number => p.x * q.y - p.y * q.x;
export const length = (p: Vec): number => Math.hypot(p.x, p.y);
export const distance = (p: Vec, q: Vec): number => length(sub(p, q));
export const lerp = (p: Vec, q: Vec, t: number): Vec => add(p, scale(sub(q, p), t));

export function normalize(p: Vec): Vec {
  const len = length(p);
  if (len < EPS) throw new Error('cannot normalize a zero-length vector');
  return scale(p, 1 / len);
}

export const approxEqual = (a: number, b: number, eps = 1e-7): boolean => Math.abs(a - b) <= eps;
export const approxEqualVec = (p: Vec, q: Vec, eps = 1e-7): boolean =>
  approxEqual(p.x, q.x, eps) && approxEqual(p.y, q.y, eps);

export const line = (a: Vec, b: Vec): Line => {
  if (distance(a, b) < EPS) throw new Error('a line needs two distinct points');
  return { a, b };
};

/**
 * The line every point of which is equally far from `a` and `b`: folding
 * along it brings `a` onto `b`.
 */
export function perpendicularBisector(a: Vec, b: Vec): Line {
  const mid = scale(add(a, b), 0.5);
  const d = normalize(sub(b, a));
  // Two points a unit apart either side of the midpoint, so that rounding
  // the line's points (as a file does) moves the line as little as possible.
  const perp = { x: -d.y / 2, y: d.x / 2 };
  return line(sub(mid, perp), add(mid, perp));
}

/** Unit direction vector of a line. */
export const lineDirection = (l: Line): Vec => normalize(sub(l.b, l.a));

/** Unit normal of a line, pointing to its left side. */
export function lineNormal(l: Line): Vec {
  const d = lineDirection(l);
  return { x: -d.y, y: d.x };
}

/** Signed distance of `p` from the line; positive on the left of a → b. */
export function signedDistance(l: Line, p: Vec): number {
  return cross(lineDirection(l), sub(p, l.a));
}

/** The side of the line a point lies on. Points on the line count as the left side. */
export const sideOf = (l: Line, p: Vec): Side => (signedDistance(l, p) >= 0 ? 1 : -1);

// ---------------------------------------------------------------------------
// Affine transforms
// ---------------------------------------------------------------------------

export const IDENTITY: Mat = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 };

export const apply = (m: Mat, p: Vec): Vec => ({
  x: m.a * p.x + m.c * p.y + m.e,
  y: m.b * p.x + m.d * p.y + m.f,
});

export const applyToPolygon = (m: Mat, poly: Polygon): Polygon => poly.map((p) => apply(m, p));

export const applyToLine = (m: Mat, l: Line): Line => line(apply(m, l.a), apply(m, l.b));

/** `compose(outer, inner)` applies `inner` first, then `outer`. */
export function compose(outer: Mat, inner: Mat): Mat {
  return {
    a: outer.a * inner.a + outer.c * inner.b,
    b: outer.b * inner.a + outer.d * inner.b,
    c: outer.a * inner.c + outer.c * inner.d,
    d: outer.b * inner.c + outer.d * inner.d,
    e: outer.a * inner.e + outer.c * inner.f + outer.e,
    f: outer.b * inner.e + outer.d * inner.f + outer.f,
  };
}

export const determinant = (m: Mat): number => m.a * m.d - m.b * m.c;

export function invert(m: Mat): Mat {
  const det = determinant(m);
  if (Math.abs(det) < EPS) throw new Error('matrix is not invertible');
  const a = m.d / det;
  const b = -m.b / det;
  const c = -m.c / det;
  const d = m.a / det;
  return { a, b, c, d, e: -(a * m.e + c * m.f), f: -(b * m.e + d * m.f) };
}

/** Reflection across a line. Reflections are involutions: R ∘ R = I. */
export function reflection(l: Line): Mat {
  return partialFlip(l, Math.PI);
}

/**
 * Top-down projection of rotating the plane around `l` by `angle` radians.
 * The component along the line is kept, the perpendicular component is scaled
 * by cos(angle). At angle 0 this is the identity, at π it is `reflection(l)`.
 */
export function partialFlip(l: Line, angle: number): Mat {
  const n = lineNormal(l);
  const k = 1 - Math.cos(angle);
  const a = 1 - k * n.x * n.x;
  const b = -k * n.x * n.y;
  const c = b;
  const d = 1 - k * n.y * n.y;
  // Keep the pivot point fixed: p' = L(p - pivot) + pivot.
  const e = l.a.x - (a * l.a.x + c * l.a.y);
  const f = l.a.y - (b * l.a.x + d * l.a.y);
  return { a, b, c, d, e, f };
}

// ---------------------------------------------------------------------------
// Polygons
// ---------------------------------------------------------------------------

/** Signed area: positive for counter-clockwise vertex order. */
export function signedArea(poly: Polygon): number {
  let sum = 0;
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i] as Vec;
    const q = poly[(i + 1) % poly.length] as Vec;
    sum += cross(p, q);
  }
  return sum / 2;
}

export const area = (poly: Polygon): number => Math.abs(signedArea(poly));

/** Returns the polygon with counter-clockwise vertex order. */
export const orientCCW = (poly: Polygon): Polygon =>
  signedArea(poly) < 0 ? [...poly].reverse() : poly;

export function centroid(poly: Polygon): Vec {
  if (poly.length === 0) throw new Error('centroid of an empty polygon');
  let cx = 0;
  let cy = 0;
  let twiceArea = 0;
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i] as Vec;
    const q = poly[(i + 1) % poly.length] as Vec;
    const w = cross(p, q);
    cx += (p.x + q.x) * w;
    cy += (p.y + q.y) * w;
    twiceArea += w;
  }
  if (Math.abs(twiceArea) < EPS) {
    // Degenerate: fall back to the vertex average.
    const sum = poly.reduce(add, vec(0, 0));
    return scale(sum, 1 / poly.length);
  }
  return { x: cx / (3 * twiceArea), y: cy / (3 * twiceArea) };
}

/** Point-in-convex-polygon test (boundary counts as inside). */
export function containsPoint(poly: Polygon, p: Vec): boolean {
  if (poly.length < 3) return false;
  const ccw = orientCCW(poly);
  for (let i = 0; i < ccw.length; i++) {
    const a = ccw[i] as Vec;
    const b = ccw[(i + 1) % ccw.length] as Vec;
    if (cross(sub(b, a), sub(p, a)) < -EPS) return false;
  }
  return true;
}

export interface Split {
  /** The part on the left of the line (positive signed distance). */
  readonly positive: Polygon;
  /** The part on the right of the line (negative signed distance). */
  readonly negative: Polygon;
}

/**
 * Cut a convex polygon with a line (Sutherland–Hodgman against a half-plane,
 * run for both half-planes). Vertices lying on the line belong to both parts.
 * Parts with (near) zero area are returned as empty arrays.
 */
export function clipPolygon(poly: Polygon, l: Line): Split {
  const distances = poly.map((p) => signedDistance(l, p));
  const positive: Vec[] = [];
  const negative: Vec[] = [];
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i] as Vec;
    const q = poly[(i + 1) % poly.length] as Vec;
    const dp = distances[i] as number;
    const dq = distances[(i + 1) % poly.length] as number;
    const sp = Math.abs(dp) <= ON_LINE_EPS ? 0 : Math.sign(dp);
    const sq = Math.abs(dq) <= ON_LINE_EPS ? 0 : Math.sign(dq);
    if (sp >= 0) positive.push(p);
    if (sp <= 0) negative.push(p);
    if (sp * sq < 0) {
      // Edge crosses the line strictly: insert the intersection in both.
      const t = dp / (dp - dq);
      const x = lerp(p, q, t);
      positive.push(x);
      negative.push(x);
    }
  }
  return {
    positive: area(positive) > AREA_EPS ? positive : [],
    negative: area(negative) > AREA_EPS ? negative : [],
  };
}

/** Keep the part of `poly` on the left of the directed line a → b. */
export function clipByHalfPlane(poly: Polygon, l: Line): Polygon {
  return clipPolygon(poly, l).positive;
}

/** Intersection of two convex polygons (may be empty). */
export function intersectConvex(p: Polygon, q: Polygon): Polygon {
  if (p.length < 3 || q.length < 3) return [];
  const clipper = orientCCW(q);
  let result: Polygon = p;
  for (let i = 0; i < clipper.length && result.length >= 3; i++) {
    const a = clipper[i] as Vec;
    const b = clipper[(i + 1) % clipper.length] as Vec;
    result = clipByHalfPlane(result, line(a, b));
  }
  return result.length >= 3 ? result : [];
}

/**
 * The chord of a line inside a convex polygon: the segment where the line
 * crosses the polygon, or `null` when the line misses it (or only touches a
 * vertex).
 */
export function chord(poly: Polygon, l: Line): readonly [Vec, Vec] | null {
  const d = lineDirection(l);
  const points: Vec[] = [];
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i] as Vec;
    const q = poly[(i + 1) % poly.length] as Vec;
    const dp = signedDistance(l, p);
    const dq = signedDistance(l, q);
    const onP = Math.abs(dp) <= EPS;
    const onQ = Math.abs(dq) <= EPS;
    if (onP) points.push(p);
    if (!onP && !onQ && Math.sign(dp) !== Math.sign(dq)) {
      points.push(lerp(p, q, dp / (dp - dq)));
    }
  }
  if (points.length < 2) return null;
  let lo = points[0] as Vec;
  let hi = lo;
  let loT = dot(sub(lo, l.a), d);
  let hiT = loT;
  for (const p of points) {
    const t = dot(sub(p, l.a), d);
    if (t < loT) {
      lo = p;
      loT = t;
    }
    if (t > hiT) {
      hi = p;
      hiT = t;
    }
  }
  if (hiT - loT <= EPS) return null;
  return [lo, hi];
}

/** Axis-aligned bounding box of a set of points. */
export function bounds(points: readonly Vec[]): {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
} {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const p of points) {
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
  }
  return { minX, minY, maxX, maxY };
}
