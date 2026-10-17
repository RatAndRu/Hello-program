import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { useStore } from '../store/useStore';
import { useCtx, useEvents } from '../store/useEngine';
import { usePeriod } from '../hooks/usePeriod';
import { TransactionModal } from '../components/TransactionModal';
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  IconButton,
  Input,
  Progress,
  SectionHeader,
  Select,
  Segmented,
  AmountInput,
} from '../components/ui/primitives';
import { Icon } from '../components/Icon';
import { convert } from '../lib/rates';
import { fmtMoney } from '../lib/format';
import { addYM, endOfMonthISO, fmtDate, fmtDateShort, startOfMonthISO, todayISO } from '../lib/dates';
import { categoryBreakdown } from '../lib/engine';
import type { CashflowEvent, Transaction } from '../types';

type SortKey = 'date' | 'amount' | 'title' | 'category';

export default function Expenses() {
  const data = useStore((s) => s.data);
  const ctx = useCtx();
  const period = usePeriod();
  const [offset, setOffset] = useState(0);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [accountFilter, setAccountFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'planned' | 'done'>('all');
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('date');
  const [sortDir, setSortDir] = useState<1 | -1>(1);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Transaction | undefined>();
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [view, setView] = useState<'plan' | 'budgets'>('plan');

  const settings = data.settings;
  const base = settings.baseCurrency;
  const hide = settings.hideBalances;
  const today = todayISO();

  const activePeriod = useMemo(() => {
    if (offset === 0) return period;
    const from = startOfMonthISO(addYM(period.ym, offset));
    return { ...period, from, to: endOfMonthISO(addYM(period.ym, offset)), ym: addYM(period.ym, offset) };
  }, [period, offset]);

  const events = useEvents(activePeriod.from, activePeriod.to);
  const expenseEvents = useMemo(() => events.filter((e) => e.amount < 0), [events]);

  const filtered = useMemo(
    () =>
      expenseEvents.filter((e) => {
        if (categoryFilter && e.categoryId !== categoryFilter) return false;
        if (accountFilter && e.accountId !== accountFilter) return false;
        if (statusFilter === 'planned' && e.status === 'done') return false;
        if (statusFilter === 'done' && e.status !== 'done') return false;
        if (search && !e.title.toLowerCase().includes(search.toLowerCase())) return false;
        return true;
      }),
    [expenseEvents, categoryFilter, accountFilter, statusFilter, search],
  );

  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      let d = 0;
      if (sortKey === 'date') d = a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
      if (sortKey === 'amount') d = Math.abs(a.amount) - Math.abs(b.amount);
      if (sortKey === 'title') d = a.title.localeCompare(b.title, 'ru');
      if (sortKey === 'category')
        d = (data.categories.find((c) => c.id === a.categoryId)?.name ?? '').localeCompare(
          data.categories.find((c) => c.id === b.categoryId)?.name ?? '',
          'ru',
        );
      return d * sortDir;
    });
    return arr;
  }, [filtered, sortKey, sortDir, data.categories]);

  const totals = useMemo(() => {
    let planned = 0;
    let done = 0;
    for (const e of expenseEvents) {
      const v = Math.abs(convert(e.amount, e.currency, base, ctx.rates));
      if (e.status === 'done') done += v;
      else planned += v;
    }
    return { planned, done, total: planned + done };
  }, [expenseEvents, base, ctx.rates]);

  const remaining = useMemo(
    () =>
      expenseEvents
        .filter((e) => e.date >= today && e.status !== 'done')
        .reduce((s, e) => s + Math.abs(convert(e.amount, e.currency, base, ctx.rates)), 0),
    [expenseEvents, today, base, ctx.rates],
  );

  const byCategory = useMemo(() => categoryBreakdown(expenseEvents, ctx, 'expense'), [expenseEvents, ctx]);

  const txById = useMemo(() => new Map(data.transactions.map((t) => [t.id, t])), [data.transactions]);

  const openEdit = (event: CashflowEvent) => {
    // если событие сгенерировано правилом — открываем связанный источник через календарь
    const tx = data.transactions.find(
      (t) => t.sourceKey === event.sourceKey || (t.recurrence && `${t.sourceKey ?? `tx:${t.id}`}:${event.date}` === event.sourceKey),
    );
    if (tx) setEditing(tx);
    else setEditing(undefined);
    setModalOpen(true);
  };

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(key);
      setSortDir(1);
    }
  };

  return (
    <div className="space-y-4">
      {/* -------------------------------- сводка -------------------------------- */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">Запланировано</div>
          <div className="num mt-1 text-2xl font-bold text-slate-50">{fmtMoney(totals.planned, base, { hide, compact: true })}</div>
          <div className="mt-1 text-[11px] text-slate-500">{filtered.length} операций в периоде</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">По факту</div>
          <div className="num mt-1 text-2xl font-bold text-rose-400">{fmtMoney(totals.done, base, { hide, compact: true })}</div>
          <div className="mt-1 text-[11px] text-slate-500">уже подтверждено</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">Осталось потратить</div>
          <div className="num mt-1 text-2xl font-bold text-amberx-400">{fmtMoney(remaining, base, { hide, compact: true })}</div>
          <div className="mt-1 text-[11px] text-slate-500">с сегодня до конца периода</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">Всего за период</div>
          <div className="num mt-1 text-2xl font-bold text-slate-50">{fmtMoney(totals.total, base, { hide, compact: true })}</div>
          <div className="mt-1 text-[11px] text-slate-500">
            {dayCount(activePeriod)} дней · {fmtMoney(totals.total / Math.max(1, dayCount(activePeriod)), base, { hide, compact: true })} в день
          </div>
        </Card>
      </div>

      <Card>
        <SectionHeader
          title="План расходов"
          subtitle="Сколько, на что и в какую дату планируем тратить"
          icon="Receipt"
          right={
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1">
                <IconButton icon="ChevronLeft" label="Предыдущий месяц" onClick={() => setOffset((o) => o - 1)} />
                <span className="min-w-[112px] text-center text-[13px] font-medium capitalize text-slate-200">
                  {activePeriod.label}
                </span>
                <IconButton icon="ChevronRight" label="Следующий месяц" onClick={() => setOffset((o) => o + 1)} />
              </div>
              <Segmented
                size="sm"
                value={view}
                onChange={setView}
                options={[
                  { value: 'plan', label: 'Операции', icon: 'Layers' },
                  { value: 'budgets', label: 'Лимиты', icon: 'Target' },
                ]}
              />
              <Button
                variant="primary"
                size="sm"
                icon="Plus"
                onClick={() => {
                  setEditing(undefined);
                  setModalOpen(true);
                }}
              >
                Добавить
              </Button>
            </div>
          }
        />

        {/* ------------------------------ фильтры ------------------------------- */}
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="relative">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Поиск по названию…"
              className="w-56 pl-8"
            />
            <Icon name="Search" size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
          </div>
          <Select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} className="w-auto min-w-[150px]">
            <option value="">Все категории</option>
            {data.categories
              .filter((c) => c.kind === 'expense')
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </Select>
          <Select value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)} className="w-auto min-w-[130px]">
            <option value="">Все счета</option>
            {data.accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </Select>
          <Segmented
            size="sm"
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: 'all', label: 'Все' },
              { value: 'planned', label: 'План' },
              { value: 'done', label: 'Факт' },
            ]}
          />
          {(search || categoryFilter || accountFilter || statusFilter !== 'all') && (
            <Button
              size="sm"
              variant="ghost"
              icon="X"
              onClick={() => {
                setSearch('');
                setCategoryFilter('');
                setAccountFilter('');
                setStatusFilter('all');
              }}
            >
              Сбросить
            </Button>
          )}
          <span className="ml-auto text-[11.5px] text-slate-500">
            Показано: {sorted.length} · {fmtMoney(
              sorted.reduce((s, e) => s + Math.abs(convert(e.amount, e.currency, base, ctx.rates)), 0),
              base,
              { hide, compact: true },
            )}
          </span>
        </div>

        {view === 'plan' ? (
          sorted.length ? (
            <div className="overflow-x-auto rounded-xl border border-white/[0.06]">
              <table className="table min-w-[760px]">
                <thead>
                  <tr>
                    <Th onClick={() => toggleSort('date')} active={sortKey === 'date'} dir={sortDir}>
                      Дата
                    </Th>
                    <Th onClick={() => toggleSort('title')} active={sortKey === 'title'} dir={sortDir}>
                      Название
                    </Th>
                    <Th onClick={() => toggleSort('category')} active={sortKey === 'category'} dir={sortDir}>
                      Категория
                    </Th>
                    <th>Счёт</th>
                    <Th onClick={() => toggleSort('amount')} active={sortKey === 'amount'} dir={sortDir} align="right">
                      Сумма
                    </Th>
                    <th className="text-center">Статус</th>
                    <th className="w-20" />
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((e, i) => {
                    const cat = data.categories.find((c) => c.id === e.categoryId);
                    const acc = data.accounts.find((a) => a.id === e.accountId);
                    const tx = data.transactions.find((t) => t.sourceKey === e.sourceKey);
                    return (
                      <tr
                        key={`${e.sourceKey}-${i}`}
                        className={clsx(e.status === 'done' && 'text-slate-400')}
                      >
                        <td className="num whitespace-nowrap text-[12.5px]">
                          {fmtDateShort(e.date)}
                          {e.date === today && <span className="ml-1 text-[10px] text-brand-300">сегодня</span>}
                        </td>
                        <td>
                          <div className="flex items-center gap-2">
                            <span
                              className="grid h-6 w-6 shrink-0 place-items-center rounded-md"
                              style={{
                                color: cat?.color ?? e.color,
                                background: `${cat?.color ?? e.color}22`,
                              }}
                            >
                              <Icon name={cat?.icon ?? e.icon ?? 'Circle'} size={13} />
                            </span>
                            <span className="truncate text-[13px] font-medium">{e.title}</span>
                            {tx?.recurrence && (
                              <Badge tone="violet" icon="Repeat">
                                {tx.recurrence.every} {tx.recurrence.unit === 'month' ? 'мес' : tx.recurrence.unit === 'week' ? 'нед' : tx.recurrence.unit === 'day' ? 'дн' : 'г'}
                              </Badge>
                            )}
                            {e.sourceType === 'subscription' && (
                              <Badge tone="violet" icon="Repeat">
                                подписка
                              </Badge>
                            )}
                            {e.sourceType === 'credit' && (
                              <Badge tone="red" icon="CreditCard">
                                кредит
                              </Badge>
                            )}
                          </div>
                        </td>
                        <td>
                          {cat ? (
                            <span className="text-[12.5px]" style={{ color: `${cat.color}dd` }}>
                              {cat.name}
                            </span>
                          ) : (
                            <span className="text-[12.5px] text-slate-600">—</span>
                          )}
                        </td>
                        <td className="text-[12.5px] text-slate-400">{acc?.name ?? '—'}</td>
                        <td className="num whitespace-nowrap text-right text-[13px] font-semibold">
                          {fmtMoney(Math.abs(e.amount), e.currency, { hide })}
                        </td>
                        <td className="text-center">
                          {e.status === 'done' ? (
                            <Badge tone="green">факт</Badge>
                          ) : (
                            <Badge tone="slate">план</Badge>
                          )}
                        </td>
                        <td>
                          <div className="flex items-center justify-end gap-1">
                            <IconButton
                              icon={e.status === 'done' ? 'RotateCcw' : 'Check'}
                              size={13}
                              label={e.status === 'done' ? 'Вернуть в план' : 'Отметить фактом'}
                              onClick={() => useStore.getState().toggleEventDone(e)}
                            />
                            <IconButton
                              icon="Pencil"
                              size={13}
                              label="Изменить"
                              onClick={() => openEdit(e)}
                              disabled={e.sourceType === 'subscription' || e.sourceType === 'credit' || e.sourceType === 'income'}
                            />
                            {tx && txById.has(tx.id) && (
                              <IconButton
                                icon="Trash2"
                                size={13}
                                label="Удалить"
                                onClick={() => setDeleteId(tx.id)}
                                className="hover:text-rose-400"
                              />
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon="Receipt"
              title="Ничего не запланировано"
              description="Добавьте planned-расходы: аренда, ЖКХ, продукты, крупные покупки — с датами и повторениями."
              action={
                <Button
                  variant="primary"
                  icon="Plus"
                  onClick={() => {
                    setEditing(undefined);
                    setModalOpen(true);
                  }}
                >
                  Добавить расход
                </Button>
              }
            />
          )
        ) : (
          <BudgetGrid byCategory={byCategory} />
        )}
      </Card>

      {/* ---------------------------- категории периода -------------------------- */}
      {byCategory.length > 0 && (
        <Card>
          <SectionHeader title="Структура расходов за период" subtitle="Сколько уходит по категориям" icon="PieChart" />
          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {byCategory.slice(0, 9).map((c) => {
              const pct = totals.total > 0 ? (c.value / totals.total) * 100 : 0;
              return (
                <div key={c.categoryId} className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-2">
                      <span
                        className="grid h-7 w-7 shrink-0 place-items-center rounded-lg"
                        style={{ color: c.color, background: `${c.color}22` }}
                      >
                        <Icon name={data.categories.find((x) => x.id === c.categoryId)?.icon ?? 'Circle'} size={14} />
                      </span>
                      <span className="truncate text-[13px] text-slate-200">{c.name}</span>
                    </span>
                    <span className="num shrink-0 text-[13px] font-semibold text-slate-100">
                      {fmtMoney(c.value, base, { hide, compact: true })}
                    </span>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <Progress value={pct} color={c.color} height={6} />
                    <span className="num w-10 shrink-0 text-right text-[10.5px] text-slate-500">{pct.toFixed(0)}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      <TransactionModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        tx={editing}
        defaultKind="expense"
        defaultDate={activePeriod.from > today ? activePeriod.from : today}
        key={editing?.id ?? 'new'}
      />

      <ConfirmDialog
        open={Boolean(deleteId)}
        onClose={() => setDeleteId(null)}
        onConfirm={() => {
          if (deleteId) useStore.getState().deleteTransaction(deleteId);
          setDeleteId(null);
        }}
        title="Удалить операцию?"
        description="Операция будет удалена из плана и из истории."
      />
    </div>
  );
}

function Th({
  children,
  onClick,
  active,
  dir,
  align,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  active?: boolean;
  dir?: 1 | -1;
  align?: 'right';
}) {
  return (
    <th className={align === 'right' ? 'text-right' : ''}>
      <button onClick={onClick} className={clsx('inline-flex items-center gap-1 transition', active ? 'text-brand-300' : 'hover:text-slate-200')}>
        {children}
        <Icon name={active ? (dir === 1 ? 'ChevronUp' : 'ChevronDown') : 'ChevronsUpDown'} size={12} className="opacity-60" />
      </button>
    </th>
  );
}

function BudgetGrid({ byCategory }: { byCategory: { categoryId: string; name: string; color: string; value: number }[] }) {
  const data = useStore((s) => s.data);
  const updateCategory = useStore((s) => s.updateCategory);
  const base = data.settings.baseCurrency;
  const hide = data.settings.hideBalances;

  const rows = data.categories
    .filter((c) => c.kind === 'expense')
    .map((c) => ({ ...c, spent: byCategory.find((b) => b.categoryId === c.id)?.value ?? 0 }))
    .sort((a, b) => b.spent - a.spent);

  return (
    <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
      {rows.map((c) => {
        const budget = c.budgetMonthly ?? 0;
        const pct = budget > 0 ? (c.spent / budget) * 100 : 0;
        const over = budget > 0 && c.spent > budget;
        return (
          <div key={c.id} className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-2">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg" style={{ color: c.color, background: `${c.color}22` }}>
                  <Icon name={c.icon} size={14} />
                </span>
                <span className="truncate text-[13px] text-slate-200">{c.name}</span>
              </span>
              <span className={clsx('num shrink-0 text-[13px] font-semibold', over ? 'text-rose-400' : 'text-slate-100')}>
                {fmtMoney(c.spent, base, { hide, compact: true })}
              </span>
            </div>

            <div className="mt-2.5">
              <Progress value={c.spent} max={budget || 1} color={c.color} height={6} />
              <div className="mt-1 flex items-center justify-between text-[10.5px] text-slate-500">
                <span>{budget > 0 ? `${pct.toFixed(0)}% от лимита` : 'лимит не задан'}</span>
                {over && <span className="text-rose-400">перерасход {fmtMoney(c.spent - budget, base, { hide, compact: true })}</span>}
              </div>
            </div>

            <div className="mt-2 flex items-center gap-2">
              <span className="text-[11px] text-slate-500">Лимит:</span>
              <div className="w-28">
                <AmountInput
                  value={budget || undefined}
                  onChange={(v) => updateCategory(c.id, { budgetMonthly: v })}
                  placeholder="не задан"
                  className="px-2 py-1 text-[12px]"
                />
              </div>
              <span className="num ml-auto text-[11px] text-slate-500">
                ≈ {fmtMoney(c.spent / Math.max(1, new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).getDate()), base, { hide, cents: false, compact: true, tight: true })}/день
              </span>
            </div>
          </div>
        );
      })}

      <div className="rounded-xl border border-dashed border-white/10 p-3">
        <div className="text-[12.5px] font-medium text-slate-300">Как считать лимит</div>
        <p className="mt-1 text-[11.5px] leading-relaxed text-slate-500">
          Лимит сравнивается с расходами за выбранный период. Он учитывает и план, и факт — вы сразу видите, где
          намечается перерасход.
        </p>
      </div>
    </div>
  );
}

function dayCount(period: { from: string; to: string }): number {
  return Math.round((new Date(period.to).getTime() - new Date(period.from).getTime()) / 86400000) + 1;
}

export { fmtDate };
