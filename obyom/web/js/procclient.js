// Запуск обработки: в фоновом потоке, если WebView его даёт, иначе — в основном.
// Важно: runPipeline и все зависимости динамически импортируются после того как решили,
// в каком потоке работаем — это не даёт статическому import сломать worker ещё до ping'а.
let probe = null;
function tryWorker() {
  if (probe) return probe;
  probe = new Promise((res) => {
    let w;
    try { w = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' }); }
    catch (e) { res(null); return; }
    // 2.5 секунды ждём pong — на Android модульный worker может не завестись (старый WebView)
    const to = setTimeout(() => { try { w.terminate(); } catch (e) {} res(null); }, 2500);
    w.onmessage = (e) => {
      if (e.data.type === 'pong') { clearTimeout(to); w.onmessage = null; res(w); }
      else if (e.data.type === 'error') { clearTimeout(to); try { w.terminate(); } catch (ee) {} res(null); }
    };
    w.onerror = () => { clearTimeout(to); try { w.terminate(); } catch (ee) {} res(null); };
    w.postMessage({ type: 'ping' });
  });
  return probe;
}
function retire(w) { w.onmessage = null; setTimeout(() => { try { w.terminate(); } catch (e) {} }, 3000); }
// cb: {progress, preview, log}; возвращает {promise, stop()}
export function startProcessing(job, cb) {
  let stopFn = () => {}, stopped = false;
  stopFn = () => { stopped = true; }; // на время старта — Стоп сразу выставляет флаг
  const promise = (async () => {
    const { runPipeline } = await import('./pipeline.js');
    if (stopped) throw new Error('stopped');
    const w = await tryWorker();
    if (stopped) throw new Error('stopped');
    if (w) {
      cb.log && cb.log('обработка в фоновом потоке');
      return await new Promise((res, rej) => {
        stopFn = () => w.postMessage({ type: 'stop' });
        w.onmessage = (e) => {
          const m = e.data;
          if (m.type === 'progress') cb.progress(m.stage, m.p, m.text);
          else if (m.type === 'preview') cb.preview && cb.preview(m.packed);
          else if (m.type === 'log') cb.log && cb.log(m.text);
          else if (m.type === 'partial') cb.partial && cb.partial(m.result);
          else if (m.type === 'done') { probe = null; retire(w); res(m.result); }
          else if (m.type === 'error') {
            probe = null; retire(w);
            cb.log && cb.log('ошибка фонового потока, переключаюсь на основной: ' + m.message);
            fallback();
          }
        };
        w.onerror = () => {
          probe = null; retire(w);
          cb.log && cb.log('поток упал, переключаюсь на основной');
          fallback();
        };
        w.postMessage({ type: 'run', job });
        async function fallback() {
          try {
            stopFn = () => { stopped = true; };
            const r = await runPipeline(job, cb, () => stopped);
            res(r);
          } catch (err) { rej(err); }
        }
      });
    }
    cb.log && cb.log('обработка в основном потоке');
    stopFn = () => { stopped = true; };
    return await runPipeline(job, cb, () => stopped);
  })();
  return { promise, stop: () => stopFn() };
}
