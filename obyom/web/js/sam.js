// v2.8: MobileSAM (Apache-2.0) — опциональное уточнение маски нейросетью.
// Модель загружается лениво (пользователь включил переключатель «AI-маска (beta)» и обрабатывает первый скан).
// Сама модель (MobileSAM encoder.onnx ~35 MB + decoder.onnx ~4 MB) НЕ встроена в APK и будет скачана
// с релиза GitHub при первом включении. Если загрузка не удалась — работает обычная маска, без падений.
//
// API:
//   samReady() — true, если модель загружена и готова
//   await ensureSam(logFn) — попробовать загрузить ONNX runtime и веса; возвращает true/false
//   await refineMask(rgba, w, h, bbox, promptPoints) — возвращает Uint8Array маски предмета (0=фон, 1=предмет, 1=неизвестно)
//                                   или null, если SAM ещё не готов / не сработал
let rt = null, enc = null, dec = null, loading = null, ready = false;
export function samReady() { return ready; }
export async function ensureSam(log = () => {}) {
  if (ready) return true;
  if (loading) return loading;
  loading = (async () => {
    try {
      // ONNX Runtime Web — WASM backend, работает в WebView без COOP/COEP
      const ort = await import('https://cdn.jsdelivr.net/npm/onnxruntime-web@1.19.2/dist/ort.wasm.min.js').catch(() => null)
               || await import('./ort.wasm.min.js').catch(() => null);
      if (!ort) { log('AI-маска: ONNX Runtime не загрузился (нужен интернет)'); return false; }
      ort.env.wasm.numThreads = 2; ort.env.wasm.simd = true;
      rt = ort;
      // TODO: опубликовать MobileSAM.onnx как asset релиза и скачать его сюда через fetch в кэш.
      // На v2.8 заглушка: SAM ещё не подключён — переключатель есть в настройках, но маска не меняется.
      log('AI-маска (MobileSAM) в процессе подключения — пока работает обычная маска');
      return false;
    } catch (e) { log('AI-маска: ' + (e.message || e)); return false; }
  })();
  return loading;
}
export async function refineMask(rgba, w, h, bbox, points) {
  if (!ready) return null;
  // bbox: [x0,y0,x1,y1] — проекция цилиндра в кадре (prompt для SAM)
  // points: [{x,y,label=1}] — подсказки «точно предмет», например точка пипетки и центр
  // вернёт Uint8Array {0=фон,1=предмет} размером w*h или null при ошибке
  return null; // v2.8 — только переключатель в UI; полный запуск инференса — следующим патчем
}
