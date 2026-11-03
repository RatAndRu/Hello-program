import { area, centroid, containsPoint } from './geometry';
import { type PaperState, currentPolygon, foldedPoints } from './paper';
import { type ViewFrame } from './sequence';
import { type Hinge, type Panel, type StepAnimation, type Vec3, hinges, stepPose } from './rigid';
import { solveSheet } from './solve';

export type { StepAnimation } from './rigid';

/** How the 3D view is turned: yaw spins the sheet on the table, pitch tilts it. Radians. */
export interface Orbit {
  /**
   * Optional fixed turn applied first: rows are the model-space directions
   * that map to screen right, screen up and towards the viewer. Named views
   * set it; dragging then adds yaw and pitch on top.
   */
  readonly basis?: readonly [Vec3, Vec3, Vec3];
  readonly yaw: number;
  readonly pitch: number;
  /** Turn of the picture about the line of sight. */
  readonly roll: number;
  readonly zoom: number;
}

export const DEFAULT_ORBIT: Orbit = { yaw: -0.55, pitch: 0.95, roll: 0, zoom: 1 };

/** The sheet's own axes, used when a sequence says nothing about how it stands. */
export const DEFAULT_FRAME: ViewFrame = { front: { x: 1, y: 0 }, top: { x: 0, y: 1 } };

/**
 * A frame for a model that says nothing about how it stands, from its
 * shape: the long axis of the folded sheet is taken as its front-to-back
 * direction and the axis across it as up. A shape with no long axis (a
 * square, a circle) keeps the sheet's own axes.
 */
export function autoFrame(state: PaperState): ViewFrame {
  // Second moments of the folded sheet, every facet weighted by its area.
  let total = 0;
  let cx = 0;
  let cy = 0;
  const parts = state.facets.map((f) => {
    const poly = currentPolygon(f);
    const a = area(poly);
    const c = centroid(poly);
    total += a;
    cx += c.x * a;
    cy += c.y * a;
    return { poly, a, c };
  });
  if (total < 1e-12) return DEFAULT_FRAME;
  cx /= total;
  cy /= total;
  let sxx = 0;
  let sxy = 0;
  let syy = 0;
  for (const { poly, a } of parts) {
    for (const p of poly) {
      const dx = p.x - cx;
      const dy = p.y - cy;
      const w = a / poly.length;
      sxx += dx * dx * w;
      sxy += dx * dy * w;
      syy += dy * dy * w;
    }
  }
  const spread = Math.hypot(sxx - syy, 2 * sxy);
  // Nearly isotropic: no direction to prefer.
  if (spread < 0.05 * (sxx + syy)) return DEFAULT_FRAME;
  const angle = 0.5 * Math.atan2(2 * sxy, sxx - syy);
  const front = { x: Math.cos(angle), y: Math.sin(angle) };
  return { front, top: { x: -front.y, y: front.x } };
}

export interface NamedView {
  readonly id: 'front' | 'side' | 'top' | 'isometric';
  /** The formal name of the view. */
  readonly label: string;
  /** What fits on a button. */
  readonly short: string;
  readonly orbit: Orbit;
}

const unit3 = (a: Vec3): Vec3 => {
  const l = Math.hypot(a.x, a.y, a.z) || 1;
  return { x: a.x / l, y: a.y / l, z: a.z / l };
};
const cross3 = (a: Vec3, b: Vec3): Vec3 => ({
  x: a.y * b.z - a.z * b.y,
  y: a.z * b.x - a.x * b.z,
  z: a.x * b.y - a.y * b.x,
});
const mix3 = (a: Vec3, sa: number, b: Vec3, sb: number): Vec3 => ({
  x: a.x * sa + b.x * sb,
  y: a.y * sa + b.y * sb,
  z: a.z * sa + b.z * sb,
});

/**
 * The fixed views of a model, from how it stands: `front` points out of its
 * face, `top` up its back, both in the folded sheet's plane. The front view
 * looks at the face with the back up; the side view shows the profile with
 * the face to the left; the top view looks down the back with the face at
 * the top of the picture; the isometric view is the side view turned 45°
 * about the vertical.
 */
export function namedViews(frame: ViewFrame = DEFAULT_FRAME): NamedView[] {
  const f = unit3({ x: frame.front.x, y: frame.front.y, z: 0 });
  const tRaw = { x: frame.top.x, y: frame.top.y, z: 0 };
  const along = tRaw.x * f.x + tRaw.y * f.y;
  const t = unit3({ x: tRaw.x - f.x * along, y: tRaw.y - f.y * along, z: 0 });
  const n = cross3(f, t);
  const view = (
    id: NamedView['id'],
    label: string,
    short: string,
    right: Vec3,
    up: Vec3,
    toward: Vec3,
  ): NamedView => ({
    id,
    label,
    short,
    orbit: { basis: [right, up, toward], yaw: 0, pitch: 0, roll: 0, zoom: 1 },
  });
  const minus = (a: Vec3): Vec3 => ({ x: -a.x, y: -a.y, z: -a.z });
  const side = view('side', 'Side view', 'Side', minus(f), t, minus(n));
  const c = Math.SQRT1_2;
  return [
    view('front', 'Front view', 'Front', minus(n), t, f),
    side,
    view('top', 'Top view', 'Top', n, f, t),
    view(
      'isometric',
      'Isometric',
      'Iso',
      mix3(minus(f), c, minus(n), c),
      t,
      mix3(minus(n), c, f, c),
    ),
  ];
}

export const MIN_ORBIT_ZOOM = 0.5;
export const MAX_ORBIT_ZOOM = 4;

/** Paper thicknesses offered as presets, in millimetres of a 15 cm sheet. */
export const THICKNESS_STEPS_MM: readonly number[] = [0, 0.07, 0.2];
export const DEFAULT_THICKNESS_MM = 0.07;
export const MAX_THICKNESS_MM = 1;
/** The sheet the thickness presets are given for, in millimetres. */
export const SHEET_MM = 150;

/** Crease openings offered as presets, in degrees; any other value can be typed. */
export const OPENING_STEPS: readonly number[] = [0, 6, 15, 30];
export const DEFAULT_OPENING = 6;
export const MAX_OPENING = 90;

/** An angle brought back into (-π, π]. */
export const wrapAngle = (a: number): number => {
  const twoPi = 2 * Math.PI;
  let r = a % twoPi;
  if (r <= -Math.PI) r += twoPi;
  if (r > Math.PI) r -= twoPi;
  return r;
};

export interface SceneOptions {
  /** How far every folded crease is opened from flat, in radians. */
  readonly opening: number;
  readonly animation?: StepAnimation;
  /** Thickness of the paper, in sheet units; layers are kept this far apart. */
  readonly thickness?: number;
  /** The facet to hold still, when the caller wants the same one as last time. */
  readonly anchorId?: number;
}

/** A line to draw: the sheet's boundary or a crease that is bent in the current pose. */
export interface SceneEdge {
  readonly a: Vec3;
  readonly b: Vec3;
}

/**
 * How buried each corner of a facet is, per face: 0 in the open, 1 deep in
 * a stack. The renderer darkens the paper by it, which is what ambient
 * occlusion would do inside the folds if the paper were not too thin for
 * a screen-space method to see.
 */
export interface FacetShade {
  /** Shade at each corner, front face and back face. */
  readonly top: number[];
  readonly bottom: number[];
  /**
   * An inner ring of points, one per corner, a short way in towards the
   * centre (`inner[i]` is how far along, 0 at the corner, 1 at the centre),
   * with their own shade: the darkening stays near the creases instead of
   * spreading across a whole wing.
   */
  readonly inner: number[];
  readonly innerTop: number[];
  readonly innerBottom: number[];
}

export interface SolvedScene {
  readonly panels: Panel[];
  readonly edges: SceneEdge[];
  /** Shade of every facet's corners, by facet id. */
  readonly shade: Record<number, FacetShade>;
  /**
   * Each facet's place in its stack, by facet id: how many facets lie
   * under it in the flat model where it sits. Layers that the solver leaves
   * almost coincident are drawn in this order, not in the order of their
   * last fraction of a millimetre.
   */
  readonly rank: Record<number, number>;
  /** False while a step plays: the picture is a frame of a swing, not a pose to frame the camera on. */
  readonly settled: boolean;
  /** The facet that was held still. */
  readonly anchorId: number | undefined;
  /** Centre of the sheet's extent (in the sheet's plane) that views turn about. */
  readonly centre: Vec3;
  /** Farthest any solved point lies from the centre. */
  readonly reach: number;
}

/** How far from a facet another layer still darkens it, as a share of the sheet. */
const SHADE_REACH = 0.05;
/** How far in from a corner the inner ring sits, as a share of the sheet. */
const RING_REACH = 0.07;

const dot3 = (a: Vec3, b: Vec3): number => a.x * b.x + a.y * b.y + a.z * b.z;
const sub3 = (a: Vec3, b: Vec3): Vec3 => ({ x: a.x - b.x, y: a.y - b.y, z: a.z - b.z });
const add3 = (a: Vec3, b: Vec3): Vec3 => ({ x: a.x + b.x, y: a.y + b.y, z: a.z + b.z });
const mul3 = (a: Vec3, s: number): Vec3 => ({ x: a.x * s, y: a.y * s, z: a.z * s });

/** Whether `q`, lying in the panel's plane, is inside its polygon. */
function insidePanel(panel: Panel, q: Vec3): boolean {
  const n = panel.normal;
  const pts = panel.points;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i] as Vec3;
    const b = pts[(i + 1) % pts.length] as Vec3;
    if (dot3(cross3(sub3(b, a), sub3(q, a)), n) < -1e-9) return false;
  }
  return true;
}

/**
 * How buried every facet is, from the solved sheet itself: at each corner
 * and each point of an inner ring, how close other layers lie over the
 * front face and over the back face (a layer touching counts fully, one
 * at the reach not at all). Light cannot get into the slit between two
 * layers, which is what screen-space occlusion would show if paper were
 * not too thin for it.
 */
function occlusionShade(panels: readonly Panel[], size: number): Record<number, FacetShade> {
  const reach = SHADE_REACH * size;
  const bodies = panels.map((panel) => {
    let centre: Vec3 = { x: 0, y: 0, z: 0 };
    for (const p of panel.points) centre = add3(centre, p);
    centre = mul3(centre, 1 / Math.max(1, panel.points.length));
    let radius = 0;
    for (const p of panel.points) {
      radius = Math.max(radius, Math.hypot(p.x - centre.x, p.y - centre.y, p.z - centre.z));
    }
    return { panel, centre, radius, normal: unit3(panel.normal) };
  });
  const result: Record<number, FacetShade> = {};
  for (const a of bodies) {
    const near = bodies.filter(
      (b) =>
        b !== a &&
        Math.hypot(b.centre.x - a.centre.x, b.centre.y - a.centre.y, b.centre.z - a.centre.z) <=
          a.radius + b.radius + reach,
    );
    // Layers over the front (+) and back (−) of the point, weighted by closeness.
    const cover = (p: Vec3): [number, number] => {
      let front = 0;
      let back = 0;
      for (const b of near) {
        const along = dot3(a.normal, b.normal);
        if (Math.abs(along) < 1e-6) continue;
        const s = dot3(sub3(b.panel.points[0] as Vec3, p), b.normal) / along;
        if (Math.abs(s) < 1e-7 || Math.abs(s) > reach) continue;
        if (!insidePanel(b.panel, add3(p, mul3(a.normal, s)))) continue;
        const weight = 1 - Math.abs(s) / reach;
        if (s > 0) front += weight;
        else back += weight;
      }
      return [Math.min(1, front), Math.min(1, back)];
    };
    const top: number[] = [];
    const bottom: number[] = [];
    const inner: number[] = [];
    const innerTop: number[] = [];
    const innerBottom: number[] = [];
    const ringReach = RING_REACH * size;
    for (const corner of a.panel.points) {
      const toCentre = sub3(a.centre, corner);
      const away = Math.hypot(toCentre.x, toCentre.y, toCentre.z);
      // A corner on a crease lies in its neighbour's plane; look just inside it.
      const [t, b] = cover(add3(corner, mul3(toCentre, away < 1e-9 ? 0 : 1e-3 / away)));
      top.push(t);
      bottom.push(b);
      const k = away < 1e-9 ? 1 : Math.min(1, ringReach / away);
      inner.push(k);
      const [it, ib] = cover(add3(corner, mul3(toCentre, k)));
      innerTop.push(it);
      innerBottom.push(ib);
    }
    result[a.panel.facet.id] = { top, bottom, inner, innerTop, innerBottom };
  }
  return result;
}

const rankCache = new WeakMap<PaperState, Record<number, number>>();

/** How many facets lie under each facet at its centre, in the flat model. */
export function stackRank(state: PaperState): Record<number, number> {
  const cached = rankCache.get(state);
  if (cached) return cached;
  const folded = state.facets.map((f) => ({ f, poly: currentPolygon(f) }));
  const result: Record<number, number> = {};
  for (const { f, poly } of folded) {
    const c = centroid(poly);
    let below = 0;
    for (const other of folded) {
      if (other.f.z < f.z && containsPoint(other.poly, c)) below++;
    }
    result[f.id] = below;
  }
  rankCache.set(state, result);
  return result;
}

/** The hinge along a facet's edge, if the edge lies on one. */
function hingeAlong(
  byFacet: Map<number, Hinge[]>,
  facetId: number,
  a: { x: number; y: number },
  b: { x: number; y: number },
): Hinge | null {
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  for (const h of byFacet.get(facetId) ?? []) {
    const dx = h.b.x - h.a.x;
    const dy = h.b.y - h.a.y;
    const len = Math.hypot(dx, dy);
    if (len < 1e-9) continue;
    const off = Math.abs((dx * (mid.y - h.a.y) - dy * (mid.x - h.a.x)) / len);
    const along = (dx * (mid.x - h.a.x) + dy * (mid.y - h.a.y)) / len;
    if (off < 1e-6 && along > -1e-6 && along < len + 1e-6) return h;
  }
  return null;
}

/**
 * The sheet solved as paper for the given opening (and step in progress):
 * every facet placed in space, plus the edges worth drawing. The 3D card
 * renders this; it is also what the tests look at.
 */
export function solvedScene(state: PaperState, options: SceneOptions): SolvedScene {
  const all = hinges(state);
  const pose = stepPose(state, options.opening, options.animation);
  // Solved from the rigid walk every time: a few milliseconds for a crane,
  // and a flat warm start would stall the crease constraints.
  const anchorId = options.anchorId ?? pose.rootId;
  const panels = solveSheet(state, all, {
    ...pose,
    ...(anchorId !== undefined ? { rootId: anchorId } : {}),
    iterations: 80,
    thickness: options.thickness ?? 0,
  }).panels;
  const animation = options.animation;
  const byFacet = new Map<number, Hinge[]>();
  for (const h of all) {
    for (const id of [h.p, h.q]) {
      const list = byFacet.get(id);
      if (list) list.push(h);
      else byFacet.set(id, [h]);
    }
  }
  const angleOf = pose.angleOf ?? ((h: Hinge): number => h.shown);
  // An edge is drawn only where the paper actually bends or ends; seams
  // between facets lying flat against each other stay invisible.
  const BEND = (2 * Math.PI) / 180;
  const edges: SceneEdge[] = [];
  for (const panel of panels) {
    const poly = panel.facet.poly;
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i] as { x: number; y: number };
      const b = poly[(i + 1) % poly.length] as { x: number; y: number };
      const hinge = hingeAlong(byFacet, panel.facet.id, a, b);
      if (hinge !== null && Math.abs(angleOf(hinge)) < BEND) continue;
      // Each crease is shared by two facets; draw it once, from the lower id.
      if (hinge !== null && hinge.p !== panel.facet.id && hinge.q !== panel.facet.id) continue;
      if (hinge !== null && Math.min(hinge.p, hinge.q) !== panel.facet.id) continue;
      edges.push({ a: panel.points[i] as Vec3, b: panel.points[(i + 1) % poly.length] as Vec3 });
    }
  }
  // While a step plays the sheet may reach further than its end state does.
  const extent = animation
    ? [...foldedPoints(state), ...foldedPoints(animation.previous)]
    : foldedPoints(state);
  const xs = extent.map((p) => p.x);
  const ys = extent.map((p) => p.y);
  const centre: Vec3 = {
    x: (Math.min(...xs) + Math.max(...xs)) / 2,
    y: (Math.min(...ys) + Math.max(...ys)) / 2,
    z: 0,
  };
  let reach = state.size * 0.3;
  for (const panel of panels) {
    for (const p of panel.points) {
      reach = Math.max(reach, Math.hypot(p.x - centre.x, p.y - centre.y, p.z - centre.z));
    }
  }
  return {
    panels,
    edges,
    shade: occlusionShade(panels, state.size),
    rank: stackRank(state),
    settled: !animation,
    anchorId,
    centre,
    reach,
  };
}

/**
 * The orbit as a rotation from model space to view space: rows are the
 * model-space directions that map to screen right, screen up and towards
 * the viewer (a named view's basis first, then yaw, pitch and roll).
 */
export function viewRotation(orbit: Orbit): readonly [Vec3, Vec3, Vec3] {
  const rotate = (p: Vec3): Vec3 => {
    let { x, y, z } = p;
    if (orbit.basis) {
      const [r, u, d] = orbit.basis;
      const bx = r.x * x + r.y * y + r.z * z;
      const by = u.x * x + u.y * y + u.z * z;
      const bz = d.x * x + d.y * y + d.z * z;
      x = bx;
      y = by;
      z = bz;
    }
    const cy = Math.cos(orbit.yaw);
    const sy = Math.sin(orbit.yaw);
    const x1 = x * cy - y * sy;
    const y1 = x * sy + y * cy;
    const cp = Math.cos(orbit.pitch);
    const sp = Math.sin(orbit.pitch);
    // Pitch 0 looks straight down; pitch π/2 looks along the table.
    const x2 = x1;
    const y2 = y1 * cp + z * sp;
    const z2 = -y1 * sp + z * cp;
    const cr = Math.cos(orbit.roll);
    const sr = Math.sin(orbit.roll);
    return { x: x2 * cr - y2 * sr, y: x2 * sr + y2 * cr, z: z2 };
  };
  // The rows of the rotation are the images of the model axes, transposed.
  const ex = rotate({ x: 1, y: 0, z: 0 });
  const ey = rotate({ x: 0, y: 1, z: 0 });
  const ez = rotate({ x: 0, y: 0, z: 1 });
  return [
    { x: ex.x, y: ey.x, z: ez.x },
    { x: ex.y, y: ey.y, z: ez.y },
    { x: ex.z, y: ey.z, z: ez.z },
  ];
}
