import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { useStore } from '../store/useStore';
import { useCtx, useEvents, useProjection } from '../store/useEngine';
import { Card, Button, Chip, IconButton, Modal, Segmented, EmptyState, Badge } from '../components/ui/primitives';
import { QuickAddTx } from '../components/QuickAddTx';
import { EventRow, EventIcon } from '../components/EventRow';
import {
  addYM,
  endOfMonthISO,
  fmtDate,
  fromISO,
  isDayOff,
  monthGrid,
  nowYM,
  startOfMonthISO,
  todayISO,
  ymLabel,
  weekdayShort,
} from '../lib/dates';
import { convert } from '../lib/rates';
import { fmtMoney } from '../lib/format';
import type { CashflowEvent } from '../types';

const TYPE_FILTERS = [
  { id: 'income', label: 'Доходы', icon: 'TrendingUp', color: '#10d19a' },
  { id: 'subscription', label: 'Подписки', icon: 'Repeat', color: '#8b5cf6' },
  { id: 'credit', label: 'Кредиты', icon: 'CreditCard', color: '#f43f5e' },
  { id: 'planned', label: 'План', icon: 'Receipt', color: '#38c3f5' },
  { id: 'manual', label: 'Операции', icon: 'Wallet', color: '#fbbf5c' },
  { id: 'interest', label: 'Проценты', icon: 'Percent', color: '#34e5b0' },
] as const;

export default function CalendarPage() {
  const data = useStore((s) => s.data);
  const ctx = useCtx();
  const settings = data.settings;
  const base = settings.baseCurrency;
  const hide = settings.hideBalances;
  const today = todayISO();

  const [ym, setYm] = useState(nowYM());
  const [selected, setSelected] = useState(today);
  const [types, setTypes] = useState<Set<string>>(new Set(TYPE_FILTERS.map((t) => t.id)));
  const [accountFilter, setAccountFilter] = useState('');
  const [showDone, setShowDone] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [view, setView] = useState<'month' | 'list'>('month');

  const from = startOfMonthISO(ym);
  const to = endOfMonthISO(ym);
  const rawEvents = useEvents(from, to);
  const projection = useProjection(from, to);

  const accountsMap = useMemo(() => new Map(data.accounts.map((a) => [a.id, a])), [data.accounts]);

  const events = useMemo(
    () =>
      rawEvents.filter((e) => {
        if (!types.has(e.sourceType)) return false;
        if (accountFilter && e.accountId !== accountFilter) return false;
        if (!showDone && e.status === 'done') return false;
        return true;
      }),
    [rawEvents, types, accountFilter, showDone],
  );

  const byDay = useMemo(() => {
    const map = new Map<string, CashflowEvent[]>();
    for (const e of events) {
      const arr = map.get(e.date);
      if (arr) arr.push(e);
      else map.set(e.date, [e]);
    }
    return map;
  }, [events]);

  const dayTotals = useMemo(() => {
    const map = new Map<string, { income: number; expense: number }>();
    for (const [date, list] of byDay) {
      let income = 0;
      let expense = 0;
      for (const e of list) {
        const v = convert(e.amount, e.currency, base, ctx.rates);
        if (v >= 0) income += v;
        else expense += -v;
      }
      map.set(date, { income, expense });
    }
    return map;
  }, [byDay, base, ctx.rates]);

  const cells = useMemo(() => monthGrid(ym, settings.firstDayOfWeek), [ym, settings.firstDayOfWeek]);
  const monthTotals = useMemo(() => {
    let income = 0;
    let expense = 0;
    for (const v of dayTotals.values()) {
      income += v.income;
      expense += v.expense;
    }
    return { income, expense, net: income - expense };
  }, [dayTotals]);

  const balanceAt = useMemo(() => {
    const map = new Map<string, number>();
    for (const d of projection.days) map.set(d.date, d.balance);
    return map;
  }, [projection.days]);

  const selectedEvents = (byDay.get(selected) ?? []).slice().sort((a, b) => b.amount - a.amount);
  const monthEndBalance = balanceAt.get(to) ?? projection.days[projection.days.length - 1]?.balance ?? 0;

  const listEvents = useMemo(
    () => events.slice().sort((a, b) => (a.date === b.date ? b.amount - a.amount : a.date < b.date ? -1 : 1)),
    [events],
  );

  const toggleType = (id: string) =>
    setTypes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const weekDays = useMemo(() => cells.slice(0, 7).map((c) => weekdayShort(fromISO(c.date))), [cells]);

  return (
    <div className="space-y-4">
      {/* ------------------------------ панель управления ----------------------------- */}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-1.5">
            <IconButton icon="ChevronLeft" label="Предыдущий месяц" onClick={() => setYm(addYM(ym, -1))} />
            <div className="min-w-[168px] px-1 text-center">
              <div className="text-[15px] font-semibold capitalize text-slate-100">{ymLabel(ym)}</div>
              <div className="text-[11px] text-slate-500">
                {monthTotals.income > 0 || monthTotals.expense > 0
                  ? `+${fmtMoney(monthTotals.income, base, { hide, compact: true })} / −${fmtMoney(monthTotals.expense, base, { hide, compact: true })}`
                  : 'нет операций'}
              </div>
            </div>
            <IconButton icon="ChevronRight" label="Следующий месяц" onClick={() => setYm(addYM(ym, 1))} />
            <Button variant="ghost" size="sm" className="ml-1" onClick={() => { setYm(nowYM()); setSelected(today); }}>
              Сегодня
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Segmented
              size="sm"
              value={view}
              onChange={setView}
              options={[
                { value: 'month', label: 'Сетка', icon: 'CalendarDays' },
                { value: 'list', label: 'Списком', icon: 'Layers' },
              ]}
            />
            <select
              className="select w-auto py-1.5 text-[13px]"
              value={accountFilter}
              onChange={(e) => setAccountFilter(e.target.value)}
            >
              <option value="">Все счета</option>
              {data.accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <Button variant="ghost" size="sm" onClick={() => setShowDone((v) => !v)} icon={showDone ? 'Eye' : 'EyeOff'}>
              {showDone ? 'С фактом' : 'Только план'}
            </Button>
            <Button variant="primary" size="sm" icon="Plus" onClick={() => setAddOpen(true)}>
              На {fmtDate(selected, 'd MMM')}
            </Button>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {TYPE_FILTERS.map((t) => (
            <Chip key={t.id} active={types.has(t.id)} onClick={() => toggleType(t.id)} icon={t.icon}>
              {t.label}
            </Chip>
          ))}
          <button
            className="ml-1 text-[11px] text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline"
            onClick={() => setTypes(new Set(TYPE_FILTERS.map((t) => t.id)))}
          >
            показать все
          </button>
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        {/* --------------------------------- сетка --------------------------------- */}
        <Card pad={false} className="overflow-hidden">
          <div className="grid grid-cols-7 border-b border-white/[0.07] bg-white/[0.02]">
            {weekDays.map((w, i) => (
              <div
                key={i}
                className={clsx(
                  'px-2 py-2 text-center text-[11px] font-semibold uppercase tracking-wide',
                  fromISO(cells[i]?.date ?? today).getDay() === 0 || fromISO(cells[i]?.date ?? today).getDay() === 6
                    ? 'text-rose-400/70'
                    : 'text-slate-400',
                )}
              >
                {w}
              </div>
            ))}
          </div>

          <div className="grid grid-cols-7">
            {cells.map((cell) => {
              const list = byDay.get(cell.date) ?? [];
              const totals = dayTotals.get(cell.date);
              const balance = balanceAt.get(cell.date);
              const off = isDayOff(cell.date);
              const isSelected = cell.date === selected;
              const inFuture = cell.date >= today;

              return (
                <button
                  key={cell.date}
                  onClick={() => setSelected(cell.date)}
                  onDoubleClick={() => setAddOpen(true)}
                  className={clsx(
                    'group relative flex min-h-[104px] flex-col gap-1 border-b border-r border-white/[0.05] p-1.5 text-left transition',
                    cell.inMonth ? 'bg-transparent' : 'bg-ink-950/40',
                    off && cell.inMonth && 'bg-white/[0.012]',
                    'hover:bg-white/[0.04]',
                    isSelected && 'ring-1 ring-inset ring-brand-400/70',
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span
                      className={clsx(
                        'num grid h-6 w-6 place-items-center rounded-md text-[12px] font-semibold',
                        cell.isToday
                          ? 'bg-gradient-to-br from-brand-400 to-brand-600 text-ink-950'
                          : off
                            ? 'text-rose-400/80'
                            : cell.inMonth
                              ? 'text-slate-300'
                              : 'text-slate-600',
                      )}
                    >
                      {cell.day}
                    </span>
                    {totals && (totals.income > 0 || totals.expense > 0) && (
                      <span className="flex flex-col items-end gap-0.5">
                        {totals.income > 0 && (
                          <span className="num text-[9.5px] font-semibold text-mint-400">
                            +{fmtMoney(totals.income, base, { hide, cents: false, compact: true, tight: true })}
                          </span>
                        )}
                        {totals.expense > 0 && (
                          <span className="num text-[9.5px] font-semibold text-rose-400/90">
                            −{fmtMoney(totals.expense, base, { hide, cents: false, compact: true, tight: true })}
                          </span>
                        )}
                      </span>
                    )}
                  </div>

                  <div className="flex flex-1 flex-col gap-[3px] overflow-hidden">
                    {list.slice(0, 3).map((e) => (
                      <div
                        key={`${e.sourceKey}-${e.accountId}-${e.amount}`}
                        className="flex items-center gap-1 overflow-hidden rounded-[5px] px-1 py-[2px] text-[9.5px] leading-tight"
                        style={{
                          background: `${e.color ?? '#38c3f5'}1f`,
                          color: `${e.color ?? '#38c3f5'}`,
                          opacity: e.status === 'done' ? 0.5 : 1,
                        }}
                        title={`${e.title}: ${fmtMoney(e.amount, e.currency)}`}
                      >
                        <span className="truncate">{e.title}</span>
                      </div>
                    ))}
                    {list.length > 3 && (
                      <span className="px-1 text-[9px] font-medium text-slate-500">+{list.length - 3} ещё</span>
                    )}
                  </div>

                  {balance !== undefined && inFuture && (
                    <div className="num mt-auto text-right text-[9.5px] text-slate-500">
                      {fmtMoney(balance, base, { hide, cents: false, compact: true, tight: true })}
                    </div>
                  )}
                </button>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.07] bg-white/[0.02] px-3 py-2.5 text-[11.5px]">
            <span className="flex items-center gap-4">
              <span className="text-slate-400">
                Доходы: <b className="num text-mint-400">{fmtMoney(monthTotals.income, base, { hide, compact: true })}</b>
              </span>
              <span className="text-slate-400">
                Расходы: <b className="num text-rose-400">{fmtMoney(monthTotals.expense, base, { hide, compact: true })}</b>
              </span>
              <span className="text-slate-400">
                Сальдо:{' '}
                <b className={clsx('num', monthTotals.net >= 0 ? 'text-mint-400' : 'text-rose-400')}>
                  {fmtMoney(monthTotals.net, base, { hide, compact: true })}
                </b>
              </span>
            </span>
            <span className="text-slate-400">
              Баланс на конец месяца: <b className="num text-slate-100">{fmtMoney(monthEndBalance, base, { hide, compact: true })}</b>
            </span>
          </div>
        </Card>

        {/* ------------------------------ панель дня ------------------------------- */}
        <div className="space-y-4">
          <Card>
            <div className="mb-3 flex items-start justify-between gap-2">
              <div>
                <div className="text-[15px] font-semibold capitalize text-slate-100">{fmtDate(selected, 'EEEE, d MMMM')}</div>
                <div className="mt-0.5 text-[11px] text-slate-500">
                  {selectedEvents.length
                    ? `${selectedEvents.length} событий на сумму ${fmtMoney(
                        selectedEvents.reduce((s, e) => s + convert(e.amount, e.currency, base, ctx.rates), 0),
                        base,
                        { hide, signed: true, compact: true },
                      )}`
                    : 'Событий нет'}
                </div>
              </div>
              <IconButton icon="Plus" label="Добавить операцию" onClick={() => setAddOpen(true)} />
            </div>

            {selectedEvents.length ? (
              <div className="space-y-1">
                {selectedEvents.map((e, i) => (
                  <EventRow
                    key={`${e.sourceKey}-${i}`}
                    event={e}
                  />
                ))}
              </div>
            ) : (
              <EmptyState
                icon="CalendarDays"
                title="Свободный день"
                description="Ничего не запланировано — можно добавить операцию или отдохнуть"
              />
            )}

            {balanceAt.get(selected) !== undefined && (
              <div className="mt-3 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2 text-[11.5px] text-slate-400">
                Прогноз баланса на конец дня:{' '}
                <b className="num text-slate-100">{fmtMoney(balanceAt.get(selected) ?? 0, base, { hide })}</b>
              </div>
            )}
          </Card>

          {/* --------------------------- список за месяц --------------------------- */}
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-[14px] font-semibold text-slate-100">
                {view === 'list' ? 'Все события месяца' : 'Календарь событий'}
              </h3>
              <Badge tone="slate">{listEvents.length}</Badge>
            </div>
            <div className="scroll-thin max-h-[420px] space-y-0.5 pr-1">
              {listEvents.map((e, i) => (
                <button
                  key={`${e.sourceKey}-${i}`}
                  onClick={() => setSelected(e.date)}
                  className={clsx(
                    'flex w-full items-center gap-2.5 rounded-xl px-2 py-1.5 text-left transition hover:bg-white/[0.05]',
                    e.date === selected && 'bg-white/[0.06]',
                  )}
                >
                  <EventIcon event={e} size={14} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12.5px] text-slate-200">{e.title}</span>
                    <span className="num text-[10.5px] text-slate-500">
                      {fmtDate(e.date, 'd MMM')} · {accountsMap.get(e.accountId)?.name ?? ''}
                    </span>
                  </span>
                  <span className={clsx('num shrink-0 text-[12px] font-semibold', e.amount >= 0 ? 'text-mint-400' : 'text-slate-200')}>
                    {e.amount >= 0 ? '+' : '−'}
                    {fmtMoney(Math.abs(e.amount), e.currency, { hide, cents: false, compact: true, tight: true })}
                  </span>
                </button>
              ))}
              {!listEvents.length && (
                <div className="py-6 text-center text-xs text-slate-500">Нет событий с текущими фильтрами</div>
              )}
            </div>
          </Card>
        </div>
      </div>

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title={`Операция на ${fmtDate(selected, 'd MMMM yyyy')}`}
        subtitle="План или факт — как вам удобнее"
        icon="Plus"
      >
        <QuickAddTx defaultDate={selected} onDone={() => setAddOpen(false)} />
      </Modal>
    </div>
  );
}
