import type { Currency, ISODate, RatesProvider, RatesSnapshot } from '../types';
import { todayISO } from './dates';

/* ============================================================================
 *  Курсы валют.
 *  Провайдеры подключаются прямо из браузера (CORS-friendly), поэтому
 *  приложение остаётся полностью статическим PWA без собственного бэкенда.
 *  При недоступности сети используется кэш / ручные курсы.
 * ==========================================================================*/

export type ProviderId = 'cbr' | 'ecb' | 'erapi' | 'jsdelivr';

export const PROVIDERS: { id: ProviderId; name: string; note: string }[] = [
  { id: 'cbr', name: 'ЦБ РФ', note: 'Официальный курс Банка России, обновляется по будням' },
  { id: 'ecb', name: 'ЕЦБ (Frankfurter)', note: 'Курс Европейского центробанка' },
  { id: 'erapi', name: 'ExchangeRate API', note: 'Мировые валюты, open.er-api.com' },
  { id: 'jsdelivr', name: 'Currency API (CDN)', note: 'Резервный источник через jsDelivr' },
];

interface RawRates {
  base: Currency;
  date: string;
  rates: Record<string, number>;
}

const timeoutSignal = (ms = 9000): AbortSignal => {
  const ctrl = new AbortController();
  setTimeout(() => ctrl.abort(), ms);
  return ctrl.signal;
};

/** Пересчёт курсов под нужную базовую валюту: rates[X] = X за 1 base */
export function rebase(rates: Record<string, number>, fromBase: Currency, toBase: Currency): Record<string, number> | null {
  if (fromBase === toBase) return { ...rates, [toBase]: 1 };
  const k = rates[toBase];
  if (!k || !Number.isFinite(k) || k === 0) return null;
  const out: Record<string, number> = {};
  for (const [c, v] of Object.entries(rates)) {
    if (Number.isFinite(v)) out[c] = v / k;
  }
  out[toBase] = 1;
  return out;
}

async function getJSON<T>(url: string, signal: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal, headers: { accept: 'application/json' }, cache: 'no-store' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

/* --------------------------------- провайдеры --------------------------------- */

async function fetchCBR(base: Currency): Promise<RawRates> {
  type CBRResp = {
    Date: string;
    Valute: Record<string, { Value: number; Nominal: number; CharCode: string }>;
  };
  const data = await getJSON<CBRResp>('https://www.cbr-xml-daily.ru/daily_json.js', timeoutSignal());
  const rates: Record<string, number> = { RUB: 1 };
  for (const v of Object.values(data.Valute ?? {})) {
    if (v?.CharCode && Number.isFinite(v.Value)) rates[v.CharCode] = v.Value / (v.Nominal || 1);
  }
  const date = (data.Date ?? '').slice(0, 10) || todayISO();
  const final = base === 'RUB' ? rates : rebase(rates, 'RUB', base);
  if (!final) throw new Error('ЦБ РФ не отдаёт курс для базовой валюты ' + base);
  return { base, date, rates: final };
}

async function fetchECB(base: Currency): Promise<RawRates> {
  const url = `https://api.frankfurter.app/latest?from=${encodeURIComponent(base)}`;
  const data = await getJSON<{ amount: number; base: string; date: string; rates: Record<string, number> }>(
    url,
    timeoutSignal(),
  );
  return { base, date: data.date ?? todayISO(), rates: { ...data.rates, [base]: 1 } };
}

async function fetchErApi(base: Currency): Promise<RawRates> {
  const url = `https://open.er-api.com/v6/latest/${encodeURIComponent(base)}`;
  const data = await getJSON<{ result: string; base_code: string; rates: Record<string, number>; time_last_update_utc?: string }>(
    url,
    timeoutSignal(),
  );
  if (data.result !== 'success') throw new Error('er-api: ' + data.result);
  const date = data.time_last_update_utc ? new Date(data.time_last_update_utc).toISOString().slice(0, 10) : todayISO();
  return { base, date, rates: { ...data.rates, [base]: 1 } };
}

async function fetchJsDelivr(base: Currency): Promise<RawRates> {
  const url = `https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/${base.toLowerCase()}.json`;
  const data = await getJSON<{ date: string; [base: string]: Record<string, number> | string }>(url, timeoutSignal());
  const node = data[base.toLowerCase()];
  if (!node || typeof node === 'string') throw new Error('currency-api: нет данных');
  return { base, date: (data.date as string) ?? todayISO(), rates: { ...(node as Record<string, number>), [base]: 1 } };
}

const LOADERS: Record<ProviderId, (base: Currency) => Promise<RawRates>> = {
  cbr: fetchCBR,
  ecb: fetchECB,
  erapi: fetchErApi,
  jsdelivr: fetchJsDelivr,
};

/** Криптовалюты подтягиваем отдельно (не входят в официальные курсы) */
async function fetchCrypto(base: Currency): Promise<Record<string, number>> {
  try {
    const url =
      'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,tether&vs_currencies=' +
      ['usd', 'eur', 'rub'].join(',');
    const data = await getJSON<Record<string, Record<string, number>>>(url, timeoutSignal(7000));
    const vs = base.toLowerCase();
    const out: Record<string, number> = {};
    const map: Record<string, string> = { bitcoin: 'BTC', ethereum: 'ETH', tether: 'USDT' };
    for (const [id, code] of Object.entries(map)) {
      const v = data?.[id]?.[vs];
      if (Number.isFinite(v) && v) out[code] = v; // 1 BTC = v base
    }
    return out;
  } catch {
    return {};
  }
}

export interface FetchRatesResult {
  snapshot: RatesSnapshot;
  error?: string;
  tried: { provider: ProviderId; ok: boolean; error?: string }[];
}

/** Загрузка курсов с перебором провайдеров при сбоях */
export async function fetchRates(
  provider: RatesProvider,
  base: Currency,
  opts: { withCrypto?: boolean } = {},
): Promise<FetchRatesResult> {
  const order: ProviderId[] =
    provider === 'auto' || provider === 'manual'
      ? base === 'RUB'
        ? ['cbr', 'erapi', 'jsdelivr', 'ecb']
        : ['erapi', 'jsdelivr', 'ecb', 'cbr']
      : [provider];

  const tried: { provider: ProviderId; ok: boolean; error?: string }[] = [];

  for (const p of order) {
    try {
      const raw = await LOADERS[p](base);
      const rates: Record<string, number> = { ...raw.rates, [base]: 1 };
      if (opts.withCrypto) {
        const crypto = await fetchCrypto(base);
        for (const [code, v] of Object.entries(crypto)) rates[code] = v;
      }
      tried.push({ provider: p, ok: true });
      return {
        snapshot: { provider: p, base, date: raw.date, fetchedAt: Date.now(), rates },
        tried,
      };
    } catch (e) {
      tried.push({ provider: p, ok: false, error: e instanceof Error ? e.message : String(e) });
    }
  }

  throw new FetchRatesError('Не удалось получить курсы валют', tried);
}

export class FetchRatesError extends Error {
  tried: { provider: ProviderId; ok: boolean; error?: string }[];
  constructor(message: string, tried: { provider: ProviderId; ok: boolean; error?: string }[]) {
    super(message);
    this.name = 'FetchRatesError';
    this.tried = tried;
  }
}

/* ------------------------------- конвертация -------------------------------- */

export interface ConvertRates {
  rates: Record<string, number>;
  base: Currency;
  manual?: Record<string, number>;
}

/**
 * Перевод суммы из одной валюты в другую.
 * rates[c] — сколько единиц c даёт 1 единица base.
 */
export function convert(amount: number, from: Currency, to: Currency, snap: ConvertRates | null | undefined): number {
  if (!Number.isFinite(amount)) return 0;
  if (from === to) return amount;
  if (!snap) return amount;
  const { rates, base, manual } = snap;

  const rateOf = (c: Currency): number | null => {
    if (c === base) return 1;
    if (manual && manual[c] && manual[c] > 0) return manual[c];
    const v = rates?.[c];
    return Number.isFinite(v) && v > 0 ? v : null;
  };

  const rf = rateOf(from);
  const rt = rateOf(to);
  if (rf === null || rt === null) return amount; // курса нет — возвращаем как есть
  // amount в валюте from -> в base -> в to
  return (amount / rf) * rt;
}

export function hasRate(from: Currency, to: Currency, snap: ConvertRates | null | undefined): boolean {
  if (from === to) return true;
  if (!snap) return false;
  const { rates, base, manual } = snap;
  const get = (c: Currency) => (c === base ? 1 : manual?.[c] || rates?.[c]);
  const rf = get(from);
  const rt = get(to);
  return Boolean(rf && rt && rf > 0 && rt > 0);
}

export function isRatesFresh(snap: RatesSnapshot | null, maxAgeMs = 24 * 60 * 60 * 1000): boolean {
  if (!snap) return false;
  return Date.now() - snap.fetchedAt < maxAgeMs;
}

export function rateText(from: Currency, to: Currency, snap: ConvertRates | null): string {
  if (!snap) return '—';
  const v = convert(1, from, to, snap);
  if (!Number.isFinite(v)) return '—';
  const digits = v >= 100 ? 2 : v >= 1 ? 4 : 6;
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(v);
}

/* ------------------------------- история курсов ------------------------------ */

const HIST_KEY = 'budgetlife.rates.history.v1';
const HIST_MAX = 120;

export interface RatesHistoryPoint {
  date: ISODate;
  fetchedAt: number;
  rates: Record<string, number>;
}

/** Сохраняем снимок курсов, чтобы строить мини-график динамики */
export function saveRatesHistory(snap: RatesSnapshot): void {
  try {
    const hist = loadRatesHistory();
    const last = hist[hist.length - 1];
    if (last && last.date === snap.date && last.rates[snap.base] === snap.rates[snap.base]) {
      hist[hist.length - 1] = { date: snap.date, fetchedAt: snap.fetchedAt, rates: snap.rates };
    } else {
      hist.push({ date: snap.date, fetchedAt: snap.fetchedAt, rates: snap.rates });
    }
    localStorage.setItem(HIST_KEY, JSON.stringify(hist.slice(-HIST_MAX)));
  } catch {
    /* браузер запретил запись — не критично */
  }
}

export function loadRatesHistory(): RatesHistoryPoint[] {
  try {
    const raw = localStorage.getItem(HIST_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as RatesHistoryPoint[]) : [];
  } catch {
    return [];
  }
}

/** Динамика пары валют по истории: сколько единиц `to` даёт 1 `from` */
export function pairHistory(from: Currency, to: Currency, base: Currency, tail = 30): number[] {
  const hist = loadRatesHistory().slice(-tail);
  return hist
    .map((p) => {
      const rf = from === base ? 1 : p.rates[from];
      const rt = to === base ? 1 : p.rates[to];
      if (!rf || !rt) return NaN;
      return rt / rf;
    })
    .filter((v) => Number.isFinite(v));
}
