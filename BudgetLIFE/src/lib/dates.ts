import {
  addDays,
  addMonths,
  differenceInCalendarDays,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  parseISO,
  startOfMonth,
  startOfWeek,
} from 'date-fns';
import { ru } from 'date-fns/locale';
import type { CycleUnit, ISODate, YM } from '../types';

/* ------------------------------- базовое -------------------------------- */

export const pad2 = (n: number) => String(n).padStart(2, '0');

/** Date -> 'YYYY-MM-DD' (локальное время, без сдвига UTC) */
export function toISO(d: Date): ISODate {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

/** 'YYYY-MM-DD' -> Date (локальная полночь) */
export function fromISO(s: ISODate): Date {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(y, (m ?? 1) - 1, d ?? 1);
}

export const todayISO = (): ISODate => toISO(new Date());
export const nowYM = (): YM => toISO(new Date()).slice(0, 7);

export function daysInMonth(year: number, month1: number): number {
  return new Date(year, month1, 0).getDate();
}

export function ymOf(date: ISODate | Date): YM {
  const d = typeof date === 'string' ? fromISO(date) : date;
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

export function ymToDate(ym: YM, day = 1): Date {
  const [y, m] = ym.split('-').map(Number);
  return new Date(y, m - 1, Math.min(day, daysInMonth(y, m)));
}

export function ymLabel(ym: YM, short = false): string {
  const d = ymToDate(ym);
  return format(d, short ? 'LLL yyyy' : 'LLLL yyyy', { locale: ru });
}

export function ymRange(from: YM, to: YM): YM[] {
  const out: YM[] = [];
  let cur = from;
  let guard = 0;
  while (cur <= to && guard++ < 1200) {
    out.push(cur);
    cur = ymOf(toISO(addMonths(ymToDate(cur), 1)));
  }
  return out;
}

export function addYM(ym: YM, delta: number): YM {
  return ymOf(toISO(addMonths(ymToDate(ym), delta)));
}

export function compareISO(a: ISODate, b: ISODate): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

export function isBetween(date: ISODate, from: ISODate, to: ISODate): boolean {
  return date >= from && date <= to;
}

/* ---------------------------- производственный календарь ------------------------------ */

const FIXED_DAYOFFS = [
  '01-01',
  '01-02',
  '01-03',
  '01-04',
  '01-05',
  '01-06',
  '01-07',
  '01-08',
  '02-23',
  '03-08',
  '05-01',
  '05-02',
  '05-03',
  '05-04',
  '05-05',
  '05-06',
  '05-07',
  '05-08',
  '05-09',
  '06-12',
  '11-04',
  '12-31',
];

/** Суббота/воскресенье или общероссийский праздник */
export function isDayOff(d: Date | ISODate): boolean {
  const date = typeof d === 'string' ? fromISO(d) : d;
  const wd = date.getDay();
  if (wd === 0 || wd === 6) return true;
  const md = `${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
  return FIXED_DAYOFFS.includes(md);
}

export function isWeekendDay(d: Date | ISODate): boolean {
  const date = typeof d === 'string' ? fromISO(d) : d;
  const wd = date.getDay();
  return wd === 0 || wd === 6;
}

export function shiftToWorkday(d: Date, dir: -1 | 1): Date {
  let cur = d;
  let guard = 0;
  while (isDayOff(cur) && guard++ < 14) cur = addDays(cur, dir);
  return cur;
}

/* -------------------------- вычисление даты выплаты ---------------------------- */

/**
 * day > 0 — конкретный день месяца; -1 — последний день, -2 — предпоследний.
 * rule: exact | prevWorkday | nextWorkday
 */
export function resolvePayDay(
  ym: YM,
  day: number,
  rule: 'exact' | 'prevWorkday' | 'nextWorkday' = 'prevWorkday',
): ISODate {
  const [y, m] = ym.split('-').map(Number);
  const dim = daysInMonth(y, m);
  let d: number;
  if (day > 0) d = Math.min(day, dim);
  else d = Math.max(1, Math.min(dim, dim + 1 + day));
  const date = new Date(y, m - 1, d);
  if (rule === 'prevWorkday') return toISO(shiftToWorkday(date, -1));
  if (rule === 'nextWorkday') return toISO(shiftToWorkday(date, 1));
  return toISO(date);
}

export function describePayDay(day: number): string {
  if (day === -1) return 'последний день месяца';
  if (day === -2) return 'предпоследний день месяца';
  return `${day}-го числа`;
}

/* -------------------------------- циклы --------------------------------- */

/** Прибавить n циклов к дате */
export function addCycles(date: ISODate, every: number, unit: CycleUnit, n: number): ISODate {
  let d = fromISO(date);
  switch (unit) {
    case 'day':
      d = addDays(d, every * n);
      break;
    case 'week':
      d = addDays(d, every * 7 * n);
      break;
    case 'month': {
      const target = addMonths(d, every * n);
      // сохраняем день месяца (31 -> 28/30 при коротких месяцах)
      const dim = daysInMonth(target.getFullYear(), target.getMonth() + 1);
      const day = Math.min(fromISO(date).getDate(), dim);
      d = new Date(target.getFullYear(), target.getMonth(), day);
      break;
    }
    case 'year': {
      const target = addMonths(d, every * 12 * n);
      const dim = daysInMonth(target.getFullYear(), target.getMonth() + 1);
      const day = Math.min(fromISO(date).getDate(), dim);
      d = new Date(target.getFullYear(), target.getMonth(), day);
      break;
    }
  }
  return toISO(d);
}

/** Среднее количество дней в одном цикле (для пересчёта в «в месяц») */
export function cycleDays(every: number, unit: CycleUnit): number {
  const base = { day: 1, week: 7, month: 30.4375, year: 365.25 }[unit];
  return base * Math.max(1, every);
}

export function cycleLabel(every: number, unit: CycleUnit): string {
  const n = Math.max(1, every);
  const map: Record<CycleUnit, [string, string, string]> = {
    day: ['день', 'дня', 'дней'],
    week: ['неделю', 'недели', 'недель'],
    month: ['месяц', 'месяца', 'месяцев'],
    year: ['год', 'года', 'лет'],
  };
  const plural = pluralRu(n, map[unit]);
  return n === 1 ? `каждый ${map[unit][0]}`.replace('каждый день', 'ежедневно') : `раз в ${n} ${plural}`;
}

export function pluralRu(n: number, forms: [string, string, string]): string {
  const abs = Math.abs(Math.trunc(n)) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return forms[2];
  if (last > 1 && last < 5) return forms[1];
  if (last === 1) return forms[0];
  return forms[2];
}

/* ------------------------------- формат дат -------------------------------- */

export function fmtDate(iso: ISODate, pattern = 'd MMM yyyy'): string {
  return format(fromISO(iso), pattern, { locale: ru });
}

export function fmtDateShort(iso: ISODate): string {
  return format(fromISO(iso), 'd MMM', { locale: ru });
}

export function fmtDayNum(iso: ISODate): string {
  return format(fromISO(iso), 'd', { locale: ru });
}

export function weekdayShort(d: Date): string {
  return format(d, 'EEEEEE', { locale: ru });
}

export function humanRelative(iso: ISODate): string {
  const diff = differenceInCalendarDays(fromISO(iso), new Date());
  if (diff === 0) return 'сегодня';
  if (diff === 1) return 'завтра';
  if (diff === -1) return 'вчера';
  if (diff > 1 && diff < 7) return `через ${diff} ${pluralRu(diff, ['день', 'дня', 'дней'])}`;
  if (diff < -1 && diff > -7) return `${Math.abs(diff)} ${pluralRu(Math.abs(diff), ['день', 'дня', 'дней'])} назад`;
  if (diff >= 7) return `через ${Math.round(diff / 7)} ${pluralRu(Math.round(diff / 7), ['неделю', 'недели', 'недель'])}`;
  return `${Math.abs(Math.round(diff / 7))} ${pluralRu(Math.abs(Math.round(diff / 7)), ['неделю', 'недели', 'недель'])} назад`;
}

/* ------------------------------ календарная сетка ------------------------------ */

export interface CalCell {
  date: ISODate;
  inMonth: boolean;
  isToday: boolean;
  day: number;
}

export function monthGrid(ym: YM, firstDayOfWeek: 0 | 1 | 7 = 1): CalCell[] {
  const [y, m] = ym.split('-').map(Number);
  const first = new Date(y, m - 1, 1);
  const start = startOfWeek(first, { weekStartsOn: (firstDayOfWeek === 7 ? 0 : firstDayOfWeek) as 0 | 1 });
  const end = endOfWeek(endOfMonth(first), { weekStartsOn: (firstDayOfWeek === 7 ? 0 : firstDayOfWeek) as 0 | 1 });
  const days = eachDayOfInterval({ start, end });
  const today = todayISO();
  return days.map((d) => {
    const iso = toISO(d);
    return {
      date: iso,
      inMonth: d.getMonth() === m - 1 && d.getFullYear() === y,
      isToday: iso === today,
      day: d.getDate(),
    };
  });
}

/** Все дни интервала включительно */
export function dateRange(from: ISODate, to: ISODate): ISODate[] {
  return eachDayOfInterval({ start: fromISO(from), end: fromISO(to) }).map(toISO);
}

export function startOfMonthISO(ym: YM): ISODate {
  return toISO(startOfMonth(ymToDate(ym)));
}

export function endOfMonthISO(ym: YM): ISODate {
  return toISO(endOfMonth(ymToDate(ym)));
}

export function parseISODateSafe(s?: string): ISODate | undefined {
  if (!s) return undefined;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return undefined;
  const d = parseISO(s);
  return Number.isNaN(d.getTime()) ? undefined : s;
}

export { addDays, addMonths, startOfMonth, endOfMonth, eachDayOfInterval, differenceInCalendarDays, format, parseISO };
