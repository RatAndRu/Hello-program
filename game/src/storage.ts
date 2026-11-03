import {
  createWorld,
  createState,
  clone,
  type SaveData,
  type World,
  type GameState,
} from "./model";
import { validateWorld } from "./engine";
const DB_NAME = "adventure-workshop-v1";
const KEY = "save";
let connection: Promise<IDBDatabase> | undefined;
function db() {
  if (!connection)
    connection = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore("saves");
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => {
        connection = undefined;
        reject(req.error);
      };
    });
  return connection;
}
export async function loadSave(): Promise<SaveData> {
  const database = await db();
  return new Promise((resolve, reject) => {
    const req = database
      .transaction("saves", "readonly")
      .objectStore("saves")
      .get(KEY);
    req.onsuccess = () => {
      if (!req.result) {
        const world = createWorld();
        resolve({
          world,
          state: createState(world),
          draft: null,
          snapshots: [],
        });
        return;
      }
      try {
        resolve(validateSave(req.result));
      } catch (e) {
        reject(e);
      }
    };
    req.onerror = () => reject(req.error);
  });
}
export async function persistSave(save: SaveData): Promise<void> {
  const database = await db();
  return new Promise((resolve, reject) => {
    const tx = database.transaction("saves", "readwrite");
    tx.objectStore("saves").put(save, KEY);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}
export function validateSave(value: unknown): SaveData {
  if (!value || typeof value !== "object")
    throw new Error("Файл не содержит сохранение.");
  const v = value as SaveData;
  const errors = validateWorld(v.world);
  if (errors.length) throw new Error(errors.slice(0, 5).join("\n"));
  validateState(v.world, v.state);
  const snapshots = Array.isArray(v.snapshots) ? v.snapshots.slice(0, 8) : [];
  for (const s of snapshots) {
    if (
      typeof s.id !== "string" ||
      typeof s.label !== "string" ||
      typeof s.date !== "string" ||
      validateWorld(s.world).length
    )
      throw new Error("Резервная копия повреждена.");
    validateState(s.world, s.state);
  }
  return {
    world: clone(v.world),
    state: clone(v.state),
    draft: v.draft
      ? (() => {
          const e = validateWorld(v.draft);
          if (e.length) throw new Error(e[0]);
          return clone(v.draft);
        })()
      : null,
    snapshots: clone(snapshots),
  };
}
function validateState(w: World, s: GameState) {
  const number = (v: unknown, min = 0, max = 999999) =>
    typeof v === "number" && Number.isFinite(v) && v >= min && v <= max;
  if (
    !s ||
    !Number.isInteger(s.x) ||
    !Number.isInteger(s.y) ||
    !number(s.x, 1, 16) ||
    !number(s.y, 1, 10) ||
    !number(s.steps) ||
    !s.stats ||
    !s.inventory ||
    !s.quests ||
    !s.flags ||
    !s.entityStats ||
    !Array.isArray(s.removed) ||
    !Array.isArray(s.opened) ||
    !Array.isArray(s.log)
  )
    throw new Error("Сохранение персонажа повреждено.");
  if (
    Object.values(s.stats).some((v) => !number(v)) ||
    Object.values(s.inventory).some((v) => !number(v)) ||
    Object.values(s.quests).some(
      (v) => !["available", "active", "completed"].includes(v),
    ) ||
    Object.values(s.flags).some((v) => typeof v !== "boolean") ||
    s.log.some((v) => typeof v !== "string" || v.length > 2000) ||
    s.log.length > 100 ||
    s.removed.some((v) => typeof v !== "string") ||
    s.opened.some((v) => typeof v !== "string")
  )
    throw new Error("Некорректные данные персонажа.");
  for (const e of Object.values(s.entityStats))
    if (!e || typeof e !== "object" || Object.values(e).some((v) => !number(v)))
      throw new Error("Некорректные характеристики объектов.");
  for (const def of w.stats)
    if (s.stats[def.id] === undefined) s.stats[def.id] = def.initial;
}
export function downloadWorld(world: World, state: GameState) {
  const data = JSON.stringify(
    { world, state, snapshots: [], draft: null },
    null,
    2,
  );
  const url = URL.createObjectURL(
    new Blob([data], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `iskra-world-v${world.revision}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function readImport(file: File): Promise<SaveData> {
  if (file.size > 20 * 1024 * 1024)
    throw new Error("Файл слишком большой. Максимум — 20 МБ.");
  let raw: unknown;
  try {
    raw = JSON.parse(await file.text(), (key, value) => {
      if (["__proto__", "constructor", "prototype"].includes(key))
        throw new Error("Недопустимое поле.");
      return value;
    });
  } catch {
    throw new Error(
      "Не удалось прочитать JSON. Выбери файл экспорта этого приложения.",
    );
  }
  return validateSave(raw);
}
export async function readImage(
  file: File,
  background = false,
): Promise<string> {
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type))
    throw new Error(
      "Поддерживаются PNG, JPEG и WebP. SVG и исполняемые файлы не загружаются.",
    );
  if (file.size > 8 * 1024 * 1024)
    throw new Error("Изображение должно быть меньше 8 МБ.");
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    if (
      img.width * img.height > 40000000 ||
      Math.max(img.width, img.height) > 16000
    )
      throw new Error(
        "Изображение слишком большое по числу пикселей. Уменьши его перед загрузкой.",
      );
    const max = background ? 1280 : 256;
    const scale = Math.min(1, max / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(img.width * scale));
    canvas.height = Math.max(1, Math.round(img.height * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Браузер не смог обработать изображение.");
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const data = canvas.toDataURL("image/webp", 0.85);
    if (data.length > 2400000)
      throw new Error(
        "Изображение слишком сложное. Попробуй картинку меньшего размера.",
      );
    return data;
  } catch (e) {
    if (e instanceof Error && e.message.startsWith("Изображение")) throw e;
    throw new Error(
      "Не удалось открыть изображение. Попробуй другой PNG, JPEG или WebP.",
    );
  } finally {
    URL.revokeObjectURL(url);
  }
}
