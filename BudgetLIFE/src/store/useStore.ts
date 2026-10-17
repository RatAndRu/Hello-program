import { create } from 'zustand';
import type {
  Account,
  AppState,
  CashflowEvent,
  Category,
  Credit,
  Currency,
  IncomeSource,
  MonthOverride,
  PayDayOverride,
  RatesProvider,
  Settings,
  Subscription,
  Transaction,
} from '../types';
import { loadState, saveBackup, saveState } from './db';
import { emptyState, newAccount, DEFAULT_SETTINGS } from './defaults';
import { buildDemoState } from './demo';
import { fetchRates, saveRatesHistory } from '../lib/rates';
import { uid } from '../lib/id';

/* ============================================================================
 *  Единый стор приложения.
 *  Мутации выполняются через `mutate` (клон состояния + правка),
 *  после чего состояние автоматически сохраняется в IndexedDB (сdebounce).
 * ==========================================================================*/

export type RatesStatus = 'idle' | 'loading' | 'ok' | 'error';

interface StoreState {
  data: AppState;
  hydrated: boolean;
  ratesStatus: RatesStatus;
  ratesError?: string;
  lastSavedAt?: number;

  hydrate: () => Promise<void>;
  mutate: (fn: (draft: AppState) => void, opts?: { backup?: boolean }) => void;
  patchSettings: (patch: Partial<Settings>) => void;

  /* счета */
  addAccount: (partial?: Partial<Account>) => string;
  updateAccount: (id: string, patch: Partial<Account>) => void;
  deleteAccount: (id: string) => void;
  setAccountBalance: (id: string, balance: number) => void;

  /* категории */
  addCategory: (partial: Partial<Category>) => string;
  updateCategory: (id: string, patch: Partial<Category>) => void;
  deleteCategory: (id: string) => void;

  /* доходы */
  addIncome: (partial?: Partial<IncomeSource>) => string;
  updateIncome: (id: string, patch: Partial<IncomeSource>) => void;
  deleteIncome: (id: string) => void;
  setMonthOverride: (incomeId: string, ym: string, patch: MonthOverride | null) => void;
  setPayDayOverride: (incomeId: string, ym: string, pd: PayDayOverride) => void;

  /* подписки */
  addSubscription: (partial?: Partial<Subscription>) => string;
  updateSubscription: (id: string, patch: Partial<Subscription>) => void;
  deleteSubscription: (id: string) => void;

  /* кредиты */
  addCredit: (partial?: Partial<Credit>) => string;
  updateCredit: (id: string, patch: Partial<Credit>) => void;
  deleteCredit: (id: string) => void;

  /* операции */
  addTransaction: (tx: Partial<Transaction>) => string;
  updateTransaction: (id: string, patch: Partial<Transaction>) => void;
  deleteTransaction: (id: string) => void;
  toggleEventDone: (event: CashflowEvent, opts?: { amount?: number; date?: string }) => void;

  /* курсы */
  refreshRates: (provider?: RatesProvider, opts?: { silent?: boolean }) => Promise<void>;
  setManualRate: (currency: Currency, value: number) => void;

  /* данные целиком */
  loadDemo: () => void;
  resetAll: (opts?: { withDemo?: boolean }) => void;
  importState: (json: string) => { ok: boolean; error?: string };
  exportState: () => string;
}

let saveTimer: number | undefined;
let lastBackupDay = '';

function scheduleSave(get: () => StoreState) {
  if (typeof window === 'undefined') return;
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(async () => {
    const { data } = get();
    await saveState(data);
    const day = new Date().toISOString().slice(0, 10);
    if (day !== lastBackupDay) {
      lastBackupDay = day;
      await saveBackup(`Авто ${day}`, data);
    }
    useStore.setState({ lastSavedAt: Date.now() });
  }, 600);
}

export const useStore = create<StoreState>((set, get) => ({
  data: emptyState(),
  hydrated: false,
  ratesStatus: 'idle',

  hydrate: async () => {
    try {
      const saved = await loadState();
      if (saved && typeof saved === 'object' && Array.isArray(saved.accounts)) {
        const data: AppState = {
          ...emptyState(),
          ...saved,
          settings: { ...DEFAULT_SETTINGS, ...(saved.settings ?? {}) },
        };
        set({ data, hydrated: true });
      } else {
        set({ data: emptyState(), hydrated: true });
      }
    } catch {
      set({ data: emptyState(), hydrated: true });
    }
    // курсы: обновляем, если их нет или они старше 12 часов
    const { data } = get();
    const stale = !data.rates || Date.now() - data.rates.fetchedAt > 12 * 3600 * 1000;
    if (stale && data.settings.ratesProvider !== 'manual') {
      void get().refreshRates(undefined, { silent: true });
    }
  },

  mutate: (fn, opts) => {
    set((state) => {
      const draft: AppState = typeof structuredClone === 'function' ? structuredClone(state.data) : JSON.parse(JSON.stringify(state.data));
      fn(draft);
      draft.updatedAt = Date.now();
      return { data: draft };
    });
    if (opts?.backup) {
      void saveBackup('Ручная копия', get().data);
    }
    scheduleSave(get);
  },

  patchSettings: (patch) => {
    get().mutate((d) => {
      d.settings = { ...d.settings, ...patch };
    });
  },

  /* ------------------------------- счета -------------------------------- */
  addAccount: (partial) => {
    const acc = newAccount(partial);
    get().mutate((d) => {
      d.accounts.push(acc);
    });
    return acc.id;
  },
  updateAccount: (id, patch) =>
    get().mutate((d) => {
      const i = d.accounts.findIndex((a) => a.id === id);
      if (i >= 0) d.accounts[i] = { ...d.accounts[i], ...patch, interest: { ...d.accounts[i].interest, ...(patch.interest ?? {}) } };
    }),
  deleteAccount: (id) =>
    get().mutate((d) => {
      d.accounts = d.accounts.filter((a) => a.id !== id);
      d.transactions = d.transactions.filter((t) => t.accountId !== id && t.toAccountId !== id);
      d.incomes.forEach((i) => {
        if (i.accountId === id) i.accountId = d.accounts[0]?.id ?? '';
      });
      d.subscriptions = d.subscriptions.filter((s) => s.accountId !== id);
      d.credits = d.credits.filter((c) => c.accountId !== id);
    }),
  setAccountBalance: (id, balance) =>
    get().mutate((d) => {
      const acc = d.accounts.find((a) => a.id === id);
      if (acc) acc.balance = balance;
    }),

  /* ----------------------------- категории ------------------------------ */
  addCategory: (partial: Partial<Category> = {}) => {
    const id = uid('cat');
    get().mutate((d) => {
      d.categories.push({
        id,
        name: partial.name ?? 'Новая категория',
        kind: partial.kind ?? 'expense',
        color: partial.color ?? '#38c3f5',
        icon: partial.icon ?? 'Circle',
        order: d.categories.length,
        budgetMonthly: partial.budgetMonthly,
      });
    });
    return id;
  },
  updateCategory: (id, patch) =>
    get().mutate((d) => {
      const i = d.categories.findIndex((c) => c.id === id);
      if (i >= 0) d.categories[i] = { ...d.categories[i], ...patch };
    }),
  deleteCategory: (id) =>
    get().mutate((d) => {
      d.categories = d.categories.filter((c) => c.id !== id);
      d.transactions.forEach((t) => {
        if (t.categoryId === id) t.categoryId = undefined;
      });
    }),

  /* ------------------------------- доходы ------------------------------- */
  addIncome: (partial: Partial<IncomeSource> = {}) => {
    const id = uid('inc');
    get().mutate((d) => {
      d.incomes.push({
        id,
        name: partial.name ?? 'Новый доход',
        kind: partial.kind ?? 'salary',
        accountId: partial.accountId ?? d.accounts[0]?.id ?? '',
        currency: partial.currency ?? d.settings.baseCurrency,
        amount: partial.amount ?? 0,
        variable: partial.variable ?? false,
        payDays: partial.payDays ?? [{ id: uid('pd'), label: 'Выплата', day: 10, rule: 'prevWorkday' }],
        startYM: partial.startYM ?? new Date().toISOString().slice(0, 7),
        active: true,
        overrides: {},
        order: d.incomes.length,
        tax: partial.tax,
        categoryId: partial.categoryId,
        note: partial.note,
      });
    });
    return id;
  },
  updateIncome: (id, patch) =>
    get().mutate((d) => {
      const i = d.incomes.findIndex((s) => s.id === id);
      if (i >= 0) d.incomes[i] = { ...d.incomes[i], ...patch };
    }),
  deleteIncome: (id) =>
    get().mutate((d) => {
      d.incomes = d.incomes.filter((s) => s.id !== id);
      d.transactions = d.transactions.filter((t) => t.sourceId !== id);
    }),
  setMonthOverride: (incomeId, ym, patch) =>
    get().mutate((d) => {
      const src = d.incomes.find((s) => s.id === incomeId);
      if (!src) return;
      src.overrides = src.overrides ?? {};
      if (!patch) delete src.overrides[ym];
      else src.overrides[ym] = { ...(src.overrides[ym] ?? {}), ...patch };
    }),
  setPayDayOverride: (incomeId, ym, pd) =>
    get().mutate((d) => {
      const src = d.incomes.find((s) => s.id === incomeId);
      if (!src) return;
      src.overrides = src.overrides ?? {};
      const cur = src.overrides[ym] ?? {};
      const list = [...(cur.payDays ?? [])];
      const idx = list.findIndex((p) => p.id === pd.id);
      if (idx >= 0) list[idx] = { ...list[idx], ...pd };
      else list.push(pd);
      src.overrides[ym] = { ...cur, payDays: list };
    }),

  /* ----------------------------- подписки ------------------------------- */
  addSubscription: (partial: Partial<Subscription> = {}) => {
    const id = uid('sub');
    get().mutate((d) => {
      d.subscriptions.push({
        id,
        name: partial.name ?? 'Новая подписка',
        amount: partial.amount ?? 0,
        currency: partial.currency ?? d.settings.baseCurrency,
        cycle: partial.cycle ?? { every: 1, unit: 'month' },
        startDate: partial.startDate ?? new Date().toISOString().slice(0, 10),
        accountId: partial.accountId ?? d.accounts[0]?.id ?? '',
        categoryId: partial.categoryId,
        active: true,
        autoRenew: true,
        remindDays: partial.remindDays ?? 1,
        priceHistory: [],
        color: partial.color ?? '#8b5cf6',
        icon: partial.icon ?? 'Repeat',
        note: partial.note,
      });
    });
    return id;
  },
  updateSubscription: (id, patch) =>
    get().mutate((d) => {
      const i = d.subscriptions.findIndex((s) => s.id === id);
      if (i >= 0) d.subscriptions[i] = { ...d.subscriptions[i], ...patch };
    }),
  deleteSubscription: (id) =>
    get().mutate((d) => {
      d.subscriptions = d.subscriptions.filter((s) => s.id !== id);
      d.transactions = d.transactions.filter((t) => t.sourceId !== id);
    }),

  /* ------------------------------ кредиты ------------------------------- */
  addCredit: (partial: Partial<Credit> = {}) => {
    const id = uid('cr');
    get().mutate((d) => {
      d.credits.push({
        id,
        name: partial.name ?? 'Новый кредит',
        kind: partial.kind ?? 'loan',
        accountId: partial.accountId ?? d.accounts[0]?.id ?? '',
        currency: partial.currency ?? d.settings.baseCurrency,
        principal: partial.principal ?? 0,
        annualRate: partial.annualRate ?? 0,
        termMonths: partial.termMonths ?? 12,
        startDate: partial.startDate ?? new Date().toISOString().slice(0, 10),
        paymentDay: partial.paymentDay ?? 15,
        paymentType: partial.paymentType ?? 'annuity',
        repayMode: partial.repayMode ?? 'min',
        extraPayment: partial.extraPayment ?? 0,
        color: partial.color ?? '#f43f5e',
        active: true,
        ...partial,
      } as Credit);
    });
    return id;
  },
  updateCredit: (id, patch) =>
    get().mutate((d) => {
      const i = d.credits.findIndex((c) => c.id === id);
      if (i >= 0) d.credits[i] = { ...d.credits[i], ...patch };
    }),
  deleteCredit: (id) =>
    get().mutate((d) => {
      d.credits = d.credits.filter((c) => c.id !== id);
    }),

  /* ----------------------------- операции ------------------------------- */
  addTransaction: (tx) => {
    const id = tx.id ?? uid('tx');
    get().mutate((d) => {
      d.transactions.push({
        id,
        date: tx.date ?? new Date().toISOString().slice(0, 10),
        amount: tx.amount ?? 0,
        currency: tx.currency ?? d.accounts.find((a) => a.id === tx.accountId)?.currency ?? d.settings.baseCurrency,
        accountId: tx.accountId ?? d.accounts[0]?.id ?? '',
        toAccountId: tx.toAccountId,
        categoryId: tx.categoryId,
        title: tx.title ?? 'Операция',
        note: tx.note,
        kind: tx.kind ?? (tx.amount ?? 0) < 0 ? 'expense' : 'income',
        status: tx.status ?? 'planned',
        sourceType: tx.sourceType ?? (tx.status === 'planned' ? 'planned' : 'manual'),
        sourceId: tx.sourceId,
        sourceKey: tx.sourceKey,
        recurrence: tx.recurrence,
        createdAt: Date.now(),
        updatedAt: Date.now(),
      });
    });
    return id;
  },
  updateTransaction: (id, patch) =>
    get().mutate((d) => {
      const i = d.transactions.findIndex((t) => t.id === id);
      if (i >= 0) d.transactions[i] = { ...d.transactions[i], ...patch, updatedAt: Date.now() };
    }),
  deleteTransaction: (id) =>
    get().mutate((d) => {
      d.transactions = d.transactions.filter((t) => t.id !== id);
    }),

  toggleEventDone: (event, opts) =>
    get().mutate((d) => {
      const existing = d.transactions.find((t) => t.sourceKey === event.sourceKey);
      if (existing) {
        if (existing.status === 'done') {
          if (existing.sourceType === 'manual' || existing.sourceType === 'planned') {
            existing.status = 'planned';
            existing.updatedAt = Date.now();
          } else {
            d.transactions = d.transactions.filter((t) => t.id !== existing.id);
          }
          return;
        }
        existing.status = 'done';
        existing.amount = opts?.amount ?? event.amount;
        existing.date = opts?.date ?? event.date;
        existing.categoryId = event.categoryId ?? existing.categoryId;
        existing.updatedAt = Date.now();
        return;
      }
      d.transactions.push({
        id: uid('tx'),
        date: opts?.date ?? event.date,
        amount: opts?.amount ?? event.amount,
        currency: event.currency,
        accountId: event.accountId,
        categoryId: event.categoryId,
        title: event.title,
        kind: event.kind === 'transfer' ? 'transfer' : event.amount >= 0 ? 'income' : 'expense',
        status: 'done',
        sourceType: event.sourceType,
        sourceId: event.sourceId,
        sourceKey: event.sourceKey,
        note: event.note,
        createdAt: Date.now(),
        updatedAt: Date.now(),
      });
    }),

  /* ------------------------------- курсы -------------------------------- */
  refreshRates: async (provider, opts) => {
    const settings = get().data.settings;
    const base = settings.baseCurrency;
    const useProvider = provider ?? settings.ratesProvider;
    if (useProvider === 'manual') {
      set({ ratesStatus: 'ok', ratesError: undefined });
      return;
    }
    if (!opts?.silent) set({ ratesStatus: 'loading', ratesError: undefined });
    try {
      const { snapshot, tried } = await fetchRates(useProvider, base, { withCrypto: true });
      get().mutate((d) => {
        d.rates = snapshot;
      });
      saveRatesHistory(snapshot);
      const failed = tried.filter((t) => !t.ok);
      set({
        ratesStatus: 'ok',
        ratesError: failed.length ? `Резервный источник: ${failed.map((f) => f.provider).join(', ')} недоступен` : undefined,
      });
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Не удалось загрузить курсы';
      set({ ratesStatus: get().data.rates ? 'error' : 'error', ratesError: message });
    }
  },
  setManualRate: (currency, value) =>
    get().mutate((d) => {
      d.settings.manualRates = { ...(d.settings.manualRates ?? {}), [currency]: value };
    }),

  /* ---------------------------- данные целиком -------------------------- */
  loadDemo: () => {
    const demo = buildDemoState();
    set({ data: demo });
    void saveState(demo);
    void saveBackup('Перед загрузкой демо', get().data).catch(() => undefined);
    void get().refreshRates(undefined, { silent: true });
  },
  resetAll: () => {
    const fresh = emptyState();
    set({ data: fresh });
    void saveState(fresh);
  },
  importState: (json) => {
    try {
      const parsed = JSON.parse(json) as AppState;
      if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.accounts)) {
        return { ok: false, error: 'Неверный формат файла' };
      }
      const data: AppState = { ...emptyState(), ...parsed, settings: { ...DEFAULT_SETTINGS, ...(parsed.settings ?? {}) } };
      set({ data });
      void saveState(data);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : 'Ошибка чтения файла' };
    }
  },
  exportState: () => JSON.stringify(get().data, null, 2),
}));

/* ------------------------------- селекторы -------------------------------- */

export const useData = () => useStore((s) => s.data);
export const useSettings = () => useStore((s) => s.data.settings);
export const useAccounts = () => useStore((s) => s.data.accounts);
export const useIncomes = () => useStore((s) => s.data.incomes);
export const useSubscriptions = () => useStore((s) => s.data.subscriptions);
export const useCredits = () => useStore((s) => s.data.credits);
export const useTransactions = () => useStore((s) => s.data.transactions);
export const useCategories = () => useStore((s) => s.data.categories);
export const useRates = () => useStore((s) => s.data.rates);
