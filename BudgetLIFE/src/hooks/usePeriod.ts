import { useMemo } from 'react';
import { useStore } from '../store/useStore';
import {
  addMonths,
  daysInMonth,
  fromISO,
  toISO,
  todayISO,
  ymLabel,
  ymOf,
} from '../lib/dates';
import type { ISODate } from '../types';

export interface Period {
  from: ISODate;
  to: ISODate;
  label: string;
  short: string;
  ym: string;
  financial: boolean;
}

/** Сдвиг периода на n периодов вперёд/назад */
export function periodBounds(ref: ISODate, startDay: number, offset = 0): Period {
  const d = fromISO(ref);
  const y = d.getFullYear();
  const m = d.getMonth() + 1;
  const dim = daysInMonth(y, m);
  const financial = startDay > 1;

  let from: Date;
  let to: Date;

  if (!financial) {
    from = new Date(y, m - 1, 1);
    to = new Date(y, m, 0);
  } else {
    const day = Math.min(startDay, dim);
    if (d.getDate() >= day) {
      from = new Date(y, m - 1, day);
      const nm = addMonths(new Date(y, m - 1, 1), 1);
      const ndim = daysInMonth(nm.getFullYear(), nm.getMonth() + 1);
      to = new Date(nm.getFullYear(), nm.getMonth(), Math.min(startDay, ndim));
      to.setDate(to.getDate() - 1);
    } else {
      const pm = addMonths(new Date(y, m - 1, 1), -1);
      const pdim = daysInMonth(pm.getFullYear(), pm.getMonth() + 1);
      from = new Date(pm.getFullYear(), pm.getMonth(), Math.min(startDay, pdim));
      to = new Date(y, m - 1, day);
      to.setDate(to.getDate() - 1);
    }
  }

  if (offset !== 0) {
    from = addMonths(from, offset);
    to = addMonths(to, offset);
  }

  const fromISODate = toISO(from);
  const toISODate = toISO(to);
  const label = financial
    ? `${fromISODate.slice(8, 10)}.${fromISODate.slice(5, 7)} — ${toISODate.slice(8, 10)}.${toISODate.slice(5, 7)}.${toISODate.slice(0, 4)}`
    : ymLabel(ymOf(fromISODate));

  return {
    from: fromISODate,
    to: toISODate,
    label,
    short: label,
    ym: ymOf(fromISODate),
    financial,
  };
}

/** Текущий финансовый месяц с учётом настройки «начало месяца» */
export function usePeriod(offset = 0): Period {
  const startDay = useStore((s) => s.data.settings.monthStartDay);
  const ref = todayISO();
  return useMemo(() => periodBounds(ref, startDay, offset), [ref, startDay, offset]);
}

export function usePeriodSeries(count = 6, endOffset = 0): Period[] {
  const startDay = useStore((s) => s.data.settings.monthStartDay);
  const ref = todayISO();
  return useMemo(
    () => Array.from({ length: count }, (_, i) => periodBounds(ref, startDay, i - count + 1 + endOffset)),
    [ref, startDay, count, endOffset],
  );
}
