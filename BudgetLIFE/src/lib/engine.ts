import type {
  Account,
  CashflowEvent,
  Category,
  Credit,
  Currency,
  DayPoint,
  IncomeSource,
  ISODate,
  ProjectionResult,
  Subscription,
  Transaction,
  YM,
} from '../types';
import { convert, type ConvertRates } from './rates';
import {
  addCycles,
  addYM,
  compareISO,
  cycleDays,
  daysInMonth,
  fromISO,
  isDayOff,
  resolvePayDay,
  toISO,
  todayISO,
  ymOf,
} from './dates';
import { cardPaymentDate, cardSchedule, loanSchedule } from './credit';

/* ============================================================================
 *  Движок денежного потока: превращает правила (источники дохода, подписки,
 *  кредиты, счета с процентами) в конкретные события по датам и проецирует
 *  баланс по дням.
 * ==========================================================================*/

export interface EngineCtx {
  accounts: Account[];
  categories: Category[];
  incomes: IncomeSource[];
  subscriptions: Subscription[];
  credits: Credit[];
  transactions: Transaction[];
  rates: ConvertRates;
  baseCurrency: Currency;
}

const isLeap = (y: number) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
const daysInYear = (d: Date) => (isLeap(d.getFullYear()) ? 366 : 365);

/* --------------------------- генерация событий ------------------------------- */

interface BuildOpts {
  /** Включать события пополнения счетов */
  topUps?: boolean;
  /** Только будущие события (по умолчанию — все в интервале) */
  onlyFuture?: boolean;
}

function accountOf(ctx: EngineCtx, id: string): Account | undefined {
  return ctx.accounts.find((a) => a.id === id);
}

/** Сумма выплаты с учётом долей по дням выплат */
function splitMonthAmount(source: IncomeSource, total: number): number[] {
  const pds = source.payDays;
  if (!pds.length) return [];
  const fixedSum = pds.reduce((s, p) => s + (p.amount ?? 0), 0);
  const definedShare = pds.reduce((s, p) => s + (p.amount == null ? (p.share ?? 0) : 0), 0);
  const free = pds.filter((p) => p.amount == null);

  return pds.map((p) => {
    if (p.amount != null) return p.amount;
    let share = p.share ?? 0;
    if (!share) {
      if (free.length === 0) share = 0;
      else if (definedShare > 0 && definedShare < 1) share = (1 - definedShare) / free.length;
      else share = pds.filter((x) => x.amount == null && !x.share).length
        ? (1 - definedShare) / Math.max(1, pds.filter((x) => x.amount == null && !x.share).length)
        : 1 / free.length;
    }
    return (total - fixedSum >= 0 ? total : total) * share;
  });
}

function mkEvent(e: Omit<CashflowEvent, 'id'>): CashflowEvent {
  return { ...e, id: `${e.sourceKey}` };
}

/** Даты зачисления процентов для счёта (для событий и капитализации) */
export function interestPayoutDates(acc: Account, from: ISODate, to: ISODate): ISODate[] {
  const cfg = acc.interest;
  if (!cfg.enabled || cfg.annualRate <= 0 || cfg.capitalization === 'none') return [];
  const out: ISODate[] = [];
  const day = cfg.payoutDay && cfg.payoutDay > 0 ? cfg.payoutDay : 31;
  let ym = ymOf(from);
  let guard = 0;
  while (ym <= ymOf(to) && guard++ < 800) {
    const [y, m] = ym.split('-').map(Number);
    const dim = daysInMonth(y, m);
    let date: ISODate | null = null;
    switch (cfg.capitalization) {
      case 'daily':
      case 'monthly':
        date = toISO(new Date(y, m - 1, Math.min(day, dim)));
        break;
      case 'quarterly':
        if (m % 3 === 0) date = toISO(new Date(y, m - 1, Math.min(day, dim)));
        break;
      case 'yearly': {
        const startMonth = cfg.termStart ? fromISO(cfg.termStart).getMonth() + 1 : 12;
        if (m === startMonth) date = toISO(new Date(y, m - 1, Math.min(day, dim)));
        break;
      }
      case 'endOfTerm':
        if (cfg.termEnd && cfg.termEnd >= from && cfg.termEnd <= to) out.push(cfg.termEnd);
        break;
      default:
        break;
    }
    if (date && date >= from && date <= to && !out.includes(date)) out.push(date);
    ym = addYM(ym, 1);
  }
  return out.sort();
}

/** Плановые суммы процентов по счёту (быстрая оценка, без проекции) */
export function estimateMonthlyInterest(acc: Account): number {
  const cfg = acc.interest;
  if (!cfg.enabled || cfg.annualRate <= 0) return 0;
  const base = acc.balance + (cfg.monthlyTopUp || 0) / 2;
  const yearly = (base * cfg.annualRate) / 100;
  const multiplier =
    cfg.capitalization === 'daily' ? 1.0025 : cfg.capitalization === 'monthly' ? 1 : 1;
  return (yearly / 12) * multiplier;
}


/**
 * Все выплаты источника дохода в конкретном месяце
 * с учётом ручных корректировок, налога и переноса с выходных.
 */
export function incomeMonthPayments(
  src: IncomeSource,
  ym: string,
): { id: string; label: string; date: ISODate; amount: number; tentative: boolean }[] {
  if (ym < src.startYM) return [];
  if (src.endYM && ym > src.endYM) return [];
  const ov = src.overrides?.[ym];
  if (ov?.skip) return [];
  const gross = ov?.amount ?? src.amount;
  const taxRate = src.tax?.enabled ? (src.tax.rate ?? 0) : 0;
  const net = gross * (1 - taxRate / 100);
  const tentative = src.variable && ov?.amount == null;
  const amounts = splitMonthAmount(src, net);

  return src.payDays
    .map((pd, i) => {
      const pdo = ov?.payDays?.find((p) => p.id === pd.id);
      let date = pdo?.date ?? resolvePayDay(ym, pd.day, pd.rule);
      if (pd.rule !== 'exact' && isDayOff(date)) date = resolvePayDay(ym, pd.day, pd.rule);
      return {
        id: pd.id,
        label: pd.label,
        date,
        amount: pdo?.amount ?? amounts[i] ?? 0,
        tentative,
        skipped: Boolean(pdo?.skipped),
      };
    })
    .filter((p) => !p.skipped);
}

/** Активен ли источник дохода в указанном месяце */
export function incomeActiveInMonth(src: IncomeSource, ym: string): boolean {
  if (ym < src.startYM) return false;
  if (src.endYM && ym > src.endYM) return false;
  return !src.overrides?.[ym]?.skip;
}

function incomeEvents(ctx: EngineCtx, from: ISODate, to: ISODate): CashflowEvent[] {
  const events: CashflowEvent[] = [];
  const fromYM = ymOf(from);
  const toYM = ymOf(to);

  for (const src of ctx.incomes) {
    if (!src.active) continue;
    const acc = accountOf(ctx, src.accountId);
    if (!acc) continue;

    const start = src.startYM > fromYM ? src.startYM : fromYM;
    const end = src.endYM && src.endYM < toYM ? src.endYM : toYM;
    if (start > end) continue;

    let ym = start;
    let guard = 0;
    while (ym <= end && guard++ < 600) {
      for (const p of incomeMonthPayments(src, ym)) {
        if (p.date < from || p.date > to) continue;
        const amount = convert(p.amount, src.currency, acc.currency, ctx.rates);
        events.push(
          mkEvent({
            date: p.date,
            title: src.payDays.length > 1 ? `${src.name} · ${p.label || 'выплата'}` : src.name,
            amount,
            currency: acc.currency,
            accountId: acc.id,
            kind: 'income',
            sourceType: 'income',
            sourceId: src.id,
            sourceKey: `income:${src.id}:${ym}:${p.id}`,
            categoryId: src.categoryId,
            status: 'planned',
            tentative: p.tentative,
            note: src.overrides?.[ym]?.note,
            color: '#10d19a',
            icon: 'Wallet',
          }),
        );
      }
      ym = addYM(ym, 1);
    }
  }
  return events;
}

function subscriptionEvents(ctx: EngineCtx, from: ISODate, to: ISODate): CashflowEvent[] {
  const events: CashflowEvent[] = [];
  for (const sub of ctx.subscriptions) {
    if (!sub.active) continue;
    const acc = accountOf(ctx, sub.accountId);
    if (!acc) continue;
    const { every, unit } = sub.cycle;
    const step = Math.max(1, every);

    // быстро прокручиваем циклы до начала периода
    let date = sub.startDate;
    if (date < from) {
      const cyclesBehind = Math.max(0, Math.ceil((fromISO(from).getTime() - fromISO(date).getTime()) / 86400000 / cycleDays(step, unit)) - 1);
      date = addCycles(date, step, unit, Math.max(0, cyclesBehind));
    }
    let guard = 0;
    while (date <= to && guard++ < 2000) {
      if (date >= from && date <= to) {
        if (sub.endDate && date > sub.endDate) break;
        if (!sub.trialUntil || date > sub.trialUntil) {
          const price =
            sub.priceHistory
              .filter((p) => p.from <= date)
              .sort((a, b) => (a.from < b.from ? 1 : -1))[0]?.amount ?? sub.amount;
          events.push(
            mkEvent({
              date,
              title: sub.name,
              amount: -Math.abs(convert(price, sub.currency, acc.currency, ctx.rates)),
              currency: acc.currency,
              accountId: acc.id,
              kind: 'expense',
              sourceType: 'subscription',
              sourceId: sub.id,
              sourceKey: `sub:${sub.id}:${date}`,
              categoryId: sub.categoryId,
              status: 'planned',
              color: sub.color,
              icon: sub.icon,
              note: sub.note,
            }),
          );
        }
      }
      date = addCycles(date, step, unit, 1);
    }
  }
  return events;
}

function creditEvents(ctx: EngineCtx, from: ISODate, to: ISODate): CashflowEvent[] {
  const events: CashflowEvent[] = [];
  for (const cr of ctx.credits) {
    if (!cr.active) continue;
    const acc = accountOf(ctx, cr.accountId);
    if (!acc) continue;

    if (cr.kind === 'credit_card') {
      const rows = cardSchedule(cr, from, to);
      for (const r of rows) {
        if (r.payment <= 0) continue;
        events.push(
          mkEvent({
            date: r.date,
            title: `${cr.name} · платёж`,
            amount: -Math.abs(convert(r.payment, cr.currency, acc.currency, ctx.rates)),
            currency: acc.currency,
            accountId: acc.id,
            kind: 'expense',
            sourceType: 'credit',
            sourceId: cr.id,
            sourceKey: `credit:${cr.id}:${r.date}`,
            status: 'planned',
            color: cr.color,
            icon: 'CreditCard',
            parts: { principal: r.principal, interest: r.interest },
            note:
              cr.repayMode === 'full'
                ? 'Погашение в беспроцентный период'
                : `В т.ч. проценты ${Math.round(r.interest)}`,
          }),
        );
      }
      continue;
    }

    const rows = loanSchedule(cr);
    for (const r of rows) {
      if (r.date < from || r.date > to) continue;
      const payment = r.payment + (cr.extraPayment || 0);
      events.push(
        mkEvent({
          date: r.date,
          title: `${cr.name} · платёж ${r.index}`,
          amount: -Math.abs(convert(payment, cr.currency, acc.currency, ctx.rates)),
          currency: acc.currency,
          accountId: acc.id,
          kind: 'expense',
          sourceType: 'credit',
          sourceId: cr.id,
          sourceKey: `credit:${cr.id}:${r.index}`,
          status: 'planned',
          color: cr.color,
          icon: 'Landmark',
          parts: { principal: r.principal + (cr.extraPayment || 0), interest: r.interest },
          note: `Остаток долга после платежа: ${Math.round(r.balance)}`,
        }),
      );
    }
  }
  return events;
}

function topUpEvents(ctx: EngineCtx, from: ISODate, to: ISODate): CashflowEvent[] {
  const events: CashflowEvent[] = [];
  for (const acc of ctx.accounts) {
    const cfg = acc.interest;
    if (!cfg.monthlyTopUp || cfg.monthlyTopUp <= 0 || acc.archived) continue;
    let ym = ymOf(from);
    let guard = 0;
    while (ym <= ymOf(to) && guard++ < 600) {
      if (cfg.topUpStartYM && ym < cfg.topUpStartYM) {
        ym = addYM(ym, 1);
        continue;
      }
      if (cfg.topUpEndYM && ym > cfg.topUpEndYM) break;
      const date = resolvePayDay(ym, cfg.topUpDay || 1, 'exact');
      if (date >= from && date <= to) {
        events.push(
          mkEvent({
            date,
            title: `Пополнение · ${acc.name}`,
            amount: Math.abs(cfg.monthlyTopUp),
            currency: acc.currency,
            accountId: acc.id,
            kind: 'income',
            sourceType: 'topup',
            sourceId: acc.id,
            sourceKey: `topup:${acc.id}:${ym}`,
            status: 'planned',
            color: '#38c3f5',
            icon: 'PlusCircle',
          }),
        );
      }
      ym = addYM(ym, 1);
    }
  }
  return events;
}

/** Даты повторения запланированной операции внутри интервала */
export function recurrenceDates(tx: Transaction, from: ISODate, to: ISODate): ISODate[] {
  const rec = tx.recurrence;
  if (!rec) return [tx.date];
  const step = Math.max(1, rec.every);
  const unit = rec.unit;
  let date = tx.date;
  // докручиваем до начала интервала
  if (date < from) {
    const spanDays = Math.max(0, (fromISO(from).getTime() - fromISO(date).getTime()) / 86400000);
    const perCycle = cycleDays(step, unit);
    date = addCycles(date, step, unit, Math.max(0, Math.floor(spanDays / perCycle)));
  }
  const out: ISODate[] = [];
  let guard = 0;
  while (date <= to && guard++ < 2000) {
    if (date >= from && (!rec.until || date <= rec.until)) out.push(date);
    date = addCycles(date, step, unit, 1);
  }
  if (!out.length && tx.date >= from && tx.date <= to) out.push(tx.date);
  return out;
}

function transactionEvents(ctx: EngineCtx, from: ISODate, to: ISODate): CashflowEvent[] {
  const events: CashflowEvent[] = [];
  for (const tx of ctx.transactions) {
    const acc = accountOf(ctx, tx.accountId);
    if (!acc) continue;
    const dates = tx.recurrence ? recurrenceDates(tx, from, to) : tx.date >= from && tx.date <= to ? [tx.date] : [];
    for (const date of dates) {
      const isOut = tx.amount < 0;
      const key = tx.sourceKey ?? `tx:${tx.id}`;
      events.push(
        mkEvent({
          date,
          title: tx.title,
          amount: tx.amount,
          currency: acc.currency,
          accountId: acc.id,
          kind: tx.kind,
          sourceType: tx.sourceType ?? 'manual',
          sourceId: tx.sourceId ?? tx.id,
          sourceKey: dates.length > 1 ? `${key}:${date}` : key,
          categoryId: tx.categoryId,
          status: tx.status,
          note: tx.note,
          color: isOut ? '#fb7d8e' : '#10d19a',
        }),
      );
      if (tx.kind === 'transfer' && tx.toAccountId) {
        const target = accountOf(ctx, tx.toAccountId);
        if (target) {
          const amount = convert(Math.abs(tx.amount), acc.currency, target.currency, ctx.rates);
          events.push(
            mkEvent({
              date,
              title: `${tx.title} → ${target.name}`,
              amount,
              currency: target.currency,
              accountId: target.id,
              kind: 'transfer',
              sourceType: tx.sourceType ?? 'manual',
              sourceId: tx.sourceId ?? tx.id,
              sourceKey: `${dates.length > 1 ? `${key}:${date}` : key}:in`,
              status: tx.status,
              note: tx.note,
              color: '#a78bfa',
            }),
          );
        }
      }
    }
  }
  return events;
}

/** События, сгенерированные правилами (без факта и без процентов) */
export function buildEvents(ctx: EngineCtx, from: ISODate, to: ISODate, opts: BuildOpts = {}): CashflowEvent[] {
  const { topUps = true } = opts;
  const generated: CashflowEvent[] = [
    ...incomeEvents(ctx, from, to),
    ...subscriptionEvents(ctx, from, to),
    ...creditEvents(ctx, from, to),
    ...(topUps ? topUpEvents(ctx, from, to) : []),
  ];

  // Операции, созданные вручную или как план бюджета
  const manual = transactionEvents(ctx, from, to);
  const all = [...generated, ...manual];

  // Подтверждённые операции (факт) перекрывают план по sourceKey
  const facts = new Map<string, Transaction>();
  for (const tx of ctx.transactions) {
    if (!tx.sourceKey || tx.status !== 'done') continue;
    facts.set(tx.sourceKey, tx);
  }

  const merged = new Map<string, CashflowEvent>();
  for (const e of all) {
    const fact = facts.get(e.sourceKey);
    if (fact && fact.status === 'done') {
      const acc = accountOf(ctx, fact.accountId);
      const resolved: CashflowEvent = {
        ...e,
        status: 'done' as const,
        amount: convert(fact.amount, fact.currency, e.currency, ctx.rates),
        accountId: fact.accountId ?? e.accountId,
        currency: acc?.currency ?? e.currency,
        title: fact.title || e.title,
        categoryId: fact.categoryId ?? e.categoryId,
        note: fact.note ?? e.note,
        tentative: false,
      };
      merged.set(e.sourceKey, resolved);
      continue;
    }
    const prev = merged.get(e.sourceKey);
    if (!prev || (prev.status === 'planned' && e.status === 'done')) merged.set(e.sourceKey, e);
  }

  const result = [...merged.values()];
  result.sort((a, b) => (a.date === b.date ? b.amount - a.amount : compareISO(a.date, b.date)));
  return result;
}

/* ------------------------------- проекция --------------------------------- */

export interface ProjectOptions {
  /** Считать проценты по счетам */
  withInterest?: boolean;
  /** С какой даты начинать кривую баланса (по умолчанию — сегодня) */
  startFrom?: ISODate;
}

/**
 * Дневная проекция: баланс по каждому счёту и суммарно,
 * с учётом всех правил, процентов и пополнений.
 */
export function project(ctx: EngineCtx, from: ISODate, to: ISODate, options: ProjectOptions = {}): ProjectionResult {
  const { withInterest = true, startFrom } = options;
  const today = todayISO();
  const loopStart = startFrom ?? (from < today ? today : from);

  const events = buildEvents(ctx, from, to);
  const byDate = new Map<ISODate, CashflowEvent[]>();
  for (const e of events) {
    const arr = byDate.get(e.date);
    if (arr) arr.push(e);
    else byDate.set(e.date, [e]);
  }

  const balances: Record<string, number> = {};
  for (const a of ctx.accounts) balances[a.id] = a.balance;

  const accrued: Record<string, number> = {};
  const payoutDates: Record<string, Set<string>> = {};
  const monthlyInterest: Record<string, number> = {};
  const interestByAccount: Record<string, number> = {};
  const interestEvents: CashflowEvent[] = [];

  if (withInterest) {
    for (const a of ctx.accounts) {
      accrued[a.id] = 0;
      monthlyInterest[a.id] = 0;
      payoutDates[a.id] = new Set(interestPayoutDates(a, loopStart, to));
    }
  }

  const days: DayPoint[] = [];
  let min: { balance: number; date: ISODate } | null = null;
  let max: { balance: number; date: ISODate } | null = null;

  const daysCount = Math.max(0, Math.round((fromISO(to).getTime() - fromISO(loopStart).getTime()) / 86400000) + 1);
  if (fromISO(to) < fromISO(loopStart)) {
    return { days, events, interestByAccount, min: null, max: null };
  }

  const cursor = fromISO(loopStart);
  for (let i = 0; i < daysCount; i++) {
    const date = toISO(cursor);
    const dayEvents = (byDate.get(date) ?? []).filter((e) => !(e.status === 'done' && e.date <= today));
    let income = 0;
    let expense = 0;
    let interestToday = 0;

    for (const e of dayEvents) {
      if (e.kind === 'transfer' && e.amount > 0) {
        balances[e.accountId] = (balances[e.accountId] ?? 0) + e.amount;
        continue;
      }
      balances[e.accountId] = (balances[e.accountId] ?? 0) + e.amount;
      const inBase = convert(e.amount, e.currency, ctx.baseCurrency, ctx.rates);
      if (inBase >= 0) income += inBase;
      else expense += -inBase;
    }

    // проценты
    if (withInterest) {
      for (const a of ctx.accounts) {
        const cfg = a.interest;
        if (!cfg.enabled || cfg.annualRate <= 0 || cfg.capitalization === 'none' || a.archived) continue;
        const bal = balances[a.id] ?? 0;
        const daily = (bal * (cfg.annualRate / 100)) / daysInYear(cursor);
        accrued[a.id] = (accrued[a.id] ?? 0) + daily;
        monthlyInterest[a.id] = (monthlyInterest[a.id] ?? 0) + daily;

        if (cfg.capitalization === 'daily') {
          balances[a.id] = bal + daily;
        }

        const isPayout = payoutDates[a.id]?.has(date);
        if (isPayout) {
          const sum = accrued[a.id] ?? 0;
          const inBase = convert(sum, a.currency, ctx.baseCurrency, ctx.rates);
          interestByAccount[a.id] = (interestByAccount[a.id] ?? 0) + inBase;
          interestToday += inBase;
          if (cfg.capitalization === 'daily') {
            // проценты уже зачислены ежедневно — только показываем итог за месяц
            interestEvents.push(
              mkEvent({
                date,
                title: `Проценты · ${a.name}`,
                amount: sum,
                currency: a.currency,
                accountId: a.id,
                kind: 'interest',
                sourceType: 'interest',
                sourceId: a.id,
                sourceKey: `interest:${a.id}:${date}`,
                status: 'planned',
                color: '#34e5b0',
                icon: 'Percent',
                note: 'Ежедневная капитализация',
              }),
            );
          } else if (cfg.payoutMode === 'payout' && cfg.payoutAccountId && cfg.payoutAccountId !== a.id) {
            const target = ctx.accounts.find((x) => x.id === cfg.payoutAccountId);
            if (target) {
              const amount = convert(sum, a.currency, target.currency, ctx.rates);
              balances[target.id] = (balances[target.id] ?? 0) + amount;
              interestEvents.push(
                mkEvent({
                  date,
                  title: `Проценты · ${a.name}`,
                  amount,
                  currency: target.currency,
                  accountId: target.id,
                  kind: 'interest',
                  sourceType: 'interest',
                  sourceId: a.id,
                  sourceKey: `interest:${a.id}:${date}`,
                  status: 'planned',
                  color: '#34e5b0',
                  icon: 'Percent',
                  note: 'Выплата процентов на другой счёт',
                }),
              );
            }
          } else {
            balances[a.id] = (balances[a.id] ?? 0) + sum;
            interestEvents.push(
              mkEvent({
                date,
                title: `Проценты · ${a.name}`,
                amount: sum,
                currency: a.currency,
                accountId: a.id,
                kind: 'interest',
                sourceType: 'interest',
                sourceId: a.id,
                sourceKey: `interest:${a.id}:${date}`,
                status: 'planned',
                color: '#34e5b0',
                icon: 'Percent',
                note: 'Капитализация процентов',
              }),
            );
          }
          accrued[a.id] = 0;
        }
      }
    }

    let total = 0;
    const byAccount: Record<string, number> = {};
    for (const a of ctx.accounts) {
      byAccount[a.id] = balances[a.id] ?? 0;
      if (a.includeInTotal && !a.archived) total += convert(balances[a.id] ?? 0, a.currency, ctx.baseCurrency, ctx.rates);
    }

    days.push({ date, income, expense, interest: interestToday, net: income - expense, balance: total, byAccount });
    if (!min || total < min.balance) min = { balance: total, date };
    if (!max || total > max.balance) max = { balance: total, date };

    cursor.setDate(cursor.getDate() + 1);
  }

  const allEvents = [...events, ...interestEvents].sort((a, b) =>
    a.date === b.date ? b.amount - a.amount : compareISO(a.date, b.date),
  );

  return { days, events: allEvents, interestByAccount, min, max };
}

/* ------------------------------ агрегаты ---------------------------------- */

export function sumBy<T>(items: T[], fn: (i: T) => number): number {
  return items.reduce((s, i) => s + (fn(i) || 0), 0);
}

export function monthBounds(ym: YM): { from: ISODate; to: ISODate } {
  const [y, m] = ym.split('-').map(Number);
  return {
    from: `${ym}-01`,
    to: toISO(new Date(y, m, 0)),
  };
}

/** «Финансовый месяц» с заданным днём начала (например, от зарплаты до зарплаты) */
export function financialMonthBounds(ref: ISODate, startDay: number): { from: ISODate; to: ISODate } {
  const d = fromISO(ref);
  const y = d.getFullYear();
  const m = d.getMonth() + 1;
  const dim = daysInMonth(y, m);
  const day = Math.min(Math.max(1, startDay), dim);
  const start = new Date(y, m - 1, day);
  let from: Date;
  let to: Date;
  if (d.getDate() >= day) {
    from = start;
    const nm = addYM(ymOf(ref), 1);
    const [ny, nmo] = nm.split('-').map(Number);
    const ndim = daysInMonth(ny, nmo);
    to = new Date(ny, nmo - 1, Math.min(Math.max(1, startDay), ndim));
    to.setDate(to.getDate() - 1);
  } else {
    const pm = addYM(ymOf(ref), -1);
    const [py, pmo] = pm.split('-').map(Number);
    const pdim = daysInMonth(py, pmo);
    from = new Date(py, pmo - 1, Math.min(Math.max(1, startDay), pdim));
    to = new Date(y, m - 1, day);
    to.setDate(to.getDate() - 1);
  }
  return { from: toISO(from), to: toISO(to) };
}

export function eventsInRange(events: CashflowEvent[], from: ISODate, to: ISODate): CashflowEvent[] {
  return events.filter((e) => e.date >= from && e.date <= to);
}

export function totalsOf(events: CashflowEvent[], ctx: EngineCtx) {
  let income = 0;
  let expense = 0;
  for (const e of events) {
    const v = convert(e.amount, e.currency, ctx.baseCurrency, ctx.rates);
    if (v >= 0) income += v;
    else expense += -v;
  }
  return { income, expense, net: income - expense };
}

export function categoryBreakdown(
  events: CashflowEvent[],
  ctx: EngineCtx,
  kind: 'income' | 'expense',
): { categoryId: string; name: string; color: string; value: number }[] {
  const map = new Map<string, number>();
  for (const e of events) {
    const v = convert(e.amount, e.currency, ctx.baseCurrency, ctx.rates);
    const isIncome = v >= 0;
    if (kind === 'income' ? !isIncome : isIncome) continue;
    const key = e.categoryId ?? '__none__';
    map.set(key, (map.get(key) ?? 0) + Math.abs(v));
  }
  return [...map.entries()]
    .map(([categoryId, value]) => {
      const cat = ctx.categories.find((c) => c.id === categoryId);
      return {
        categoryId,
        name: cat?.name ?? 'Без категории',
        color: cat?.color ?? '#64748b',
        value,
      };
    })
    .sort((a, b) => b.value - a.value);
}

export { cardPaymentDate };
