/**
 * Множитель плотного normal/depth/edge буфера для линейных стилей.
 *
 * Beauty-проход остаётся в исходном разрешении. Здесь рассчитывается только
 * геометрический контур: на DPR=1 нужны четыре subpixel-образца на пиксель,
 * на DPR=2 их даёт сам output buffer. Модуль чистый, чтобы границы и лимит
 * памяти проверялись обычным Node-тестом без WebGL.
 */
export function edgeCoverageScale(width, height, pixelRatio = 1, maxPixels = 8000000) {
  const w = Math.max(Number(width) || 1, 1);
  const h = Math.max(Number(height) || 1, 1);
  const ratio = Number.isFinite(Number(pixelRatio)) ? Number(pixelRatio) : 1;
  const safeRatio = Math.max(ratio, 0.5);
  const desired = Math.max(1, Math.min(2, 2 / safeRatio));
  const budget = Math.max(Number(maxPixels) || 8000000, 1);
  const cap = Math.sqrt(budget / Math.max(w * h, 1));
  return Math.max(1, Math.min(desired, cap));
}
