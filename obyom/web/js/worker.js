// Фоновый поток обработки (чтобы интерфейс не замирал).
// Загрузка pipeline — динамическая: если статический import падает на старом WebView,
// воркер не умирает молча, а шлёт ошибку в main.
let runPipeline = null;
let loadErr = null;
import('./pipeline.js')
  .then((m) => { runPipeline = m.runPipeline; })
  .catch((e) => { loadErr = (e && e.message) ? e.message : String(e); });

let stop = false;
self.onmessage = async (e) => {
  const m = e.data;
  if (m.type === 'ping') {
    if (loadErr) { self.postMessage({ type: 'error', message: 'Не загрузился воркер: ' + loadErr }); return; }
    self.postMessage({ type: 'pong', ready: !!runPipeline });
    return;
  }
  if (m.type === 'stop') { stop = true; return; }
  if (m.type === 'run') {
    stop = false;
    let waited = 0;
    while (!runPipeline && !loadErr && waited < 150) { await new Promise(r => setTimeout(r, 100)); waited++; }
    if (loadErr) { self.postMessage({ type: 'error', message: 'Не загрузился воркер: ' + loadErr }); return; }
    if (!runPipeline) { self.postMessage({ type: 'error', message: 'Воркер не загрузился' }); return; }
    try {
      const r = await runPipeline(m.job, {
        progress: (stage, p, text) => self.postMessage({ type: 'progress', stage, p, text }),
        preview: (packed) => self.postMessage({ type: 'preview', packed }, [packed.buffer]),
        log: (text) => self.postMessage({ type: 'log', text }),
        partial: (r) => self.postMessage({ type: 'partial', result: r }),
      }, () => stop);
      const tr = [r.mesh.pos.buffer, r.mesh.nrm.buffer, r.mesh.col.buffer, r.mesh.idx.buffer];
      if (r.splats) tr.push(r.splats.buffer);
      self.postMessage({ type: 'done', result: r }, tr);
    } catch (err) {
      self.postMessage({ type: 'error', message: (err && err.message) ? err.message : String(err) });
    }
  }
};
self.addEventListener('error', (e) => {
  self.postMessage({ type: 'error', message: 'ошибка воркера: ' + ((e && e.message) || 'неизвестно') });
});
