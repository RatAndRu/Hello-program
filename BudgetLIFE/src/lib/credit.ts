import type { Credit, ISODate } from '../types';
import { addMonths, daysInMonth, fromISO, toISO, resolvePayDay, ymOf, addYM, ymToDate, todayISO } from './dates';

/* ============================================================================
 *  Кредиты: аннуитетные и дифференцированные платежи, кредитные карты
 *  с беспроцентным периодом.
 * ==========================================================================*/

export interface ScheduleRow {
  index: number;
  date: ISODate;
  payment: number;
  interest: number;
  principal: number;
  balance: number;
}

export const monthlyRate = (annualRate: number): number => annualRate / 100 / 12;

/** Аннуитетный платёж */
export function annuityPayment(principal: number, annualRate: number, termMonths: number): number {
  if (termMonths <= 0) return 0;
  const r = monthlyRate(annualRate);
  if (r === 0) return principal / termMonths;
  const k = Math.pow(1 + r, termMonths);
  return (principal * r * k) / (k - 1);
}

/** Полных месяцев, прошедших с даты выдачи кредита */
export function monthsElapsed(startDate: ISODate, ref: ISODate = todayISO()): number {
  const s = fromISO(startDate);
  const e = fromISO(ref);
  let m = (e.getFullYear() - s.getFullYear()) * 12 + (e.getMonth() - s.getMonth());
  if (e.getDate() < s.getDate()) m -= 1;
  return Math.max(0, m);
}

export function nextPaymentDate(startDate: ISODate, paymentDay: number, offsetMonths: number): ISODate {
  const s = fromISO(startDate);
  const d = addMonths(new Date(s.getFullYear(), s.getMonth(), 1), offsetMonths);
  const dim = daysInMonth(d.getFullYear(), d.getMonth() + 1);
  const day = Math.min(paymentDay > 0 ? paymentDay : dim, dim);
  return toISO(new Date(d.getFullYear(), d.getMonth(), day));
}

/**
 * График платежей по классическому кредиту / рассрочке.
 * Если задан currentBalance — строим остаток с сегодняшнего дня.
 */
export function loanSchedule(credit: Credit): ScheduleRow[] {
  const {
    principal,
    annualRate,
    termMonths,
    startDate,
    paymentDay,
    paymentType,
    currentBalance,
  } = credit;

  const rows: ScheduleRow[] = [];
  if (termMonths <= 0) return rows;

  const elapsed = monthsElapsed(startDate);
  const paidMonths = currentBalance != null ? Math.min(termMonths, elapsed + 1) : 0;
  const remainingMonths = Math.max(1, termMonths - paidMonths);
  let balance = currentBalance ?? principal;
  if (balance <= 0) return rows;

  const r = monthlyRate(annualRate);
  const basePrincipal = principal;
  const fixedPrincipalPart = basePrincipal / termMonths;
  const annuity = annuityPayment(balance, annualRate, remainingMonths);

  for (let i = 1; i <= remainingMonths; i++) {
    const date = nextPaymentDate(startDate, paymentDay, paidMonths + i);
    const interest = balance * r;
    let principalPart: number;
    let payment: number;

    if (paymentType === 'differentiated') {
      principalPart = Math.min(fixedPrincipalPart, balance);
      payment = principalPart + interest;
    } else {
      payment = annuity;
      principalPart = Math.min(payment - interest, balance);
      if (principalPart <= 0) principalPart = Math.min(payment, balance);
    }

    // последний платёж закрывает остаток
    if (i === remainingMonths || balance - principalPart < 0.01) {
      principalPart = balance;
      payment = principalPart + interest;
    }

    balance = Math.max(0, balance - principalPart);
    rows.push({
      index: paidMonths + i,
      date,
      payment,
      interest,
      principal: principalPart,
      balance,
    });
    if (balance <= 0) break;
  }
  return rows;
}

/* ---------------------------- кредитная карта -------------------------------- */

/** Дата выписки в указанном месяце */
export function statementDate(ym: string, day: number): ISODate {
  const d = ymToDate(ym);
  const dim = daysInMonth(d.getFullYear(), d.getMonth() + 1);
  return toISO(new Date(d.getFullYear(), d.getMonth(), Math.min(day, dim)));
}

/** Крайний день беспроцентного периода для выписки */
export function graceEndDate(credit: Credit, statement: ISODate): ISODate {
  const days = credit.graceDays ?? 0;
  if (credit.gracePaymentDay) {
    const d = fromISO(statement);
    const dim = daysInMonth(d.getFullYear(), d.getMonth() + 1);
    const day = Math.min(credit.gracePaymentDay, dim);
    return toISO(new Date(d.getFullYear(), d.getMonth(), day));
  }
  const d = fromISO(statement);
  return toISO(new Date(d.getFullYear(), d.getMonth(), d.getDate() + days));
}

/** Дата платежа по карте в месяце ym */
export function cardPaymentDate(credit: Credit, ym: string): ISODate {
  const d = ymToDate(ym);
  if (credit.gracePaymentDay) {
    const dim = daysInMonth(d.getFullYear(), d.getMonth() + 1);
    const day = Math.min(credit.gracePaymentDay, dim);
    const date = new Date(d.getFullYear(), d.getMonth(), day);
    if (credit.statementDay && day <= credit.statementDay) {
      return toISO(addMonths(date, 1));
    }
    return toISO(date);
  }
  if (credit.statementDay) {
    return graceEndDate(credit, statementDate(ym, credit.statementDay));
  }
  return resolvePayDay(ym, 15, 'prevWorkday');
}

export function minPayment(credit: Credit, debt = credit.used ?? 0): number {
  const fixed = credit.minPaymentFixed ?? 0;
  const percent = credit.minPaymentPercent ?? 5;
  return Math.max(fixed, (debt * percent) / 100);
}

/**
 * Сколько осталось дней беспроцентного периода и когда крайний срок платежа.
 * Для карты считаем ближайшую будущую выписку/платёж.
 */
export function graceInfo(credit: Credit, ref: ISODate = todayISO()) {
  if (credit.kind !== 'credit_card' || !credit.graceDays) return null;
  const statementDay = credit.statementDay ?? 1;
  let ym = ymOf(ref);
  let paymentDate = cardPaymentDate(credit, ym);
  let guard = 0;
  while (paymentDate < ref && guard++ < 14) {
    ym = addYM(ym, 1);
    paymentDate = cardPaymentDate(credit, ym);
  }
  const statement = statementDate(ym, statementDay);
  const end = credit.gracePaymentDay
    ? cardPaymentDate(credit, ym)
    : graceEndDate(credit, statement);
  const daysLeft = Math.round((fromISO(end).getTime() - fromISO(ref).getTime()) / 86400000);
  return {
    statementDate: statement < ref ? statementDate(addYM(ym, 1), statementDay) : statement,
    paymentDate: end,
    daysLeft,
    debt: credit.used ?? 0,
    toAvoidInterest: credit.used ?? 0,
  };
}

/** Сколько процентов «сгорит», если гасить только минимальными платежами */
export function minPaymentOutlook(credit: Credit, months = 12) {
  const rate = monthlyRate(credit.annualRate);
  let debt = credit.used ?? 0;
  let paidInterest = 0;
  for (let i = 0; i < months && debt > 0.01; i++) {
    const interest = debt * rate;
    const mp = minPayment(credit, debt);
    const principal = Math.max(0, mp - interest);
    paidInterest += interest;
    debt = Math.max(0, debt - principal);
    if (principal <= 0) return { monthsToClose: Infinity, paidInterest: Infinity, debt };
  }
  return { monthsToClose: debt <= 0.01 ? months : Infinity, paidInterest, debt };
}

export interface CardPlanRow {
  date: ISODate;
  payment: number;
  interest: number;
  principal: number;
  debt: number;
}

/** Плановые платежи по кредитной карте на период */
export function cardSchedule(credit: Credit, from: ISODate, to: ISODate): CardPlanRow[] {
  const rows: CardPlanRow[] = [];
  if (credit.kind !== 'credit_card') return rows;
  let debt = credit.used ?? 0;
  if (debt <= 0) return rows;
  const rate = monthlyRate(credit.annualRate);
  const payFull = credit.repayMode === 'full';

  let ym = ymOf(from);
  let guard = 0;
  while (ym <= ymOf(to) && guard++ < 600) {
    const date = cardPaymentDate(credit, ym);
    if (date >= from && date <= to && debt > 0.009) {
      const interest = payFull ? 0 : debt * rate;
      let payment: number;
      if (payFull) payment = debt;
      else if (credit.repayMode === 'custom') payment = Math.min(credit.customRepayAmount ?? 0, debt + interest);
      else payment = minPayment(credit, debt);
      payment = Math.min(payment, debt + interest);
      const principal = Math.max(0, payment - interest);
      debt = Math.max(0, debt - principal);
      rows.push({ date, payment, interest, principal, debt });
    }
    ym = addYM(ym, 1);
  }
  return rows;
}

/* ------------------------------- сводка ----------------------------------- */

export interface CreditSummary {
  debt: number;
  nextPayment?: { date: ISODate; amount: number; interest: number; principal: number };
  totalInterest: number;
  totalPayment: number;
  overpayment: number;
  payoffDate?: ISODate;
  monthlyPayment: number;
  grace?: ReturnType<typeof graceInfo>;
}

export function creditSummary(credit: Credit): CreditSummary {
  if (credit.kind === 'credit_card') {
    const grace = graceInfo(credit);
    const debt = credit.used ?? 0;
    const payFull = credit.repayMode === 'full';
    const interest = payFull ? 0 : debt * monthlyRate(credit.annualRate);
    const payment = payFull
      ? debt
      : credit.repayMode === 'custom'
        ? (credit.customRepayAmount ?? 0)
        : minPayment(credit, debt);
    const outlook = minPaymentOutlook(credit, 120);
    return {
      debt,
      nextPayment: grace ? { date: grace.paymentDate, amount: payment, interest, principal: Math.max(0, payment - interest) } : undefined,
      totalInterest: payFull ? 0 : outlook.paidInterest,
      totalPayment: debt + (payFull ? 0 : outlook.paidInterest),
      overpayment: payFull ? 0 : outlook.paidInterest,
      monthlyPayment: payment,
      grace,
    };
  }

  const rows = loanSchedule(credit);
  const totalInterest = rows.reduce((s, r) => s + r.interest, 0);
  const totalPayment = rows.reduce((s, r) => s + r.payment, 0);
  const next = rows.find((r) => r.date >= todayISO()) ?? rows[0];
  const balanceBase = credit.currentBalance ?? credit.principal;
  return {
    debt: rows.length ? rows[rows.length - 1].balance === 0 ? balanceBase : rows[0].balance : 0,
    nextPayment: next
      ? { date: next.date, amount: next.payment + (credit.extraPayment || 0), interest: next.interest, principal: next.principal }
      : undefined,
    totalInterest,
    totalPayment,
    overpayment: totalPayment - balanceBase,
    payoffDate: rows.length ? rows[rows.length - 1].date : undefined,
    monthlyPayment: rows.length ? rows[0].payment : 0,
  };
}
