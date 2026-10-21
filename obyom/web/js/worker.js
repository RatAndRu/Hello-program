// Фоновый поток обработки (чтобы интерфейс не замирал)
import { runPipeline } from './pipeline.js';
let stop = false;
self.onmessage = async (e) => {
  const m = e.data;
  if (m.type === 'ping') { self.postMessage({ type: 'pong' }); return; }
  if (m.type === 'stop') { stop = true; return; }
  if (m.type === 'run') {
    stop = false;
    try {
      const r = await runPipeline(m.job, {
        progress: (stage, p, text) => self.postMessage({ type: 'progress', stage, p, text }),
        preview: (packed) => self.postMessage({ type: 'preview', packed }, [packed.buffer]),
        log: (text) => self.postMessage({ type: 'log', text }),
      }, () => stop);
      const tr = [r.mesh.pos.buffer, r.mesh.nrm.buffer, r.mesh.col.buffer, r.mesh.idx.buffer]; if (r.splats) tr.push(r.splats.buffer);
      self.postMessage({ type: 'done', result: r }, tr);
    } catch (err) { self.postMessage({ type: 'error', message: err.message || String(err) }); }
  }
};
