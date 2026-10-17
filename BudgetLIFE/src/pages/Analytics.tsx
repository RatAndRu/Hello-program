import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { useStore } from '../store/useStore';
import { useCtx, useEvents } from '../store/useEngine';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Progress,
  SectionHeader,
  Segmented,
  Select,
} from '../components/ui/primitives';
import { Icon } from '../components/Icon';
import { BalanceChart, CashflowBars, CategoryDonut, ChartCard, LineSeries, type MonthBar, type Slice } from '../components/charts';
import { convert } from '../lib/rates';
import { fmtMoney, fmtNumber, fmtPercent } from '../lib/format';
import {
  addMonths,
  addYM,
  fmtDate,
  fmtDateShort,
  fromISO,
  nowYM,
  toISO,
  todayISO,
  ymLabel,
  ymOf,
  ymRange,
} from '../lib/dates';
import { categoryBreakdown, monthBounds } from '../lib/engine';
import { useProjection } from '../store/useEngine';

type SortKey = 'date' | 'amount' | 'title' | 'category' | 'account';

export default function Analytics() {
  const data = useStore((s) => s.data);
  const ctx = useCtx();
  const settings = data.settings;
  const base = settings.baseCurrency;
  const hide = settings.hideBalances;

  const [monthsBack, setMonthsBack] = useState(6);
  const [tab, setTab] = useState<'overview' | 'categories' | 'operations'>('overview');
  const [direction, setDirection] = useState<'all' | 'income' | 'expense'>('all');
  const [accountFilter, setAccountFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'planned' | 'done'>('all');
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('date');
  const [sortDir, setSortDir] = useState<1 | -1>(-1);

  const today = todayISO();
  const thisYM = nowYM();
  const fromYM = addYM(thisYM, -(monthsBack - 1));
  const from = `${fromYM}-01`;
  const to = `${thisYM}-31`;

  const events = useEvents(from, to);
  const projection = useProjection(today, toISO(addMonths(fromISO(today), Math.max(1, monthsBack))));

  const filtered = useMemo(
    () =>
      events.filter((e) => {
        const v = convert(e.amount, e.currency, base, ctx.rates);
        if (direction === 'income' && v <= 0) return false;
        if (direction === 'expense' && v >= 0) return false;
        if (accountFilter && e.accountId !== accountFilter) return false;
        if (categoryFilter && e.categoryId !== categoryFilter) return false;
        if (statusFilter === 'planned' && e.status === 'done') return false;
        if (statusFilter === 'done' && e.status !== 'done') return false;
        if (search && !e.title.toLowerCase().includes(search.toLowerCase())) return false;
        return true;
      }),
    [events, direction, accountFilter, categoryFilter, statusFilter, search, base, ctx.rates],
  );

  /* --------------------------- месячная статистика --------------------------- */
  const months = useMemo(() => ymRange(fromYM, thisYM), [fromYM, thisYM]);

  const series = useMemo<MonthBar[]>(
    () =>
      months.map((ym) => {
        const { from: f, to: t } = monthBounds(ym);
        let income = 0;
        let expense = 0;
        let incomeDone = 0;
        let expenseDone = 0;
        for (const e of events) {
          if (e.date < f || e.date > t) continue;
          const v = convert(e.amount, e.currency, base, ctx.rates);
          if (v >= 0) {
            income += v;
            if (e.status === 'done') incomeDone += v;
          } else {
            expense += -v;
            if (e.status === 'done') expenseDone += -v;
          }
        }
        return {
          label: ymLabel(ym, true).replace('.', ''),
          income: Math.round(income),
          expense: Math.round(expense),
          net: Math.round(income - expense),
          incomeDone: Math.round(incomeDone),
          expenseDone: Math.round(expenseDone),
        } as MonthBar & { net: number; incomeDone: number; expenseDone: number };
      }),
    [months, events, base, ctx.rates],
  );

  const netSeries = useMemo(
    () => series.map((s) => ({ label: s.label, Чистый: s.net ?? 0, Доходы: s.income, Расходы: s.expense })),
    [series],
  );

  const planFactSeries = useMemo(
    () =>
      series.map((s) => ({
        label: s.label,
        'План расходов': Math.round((s.expense ?? 0) - (s.expenseDone ?? 0)),
        'Факт расходов': s.expenseDone ?? 0,
        'Факт доходов': s.incomeDone ?? 0,
      })),
    [series],
  );

  const expenseSlices = useMemo<Slice[]>(
    () =>
      categoryBreakdown(
        filtered.length ? filtered : events,
        ctx,
        'expense',
      )
        .slice(0, 9)
        .map((c) => ({ name: c.name, value: c.value, color: c.color })),
    [filtered, events, ctx],
  );

  const incomeSlices = useMemo<Slice[]>(
    () =>
      categoryBreakdown(filtered.length ? filtered : events, ctx, 'income')
        .slice(0, 9)
        .map((c) => ({ name: c.name, value: c.value, color: c.color })),
    [filtered, events, ctx],
  );

  /* ---------------------------------- KPI ---------------------------------- */
  const stats = useMemo(() => {
    const done = events.filter((e) => e.status === 'done');
    let income = 0;
    let expense = 0;
    for (const e of done) {
      const v = convert(e.amount, e.currency, base, ctx.rates);
      if (v >= 0) income += v;
      else expense += -v;
    }
    const byDate = new Map<string, number>();
    for (const e of done) {
      const v = convert(e.amount, e.currency, base, ctx.rates);
      if (v < 0) byDate.set(e.date, (byDate.get(e.date) ?? 0) + -v);
    }
    const biggest = [...byDate.entries()].sort((a, b) => b[1] - a[1])[0];
    const expenses = events.filter((e) => convert(e.amount, e.currency, base, ctx.rates) < 0);
    const avgExpense = expense / Math.max(1, months.length);
    const avgIncome = income / Math.max(1, months.length);
    const topExpense = expenses
      .slice()
      .sort((a, b) => Math.abs(convert(b.amount, b.currency, base, ctx.rates)) - Math.abs(convert(a.amount, a.currency, base, ctx.rates)))[0];
    return {
      income,
      expense,
      saved: income - expense,
      savingRate: income > 0 ? ((income - expense) / income) * 100 : 0,
      avgExpense,
      avgIncome,
      biggest,
      topExpense,
      count: events.length,
      doneCount: done.length,
    };
  }, [events, base, ctx.rates, months.length]);

  /* ------------------------------ операции --------------------------------- */
  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      let d = 0;
      switch (sortKey) {
        case 'date':
          d = a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
          break;
        case 'amount':
          d = Math.abs(convert(a.amount, a.currency, base, ctx.rates)) - Math.abs(convert(b.amount, b.currency, base, ctx.rates));
          break;
        case 'title':
          d = a.title.localeCompare(b.title, 'ru');
          break;
        case 'category':
          d = (data.categories.find((c) => c.id === a.categoryId)?.name ?? '').localeCompare(
            data.categories.find((c) => c.id === b.categoryId)?.name ?? '',
            'ru',
          );
          break;
        case 'account':
          d = (data.accounts.find((x) => x.id === a.accountId)?.name ?? '').localeCompare(
            data.accounts.find((x) => x.id === b.accountId)?.name ?? '',
            'ru',
          );
          break;
      }
      return d * sortDir;
    });
    return arr;
  }, [filtered, sortKey, sortDir, base, ctx.rates, data.categories, data.accounts]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(key);
      setSortDir(-1);
    }
  };

  const resetFilters = () => {
    setDirection('all');
    setAccountFilter('');
    setCategoryFilter('');
    setStatusFilter('all');
    setSearch('');
  };

  const filtersActive = direction !== 'all' || Boolean(accountFilter) || Boolean(categoryFilter) || statusFilter !== 'all' || Boolean(search);

  return (
    <div className="space-y-4">
      {/* -------------------------------- фильтры ------------------------------- */}
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { value: 'overview', label: 'Обзор', icon: 'ChartLine' },
              { value: 'categories', label: 'Категории', icon: 'PieChart' },
              { value: 'operations', label: 'Операции', icon: 'Layers' },
            ]}
          />

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <Segmented
              size="sm"
              value={String(monthsBack)}
              onChange={(v) => setMonthsBack(Number(v))}
              options={[
                { value: '3', label: '3 мес' },
                { value: '6', label: '6 мес' },
                { value: '12', label: '12 мес' },
              ]}
            />
            <Select value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)} className="w-auto min-w-[140px]">
              <option value="">Все счета</option>
              {data.accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
            <Select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} className="w-auto min-w-[150px]">
              <option value="">Все категории</option>
              {data.categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
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
            {filtersActive && (
              <Button size="sm" variant="ghost" icon="X" onClick={resetFilters}>
                Сбросить
              </Button>
            )}
          </div>
        </div>
      </Card>

      {/* --------------------------------- KPI ---------------------------------- */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Stat label="Доходы (факт)" value={fmtMoney(stats.income, base, { hide, compact: true })} tone="mint" icon="TrendingUp" />
        <Stat label="Расходы (факт)" value={fmtMoney(stats.expense, base, { hide, compact: true })} tone="rose" icon="TrendingDown" />
        <Stat
          label="Накоплено"
          value={fmtMoney(stats.saved, base, { hide, compact: true })}
          tone={stats.saved >= 0 ? 'mint' : 'rose'}
          icon="PiggyBank"
          hint={`норма сбережений ${fmtPercent(stats.savingRate, 0)}`}
        />
        <Stat
          label="Средний расход"
          value={fmtMoney(stats.avgExpense, base, { hide, compact: true })}
          tone="amber"
          icon="Receipt"
          hint="в месяц"
        />
        <Stat
          label="Самый дорогой день"
          value={stats.biggest ? fmtMoney(stats.biggest[1], base, { hide, compact: true }) : '—'}
          tone="violet"
          icon="Flame"
          hint={stats.biggest ? fmtDate(stats.biggest[0], 'd MMM yyyy') : 'нет данных'}
        />
      </div>

      {tab === 'overview' && (
        <>
          <div className="grid gap-4 xl:grid-cols-2">
            <ChartCard
              title="Доходы и расходы по месяцам"
              subtitle={`План + факт за ${monthsBack} мес.`}
              right={
                <Segmented
                  size="sm"
                  value={direction}
                  onChange={setDirection}
                  options={[
                    { value: 'all', label: 'Все' },
                    { value: 'income', label: 'Доходы' },
                    { value: 'expense', label: 'Расходы' },
                  ]}
                />
              }
            >
              <CashflowBars
                data={series.map((s) => ({
                  label: s.label,
                  income: direction === 'expense' ? 0 : s.income,
                  expense: direction === 'income' ? 0 : s.expense,
                }))}
                currency={base}
                hide={hide}
                height={280}
              />
            </ChartCard>

            <ChartCard title="Чистый денежный поток" subtitle="Доходы минус расходы по месяцам" icon="ChartLine">
              <LineSeries
                data={netSeries}
                keys={[
                  { key: 'Чистый', name: 'Чистый поток', color: '#38c3f5' },
                  { key: 'Доходы', name: 'Доходы', color: '#10d19a' },
                  { key: 'Расходы', name: 'Расходы', color: '#f43f5e' },
                ]}
                currency={base}
                hide={hide}
                height={280}
              />
            </ChartCard>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <ChartCard title="План и факт" subtitle="Как плановые траты соотносятся с реальными" icon="Target">
              <CashflowBars
                data={planFactSeries.map((p) => ({ label: p.label, income: p['Факт доходов'], expense: p['Факт расходов'] }))}
                currency={base}
                hide={hide}
                height={260}
              />
            </ChartCard>

            <ChartCard title="Динамика баланса" subtitle="Прогноз на выбранный горизонт" icon="Wallet">
              <BalanceChart days={projection.days} currency={base} hide={hide} height={260} />
            </ChartCard>
          </div>
        </>
      )}

      {tab === 'categories' && (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card>
            <SectionHeader title="Расходы по категориям" subtitle={`${monthsBack} мес. · ${fmtMoney(expenseSlices.reduce((s, x) => s + x.value, 0), base, { hide, compact: true })}`} icon="PieChart" />
            <CategoryDonut data={expenseSlices} currency={base} hide={hide} height={260} />
            <CategoryTable slices={expenseSlices} total={expenseSlices.reduce((s, x) => s + x.value, 0)} />
          </Card>
          <Card>
            <SectionHeader title="Доходы по категориям" subtitle={`${monthsBack} мес. · ${fmtMoney(incomeSlices.reduce((s, x) => s + x.value, 0), base, { hide, compact: true })}`} icon="Coins" />
            <CategoryDonut data={incomeSlices} currency={base} hide={hide} height={260} />
            <CategoryTable slices={incomeSlices} total={incomeSlices.reduce((s, x) => s + x.value, 0)} />
          </Card>
        </div>
      )}

      {tab === 'operations' && (
        <Card pad={false}>
          <div className="flex flex-wrap items-center gap-2 p-4 pb-3">
            <div className="relative">
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Поиск…"
                className="w-56 pl-8"
              />
              <Icon name="Search" size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
            </div>
            <Segmented
              size="sm"
              value={direction}
              onChange={setDirection}
              options={[
                { value: 'all', label: 'Все' },
                { value: 'income', label: 'Доходы' },
                { value: 'expense', label: 'Расходы' },
              ]}
            />
            <span className="ml-auto text-[11.5px] text-slate-500">
              {sorted.length} операций · {fmtMoney(sorted.reduce((s, e) => s + Math.abs(convert(e.amount, e.currency, base, ctx.rates)), 0), base, { hide, compact: true })}
            </span>
          </div>

          {sorted.length ? (
            <div className="overflow-x-auto">
              <table className="table min-w-[820px]">
                <thead>
                  <tr>
                    <Th onClick={() => toggleSort('date')} active={sortKey === 'date'} dir={sortDir}>Дата</Th>
                    <Th onClick={() => toggleSort('title')} active={sortKey === 'title'} dir={sortDir}>Операция</Th>
                    <Th onClick={() => toggleSort('category')} active={sortKey === 'category'} dir={sortDir}>Категория</Th>
                    <Th onClick={() => toggleSort('account')} active={sortKey === 'account'} dir={sortDir}>Счёт</Th>
                    <th className="text-center">Статус</th>
                    <Th onClick={() => toggleSort('amount')} active={sortKey === 'amount'} dir={sortDir} align="right">Сумма</Th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.slice(0, 300).map((e, i) => {
                    const cat = data.categories.find((c) => c.id === e.categoryId);
                    const acc = data.accounts.find((a) => a.id === e.accountId);
                    const v = convert(e.amount, e.currency, base, ctx.rates);
                    return (
                      <tr key={`${e.sourceKey}-${i}`}>
                        <td className="num whitespace-nowrap">{fmtDate(e.date, 'd MMM yy')}</td>
                        <td>
                          <span className="flex items-center gap-2">
                            <span
                              className="grid h-6 w-6 shrink-0 place-items-center rounded-md"
                              style={{ color: cat?.color ?? e.color, background: `${cat?.color ?? e.color}22` }}
                            >
                              <Icon name={cat?.icon ?? e.icon ?? 'Circle'} size={13} />
                            </span>
                            <span className="truncate">{e.title}</span>
                          </span>
                        </td>
                        <td className="text-[12.5px]" style={{ color: cat ? `${cat.color}dd` : undefined }}>
                          {cat?.name ?? '—'}
                        </td>
                        <td className="text-[12.5px] text-slate-400">{acc?.name ?? '—'}</td>
                        <td className="text-center">
                          {e.status === 'done' ? <Badge tone="green">факт</Badge> : <Badge tone="slate">план</Badge>}
                        </td>
                        <td className={clsx('num text-right font-semibold', v >= 0 ? 'text-mint-400' : 'text-slate-100')}>
                          {v >= 0 ? '+' : '−'}
                          {fmtMoney(Math.abs(e.amount), e.currency, { hide })}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState icon="Search" title="Ничего не найдено" description="Попробуйте изменить фильтры или период" />
          )}
        </Card>
      )}

      {/* ------------------------------ топ трат -------------------------------- */}
      {tab !== 'operations' && (
        <Card>
          <SectionHeader title="Самые крупные траты" subtitle="Топ-8 операций за период" icon="Flame" />
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {events
              .filter((e) => convert(e.amount, e.currency, base, ctx.rates) < 0)
              .sort((a, b) => Math.abs(convert(b.amount, b.currency, base, ctx.rates)) - Math.abs(convert(a.amount, a.currency, base, ctx.rates)))
              .slice(0, 8)
              .map((e, i) => {
                const cat = data.categories.find((c) => c.id === e.categoryId);
                const v = Math.abs(convert(e.amount, e.currency, base, ctx.rates));
                const max = Math.abs(
                  convert(
                    events.filter((x) => convert(x.amount, x.currency, base, ctx.rates) < 0).sort(
                      (a, b) => Math.abs(convert(b.amount, b.currency, base, ctx.rates)) - Math.abs(convert(a.amount, a.currency, base, ctx.rates)),
                    )[0]?.amount ?? 1,
                    e.currency,
                    base,
                    ctx.rates,
                  ),
                );
                return (
                  <div key={`${e.sourceKey}-${i}`} className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
                    <div className="flex items-start justify-between gap-2">
                      <span className="min-w-0">
                        <span className="block truncate text-[12.5px] font-medium text-slate-200">{e.title}</span>
                        <span className="num text-[10.5px] text-slate-500">{fmtDateShort(e.date)}</span>
                      </span>
                      <span className="num shrink-0 text-[13px] font-semibold text-slate-100">
                        {fmtMoney(v, base, { hide, compact: true })}
                      </span>
                    </div>
                    <div className="mt-2">
                      <Progress value={v} max={max || 1} color={cat?.color ?? '#f43f5e'} height={5} />
                    </div>
                  </div>
                );
              })}
          </div>
        </Card>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  icon,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: string;
  tone: 'mint' | 'rose' | 'amber' | 'violet' | 'brand';
}) {
  const tones = {
    mint: 'text-mint-400',
    rose: 'text-rose-400',
    amber: 'text-amberx-400',
    violet: 'text-viola-400',
    brand: 'text-brand-300',
  };
  return (
    <Card>
      <div className="flex items-start justify-between">
        <span className="text-[11px] uppercase tracking-wider text-slate-400">{label}</span>
        <Icon name={icon} size={14} className={clsx('opacity-70', tones[tone])} />
      </div>
      <div className={clsx('num mt-1.5 text-[20px] font-bold leading-none', tones[tone])}>{value}</div>
      {hint && <div className="mt-1 text-[11px] text-slate-500">{hint}</div>}
    </Card>
  );
}

function CategoryTable({ slices, total }: { slices: Slice[]; total: number }) {
  const base = useStore((s) => s.data.settings.baseCurrency);
  const hide = useStore((s) => s.data.settings.hideBalances);
  return (
    <div className="mt-3 space-y-1.5">
      {slices.map((s) => (
        <div key={s.name} className="flex items-center gap-2 text-[12.5px]">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: s.color }} />
          <span className="min-w-0 flex-1 truncate text-slate-300">{s.name}</span>
          <span className="num shrink-0 text-slate-500">{total > 0 ? ((s.value / total) * 100).toFixed(1) : '0'}%</span>
          <span className="num w-24 shrink-0 text-right font-medium text-slate-100">
            {fmtMoney(s.value, base, { hide, compact: true })}
          </span>
        </div>
      ))}
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

export { fmtNumber, ymOf };
