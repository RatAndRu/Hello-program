// Сохранение: настройки и направляющие — localStorage, картинка кальки — IndexedDB.

const KEY = 'reyka-state-v1';

export function loadState() {
  try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { return null; }
}

let saveTimer = 0;
export function saveState(obj) {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try { localStorage.setItem(KEY, JSON.stringify(obj)); } catch { /* переполнено — не страшно */ }
  }, 250);
}

export function clearState() { try { localStorage.removeItem(KEY); } catch { } }

function db() {
  return new Promise((res, rej) => {
    const r = indexedDB.open('reyka', 1);
    r.onupgradeneeded = () => r.result.createObjectStore('files');
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}

export async function putFile(key, blob) {
  try {
    const d = await db();
    await new Promise((res, rej) => { const tx = d.transaction('files', 'readwrite'); tx.objectStore('files').put(blob, key); tx.oncomplete = res; tx.onerror = () => rej(tx.error); });
  } catch { }
}

export async function getFile(key) {
  try {
    const d = await db();
    return await new Promise((res, rej) => { const tx = d.transaction('files', 'readonly'); const r = tx.objectStore('files').get(key); r.onsuccess = () => res(r.result || null); r.onerror = () => rej(r.error); });
  } catch { return null; }
}

export async function delFile(key) {
  try {
    const d = await db();
    await new Promise((res) => { const tx = d.transaction('files', 'readwrite'); tx.objectStore('files').delete(key); tx.oncomplete = res; tx.onerror = res; });
  } catch { }
}
