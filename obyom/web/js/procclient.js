// Запуск обработки: в фоновом потоке, если WebView его даёт, иначе — в основном
import { runPipeline } from './pipeline.js';
let probe = null;
function tryWorker() {
  if (probe) return probe;
  probe = new Promise((res) => {
    let w; try { w = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' }); } catch (e) { res(null); return; }
    const to = setTimeout(() => { try { w.terminate(); } catch (e) {} res(null); }, 4000);
    w.onmessage = (e) => { if (e.data.type === 'pong') { clearTimeout(to); w.onmessage = null; res(w); } };
    w.onerror = () => { clearTimeout(to); res(null); };
    w.postMessage({ type: 'ping' });
  });
  return probe;
}
// cb: {progress, preview, log}; возвращает {promise, stop()}
export function startProcessing(job, cb) {
  let stopFn = () => {}, stopped = false;
  const promise = (async () => {
    const w = await tryWorker();
    if (w) {
      cb.log && cb.log('обработка в фоновом потоке');
      return await new Promise((res, rej) => {
        stopFn = () => w.postMessage({ type: 'stop' });
        w.onmessage = (e) => {
          const m = e.data;
          if (m.type === 'progress') cb.progress(m.stage, m.p, m.text);
          else if (m.type === 'preview') cb.preview && cb.preview(m.packed);
          else if (m.type === 'log') cb.log && cb.log(m.text);
          else if (m.type === 'done') { probe = null; w.terminate(); res(m.result); } // новый поток на следующий раз — память освобождается
          else if (m.type === 'error') { probe = null; w.terminate(); rej(new Error(m.message)); }
        };
        w.onerror = (e) => { probe = null; rej(new Error('Ошибка фонового потока: ' + (e.message || ''))); };
        w.postMessage({ type: 'run', job });
      });
    }
    cb.log && cb.log('обработка в основном потоке');
    stopFn = () => { stopped = true; };
    return await runPipeline(job, cb, () => stopped);
  })();
  return { promise, stop: () => stopFn() };
}
