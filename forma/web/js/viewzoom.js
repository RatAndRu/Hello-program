/**
 * Масштаб после прокрутки колеса.
 *
 * Прокрутка «от себя» (deltaY < 0) приближает, «на себя» — отдаляет, как в
 * любом 3D-редакторе. Шаг зависит от силы прокрутки, но ограничен, чтобы
 * трекпад не улетал в упор одним движением.
 */
export function wheelZoom(zoom, deltaY, deltaMode = 0) {
  const unit = deltaMode === 1 ? 16 : (deltaMode === 2 ? 400 : 1);
  const delta = Math.max(-240, Math.min(240, Number(deltaY || 0) * unit));
  const next = Number(zoom || 1) * Math.exp(-delta * 0.0016);
  return Math.max(0.45, Math.min(3.2, next));
}
