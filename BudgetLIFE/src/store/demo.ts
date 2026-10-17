import type {
  Account,
  Category,
  Credit,
  IncomeSource,
  ISODate,
  Subscription,
  Transaction,
  AppState,
  YM,
} from '../types';
import { uid } from '../lib/id';
import {
  addYM,
  daysInMonth,
  fromISO,
  nowYM,
  resolvePayDay,
  toISO,
  todayISO,
} from '../lib/dates';
import { emptyInterest, EXPENSE_CATEGORIES, INCOME_CATEGORIES, PALETTE } from './defaults';

/* ============================================================================
 *  Демо-данные: «жизненный» сценарий, показывающий все возможности приложения.
 * ==========================================================================*/

/** Детерминированный генератор — демо выглядит одинаково при каждой загрузке */
function mulberry32(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const MONTHS_BACK = 4;

export function buildDemoState(): AppState {
  const rnd = mulberry32(20261006);
  const today = todayISO();
  const thisYM = nowYM();

  /* ---------------------------- категории ---------------------------- */
  const categories: Category[] = [
    ...EXPENSE_CATEGORIES.map(([name, icon, color], i) => ({
      id: `demo_cat_e_${i}`,
      name,
      kind: 'expense' as const,
      color,
      icon,
      order: i,
      budgetMonthly: [45000, 22000, 8000, 6000, 9000, 7000, 1800, 4000, 6000, 15000, 5000, 9000, 2200, 5000, 8000][i],
    })),
    ...INCOME_CATEGORIES.map(([name, icon, color], i) => ({
      id: `demo_cat_i_${i}`,
      name,
      kind: 'income' as const,
      color,
      icon,
      order: i,
    })),
  ];
  const cat = (kind: 'income' | 'expense', name: string) =>
    categories.find((c) => c.kind === kind && c.name === name)?.id;

  /* ----------------------------- счета ------------------------------- */
  const accCard: Account = {
    id: 'demo_acc_card',
    name: 'Карта «Чёрная»',
    type: 'card',
    currency: 'RUB',
    balance: 78_400,
    color: PALETTE[0],
    icon: 'CreditCard',
    includeInTotal: true,
    archived: false,
    order: 1,
    interest: { ...emptyInterest(), enabled: true, annualRate: 4, capitalization: 'monthly', payoutDay: 28 },
    note: 'Основная карта для ежедневных трат',
  };

  const accSavings: Account = {
    id: 'demo_acc_save',
    name: 'Накопительный «Копилка»',
    type: 'savings',
    currency: 'RUB',
    balance: 412_000,
    color: PALETTE[1],
    icon: 'PiggyBank',
    includeInTotal: true,
    archived: false,
    order: 2,
    interest: {
      ...emptyInterest(),
      enabled: true,
      annualRate: 13.2,
      capitalization: 'monthly',
      payoutDay: 30,
      payoutMode: 'compound',
      monthlyTopUp: 25_000,
      topUpDay: 6,
      topUpStartYM: thisYM,
    },
    note: 'Пополняю на 25 000 в месяц, проценты капитализируются',
  };

  const accDeposit: Account = {
    id: 'demo_acc_dep',
    name: 'Вклад «Прогресс»',
    type: 'deposit',
    currency: 'RUB',
    balance: 600_000,
    color: PALETTE[2],
    icon: 'Landmark',
    includeInTotal: true,
    archived: false,
    order: 3,
    interest: {
      ...emptyInterest(),
      enabled: true,
      annualRate: 15.4,
      capitalization: 'monthly',
      payoutDay: 25,
      payoutMode: 'payout',
      payoutAccountId: 'demo_acc_card',
      termStart: '2026-02-10',
      termEnd: '2027-02-10',
      monthlyTopUp: 0,
      topUpDay: 10,
    },
    note: 'Проценты выплачиваются на карту 25-го числа',
  };

  const accUsd: Account = {
    id: 'demo_acc_usd',
    name: 'Валютный счёт USD',
    type: 'savings',
    currency: 'USD',
    balance: 3_200,
    color: PALETTE[3],
    icon: 'Coins',
    includeInTotal: true,
    archived: false,
    order: 4,
    interest: { ...emptyInterest(), enabled: true, annualRate: 3.1, capitalization: 'monthly', payoutDay: 28 },
  };

  const accCash: Account = {
    id: 'demo_acc_cash',
    name: 'Наличные',
    type: 'cash',
    currency: 'RUB',
    balance: 14_500,
    color: PALETTE[4],
    icon: 'Banknote',
    includeInTotal: true,
    archived: false,
    order: 5,
    interest: emptyInterest(),
  };

  const accCrypto: Account = {
    id: 'demo_acc_usdt',
    name: 'Крипто USDT',
    type: 'crypto',
    currency: 'USDT',
    balance: 1_850,
    color: PALETTE[5],
    icon: 'Bitcoin',
    includeInTotal: true,
    archived: false,
    order: 6,
    interest: { ...emptyInterest(), enabled: true, annualRate: 6, capitalization: 'daily' },
  };

  const accCredit: Account = {
    id: 'demo_acc_credit',
    name: 'Кредитка «Платинум»',
    type: 'credit',
    currency: 'RUB',
    balance: -42_800,
    color: PALETTE[6],
    icon: 'CreditCard',
    includeInTotal: true,
    archived: false,
    order: 7,
    creditLimit: 200_000,
    interest: emptyInterest(),
  };

  const accounts: Account[] = [accCard, accSavings, accDeposit, accUsd, accCash, accCrypto, accCredit];

  /* ------------------------------ доходы ------------------------------ */
  const salary: IncomeSource = {
    id: 'demo_inc_salary',
    name: 'Зарплата (основная)',
    kind: 'salary',
    accountId: accCard.id,
    currency: 'RUB',
    amount: 210_000,
    variable: false,
    payDays: [
      { id: 'demo_pd_1', label: 'Аванс', day: 5, share: 0.4, rule: 'prevWorkday' },
      { id: 'demo_pd_2', label: 'Зарплата', day: 20, share: 0.6, rule: 'prevWorkday' },
    ],
    startYM: addYM(thisYM, -MONTHS_BACK),
    categoryId: cat('income', 'Зарплата'),
    active: true,
    tax: { enabled: true, rate: 13 },
    overrides: {},
    order: 1,
  };
  // корректировки: в прошлом месяце была премия, в этом — перенос аванса
  salary.overrides[addYM(thisYM, -1)] = { amount: 245_000, note: 'Премия за квартал' };
  salary.overrides[thisYM] = {
    payDays: [{ id: 'demo_pd_1', date: resolvePayDay(thisYM, 7, 'prevWorkday'), amount: 88_000 }],
    note: 'Аванс перенесли на 7-е',
  };
  salary.overrides[addYM(thisYM, 1)] = { amount: 210_000 };

  const freelance: IncomeSource = {
    id: 'demo_inc_free',
    name: 'Фриланс (сдельно)',
    kind: 'freelance',
    accountId: accCard.id,
    currency: 'RUB',
    amount: 48_000,
    variable: true,
    payDays: [{ id: 'demo_pd_3', label: 'Оплата проекта', day: -1, rule: 'prevWorkday' }],
    startYM: addYM(thisYM, -MONTHS_BACK),
    categoryId: cat('income', 'Фриланс'),
    active: true,
    overrides: {},
    order: 2,
    note: 'Сумма зависит от объёма заказов — уточняйте каждый месяц',
  };
  freelance.overrides[addYM(thisYM, -2)] = { amount: 63_500 };
  freelance.overrides[addYM(thisYM, -1)] = { amount: 31_000, note: 'Отпуск, мало заказов' };
  freelance.overrides[thisYM] = { amount: 52_000 };

  const rent: IncomeSource = {
    id: 'demo_inc_rent',
    name: 'Аренда квартиры',
    kind: 'rental',
    accountId: accSavings.id,
    currency: 'RUB',
    amount: 38_000,
    variable: false,
    payDays: [{ id: 'demo_pd_4', label: 'Аренда', day: 10, rule: 'nextWorkday' }],
    startYM: addYM(thisYM, -MONTHS_BACK),
    categoryId: cat('income', 'Аренда'),
    active: true,
    overrides: {},
    order: 3,
  };

  const incomes: IncomeSource[] = [salary, freelance, rent];

  /* ---------------------------- подписки ------------------------------ */
  const subs: Subscription[] = [
    {
      id: 'demo_sub_1',
      name: 'Яндекс Плюс',
      amount: 399,
      currency: 'RUB',
      cycle: { every: 1, unit: 'month' },
      startDate: '2025-11-03',
      categoryId: cat('expense', 'Подписки'),
      accountId: accCard.id,
      active: true,
      autoRenew: true,
      remindDays: 1,
      priceHistory: [],
      color: PALETTE[7],
      icon: 'Repeat',
    },
    {
      id: 'demo_sub_2',
      name: 'Кинопоиск',
      amount: 249,
      currency: 'RUB',
      cycle: { every: 1, unit: 'month' },
      startDate: '2025-09-14',
      categoryId: cat('expense', 'Развлечения'),
      accountId: accCard.id,
      active: true,
      autoRenew: true,
      remindDays: 0,
      priceHistory: [{ from: addYM(thisYM, -2) + '-14', amount: 299 }],
      color: PALETTE[8],
      icon: 'Clapperboard',
    },
    {
      id: 'demo_sub_3',
      name: 'ChatGPT Plus',
      amount: 20,
      currency: 'USD',
      cycle: { every: 1, unit: 'month' },
      startDate: '2026-01-18',
      categoryId: cat('expense', 'Подписки'),
      accountId: accCard.id,
      active: true,
      autoRenew: true,
      remindDays: 2,
      priceHistory: [],
      color: PALETTE[9],
      icon: 'Sparkles',
      note: 'Списывается в долларах — считаем по курсу',
    },
    {
      id: 'demo_sub_4',
      name: 'iCloud+ 2 ТБ',
      amount: 599,
      currency: 'RUB',
      cycle: { every: 1, unit: 'month' },
      startDate: '2025-06-21',
      categoryId: cat('expense', 'Связь и интернет'),
      accountId: accCard.id,
      active: true,
      autoRenew: true,
      remindDays: 0,
      priceHistory: [],
      color: PALETTE[10],
      icon: 'Cloud',
    },
    {
      id: 'demo_sub_5',
      name: 'Спортзал «Фитнес»',
      amount: 3_900,
      currency: 'RUB',
      cycle: { every: 1, unit: 'month' },
      startDate: '2026-03-05',
      categoryId: cat('expense', 'Спорт'),
      accountId: accCard.id,
      active: true,
      autoRenew: true,
      remindDays: 3,
      priceHistory: [],
      color: PALETTE[11],
      icon: 'Dumbbell',
      endDate: addYM(thisYM, 4) + '-05',
    },
    {
      id: 'demo_sub_6',
      name: 'Домен и хостинг',
      amount: 4_290,
      currency: 'RUB',
      cycle: { every: 1, unit: 'year' },
      startDate: '2025-12-09',
      categoryId: cat('expense', 'Прочее'),
      accountId: accCard.id,
      active: true,
      autoRenew: true,
      remindDays: 7,
      priceHistory: [],
      color: PALETTE[12],
      icon: 'Globe',
    },
    {
      id: 'demo_sub_7',
      name: 'Музыка',
      amount: 299,
      currency: 'RUB',
      cycle: { every: 1, unit: 'month' },
      startDate: '2026-07-01',
      categoryId: cat('expense', 'Развлечения'),
      accountId: accCard.id,
      active: true,
      autoRenew: true,
      remindDays: 0,
      trialUntil: addYM(thisYM, 1) + '-01',
      priceHistory: [],
      color: PALETTE[13],
      icon: 'Music',
      note: 'Пробный период — платные списания начнутся позже',
    },
    {
      id: 'demo_sub_8',
      name: 'Облачное хранилище (отключено)',
      amount: 1_290,
      currency: 'RUB',
      cycle: { every: 1, unit: 'month' },
      startDate: '2025-05-11',
      endDate: addYM(thisYM, -1) + '-11',
      categoryId: cat('expense', 'Прочее'),
      accountId: accCard.id,
      active: false,
      autoRenew: false,
      remindDays: 0,
      priceHistory: [],
      color: PALETTE[14],
      icon: 'HardDrive',
    },
  ];

  /* ----------------------------- кредиты ------------------------------ */
  const credits: Credit[] = [
    {
      id: 'demo_cr_card',
      name: 'Кредитка «Платинум»',
      kind: 'credit_card',
      accountId: accCard.id,
      currency: 'RUB',
      principal: 0,
      annualRate: 29.9,
      termMonths: 0,
      startDate: '2025-08-01',
      paymentDay: 25,
      paymentType: 'annuity',
      limit: 200_000,
      used: 42_800,
      graceDays: 55,
      statementDay: 5,
      gracePaymentDay: 25,
      minPaymentPercent: 8,
      minPaymentFixed: 1_000,
      repayMode: 'full',
      extraPayment: 0,
      color: PALETTE[6],
      active: true,
      note: 'Погашаю полностью в беспроцентный период',
    },
    {
      id: 'demo_cr_car',
      name: 'Автокредит',
      kind: 'loan',
      accountId: accCard.id,
      currency: 'RUB',
      principal: 1_450_000,
      annualRate: 12.9,
      termMonths: 60,
      startDate: '2025-10-15',
      paymentDay: 15,
      paymentType: 'annuity',
      currentBalance: 1_268_000,
      repayMode: 'min',
      extraPayment: 5_000,
      color: PALETTE[3],
      active: true,
      note: 'Досрочно гашу +5 000 сверх платежа',
    },
    {
      id: 'demo_cr_tech',
      name: 'Рассрочка на технику',
      kind: 'installment',
      accountId: accCard.id,
      currency: 'RUB',
      principal: 96_000,
      annualRate: 0,
      termMonths: 12,
      startDate: addYM(thisYM, -5) + '-10',
      paymentDay: 10,
      paymentType: 'annuity',
      currentBalance: 48_000,
      repayMode: 'min',
      extraPayment: 0,
      color: PALETTE[1],
      active: true,
    },
  ];

  /* ------------------- план бюджета (регулярные траты) ------------------ */
  const planned: Transaction[] = [];
  const push = (
    title: string,
    amount: number,
    day: number,
    categoryName: string,
    accountId: string,
    opts: Partial<Transaction> = {},
  ) => {
    planned.push({
      id: uid('tx'),
      date: resolvePayDay(thisYM, day, 'exact'),
      amount: -Math.abs(amount),
      currency: accounts.find((a) => a.id === accountId)?.currency ?? 'RUB',
      accountId,
      categoryId: cat('expense', categoryName),
      title,
      kind: 'expense',
      status: 'planned',
      sourceType: 'planned',
      recurrence: { every: 1, unit: 'month' },
      createdAt: Date.now(),
      updatedAt: Date.now(),
      ...opts,
    });
  };

  push('Аренда квартиры', 45_000, 3, 'Жильё', accCard.id);
  push('Коммуналка и ЖКХ', 7_400, 15, 'Жильё', accCard.id);
  push('Интернет и ТВ', 950, 12, 'Связь и интернет', accCard.id);
  push('Мобильная связь', 750, 12, 'Связь и интернет', accCard.id);
  push('Продукты (недельный запас)', 6_500, 1, 'Еда и продукты', accCard.id, {
    recurrence: { every: 1, unit: 'week' },
  });
  push('Транспорт / бензин', 4_200, 8, 'Транспорт', accCard.id);
  push('Кафе и доставка', 9_000, 20, 'Кафе и рестораны', accCard.id);
  push('Образование (курсы)', 6_900, 18, 'Образование', accCard.id, {
    recurrence: { every: 1, unit: 'month', until: addYM(thisYM, 5) + '-18' },
  });

  // разовые планы
  const oneOff: [string, number, string, string, number][] = [
    ['Отпуск: билеты', 68_000, 'Путешествия', accCard.id, 12],
    ['Новая зимняя резина', 34_500, 'Транспорт', accCard.id, 22],
    ['Подарок маме', 15_000, 'Подарки', accCard.id, 26],
    ['Стоматология', 22_000, 'Здоровье', accCard.id, 28],
    ['Ноутбук (апгрейд)', 95_000, 'Прочее', accSavings.id, 24],
  ];
  const nextYM = addYM(thisYM, 1);
  for (const [title, amount, categoryName, accountId, day] of oneOff) {
    planned.push({
      id: uid('tx'),
      date: resolvePayDay(nextYM, day, 'exact'),
      amount: -Math.abs(amount),
      currency: 'RUB',
      accountId,
      categoryId: cat('expense', categoryName),
      title,
      kind: 'expense',
      status: 'planned',
      sourceType: 'planned',
      createdAt: Date.now(),
      updatedAt: Date.now(),
    });
  }

  /* ----------------------- факты за прошлые месяцы ---------------------- */
  const facts: Transaction[] = [];

  // доходы по графику: прошедшие выплаты считаем полученными
  for (const src of incomes) {
    for (let k = MONTHS_BACK; k >= 0; k--) {
      const ym = addYM(thisYM, -k);
      if (ym < src.startYM) continue;
      const ov = src.overrides?.[ym];
      if (ov?.skip) continue;
      const total = ov?.amount ?? src.amount;
      const tax = src.tax?.enabled ? 1 - (src.tax.rate ?? 0) / 100 : 1;
      for (const pd of src.payDays) {
        const pdo = ov?.payDays?.find((p) => p.id === pd.id);
        if (pdo?.skipped) continue;
        const date = pdo?.date ?? resolvePayDay(ym, pd.day, pd.rule);
        if (date > today) continue;
        const raw = pdo?.amount ?? pd.amount ?? (pd.share != null ? total * pd.share : total);
        const amount = Math.round(raw * tax);
        facts.push({
          id: uid('tx'),
          date,
          amount,
          currency: src.currency,
          accountId: src.accountId,
          categoryId: src.categoryId,
          title: src.payDays.length > 1 ? `${src.name} · ${pd.label}` : src.name,
          kind: 'income',
          status: 'done',
          sourceType: 'income',
          sourceId: src.id,
          sourceKey: `income:${src.id}:${ym}:${pd.id}`,
          createdAt: Date.now(),
          updatedAt: Date.now(),
        });
      }
    }
  }

  // ежемесячные обязательные траты в прошлом
  for (let k = MONTHS_BACK; k >= 0; k--) {
    const ym = addYM(thisYM, -k);
    const addFact = (
      title: string,
      amount: number,
      day: number,
      categoryName: string,
      accountId: string,
    ) => {
      const date = resolvePayDay(ym, day, 'exact');
      if (date > today) return;
      facts.push({
        id: uid('tx'),
        date,
        amount: -Math.abs(amount),
        currency: 'RUB',
        accountId,
        categoryId: cat('expense', categoryName),
        title,
        kind: 'expense',
        status: 'done',
        sourceType: 'manual',
        createdAt: Date.now(),
        updatedAt: Date.now(),
      });
    };
    addFact('Аренда квартиры', 45_000, 3, 'Жильё', accCard.id);
    addFact('Коммуналка и ЖКХ', Math.round(6_200 + rnd() * 2_600), 15, 'Жильё', accCard.id);
    addFact('Интернет и ТВ', 950, 12, 'Связь и интернет', accCard.id);
    addFact('Мобильная связь', 750, 12, 'Связь и интернет', accCard.id);
    addFact('Транспорт / бензин', Math.round(3_400 + rnd() * 2_200), 8, 'Транспорт', accCard.id);
  }

  // подписки в прошлом (факт)
  for (const sub of subs) {
    if (!sub.active) continue;
    let date = sub.startDate;
    let guard = 0;
    while (date <= today && guard++ < 400) {
      if (date >= addYM(thisYM, -MONTHS_BACK) + '-01') {
        const price =
          sub.priceHistory.filter((p) => p.from <= date).sort((a, b) => (a.from < b.from ? 1 : -1))[0]?.amount ??
          sub.amount;
        facts.push({
          id: uid('tx'),
          date,
          amount: -Math.abs(price),
          currency: sub.currency,
          accountId: sub.accountId,
          categoryId: sub.categoryId,
          title: sub.name,
          kind: 'expense',
          status: 'done',
          sourceType: 'subscription',
          sourceId: sub.id,
          sourceKey: `sub:${sub.id}:${date}`,
          createdAt: Date.now(),
          updatedAt: Date.now(),
        });
      }
      const d = fromISO(date);
      const next =
        sub.cycle.unit === 'month'
          ? new Date(d.getFullYear(), d.getMonth() + sub.cycle.every, d.getDate())
          : sub.cycle.unit === 'year'
            ? new Date(d.getFullYear() + sub.cycle.every, d.getMonth(), d.getDate())
            : new Date(d.getTime() + sub.cycle.every * (sub.cycle.unit === 'week' ? 7 : 1) * 86400000);
      const dim = daysInMonth(next.getFullYear(), next.getMonth() + 1);
      date = toISO(new Date(next.getFullYear(), next.getMonth(), Math.min(d.getDate(), dim)));
    }
  }

  // платежи по кредитам в прошлом
  for (const cr of credits) {
    if (cr.kind === 'credit_card') continue;
    let ym: YM = cr.startDate.slice(0, 7);
    let guard = 0;
    while (ym < thisYM && guard++ < 200) {
      const date = resolvePayDay(ym, cr.paymentDay, 'exact');
      if (date >= addYM(thisYM, -MONTHS_BACK) + '-01' && date <= today && date >= cr.startDate) {
        const perMonth = cr.kind === 'installment' ? cr.principal / cr.termMonths : Math.round(cr.principal / cr.termMonths * 1.25);
        facts.push({
          id: uid('tx'),
          date,
          amount: -Math.abs(perMonth + (cr.extraPayment || 0)),
          currency: cr.currency,
          accountId: cr.accountId,
          categoryId: cat('expense', 'Прочее'),
          title: `${cr.name} · платёж`,
          kind: 'expense',
          status: 'done',
          sourceType: 'credit',
          sourceId: cr.id,
          sourceKey: `credit:${cr.id}:${ym}`,
          createdAt: Date.now(),
          updatedAt: Date.now(),
        });
      }
      ym = addYM(ym, 1);
    }
  }

  // случайные бытовые траты
  const everyday: [string, string, number, number][] = [
    ['Пятёрочка', 'Еда и продукты', 900, 3_200],
    ['Кафе «Дача»', 'Кафе и рестораны', 600, 4_500],
    ['Такси', 'Транспорт', 350, 1_900],
    ['Аптека', 'Здоровье', 400, 4_800],
    ['Кино', 'Развлечения', 500, 2_400],
    ['H&M', 'Одежда', 1_500, 9_000],
    ['Стирка/химчистка', 'Прочее', 400, 2_000],
    ['Книги', 'Образование', 500, 3_500],
  ];
  const start = fromISO(addYM(thisYM, -MONTHS_BACK) + '-01');
  for (let i = 0; i < 150; i++) {
    const dayOffset = Math.floor(rnd() * (MONTHS_BACK * 31));
    const d = new Date(start.getTime() + dayOffset * 86400000);
    if (d > new Date()) continue;
    const [title, categoryName, min, max] = everyday[Math.floor(rnd() * everyday.length)];
    const amount = Math.round((min + rnd() * (max - min)) / 10) * 10;
    facts.push({
      id: uid('tx'),
      date: toISO(d),
      amount: -amount,
      currency: 'RUB',
      accountId: rnd() > 0.82 ? accCash.id : accCard.id,
      categoryId: cat('expense', categoryName),
      title,
      kind: 'expense',
      status: 'done',
      sourceType: 'manual',
      createdAt: Date.now(),
      updatedAt: Date.now(),
    });
  }

  // перевод между счетами
  facts.push({
    id: uid('tx'),
    date: resolvePayDay(addYM(thisYM, -1), 6, 'exact'),
    amount: -25_000,
    currency: 'RUB',
    accountId: accCard.id,
    toAccountId: accSavings.id,
    title: 'Отложить на накопления',
    kind: 'transfer',
    status: 'done',
    sourceType: 'manual',
    createdAt: Date.now(),
    updatedAt: Date.now(),
  });

  facts.sort((a, b) => (a.date < b.date ? -1 : 1));

  return {
    version: 1,
    accounts,
    categories,
    incomes,
    subscriptions: subs,
    credits,
    transactions: [...facts, ...planned],
    rates: null,
    settings: {
      baseCurrency: 'RUB',
      ratesProvider: 'auto',
      manualRates: {},
      theme: 'dark',
      hideBalances: false,
      showCents: true,
      monthStartDay: 5,
      firstDayOfWeek: 1,
      workweekOnly: false,
      locale: 'ru-RU',
      demoLoaded: true,
      onboarded: true,
    },
    updatedAt: Date.now(),
  };
}

export const DEMO_LABEL = 'Демо-данные';
export type DemoISODate = ISODate;
