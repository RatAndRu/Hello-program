/* ============================================================================
 *  BudgetLIFE — доменная модель
 * ==========================================================================*/

/** Дата в формате YYYY-MM-DD */
export type ISODate = string;
/** Месяц в формате YYYY-MM */
export type YM = string;
/** Код валюты по ISO 4217 (RUB, USD, EUR, ...) либо криптотикер (BTC) */
export type Currency = string;

/* ---------------------------------- Категории ---------------------------------- */

export interface Category {
  id: string;
  name: string;
  kind: 'income' | 'expense';
  color: string;
  icon: string;
  /** Плановый лимит на месяц (в базовой валюте) */
  budgetMonthly?: number;
  order: number;
}

/* ----------------------------------- Счета ------------------------------------- */

export type AccountType =
  | 'cash'
  | 'card'
  | 'savings'
  | 'deposit'
  | 'broker'
  | 'crypto'
  | 'credit'
  | 'other';

/**
 * Капитализация процентов:
 *  none       — проценты не начисляются
 *  daily      — начисление и зачисление каждый день
 *  monthly    — начисление каждый день, зачисление раз в месяц
 *  quarterly  — раз в квартал
 *  yearly     — раз в год
 *  endOfTerm  — в конце срока вклада
 */
export type Capitalization = 'none' | 'daily' | 'monthly' | 'quarterly' | 'yearly' | 'endOfTerm';

export interface InterestConfig {
  enabled: boolean;
  /** Годовая ставка в процентах (13 => 13%) */
  annualRate: number;
  capitalization: Capitalization;
  /** День зачисления процентов (для monthly/quarterly), по умолчанию — последний день периода */
  payoutDay?: number;
  /**
   * compound — проценты остаются на счёте и увеличивают базу (капитализация)
   * payout   — проценты выводятся на другой счёт как доход
   */
  payoutMode: 'compound' | 'payout';
  /** Счёт для вывода процентов, если payoutMode = 'payout' */
  payoutAccountId?: string;
  /** Ежемесячное пополнение счёта */
  monthlyTopUp: number;
  /** День пополнения */
  topUpDay: number;
  /** Месяц начала пополнений (YYYY-MM) */
  topUpStartYM?: YM;
  /** Месяц окончания пополнений (YYYY-MM) */
  topUpEndYM?: YM;
  /** Дата открытия (для вкладов) */
  termStart?: ISODate;
  /** Дата окончания (для endOfTerm) */
  termEnd?: ISODate;
}

export interface Account {
  id: string;
  name: string;
  type: AccountType;
  currency: Currency;
  balance: number;
  color: string;
  icon: string;
  note?: string;
  includeInTotal: boolean;
  archived: boolean;
  order: number;
  interest: InterestConfig;
  /** Для кредитных карт: лимит и задолженность (дублирует кредит, но удобно для баланса) */
  creditLimit?: number;
}

/* --------------------------------- Доходы -------------------------------------- */

export type PayDayRule = 'exact' | 'prevWorkday' | 'nextWorkday';

export interface PayDay {
  id: string;
  /** «Аванс», «Зарплата», «Премия» */
  label: string;
  /** День месяца 1..31; -1 — последний день месяца; -2 — предпоследний */
  day: number;
  /** Доля от общей суммы (0..1). Если задана — сумма = amount * share */
  share?: number;
  /** Фиксированная сумма выплаты (приоритетнее доли) */
  amount?: number;
  /** Что делать, если день выплаты выпал на выходной */
  rule: PayDayRule;
}

export interface PayDayOverride {
  id: string;
  /** Конкретная дата выплаты в этом месяце */
  date?: ISODate;
  /** Сумма выплаты в этом месяце */
  amount?: number;
  /** Выплаты в этом месяце не будет */
  skipped?: boolean;
}

export interface MonthOverride {
  /** Сумма за месяц (для сдельщиков — планируемая/фактическая) */
  amount?: number;
  /** Перенос/уточнение конкретных дней выплат */
  payDays?: PayDayOverride[];
  /** В этом месяце дохода нет (отпуск за свой счёт и т.п.) */
  skip?: boolean;
  note?: string;
}

export type IncomeKind = 'salary' | 'advance' | 'freelance' | 'rental' | 'dividends' | 'social' | 'other';

export interface IncomeSource {
  id: string;
  name: string;
  kind: IncomeKind;
  accountId: string;
  currency: Currency;
  /** Базовая сумма за месяц */
  amount: number;
  /** Сумма плавает от месяца к месяцу (сдельная работа) */
  variable: boolean;
  /** Несколько дней выплат внутри месяца: аванс + зарплата и т.д. */
  payDays: PayDay[];
  /** Месяц начала (YYYY-MM) */
  startYM: YM;
  /** Месяц окончания (YYYY-MM), если доход временный */
  endYM?: YM;
  categoryId?: string;
  note?: string;
  active: boolean;
  /** Удержание налога на уровне источника */
  tax?: { enabled: boolean; rate: number };
  /** Корректировки по конкретным месяцам */
  overrides: Record<YM, MonthOverride>;
  order: number;
}

/* ------------------------------- Подписки ------------------------------------- */

export type CycleUnit = 'day' | 'week' | 'month' | 'year';

export interface Subscription {
  id: string;
  name: string;
  amount: number;
  currency: Currency;
  cycle: { every: number; unit: CycleUnit };
  /** Дата первого списания */
  startDate: ISODate;
  /** Дата окончания (если подписка конечна) */
  endDate?: ISODate;
  categoryId?: string;
  accountId: string;
  active: boolean;
  autoRenew: boolean;
  /** За сколько дней напомнить о списании */
  remindDays: number;
  note?: string;
  /** Бесплатный период до даты (списания не будет) */
  trialUntil?: ISODate;
  /** История изменения цены */
  priceHistory: { from: ISODate; amount: number }[];
  color: string;
  icon: string;
}

/* -------------------------------- Кредиты ------------------------------------- */

export type CreditKind = 'loan' | 'credit_card' | 'installment';
export type PaymentType = 'annuity' | 'differentiated';
export type RepayMode = 'full' | 'min' | 'custom';

export interface Credit {
  id: string;
  name: string;
  kind: CreditKind;
  /** Счёт списания платежа */
  accountId: string;
  currency: Currency;

  /* --- классический кредит / рассрочка --- */
  /** Сумма кредита */
  principal: number;
  /** Годовая ставка, % */
  annualRate: number;
  /** Срок, месяцев */
  termMonths: number;
  /** Дата выдачи */
  startDate: ISODate;
  /** День платежа */
  paymentDay: number;
  paymentType: PaymentType;
  /** Остаток долга (если кредит уже идёт) */
  currentBalance?: number;

  /* --- кредитная карта и беспроцентный период --- */
  /** Кредитный лимит */
  limit?: number;
  /** Потрачено из лимита (задолженность) */
  used?: number;
  /** Длина беспроцентного периода, дней */
  graceDays?: number;
  /** День формирования выписки */
  statementDay?: number;
  /** Крайний день платежа (если не задан — считается как statementDay + graceDays) */
  gracePaymentDay?: number;
  /** Минимальный платёж, % от долга */
  minPaymentPercent?: number;
  /** Минимальный платёж, фикс */
  minPaymentFixed?: number;
  /** Как планируем гасить: полностью в беспроцентный период / минимум / своя сумма */
  repayMode: RepayMode;
  customRepayAmount?: number;

  /** Досрочное погашение сверх платежа (в месяц) */
  extraPayment: number;
  note?: string;
  color: string;
  active: boolean;
}

/* ------------------------------ Операции -------------------------------------- */

export type TxKind = 'income' | 'expense' | 'transfer';
export type TxStatus = 'planned' | 'done';
export type EventSourceType =
  | 'income'
  | 'subscription'
  | 'credit'
  | 'planned'
  | 'interest'
  | 'topup'
  | 'manual';

export interface Transaction {
  id: string;
  date: ISODate;
  /** Знак: >0 — поступление, <0 — списание */
  amount: number;
  currency: Currency;
  accountId: string;
  /** Счёт получателя для переводов */
  toAccountId?: string;
  categoryId?: string;
  title: string;
  note?: string;
  kind: TxKind;
  status: TxStatus;
  sourceType: EventSourceType;
  /** Ссылка на источник (IncomeSource / Subscription / Credit / Account) */
  sourceId?: string;
  /**
   * Стабильный ключ события: 'income:<id>:<date>:<payDayId>' и т.п.
   * Нужен, чтобы факт мог «погасить» план без дублей.
   */
  sourceKey?: string;
  /** Повторение для запланированных операций (аренда, ЖКХ и т.п.) */
  recurrence?: { every: number; unit: 'day' | 'week' | 'month' | 'year'; until?: ISODate };
  /** Плановая сумма, если факт отличается */
  plannedAmount?: number;
  tags?: string[];
  createdAt: number;
  updatedAt: number;
}

/* -------------------------------- Настройки ----------------------------------- */

export type RatesProvider = 'auto' | 'cbr' | 'ecb' | 'erapi' | 'manual';

export interface Settings {
  baseCurrency: Currency;
  ratesProvider: RatesProvider;
  /** Ручные курсы: 1 <baseCurrency> = X <currency> */
  manualRates: Record<string, number>;
  theme: 'dark' | 'light' | 'system';
  hideBalances: boolean;
  showCents: boolean;
  /** Начало «финансового месяца» (часто совпадает с днём зарплаты) */
  monthStartDay: number;
  firstDayOfWeek: 0 | 1 | 7;
  workweekOnly: boolean;
  locale: string;
  demoLoaded: boolean;
  onboarded: boolean;
}

export interface RatesSnapshot {
  provider: RatesProvider | string;
  base: Currency;
  /** Дата курса по данным провайдера */
  date: ISODate;
  fetchedAt: number;
  /** 1 единица base = rates[c] единиц валюты c; rates[base] = 1 */
  rates: Record<string, number>;
}

/* --------------------- Полное состояние приложения ---------------------------- */

export interface AppState {
  version: number;
  accounts: Account[];
  categories: Category[];
  incomes: IncomeSource[];
  subscriptions: Subscription[];
  credits: Credit[];
  transactions: Transaction[];
  rates: RatesSnapshot | null;
  settings: Settings;
  updatedAt: number;
}

/* --------------------------- События денежного потока -------------------------- */

export interface CashflowEvent {
  id: string;
  date: ISODate;
  title: string;
  /** >0 доход, <0 расход, в валюте `currency` */
  amount: number;
  currency: Currency;
  accountId: string;
  kind: TxKind | 'interest';
  sourceType: EventSourceType;
  sourceId: string;
  sourceKey: string;
  categoryId?: string;
  status: TxStatus;
  /** Сумма требует уточнения (сдельщик без суммы за месяц) */
  tentative?: boolean;
  note?: string;
  color?: string;
  icon?: string;
  /** Детализация для кредитов: сколько процентов, сколько тела долга */
  parts?: { principal?: number; interest?: number; fee?: number };
}

export interface DayPoint {
  date: ISODate;
  income: number;
  expense: number;
  interest: number;
  net: number;
  /** Суммарный баланс по всем счетам (в базовой валюте) на конец дня */
  balance: number;
  /** Балансы по каждому счёту в валюте счёта */
  byAccount: Record<string, number>;
}

export interface ProjectionResult {
  days: DayPoint[];
  events: CashflowEvent[];
  /** Суммарные проценты за период по счетам */
  interestByAccount: Record<string, number>;
  /** Минимальный баланс за период и его дата */
  min: { balance: number; date: ISODate } | null;
  max: { balance: number; date: ISODate } | null;
}
