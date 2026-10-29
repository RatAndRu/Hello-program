/**
 * Ближняя и дальняя плоскости для перспективной камеры вокруг AABB модели.
 *
 * Модуль чистый (без Three.js), чтобы граничные случаи проверялись в Node.
 * Единицы — те же, что у сцены Forma (обычно мм). Сфера вокруг AABB даёт
 * консервативный запас: движение/панорамирование не обрезает углы модели.
 */
export function cameraClipRange(position, bbox) {
  if (!position || !bbox?.min || !bbox?.max) return null;
  const dx = Number(bbox.max.x) - Number(bbox.min.x);
  const dy = Number(bbox.max.y) - Number(bbox.min.y);
  const dz = Number(bbox.max.z) - Number(bbox.min.z);
  if (![dx, dy, dz].every(Number.isFinite)) return null;
  const radius = Math.max(Math.hypot(dx, dy, dz) * 0.5, 1e-6);
  const center = {
    x: (Number(bbox.min.x) + Number(bbox.max.x)) * 0.5,
    y: (Number(bbox.min.y) + Number(bbox.max.y)) * 0.5,
    z: (Number(bbox.min.z) + Number(bbox.max.z)) * 0.5,
  };
  const distance = Math.hypot(
    Number(position.x) - center.x,
    Number(position.y) - center.y,
    Number(position.z) - center.z,
  );
  if (!Number.isFinite(distance)) return null;

  // 25% запаса за описанной сферой. На дальнем плане near становится близким
  // к модели, поэтому 5-мм стенка не тоньше кванта 24-битной глубины.
  const padding = radius * 1.25 + 1e-4;
  const nearFloor = Math.max(0.001, radius * 1e-4);
  const near = Math.max(nearFloor, distance - padding);
  const far = Math.max(distance + padding, near + radius * 0.01);
  return { near, far, radius, distance };
}
