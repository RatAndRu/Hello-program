import type { Account, AccountType, Category, Settings, AppState } from '../types';
import { uid } from '../lib/id';
import { nowYM, todayISO } from '../lib/dates';

export const PALETTE = [
  '#38c3f5',
  '#10d19a',
  '#8b5cf6',
  '#f43f5e',
  '#f59e0b',
  '#34e5b0',
  '#a78bfa',
  '#fb7d8e',
  '#fbbf5c',
  '#60a5fa',
  '#2dd4bf',
  '#c084fc',
  '#94a3b8',
  '#f472b6',
  '#4ade80',
  '#38bdf8',
];

export const ACCOUNT_TYPES: Record<
  AccountType,
  { label: string; icon: string; color: string; hint: string }
> = {
  cash: { label: 'Наличные', icon: 'Banknote', color: '#34e5b0', hint: 'Кошелёк, наличные дома' },
  card: { label: 'Карта', icon: 'CreditCard', color: '#38c3f5', hint: 'Дебетовая карта, everyday-счёт' },
  savings: { label: 'Накопительный счёт', icon: 'PiggyBank', color: '#10d19a', hint: 'Счёт с процентом на остаток' },
  deposit: { label: 'Вклад', icon: 'Landmark', color: '#8b5cf6', hint: 'Срочный вклад с капитализацией' },
  broker: { label: 'Брокерский счёт', icon: 'TrendingUp', color: '#60a5fa', hint: 'Инвестиции, ИИС' },
  crypto: { label: 'Криптокошелёк', icon: 'Bitcoin', color: '#f59e0b', hint: 'Криптовалюта' },
  credit: { label: 'Кредитный счёт', icon: 'CreditCard', color: '#fb7d8e', hint: 'Кредитка, овердрафт' },
  other: { label: 'Другое', icon: 'Wallet', color: '#94a3b8', hint: 'Любой другой актив' },
};

export const DEFAULT_SETTINGS: Settings = {
  baseCurrency: 'RUB',
  ratesProvider: 'auto',
  manualRates: {},
  theme: 'dark',
  hideBalances: false,
  showCents: true,
  monthStartDay: 1,
  firstDayOfWeek: 1,
  workweekOnly: false,
  locale: 'ru-RU',
  demoLoaded: false,
  onboarded: false,
};

export const EXPENSE_CATEGORIES: [string, string, string][] = [
  ['Жильё', 'Home', '#38c3f5'],
  ['Еда и продукты', 'UtensilsCrossed', '#10d19a'],
  ['Транспорт', 'Bus', '#60a5fa'],
  ['Здоровье', 'HeartPulse', '#f43f5e'],
  ['Развлечения', 'Gamepad2', '#8b5cf6'],
  ['Одежда', 'Shirt', '#fb7d8e'],
  ['Связь и интернет', 'Wifi', '#34e5b0'],
  ['Образование', 'GraduationCap', '#a78bfa'],
  ['Подарки', 'Gift', '#f472b6'],
  ['Путешествия', 'Plane', '#38bdf8'],
  ['Спорт', 'Dumbbell', '#4ade80'],
  ['Кафе и рестораны', 'Coffee', '#fbbf5c'],
  ['Подписки', 'Repeat', '#c084fc'],
  ['Красота', 'Sparkles', '#f472b6'],
  ['Прочее', 'MoreHorizontal', '#94a3b8'],
];

export const INCOME_CATEGORIES: [string, string, string][] = [
  ['Зарплата', 'Briefcase', '#10d19a'],
  ['Аванс', 'Wallet', '#34e5b0'],
  ['Фриланс', 'Laptop', '#38c3f5'],
  ['Проценты', 'Percent', '#a78bfa'],
  ['Аренда', 'Building2', '#60a5fa'],
  ['Дивиденды', 'TrendingUp', '#4ade80'],
  ['Подарки', 'Gift', '#f472b6'],
  ['Кэшбэк', 'BadgePercent', '#fbbf5c'],
  ['Прочее', 'MoreHorizontal', '#94a3b8'],
];

export function defaultCategories(): Category[] {
  const out: Category[] = [];
  EXPENSE_CATEGORIES.forEach(([name, icon, color], i) =>
    out.push({ id: uid('cat'), name, kind: 'expense', color, icon, order: i }),
  );
  INCOME_CATEGORIES.forEach(([name, icon, color], i) =>
    out.push({ id: uid('cat'), name, kind: 'income', color, icon, order: i }),
  );
  return out;
}

export function emptyInterest() {
  return {
    enabled: false,
    annualRate: 0,
    capitalization: 'monthly' as const,
    payoutDay: undefined,
    payoutMode: 'compound' as const,
    payoutAccountId: undefined,
    monthlyTopUp: 0,
    topUpDay: 5,
  };
}

export function emptyState(): AppState {
  return {
    version: 1,
    accounts: [],
    categories: defaultCategories(),
    incomes: [],
    subscriptions: [],
    credits: [],
    transactions: [],
    rates: null,
    settings: { ...DEFAULT_SETTINGS },
    updatedAt: Date.now(),
  };
}

export function newAccount(partial: Partial<Account> = {}): Account {
  return {
    id: uid('acc'),
    name: 'Новый счёт',
    type: 'card',
    currency: 'RUB',
    balance: 0,
    color: PALETTE[0],
    icon: ACCOUNT_TYPES.card.icon,
    includeInTotal: true,
    archived: false,
    order: Date.now(),
    interest: emptyInterest(),
    ...partial,
  };
}

export const STATE_VERSION = 1;
export const NOW_YM = nowYM();
export const TODAY = todayISO();
