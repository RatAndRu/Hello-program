import type { Currency } from '../types';

/* ------------------------------- числа ---------------------------------- */

export function round2(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

export function safeNum(n: unknown, fallback = 0): number {
  const v = typeof n === 'number' ? n : Number(String(n ?? '').replace(/\s/g, '').replace(',', '.'));
  return Number.isFinite(v) ? v : fallback;
}

/** Разбор пользовательского ввода: «1 250,50» -> 1250.5 */
export function parseAmount(input: string | number | undefined | null): number {
  if (typeof input === 'number') return Number.isFinite(input) ? input : 0;
  if (!input) return 0;
  const cleaned = String(input).replace(/\u00A0|\s/g, '').replace(',', '.');
  const v = Number(cleaned);
  return Number.isFinite(v) ? v : 0;
}

/** Форматирование для поля ввода: 1250.5 -> «1 250,5» */
export function amountToInput(v: number | undefined | null): string {
  if (v === undefined || v === null || !Number.isFinite(v)) return '';
  return String(round2(v)).replace('.', ',');
}

/* ------------------------------- деньги ---------------------------------- */

export const CURRENCY_OPTIONS: { code: Currency; label: string; symbol: string; crypto?: boolean }[] = [
  { code: 'RUB', label: 'Российский рубль', symbol: '₽' },
  { code: 'USD', label: 'Доллар США', symbol: '$' },
  { code: 'EUR', label: 'Евро', symbol: '€' },
  { code: 'CNY', label: 'Китайский юань', symbol: '¥' },
  { code: 'GBP', label: 'Фунт стерлингов', symbol: '£' },
  { code: 'JPY', label: 'Японская иена', symbol: '¥' },
  { code: 'CHF', label: 'Швейцарский франк', symbol: 'Fr' },
  { code: 'KZT', label: 'Казахстанский тенге', symbol: '₸' },
  { code: 'BYN', label: 'Белорусский рубль', symbol: 'Br' },
  { code: 'TRY', label: 'Турецкая лира', symbol: '₺' },
  { code: 'AED', label: 'Дирхам ОАЭ', symbol: 'د.إ' },
  { code: 'INR', label: 'Индийская рупия', symbol: '₹' },
  { code: 'KRW', label: 'Вон Республики Корея', symbol: '₩' },
  { code: 'AMD', label: 'Армянский драм', symbol: '֏' },
  { code: 'GEL', label: 'Грузинский лари', symbol: '₾' },
  { code: 'UZS', label: 'Узбекский сум', symbol: 'soʻm' },
  { code: 'PLN', label: 'Польский злотый', symbol: 'zł' },
  { code: 'CZK', label: 'Чешская крона', symbol: 'Kč' },
  { code: 'SEK', label: 'Шведская крона', symbol: 'kr' },
  { code: 'NOK', label: 'Норвежская крона', symbol: 'kr' },
  { code: 'CAD', label: 'Канадский доллар', symbol: 'C$' },
  { code: 'AUD', label: 'Австралийский доллар', symbol: 'A$' },
  { code: 'SGD', label: 'Сингапурский доллар', symbol: 'S$' },
  { code: 'HKD', label: 'Гонконгский доллар', symbol: 'HK$' },
  { code: 'THB', label: 'Тайский бат', symbol: 'ฺ฿' },
  { code: 'BTC', label: 'Биткоин', symbol: '₿', crypto: true },
  { code: 'ETH', label: 'Эфириум', symbol: 'Ξ', crypto: true },
  { code: 'USDT', label: 'Tether', symbol: '₮', crypto: true },
];

export const CURRENCY_MAP = new Map(CURRENCY_OPTIONS.map((c) => [c.code, c]));

export function currencySymbol(code: Currency): string {
  return CURRENCY_MAP.get(code)?.symbol ?? code;
}

const decimalsFor = (code: Currency): number => {
  if (['JPY', 'KRW', 'UZS', 'VND', 'CLP'].includes(code)) return 0;
  if (['BTC', 'ETH'].includes(code)) return 6;
  if (code === 'USDT') return 2;
  return 2;
};

export interface MoneyOpts {
  /** Показывать копейки */
  cents?: boolean;
  /** Скрыть сумму (режим приватности) */
  hide?: boolean;
  /** Без пробелов между разрядами (для узких мест) */
  tight?: boolean;
  /** Со знаком +/- */
  signed?: boolean;
  /** Короткий вид: 1,2 млн ₽ */
  compact?: boolean;
}

export function fmtMoney(amount: number, currency: Currency, opts: MoneyOpts = {}): string {
  const { cents = true, hide = false, tight = false, signed = false } = opts;
  if (hide) return '••••••';
  if (!Number.isFinite(amount)) return '—';

  if (opts.compact) {
    const abs = Math.abs(amount);
    const sign = amount < 0 ? '−' : signed ? '+' : '';
    const units: [number, string][] = [
      [1e12, 'трлн'],
      [1e9, 'млрд'],
      [1e6, 'млн'],
      [1e3, 'тыс.'],
    ];
    for (const [mul, name] of units) {
      if (abs >= mul) {
        const v = abs / mul;
        return `${sign}${v.toFixed(v >= 100 ? 0 : v >= 10 ? 1 : 2).replace(/\.00$|,\d{2}$/, (m) => m)} ${name} ${currencySymbol(currency)}`.trim();
      }
    }
  }

  const d = decimalsFor(currency);
  const sign = amount < 0 ? '−' : signed ? '+' : '';
  const abs = Math.abs(amount);
  let body: string;
  try {
    body = new Intl.NumberFormat('ru-RU', {
      minimumFractionDigits: cents ? d : 0,
      maximumFractionDigits: cents ? d : 0,
      useGrouping: !tight,
    }).format(abs);
  } catch {
    body = abs.toFixed(cents ? d : 0);
  }
  return `${sign}${body} ${currencySymbol(currency)}`.trim();
}

export function fmtNumber(n: number, digits = 0): string {
  if (!Number.isFinite(n)) return '—';
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(n);
}

export function fmtPercent(n: number, digits = 2): string {
  if (!Number.isFinite(n)) return '—';
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(n)} %`;
}

export function fmtSignedMoney(amount: number, currency: Currency, opts: MoneyOpts = {}): string {
  return fmtMoney(amount, currency, { ...opts, signed: true });
}

/** «+12,4 %» / «−3,1 %» */
export function fmtDelta(percent: number): string {
  if (!Number.isFinite(percent)) return '—';
  const s = percent > 0 ? '+' : percent < 0 ? '−' : '';
  return `${s}${Math.abs(percent).toFixed(1)} %`;
}

export const HIDDEN = '••••••';
