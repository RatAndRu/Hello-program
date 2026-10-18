// Движок оцифровки с кэшем по этапам. Меняешь одну настройку — пересчитывается только то,
// что от неё зависит:
//   снимок → фон (метод, очистка) → линии (чувствительность) → толщина → контуры линий
//                                  ↘ цвета (число, пятна, палитра) → контуры цветов
//   скан-картинка (цвет/резкость/тон) и «чистовик» (тени) — свои ветки.
// Цвет линий, скрытые цвета и эффекты (неон, негатив…) вообще не считаются — только отрисовка.
// Два уровня: «draft» — в половинном разрешении (в ~4 раза быстрее, для мгновенного превью)
// и «full» — полное качество для сохранения и приближения.
import * as scan from './scan.js';
import { flatten13, enhance13 } from './scan_v13.js';

const key = (o) => JSON.stringify(o);

class Level {
  constructor(rect, ppm, k) { this.rect = rect; this.ppm = ppm; this.k = k; this.c = new Map(); }
  memo(name, deps, fn) {
    const kk = key(deps), hit = this.c.get(name);
    if (hit && hit.k === kk) return hit.v;
    const v = fn();
    this.c.set(name, { k: kk, v });
    return v;
  }
  has(name, deps) { const hit = this.c.get(name); return !!hit && hit.k === key(deps); }
}

export class ScanEngine {
  constructor() { this.levels = {}; }
  setRect(rect, ppm) {
    this.levels.full = new Level(rect, ppm, 1);
    // черновик — только если снимок крупный (иначе выигрыш мал, а детали теряются)
    this.levels.draft = ppm > 5 ? new Level(scan.half(rect), ppm / 2, 2) : this.levels.full;
  }
  // Есть ли всё нужное в кэше (тогда черновик не нужен)
  cached(req) { try { return this._run(req, true) !== null; } catch { return false; } }
  run(req) { return this._run(req, false); }

  _run(req, probe) {
    const L = this.levels[req.level || 'full'];
    if (!L) throw new Error('нет снимка');
    const miss = () => { if (probe) throw 0; };
    const get = (name, deps, fn) => { if (probe && !L.has(name, deps)) miss(); return L.memo(name, deps, fn); };
    const out = { level: req.level, k: L.k, ppm: L.ppm };
    const fdeps = { m: req.method || 'clean', c: req.clean };
    const flat = () => get('flat', fdeps, () => (req.method === 'v13' ? flatten13(L.rect, L.ppm, req.clean) : scan.flatten(L.rect, L.ppm, req.clean)));
    if (req.flat) out.flat = flat();
    if (req.enh) {
      const e = req.enh;
      out.enh = get('enh', { fdeps, e }, () => {
        const f = flat();
        if (req.method === 'v13' && (e.mode === 'color' || e.mode === 'gray' || e.mode === 'bw') && e.tone === 'none') return enhance13(f, { mode: e.mode, sharpen: e.sharpen, clean: req.clean });
        return scan.enhance(f, { mode: e.mode, sharpen: e.sharpen, clean: req.clean, tone: e.tone, ppm: L.ppm, lpi: e.lpi });
      });
    }
    if (req.vec) {
      const v = req.vec, ld = { fdeps, l: v.lineLevel };
      const lines = () => get('segL', ld, () => scan.segLines(flat(), L.ppm, v.lineLevel));
      const td = { ld, t: v.thick };
      const lmask = () => get('thin', td, () => {
        const S = lines(), m = new Uint8Array(S.w * S.h);
        for (let i = 0; i < m.length; i++) if (S.kind[i] === 1) m[i] = 1;
        return scan.scaleLines(m, S.w, S.h, v.thick);
      });
      out.lines = get('vecL', { td, s: v.smooth, g: v.gap }, () => {
        const S = lines(), r = scan.vecLines(lmask(), S.w, S.h, L.ppm, { smooth: v.smooth, gap: v.gap });
        r.auto = '#' + S.lineColor.map(x => x.toString(16).padStart(2, '0')).join('');
        return r;
      });
      if (v.colors) {
        const c = v.colors, cd = { ld, n: c.n, ms: c.minSpot, fx: c.fixed };
        const seg = () => get('segC', cd, () => {
          const S = scan.segColors(flat(), L.ppm, lines(), { colors: c.n, minSpot: c.minSpot, fixed: c.fixed });
          if (c.names) S.names = c.names;
          return S;
        });
        out.colors = get('vecC', { cd, s: v.smooth, g: v.gap, gr: c.grad, nm: c.names }, () => {
          const S = seg(); if (c.names) S.names = c.names;
          return scan.vecColors(S, L.ppm, { smooth: v.smooth, gap: v.gap, gradients: c.grad, img: flat() });
        });
      }
      if (v.fill) {
        out.fills = get('fill', { td, f: v.fill, g: v.gap, s: v.smooth }, () => {
          const S = lines();
          return scan.regionFill(lmask(), S.w, S.h, L.ppm, { palette: v.fill.palette, seed: v.fill.seed, gap: v.gap, smooth: v.smooth });
        });
      }
      if (v.wash) {
        out.wash = get('wash', { ld, w: v.wash }, () => {
          const S = lines(), m = new Uint8Array(S.w * S.h);
          for (let i = 0; i < m.length; i++) if (S.kind[i] === 1) m[i] = 1;
          return scan.washLayer(flat(), m, L.ppm, v.wash);
        });
      }
    }
    return out;
  }
}

// Очередь запросов (общая для фонового потока и запасного режима без него): из одинаковых
// по уровню берём последний, черновики — раньше полного качества.
export function makePump(eng, post) {
  let queue = [], busy = false;

  function pump() {
    if (!queue.length) { busy = false; return; }
    // команда снимка сбрасывает всё, что было до неё
    const ri = queue.map(m => m.cmd).lastIndexOf('rect');
    if (ri >= 0) {
      const m = queue[ri];
      for (const q of queue.slice(0, ri)) if (q.cmd === 'run') post({ id: q.id, stale: true });
      queue = queue.slice(ri + 1);
      try { eng.setRect(m.rect, m.ppm); post({ id: m.id, ok: true }); } catch (err) { post({ id: m.id, error: String(err && err.message || err) }); }
      setTimeout(pump, 0); return;
    }
    // проверки кэша — мгновенные, отвечаем сразу и не считаем их «новее» настоящих запросов
    const pi = queue.findIndex(m => m.probe);
    if (pi >= 0) { const m = queue.splice(pi, 1)[0]; let c = false; try { c = eng.cached(m.req); } catch { c = false; } post({ id: m.id, cached: c }); setTimeout(pump, 0); return; }
    // сначала черновики, потом полное качество; из одинаковых — последний
    const pick = (lvl) => { let idx = -1; queue.forEach((m, i) => { if (m.cmd === 'run' && (m.req.level || 'full') === lvl) idx = i; }); return idx; };
    let i = pick('draft'); if (i < 0) i = pick('full');
    if (i < 0) { const m = queue.shift(); handleMisc(m); setTimeout(pump, 0); return; }
    const m = queue[i], lvl = m.req.level || 'full';
    queue = queue.filter((q, j) => { if (j === i) return false; if (q.cmd === 'run' && (q.req.level || 'full') === lvl && j < i) { post({ id: q.id, stale: true }); return false; } return true; });
    try { post({ id: m.id, res: eng.run(m.req) }); } catch (err) { post({ id: m.id, error: String(err && err.message || err) }); }
    setTimeout(pump, 0);
  }
  function handleMisc(m) { if (m && m.id) post({ id: m.id, ok: true }); }

  return (msg) => { queue.push(msg); if (!busy) { busy = true; setTimeout(pump, 0); } };
}
