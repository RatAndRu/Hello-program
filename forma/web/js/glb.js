/**
 * Загрузка самодостаточного GLB без потоковой обёртки THREE.FileLoader.
 *
 * FileLoader читает response.body через второй ReadableStream. В Chromium
 * такой запрос может завершиться сетевым ERR_ABORTED уже после того, как все
 * байты получены и модель распарсена. Явный fetch даёт простую и проверяемую
 * границу ошибки: HTTP/чтение отдельно, разбор GLB отдельно.
 */
export async function loadGlb(loader, url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`GLB: HTTP ${response.status} ${response.statusText}`.trim());
  }
  const data = await response.arrayBuffer();
  if (!data.byteLength) throw new Error('GLB: сервер вернул пустой файл');
  const clean = String(url).split('?')[0];
  const path = clean.slice(0, clean.lastIndexOf('/') + 1);
  return new Promise((resolve, reject) => {
    try {
      loader.parse(data, path, resolve, reject);
    } catch (error) {
      reject(error);
    }
  });
}
