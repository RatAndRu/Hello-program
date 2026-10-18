// Анимации объёмных фигур: манекен, голова, глаз, причёска, рука.
// Без ИИ — каждая анимация это функция «фаза 0…1 → параметры фигуры». Кадр пишется прямо
// в настройки фигуры, поэтому пауза = готовая поза: её можно дальше править пальцем,
// сохранять, отражать. «Кадр» (фаза) выбирается и ползунком — можно поймать точный момент.
import { poseFrom3D, L8, BJ, bodyRootShift, HAND_POSES } from './manga.js';

const D = Math.PI / 180, TAU = Math.PI * 2;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const sm = (t) => { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); };
const clone = (o) => JSON.parse(JSON.stringify(o));
// плавный «туда-обратно» с паузами: 0 → 1 (вверх), держим, 1 → 0
const pingPong = (p, up = 0.35, hold = 0.15) => (p < up ? sm(p / up) : p < up + hold ? 1 : p < 2 * up + hold ? 1 - sm((p - up - hold) / up) : 0);
// моргание: короткий импульс в момент t0 (длительность w в долях фазы)
const pulse = (p, t0, w) => { const x = (p - t0) / w; return x > 0 && x < 1 ? Math.sin(Math.PI * x) : 0; };
// «шум» без случайности — сумма синусов
const wob = (p, a, b, c) => Math.sin(TAU * p * a + c) * 0.6 + Math.sin(TAU * p * b + c * 1.7) * 0.4;

// ---------------------------------------------------------------- скелет манекена
const rotX = (v, a) => { const c = Math.cos(a), s = Math.sin(a); return [v[0], v[1] * c - v[2] * s, v[1] * s + v[2] * c]; };
const rotY = (v, a) => { const c = Math.cos(a), s = Math.sin(a); return [v[0] * c + v[2] * s, v[1], -v[0] * s + v[2] * c]; };
const rotZ = (v, a) => { const c = Math.cos(a), s = Math.sin(a); return [v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2]]; };
const n3 = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
const rodr = (v, k, a) => {
  const c = Math.cos(a), s = Math.sin(a), d = v[0] * k[0] + v[1] * k[1] + v[2] * k[2];
  const cr = [k[1] * v[2] - k[2] * v[1], k[2] * v[0] - k[0] * v[2], k[0] * v[1] - k[1] * v[0]];
  return [v[0] * c + cr[0] * s + k[0] * d * (1 - c), v[1] * c + cr[1] * s + k[1] * d * (1 - c), v[2] * c + cr[2] * s + k[2] * d * (1 - c)];
};
const Lb = (n) => L8[BJ.indexOf(n)];
const ARM0 = { fl: 0, abd: 8, el: 8, tw: 0, wr: 0 }, LEG0 = { fl: 0, abd: 3, kn: 0, an: 0, tw: 0 };
// Скелет из углов суставов (градусы). Тело: x — вправо от зрителя (правая рука фигуры — x < 0),
// y — вниз, z — к зрителю (фигура смотрит на +z).
// lean — наклон корпуса вперёд, lean2 — грудь ещё вперёд, side — вбок, twist — поворот плеч,
// ptw — поворот таза, neck — голова вперёд/назад; руки: fl — вперёд, abd — в сторону, el — локоть,
// tw — плечо внутрь, wr — кисть; ноги: fl — бедро вперёд, abd — в сторону, kn — колено, an — носок.
export function skel(o) {
  const P = {}, add = (p, d, l) => [p[0] + d[0] * l, p[1] + d[1] * l, p[2] + d[2] * l];
  const lean = (o.lean || 0) * D, l2 = lean + (o.lean2 || 0) * D, sb = (o.side || 0) * D, tw = (o.twist || 0) * D, pt = (o.ptw || 0) * D;
  const U = (v) => rotY(rotZ(rotX(v, -lean), sb), tw), U2 = (v) => rotY(rotZ(rotX(v, -l2), sb * 1.3), tw * 1.15);
  P.pelvis = [0, 0, 0];
  P.chest = add(P.pelvis, U([0, -1, 0]), Lb('chest'));
  P.neck = add(P.chest, U2([0, -1, 0]), Lb('neck'));
  P.head = add(P.neck, rotY(rotZ(rotX([0, -1, 0], -(l2 + (o.neck || 0) * D)), sb * 1.3 + (o.headSide || 0) * D), tw * 1.15), Lb('head'));
  let foreR = null, hgR = null;
  for (const [s, sd] of [[-1, 'R'], [1, 'L']]) {
    const a = { ...ARM0, ...(o['arm' + sd] || {}) }, ph = a.abd * D * (s < 0 ? 1 : -1);
    P['sh' + sd] = add(P.neck, U2(n3([0.95 * s, 0.18 - (a.shrug || 0), 0])), Lb('sh' + sd));
    let up = rotX(rotZ([0, 1, 0], ph), a.fl * D), hg = rotX(rotZ([1, 0, 0], ph), a.fl * D);
    hg = rodr(hg, up, a.tw * D * (s < 0 ? 1 : -1));
    up = U2(up); hg = U2(hg);
    P['el' + sd] = add(P['sh' + sd], up, Lb('el' + sd));
    const fore = rodr(up, hg, a.el * D);
    P['wr' + sd] = add(P['el' + sd], fore, Lb('wr' + sd));
    P['ha' + sd] = add(P['wr' + sd], rodr(fore, hg, a.wr * D), Lb('ha' + sd));
    if (sd === 'R') { foreR = fore; hgR = hg; }
  }
  for (const [s, sd] of [[-1, 'R'], [1, 'L']]) {
    const b = { ...LEG0, ...(o['leg' + sd] || {}) }, ph = b.abd * D * (s < 0 ? 1 : -1);
    P['hip' + sd] = add(P.pelvis, rotY(n3([0.48 * s, 0.1, 0]), pt), Lb('hip' + sd));
    let d = rotX(rotZ([0, 1, 0], ph), b.fl * D), hg = rotX(rotZ([1, 0, 0], ph), b.fl * D);
    hg = rodr(hg, d, b.tw * D * (s < 0 ? -1 : 1));
    d = rotY(d, pt); hg = rotY(hg, pt);
    P['kn' + sd] = add(P['hip' + sd], d, Lb('kn' + sd));
    const shin = rodr(d, hg, -b.kn * D);
    P['an' + sd] = add(P['kn' + sd], shin, Lb('an' + sd));
    P['to' + sd] = add(P['an' + sd], rodr(shin, hg, (75 - b.an) * D), Lb('to' + sd));
  }
  const pose = poseFrom3D(P);
  if (o.prop) { pose.prop = o.prop; pose.propDir = n3(rodr(foreR, hgR, (o.propCock ?? 70) * D)); }
  return { pose, P };
}
const groundOf = (P) => Math.max(P.anR[1], P.anL[1], P.toR[1] - 0.05, P.toL[1] - 0.05);
const STAND = skel({}).P, G0 = groundOf(STAND), Z0 = (STAND.anR[2] + STAND.anL[2]) / 2;
// кадр: параметры скелета → поза + сдвиг корня (стопы на земле, при желании — на месте)
function bodyFrame(o) {
  const { pose, P } = skel(o);
  const root = [0, 0, 0];
  if (o.ground !== false) root[1] = G0 - groundOf(P);
  if (o.lockZ) root[2] = Z0 - (P.anR[2] + P.anL[2]) / 2;
  root[1] -= o.lift || 0;
  return { props: { pose }, root };
}
const mirrorArm = (a) => a; // руки задаются отдельно для каждой стороны

const BODY = {
  walk: { label: 'Идёт', dur: 1.15, yaw: 70, f: (p) => {
    const w = TAU * p, s = Math.sin(w);
    const leg = (q) => ({ fl: 24 * Math.sin(q), kn: 5 + 60 * Math.pow(Math.max(0, Math.cos(q + 0.5)), 1.5), an: -14 * Math.sin(q), abd: 3 });
    const arm = (q) => ({ fl: -20 * Math.sin(q), el: 14 + 16 * Math.max(0, -Math.sin(q)), abd: 7, tw: 8 });
    return bodyFrame({ lean: 4, twist: -6 * s, ptw: 6 * s, legR: leg(w), legL: leg(w + Math.PI), armR: arm(w), armL: arm(w + Math.PI) });
  } },
  run: { label: 'Бежит', dur: 0.72, yaw: 70, f: (p) => {
    const w = TAU * p, s = Math.sin(w);
    const leg = (q) => ({ fl: 14 + 44 * Math.sin(q), kn: 22 + 92 * Math.pow(Math.max(0, Math.cos(q + 0.6)), 1.3), an: 8 - 14 * Math.sin(q), abd: 2 });
    const arm = (q) => ({ fl: -42 * Math.sin(q), el: 88 + 8 * Math.sin(q), abd: 10, tw: 22 });
    return bodyFrame({ lean: 13, twist: -11 * s, ptw: 8 * s, neck: -6, legR: leg(w), legL: leg(w + Math.PI), armR: arm(w), armL: arm(w + Math.PI), lift: 0.22 * Math.max(0, Math.sin(2 * w - 0.9)) });
  } },
  sit: { label: 'Садится и встаёт', dur: 3.4, yaw: 65, f: (p) => {
    const s = pingPong(p, 0.32, 0.22), mv = Math.sin(Math.PI * s);
    const leg = { fl: 88 * s, kn: 92 * s, an: -6 * s, abd: 3 + 3 * s };
    const arm = { fl: 18 * mv + 22 * s, el: 10 + 45 * s, abd: 8, tw: 15 * s };
    return bodyFrame({ lean: 4 + 34 * mv + 4 * s, neck: -10 * mv, legR: leg, legL: leg, armR: arm, armL: arm, lockZ: true });
  } },
  squat: { label: 'Приседает', dur: 2.4, yaw: 50, f: (p) => {
    const s = pingPong(p, 0.32, 0.12);
    const leg = { fl: 112 * s, kn: 138 * s, an: -26 * s, abd: 3 + 10 * s };
    const arm = { fl: 88 * s, el: 8, abd: 8, tw: 5 };
    return bodyFrame({ lean: 40 * s, neck: -25 * s, legR: leg, legL: leg, armR: arm, armL: arm, lockZ: true });
  } },
  jump: { label: 'Прыгает', dur: 1.8, yaw: 55, f: (p) => {
    // присед → толчок → полёт → приземление → выпрямление
    let c = 0, e = 0, fly = 0, tuck = 0;
    if (p < 0.25) c = sm(p / 0.25);
    else if (p < 0.33) { const t = (p - 0.25) / 0.08; c = 1 - sm(t); e = sm(t); }
    else if (p < 0.63) { const t = (p - 0.33) / 0.3; e = 1 - sm(t * 1.5); fly = 4 * t * (1 - t); tuck = Math.sin(Math.PI * t); }
    else if (p < 0.73) c = sm((p - 0.63) / 0.1) * 0.85;
    else c = 0.85 * (1 - sm((p - 0.73) / 0.2));
    const leg = { fl: 62 * c + 35 * tuck, kn: 95 * c + 60 * tuck, an: -20 * c + 40 * e + 20 * tuck, abd: 4 };
    const arm = { fl: -45 * c + 170 * e + 120 * fly * (1 - e) * 0.6, el: 15 + 10 * c, abd: 12 + 10 * e, tw: 0 };
    return bodyFrame({ lean: 28 * c - 4 * e, neck: -15 * c, legR: leg, legL: leg, armR: arm, armL: arm, lift: 1.4 * fly, lockZ: true });
  } },
  wave: { label: 'Машет рукой', dur: 1.6, yaw: 15, f: (p) => {
    const raise = sm(p / 0.15) * (1 - sm((p - 0.85) / 0.15)), w = Math.sin(TAU * 3 * p);
    return bodyFrame({ side: -3 * raise, armR: { fl: 15 * raise, abd: 8 + 100 * raise, el: 8 + 95 * raise, tw: -90 * raise + 28 * w * raise }, armL: { ...ARM0 }, legR: { abd: 4 }, legL: { abd: 4 } });
  } },
  punch: { label: 'Бьёт кулаками', dur: 1.3, yaw: 40, f: (p) => {
    const jR = Math.pow(Math.max(0, Math.sin(TAU * p)), 0.7), jL = Math.pow(Math.max(0, -Math.sin(TAU * p)), 0.7);
    const guard = { fl: 48, abd: 18, el: 125, tw: 45 }, hit = { fl: 88, abd: 4, el: 4, tw: 8 };
    const mix = (k) => ({ fl: lerp(guard.fl, hit.fl, k), abd: lerp(guard.abd, hit.abd, k), el: lerp(guard.el, hit.el, k), tw: lerp(guard.tw, hit.tw, k) });
    return bodyFrame({ lean: 10, twist: 22 * (jL - jR), ptw: 8 * (jL - jR), armR: mix(jR), armL: mix(jL), legR: { fl: -14, kn: 14, abd: 8, an: 5 }, legL: { fl: 18, kn: 16, abd: 8 } });
  } },
  sword: { label: 'Удар мечом', dur: 1.6, yaw: 50, f: (p) => {
    // замах над головой → удар вниз-вперёд → возврат
    const up = p < 0.45 ? sm(p / 0.45) : p < 0.6 ? 1 - sm((p - 0.45) / 0.15) : 0, back = p > 0.75 ? sm((p - 0.75) / 0.25) : 0;
    const k = clamp(up - back * 0, 0, 1), down = p >= 0.45 && p < 0.75 ? sm((p - 0.45) / 0.15) : p >= 0.75 ? 1 - back : 0;
    const arm = (sd) => ({ fl: lerp(lerp(40, 165, k), 72, down * (1 - k)), abd: 14, el: lerp(lerp(55, 70, k), 12, down * (1 - k)), tw: sd ? 48 : 52 });
    return bodyFrame({ lean: 6 + 12 * down * (1 - k) - 6 * k, armR: arm(0), armL: arm(1), legR: { fl: 18 + 6 * down, kn: 16 + 10 * down, abd: 5 }, legL: { fl: -18, kn: 10, abd: 5, an: 6 }, prop: 'sword', propCock: lerp(lerp(80, 45, k), 70, down * (1 - k)) });
  } },
  bow: { label: 'Кланяется', dur: 2.6, yaw: 70, f: (p) => {
    const s = pingPong(p, 0.3, 0.2);
    return bodyFrame({ lean: 55 * s, neck: 10 * s, armR: { fl: -8 * s, abd: 4, el: 6 }, armL: { fl: -8 * s, abd: 4, el: 6 }, legR: { fl: -6 * s }, legL: { fl: -6 * s }, lockZ: true });
  } },
  stretch: { label: 'Потягивается', dur: 3.0, yaw: 20, f: (p) => {
    const s = pingPong(p, 0.35, 0.2);
    const arm = { fl: 178 * s, abd: 8 + 6 * s, el: 8 - 6 * s, tw: 0 };
    return bodyFrame({ lean: -10 * s, neck: -18 * s, armR: arm, armL: arm, legR: { an: 30 * s }, legL: { an: 30 * s }, lift: 0 });
  } },
};
void mirrorArm;

// ---------------------------------------------------------------- голова
const HEAD = {
  talk: { label: 'Говорит', dur: 2.6, f: (p, b) => {
    const syl = Math.max(0, Math.sin(TAU * 7 * p)) * (0.55 + 0.45 * Math.sin(TAU * 3.1 * p + 1)), o = Math.max(0, Math.sin(TAU * 2.3 * p + 0.5));
    return { props: { mouthOpen: clamp(syl * (p < 0.92 ? 1 : 0), 0, 1), mouthWk: 1 - 0.35 * o * syl, blink: pulse(p, 0.62, 0.06), browH: (+b.browH || 0.12) + 0.04 * Math.max(0, wob(p, 1.3, 2.1, 0.3)), pitch: (+b.pitch || 0) + 3 * wob(p, 1.1, 1.9, 0) } };
  } },
  blink: { label: 'Моргает', dur: 2.4, f: (p) => ({ props: { blink: pulse(p, 0.1, 0.07) + pulse(p, 0.62, 0.07) * (p > 0.5 ? 1 : 0) } }) },
  frown: { label: 'Морщится', dur: 2.6, f: (p, b) => {
    const k = pingPong(p, 0.3, 0.3);
    return { props: { browTilt: lerp(+b.browTilt || 0, 0.95, k), browH: lerp(+b.browH || 0.12, 0.02, k), blink: 0.5 * k, wrinkle: k, mouthStyle: k > 0.35 ? 'line' : b.mouthStyle, mouthWk: 1 - 0.3 * k, mouthOpen: 0 } };
  } },
  surprise: { label: 'Удивляется', dur: 2.4, f: (p, b) => {
    const k = pingPong(p, 0.18, 0.45);
    return { props: { browH: lerp(+b.browH || 0.12, 0.27, k), browTilt: lerp(+b.browTilt || 0, -0.45, k), eyeH: (+b.eyeH || 0.78) * (1 + 0.28 * k), iris: (+b.iris || 1.1) * (1 - 0.18 * k), mouthOpen: 0.75 * k, mouthWk: 1 - 0.45 * k, pitch: (+b.pitch || 0) + 6 * k } };
  } },
  laugh: { label: 'Смеётся', dur: 2.2, f: (p, b) => {
    const k = pingPong(p, 0.15, 0.6), h = Math.abs(Math.sin(TAU * 5 * p));
    return { props: { blink: 0.92 * k, mouthStyle: k > 0.2 ? 'smile' : b.mouthStyle, mouthOpen: k * (0.45 + 0.4 * h), browH: lerp(+b.browH || 0.12, 0.18, k), browTilt: lerp(+b.browTilt || 0, -0.3, k), pitch: (+b.pitch || 0) + k * (6 + 4 * h), roll: (+b.roll || 0) + 5 * k } };
  } },
  nod: { label: 'Кивает «да»', dur: 1.4, f: (p, b) => ({ props: { pitch: (+b.pitch || 0) - 16 * Math.max(0, Math.sin(TAU * 2 * p)) } }) },
  shake: { label: 'Мотает «нет»', dur: 1.4, f: (p, b) => ({ props: { yaw: (+b.yaw || 0) + 28 * Math.sin(TAU * 2 * p) * sm(p / 0.1) * (1 - sm((p - 0.9) / 0.1)) } }) },
  look: { label: 'Оглядывается', dur: 4.0, f: (p, b) => {
    // глаза двигаются первыми, голова догоняет; на поворотах — моргание
    const tgt = (t) => (t < 0.25 ? 0 : t < 0.5 ? -1 : t < 0.75 ? 1 : 0), eyes = (t) => { const a = tgt(t), b0 = tgt(t - 0.04); return lerp(b0, a, sm(((t * 4) % 1) / 0.08)); };
    const hx = (t) => { let s = 0; for (let i = 0; i < 6; i++) s += tgt(((t - 0.02 * i) % 1 + 1) % 1); return s / 6; };
    const head = hx(p), e = eyes(p);
    return { props: { yaw: (+b.yaw || 0) + 38 * head, gazeX: clamp(e - head * 0.7, -1, 1) * 0.8, blink: pulse(p, 0.25, 0.05) + pulse(p, 0.75, 0.05) } };
  } },
  wind: { label: 'Ветер в волосах', dur: 3.0, need: (b) => b.hairStyle && b.hairStyle !== 'none', f: (p) => ({ props: { windAmt: 0.55 + 0.35 * wob(p, 1, 2, 0.4), windT: p, windDir: 0 } }) },
};

// ---------------------------------------------------------------- глаз
const EYE = {
  blink: { label: 'Моргает', dur: 2.2, f: (p, b) => ({ props: { open: (+b.open || 1) * (1 - pulse(p, 0.15, 0.09)) } }) },
  look: { label: 'Переводит взгляд', dur: 4.0, f: (p, b) => {
    const pts = [[0, 0], [-0.75, 0.15], [-0.75, 0.15], [0.7, -0.35], [0.7, -0.35], [0.2, 0.55], [0, 0]], n = pts.length - 1, t = p * n, i = Math.min(n - 1, Math.floor(t)), f = sm((t - i) / 0.18);
    return { props: { gazeX: lerp(pts[i][0], pts[i + 1][0], f), gazeY: lerp(pts[i][1], pts[i + 1][1], f), open: (+b.open || 1) * (1 - pulse(p, 0.48, 0.05)) } };
  } },
  pupil: { label: 'Зрачок сужается и расширяется', dur: 3.0, f: (p) => ({ props: { pupil: 0.42 + 0.3 * Math.sin(TAU * p) } }) },
  squint: { label: 'Щурится', dur: 2.6, f: (p, b) => { const k = pingPong(p, 0.3, 0.3); return { props: { open: (+b.open || 1) * (1 - 0.55 * k), browTilt: lerp(+b.browTilt || 0, 0.8, k), browH: lerp(+b.browH || 12, 2, k), pupil: 0.42 - 0.08 * k } }; } },
  surprise: { label: 'Удивляется', dur: 2.4, f: (p, b) => { const k = pingPong(p, 0.15, 0.5); return { props: { open: (+b.open || 1) * (1 + 0.25 * k), pupil: 0.42 - 0.18 * k, rho: (+b.rho || 27) * (1 - 0.15 * k), browH: lerp(+b.browH || 12, 30, k) } }; } },
  tear: { label: 'Грустит', dur: 3.2, f: (p, b) => { const k = pingPong(p, 0.3, 0.35); return { props: { open: (+b.open || 1) * (1 - 0.3 * k), gazeY: -0.5 * k, browTilt: lerp(+b.browTilt || 0, -0.9, k), pupil: 0.42 + 0.08 * k } }; } },
};

// ---------------------------------------------------------------- причёска
const HAIR = {
  breeze: { label: 'Лёгкий ветер', dur: 3.0, f: (p) => ({ props: { windAmt: 0.35 + 0.15 * wob(p, 1, 2, 0.2), windT: p } }) },
  gust: { label: 'Сильный ветер', dur: 2.2, f: (p) => ({ props: { windAmt: 0.85 + 0.15 * wob(p, 1, 3, 0.7), windT: p } }) },
  turn: { label: 'Поворачивает голову', dur: 3.2, f: (p, b) => { const y = 35 * Math.sin(TAU * p); return { props: { yaw: (+b.yaw || 0) + y, windAmt: 0.25 * Math.abs(Math.cos(TAU * p)), windDir: Math.cos(TAU * p) > 0 ? 180 : 0, windT: p } }; } },
};

// ---------------------------------------------------------------- рука
const curlMix = (a, b, k) => a.map((x, i) => lerp(x, b[i], k));
const HAND = {
  fist: { label: 'Сжимает кулак', dur: 2.0, f: (p) => { const k = pingPong(p, 0.3, 0.2); return { props: { curl: curlMix(HAND_POSES.open, HAND_POSES.fist, k), tAbd: lerp(50, -20, k), tOpp: lerp(8, 52, k), tF1: lerp(0, 24, k), tF2: lerp(-5, 34, k) } }; } },
  count: { label: 'Считает 1…5', dur: 5.0, f: (p) => {
    const n = p * 5.5, up = (i) => sm(n - i), c = [1, 2, 3, 4].map(i => 1.5 * (1 - up(i - 0.5)));
    const th = up(4.5);
    return { props: { curl: [0, c[0], c[1], c[2], c[3]], tAbd: lerp(-15, 55, th), tOpp: lerp(55, 10, th), tF1: lerp(30, 0, th), tF2: lerp(35, 0, th), spread: 0.3 } };
  } },
  wave: { label: 'Машет', dur: 1.4, f: (p, b) => ({ props: { curl: HAND_POSES.open.slice(), tAbd: 45, tOpp: 8, tF1: 0, tF2: 0, rot: (+b.rot || 0) + 22 * Math.sin(TAU * 2 * p) } }) },
  beckon: { label: 'Подзывает пальцем', dur: 1.2, f: (p) => { const k = 0.5 - 0.5 * Math.cos(TAU * p); return { props: { curl: [0, 0.15 + 1.25 * k, 1.5, 1.5, 1.5], tAbd: 15, tOpp: 45, tF1: 20, tF2: 25 } }; } },
  tap: { label: 'Барабанит пальцами', dur: 1.0, f: (p) => ({ props: { curl: [0, 0.35 + 0.35 * Math.max(0, Math.sin(TAU * (p - 0.0))), 0.4 + 0.35 * Math.max(0, Math.sin(TAU * (p - 0.12))), 0.45 + 0.35 * Math.max(0, Math.sin(TAU * (p - 0.24))), 0.5 + 0.35 * Math.max(0, Math.sin(TAU * (p - 0.36)))], tAbd: 40, tOpp: 15, tF1: 6, tF2: 8 } }) },
};

export const ANIMS = { body: BODY, head: HEAD, eye: EYE, hair: HAIR, hand: HAND };
export const animList = (type, base) => Object.entries(ANIMS[type] || {}).filter(([, a]) => !a.need || a.need(base || {})).map(([k, a]) => [k, a.label]);

// ---------------------------------------------------------------- проигрывание
// st: { name, phase, playing, speed, base: { props, pts }, off, last }
export function startAnim(g, name, prev) {
  const st = prev || { phase: 0, speed: 1, base: { props: clone(g.props), pts: clone(g.pts) }, off: { x: 0, y: 0 } };
  const A = ANIMS[g.type] && ANIMS[g.type][name];
  if (!A) return null;
  if (!prev || st.name !== name) {
    st.name = name; st.phase = 0;
    // в профиль ходьба и бег читаются лучше — если фигура стоит анфас, слегка поворачиваем
    if (g.type === 'body' && A.yaw !== undefined && !(+st.base.props.yaw) && !(+st.base.props.pitch)) st.base.props.yaw = A.yaw;
  }
  st.playing = true;
  return st;
}
// если пользователь поправил фигуру на паузе — эта поза становится новой основой
export function rebaseIfEdited(g, st) {
  if (!st || st.last === undefined || JSON.stringify([g.props, g.pts]) === st.last) return;
  st.base.props = clone(g.props);
  st.base.pts = g.pts.map((q, i) => (i === 0 ? { x: q.x - st.off.x, y: q.y - st.off.y } : { ...q }));
}
export function applyAnimFrame(g, st, phase) {
  const A = st && ANIMS[g.type] && ANIMS[g.type][st.name];
  if (!A) return;
  st.phase = phase;
  const r = A.f(phase, st.base.props, g) || {};
  const props = clone(st.base.props);
  Object.assign(props, r.props || {});
  g.props = props;
  if (g.type === 'body') {
    const d = r.root ? bodyRootShift(g, r.root) : { x: 0, y: 0 };
    g.pts = st.base.pts.map((q, i) => (i === 0 ? { x: q.x + d.x, y: q.y + d.y } : { ...q }));
    st.off = d;
  }
  st.last = JSON.stringify([g.props, g.pts]);
}
export function stepAnim(g, st, dt) {
  const A = ANIMS[g.type] && ANIMS[g.type][st.name];
  if (!A || !st.playing) return;
  applyAnimFrame(g, st, ((st.phase + dt * st.speed / A.dur) % 1 + 1) % 1);
}
export function restoreBase(g, st) { g.props = clone(st.base.props); g.pts = clone(st.base.pts); }
