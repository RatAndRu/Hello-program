import Dexie, { type Table } from 'dexie';
import type { AppState } from '../types';

/* ============================================================================
 *  Локальное хранилище: IndexedDB (Dexie) + резервные копии.
 *  При недоступности IndexedDB — автоматический фолбэк на localStorage.
 * ==========================================================================*/

export interface StateRow {
  id: string;
  data: AppState;
  updatedAt: number;
}

export interface BackupRow {
  id?: number;
  createdAt: number;
  label: string;
  data: AppState;
}

class BudgetDB extends Dexie {
  state!: Table<StateRow, string>;
  backups!: Table<BackupRow, number>;

  constructor() {
    super('budgetlife');
    this.version(1).stores({
      state: 'id',
      backups: '++id, createdAt',
    });
  }
}

let dbInstance: BudgetDB | null = null;
let idbBroken = false;

export function getDB(): BudgetDB | null {
  if (idbBroken) return null;
  if (dbInstance) return dbInstance;
  try {
    dbInstance = new BudgetDB();
    return dbInstance;
  } catch {
    idbBroken = true;
    return null;
  }
}

export const STATE_KEY = 'budgetlife.state.v1';
const LS_KEY = STATE_KEY;

function lsAvailable(): boolean {
  try {
    return typeof localStorage !== 'undefined';
  } catch {
    return false;
  }
}

export async function loadState(): Promise<AppState | null> {
  const db = getDB();
  if (db) {
    try {
      const row = await db.state.get('main');
      if (row?.data) return row.data;
    } catch {
      idbBroken = true;
    }
  }
  if (lsAvailable()) {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (raw) return JSON.parse(raw) as AppState;
    } catch {
      /* ignore */
    }
  }
  return null;
}

export async function saveState(data: AppState): Promise<void> {
  const db = getDB();
  if (db) {
    try {
      await db.state.put({ id: 'main', data, updatedAt: Date.now() });
      return;
    } catch {
      idbBroken = true;
    }
  }
  if (lsAvailable()) {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(data));
    } catch {
      /* переполнение — молча игнорируем, данные всё равно в памяти */
    }
  }
}

export async function saveBackup(label: string, data: AppState, keep = 12): Promise<void> {
  const db = getDB();
  if (!db) return;
  try {
    await db.backups.add({ createdAt: Date.now(), label, data });
    const all = await db.backups.orderBy('id').toArray();
    const excess = all.length - keep;
    for (let i = 0; i < excess; i++) await db.backups.delete(all[i].id!);
  } catch {
    /* ignore */
  }
}

export async function listBackups(): Promise<{ id: number; createdAt: number; label: string }[]> {
  const db = getDB();
  if (!db) return [];
  try {
    const rows = await db.backups.orderBy('id').reverse().limit(20).toArray();
    return rows.map((r) => ({ id: r.id!, createdAt: r.createdAt, label: r.label }));
  } catch {
    return [];
  }
}

export async function getBackup(id: number): Promise<AppState | null> {
  const db = getDB();
  if (!db) return null;
  try {
    const row = await db.backups.get(id);
    return row?.data ?? null;
  } catch {
    return null;
  }
}

export async function deleteBackup(id: number): Promise<void> {
  const db = getDB();
  if (!db) return;
  try {
    await db.backups.delete(id);
  } catch {
    /* ignore */
  }
}

export async function estimateUsage(): Promise<{ usage?: number; quota?: number }> {
  try {
    if (navigator.storage?.estimate) {
      const est = await navigator.storage.estimate();
      return { usage: est.usage, quota: est.quota };
    }
  } catch {
    /* ignore */
  }
  return {};
}
