// Объём — хранение сканов в памяти телефона (IndexedDB)
const DB = 'obyom', VER = 1;
let dbp = null;
function db() {
  if (dbp) return dbp;
  dbp = new Promise((res, rej) => {
    const r = indexedDB.open(DB, VER);
    r.onupgradeneeded = () => { const d = r.result; if (!d.objectStoreNames.contains('scans')) d.createObjectStore('scans', { keyPath: 'id' }); if (!d.objectStoreNames.contains('frames')) d.createObjectStore('frames'); };
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  });
  return dbp;
}
const tx = async (store, mode, fn) => { const d = await db(); return new Promise((res, rej) => { const t = d.transaction(store, mode), s = t.objectStore(store); const r = fn(s); t.oncomplete = () => res(r && 'result' in r ? r.result : undefined); t.onerror = () => rej(t.error); t.onabort = () => rej(t.error || new Error('Недостаточно места?')); }); };
export const putScan = (scan) => tx('scans', 'readwrite', (s) => s.put(scan));
export const getScan = (id) => tx('scans', 'readonly', (s) => s.get(id));
export const delScan = async (id) => { await tx('scans', 'readwrite', (s) => s.delete(id)); await tx('frames', 'readwrite', (s) => s.delete(id)); };
export async function listScans() {
  const all = await tx('scans', 'readonly', (s) => s.getAll());
  return (all || []).map(({ id, name, date, mode, thumb, stats, hasMesh, hasSplats }) => ({ id, name, date, mode, thumb, stats, hasMesh, hasSplats })).sort((a, b) => b.date - a.date);
}
export const putFrames = (id, blobs) => tx('frames', 'readwrite', (s) => s.put(blobs, id));
export const getFrames = (id) => tx('frames', 'readonly', (s) => s.get(id));
export const delFrames = (id) => tx('frames', 'readwrite', (s) => s.delete(id));
