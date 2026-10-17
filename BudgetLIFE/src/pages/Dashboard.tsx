import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import clsx from 'clsx';
import { useStore } from '../store/useStore';
import { useCtx, useEvents, useProjection } from '../store/useEngine';
import { usePeriod } from '../hooks/usePeriod';
import { Card, SectionHeader, Button, Progress, EmptyState, Badge, IconButton, Segmented } from '../components/ui/primitives';
import { BalanceChart, CategoryDonut, ChartCard, type Slice } from '../components/charts';
import { EventsList } from '../components/EventRow';
import { Icon } from '../components/Icon';
import { convert } from '../lib/rates';
import { fmtMoney, fmtPercent } from '../lib/format';
import {
  addMonths,
  addYM,
  fromISO,
  toISO,
  todayISO,
  ymLabel,
  ymOf,
  fmtDateShort,
} from '../lib/dates';
import { categoryBreakdown, estimateMonthlyInterest, totalsOf } from '../lib/engine';
import { creditSummary, graceInfo } from '../lib/credit';
import { cycleDays } from '../lib/dates';

/* ------------------------------ карточка KPI ------------------------------- */

function Kpi({
  label,
  value,
  hint,
  icon,
  tone = 'brand',
  right,
}: {
  label: string;
  value: string;
  hint?: React.ReactNode;
  icon: string;
  tone?: 'brand' | 'mint' | 'rose' | 'violet' | 'amber';
  right?: React.ReactNode;
}) {
  const tones = {
    brand: 'from-brand-400/25 to-brand-500/5 text-brand-300',
    mint: 'from-mint-400/25 to-mint-500/5 text-mint-400',
    rose: 'from-rose-500/25 to-rose-500/5 text-rose-400',
    violet: 'from-viola-400/25 to-viola-500/5 text-viola-400',
    amber: 'from-amberx-400/25 to-amberx-500/5 text-amberx-400',
  };
  return (
    <Card className="overflow-hidden">
      <div className={clsx('absolute inset-x-0 -top-16 h-32 bg-gradient-to-b to-transparent opacity-70', tones[tone])} />
      <div className="relative">
        <div className="flex items-start justify-between gap-2">
          <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400">{label}</span>
          <Icon name={icon} size={15} className={clsx('opacity-70', tones[tone].split(' ').pop())} />
        </div>
        <div className="num mt-2 text-[22px] font-bold leading-none tracking-tight text-slate-50">{value}</div>
        {hint && <div className="mt-1.5 text-[11.5px] leading-snug text-slate-400">{hint}</div>}
        {right}
      </div>
    </Card>
  );
}

/* --------------------------------- страница -------------------------------- */

export default function Dashboard() {
  const data = useStore((s) => s.data);
  const ctx = useCtx();
  const period = usePeriod();
  const [horizon, setHorizon] = useState(3);
  const [withInterest, setWithInterest] = useState(true);

  const settings = data.settings;
  const base = settings.baseCurrency;
  const hide = settings.hideBalances;
  const today = todayISO();
  const horizonTo = toISO(addMonths(fromISO(today), horizon));

  const projection = useProjection(today, horizonTo, { withInterest });
  const periodEvents = useEvents(period.from, period.to);
  const nearEvents = useEvents(today, toISO(addMonths(fromISO(today), horizon)));

  const rates = { rates: data.rates?.rates ?? {}, base: data.rates?.base ?? base, manual: settings.manualRates };

  /* общий баланс сейчас */
  const totalNow = useMemo(
    () =>
      data.accounts
        .filter((a) => a.includeInTotal && !a.archived)
        .reduce((s, a) => s + convert(a.balance, a.currency, base, rates), 0),
    [data.accounts, base, rates],
  );

  /* итоги периода */
  const totals = useMemo(() => totalsOf(periodEvents, ctx), [periodEvents, ctx]);
  const doneTotals = useMemo(() => totalsOf(periodEvents.filter((e) => e.status === 'done'), ctx), [periodEvents, ctx]);

  /* прогноз на конец периода */
  const endBalance = useMemo(() => {
    const day = projection.days.find((d) => d.date === period.to);
    if (day) return day.balance;
    const last = projection.days[projection.days.length - 1];
    return last?.balance ?? totalNow;
  }, [projection.days, period.to, totalNow]);

  /* осталось потратить в этом периоде */
  const remainingPlanned = useMemo(
    () =>
      periodEvents
        .filter((e) => e.date >= today && e.amount < 0 && e.status !== 'done')
        .reduce((s, e) => s + Math.abs(convert(e.amount, e.currency, base, rates)), 0),
    [periodEvents, today, base, rates],
  );

  /* пассивный доход по счетам */
  const passive = useMemo(
    () =>
      data.accounts
        .filter((a) => a.interest.enabled && !a.archived)
        .reduce((s, a) => s + convert(estimateMonthlyInterest(a), a.currency, base, rates), 0),
    [data.accounts, base, rates],
  );

  /* структура расходов за период */
  const expenseSlices = useMemo<Slice[]>(
    () =>
      categoryBreakdown(periodEvents, ctx, 'expense')
        .slice(0, 8)
        .map((c) => ({ name: c.name, value: c.value, color: c.color })),
    [periodEvents, ctx],
  );

  /* топ категорий с бюджетом */
  const topCategories = useMemo(() => categoryBreakdown(periodEvents, ctx, 'expense').slice(0, 6), [periodEvents, ctx]);

  /* ближайшие события */
  const upcoming = useMemo(
    () => nearEvents.filter((e) => e.date >= today).slice(0, 14),
    [nearEvents, today],
  );

  /* подписки: эквивалент в месяц */
  const subsMonthly = useMemo(
    () =>
      data.subscriptions
        .filter((s) => s.active)
        .reduce((sum, s) => sum + convert(s.amount, s.currency, base, rates) * (30.4375 / cycleDays(s.cycle.every, s.cycle.unit)), 0),
    [data.subscriptions, base, rates],
  );

  const nextSubs = useMemo(
    () => nearEvents.filter((e) => e.sourceType === 'subscription' && e.date >= today).slice(0, 4),
    [nearEvents, today],
  );

  /* кредиты */
  const creditCards = data.credits.filter((c) => c.active && c.kind === 'credit_card');
  const loans = data.credits.filter((c) => c.active && c.kind !== 'credit_card');
  const totalDebt = useMemo(
    () =>
      data.credits
        .filter((c) => c.active)
        .reduce((s, c) => s + convert(c.kind === 'credit_card' ? (c.used ?? 0) : (c.currentBalance ?? c.principal), c.currency, base, rates), 0),
    [data.credits, base, rates],
  );
  const nextPayments = useMemo(
    () => nearEvents.filter((e) => e.sourceType === 'credit' && e.date >= today).slice(0, 4),
    [nearEvents, today],
  );

  const accountsSorted = useMemo(
    () => [...data.accounts].filter((a) => !a.archived).sort((a, b) => convert(b.balance, b.currency, base, rates) - convert(a.balance, a.currency, base, rates)),
    [data.accounts, base, rates],
  );

  if (!data.accounts.length) {
    return (
      <EmptyState
        icon="Wallet"
        title="Добавьте первый счёт"
        description="Счёт — это основа планирования: карта, наличные, вклад или накопительный счёт с процентами."
        action={
          <div className="flex gap-2">
            <Link to="/accounts" className="btn-primary">
              Добавить счёт
            </Link>
            <Button icon="Sparkles" onClick={() => useStore.getState().loadDemo()}>
              Загрузить демо
            </Button>
          </div>
        }
      />
    );
  }

  return (
    <div className="space-y-5">
      {/* ------------------------------ заголовок ------------------------------ */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-[19px] font-semibold tracking-tight text-slate-50">
            Обзор на {new Date().toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}
          </h2>
          <p className="mt-0.5 text-xs text-slate-400">
            Период: {period.label}
            {period.financial && <span className="ml-1 text-slate-600">(финансовый месяц с {settings.monthStartDay}-го)</span>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/calendar" className="btn-ghost btn-sm">
            <Icon name="CalendarDays" size={14} /> Календарь
          </Link>
          <Link to="/analytics" className="btn-ghost btn-sm">
            <Icon name="ChartLine" size={14} /> Аналитика
          </Link>
          <Link to="/incomes" className="btn-primary btn-sm">
            <Icon name="Plus" size={14} /> Доход
          </Link>
        </div>
      </div>

      {/* -------------------------------- KPI --------------------------------- */}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Kpi
          label="Общий баланс"
          value={fmtMoney(totalNow, base, { hide, compact: true })}
          hint={`${data.accounts.filter((a) => a.includeInTotal && !a.archived).length} сч${data.accounts.length === 1 ? 'ёт' : 'ета'} в учёте`}
          icon="Wallet"
          tone="brand"
        />
        <Kpi
          label="Доходы за период"
          value={fmtMoney(totals.income, base, { hide, compact: true })}
          hint={
            <>
              по факту {fmtMoney(doneTotals.income, base, { hide, compact: true })} · план{' '}
              {fmtMoney(totals.income - doneTotals.income, base, { hide, compact: true })}
            </>
          }
          icon="TrendingUp"
          tone="mint"
        />
        <Kpi
          label="Расходы за период"
          value={fmtMoney(totals.expense, base, { hide, compact: true })}
          hint={
            <>
              по факту {fmtMoney(doneTotals.expense, base, { hide, compact: true })} · план{' '}
              {fmtMoney(totals.expense - doneTotals.expense, base, { hide, compact: true })}
            </>
          }
          icon="TrendingDown"
          tone="rose"
        />
        <Kpi
          label={`Прогноз на ${period.to.slice(8, 10)}.${period.to.slice(5, 7)}`}
          value={fmtMoney(endBalance, base, { hide, compact: true })}
          hint={
            endBalance >= totalNow ? (
              <span className="text-mint-400">▲ {fmtMoney(endBalance - totalNow, base, { hide, compact: true })} к текущему</span>
            ) : (
              <span className="text-rose-400">▼ {fmtMoney(totalNow - endBalance, base, { hide, compact: true })} к текущему</span>
            )
          }
          icon="Target"
          tone="violet"
        />
        <Kpi
          label="Пассивный доход"
          value={fmtMoney(passive, base, { hide, compact: true })}
          hint="проценты по счетам в месяц"
          icon="Percent"
          tone="amber"
        />
      </div>

      {/* ------------------------------ график баланса ------------------------- */}
      <ChartCard
        title="Динамика баланса"
        subtitle="Прогноз по всем счетам с учётом запланированных операций и процентов"
        right={
          <div className="flex items-center gap-2">
            <Segmented
              size="sm"
              value={String(horizon)}
              onChange={(v) => setHorizon(Number(v))}
              options={[
                { value: '1', label: '1 мес' },
                { value: '3', label: '3 мес' },
                { value: '6', label: '6 мес' },
                { value: '12', label: '12 мес' },
              ]}
            />
            <IconButton
              icon="Percent"
              size={14}
              label={withInterest ? 'Проценты учтены' : 'Проценты не учитываются'}
              onClick={() => setWithInterest((v) => !v)}
              className={clsx(withInterest && 'border-mint-500/40 bg-mint-500/10 text-mint-400')}
            />
          </div>
        }
      >
        <BalanceChart days={projection.days} currency={base} hide={hide} height={280} />
        {projection.min && projection.min.balance < 0 && (
          <div className="mt-2 flex items-center gap-2 rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            <Icon name="AlertTriangle" size={14} />
            Внимание: {fmtDateShort(projection.min.date)} прогнозируется отрицательный баланс{' '}
            {fmtMoney(projection.min.balance, base, { hide })}
          </div>
        )}
      </ChartCard>

      {/* --------------------- счета + ближайшие события ---------------------- */}
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <SectionHeader
            title="Счета"
            subtitle="Балансы, проценты и пополнения"
            icon="Wallet"
            right={
              <Link to="/accounts" className="btn-ghost btn-sm">
                Все счета <Icon name="ChevronRight" size={14} />
              </Link>
            }
          />
          <div className="grid gap-2.5 sm:grid-cols-2">
            {accountsSorted.slice(0, 6).map((a) => {
              const inBase = convert(a.balance, a.currency, base, rates);
              const share = totalNow !== 0 ? (inBase / totalNow) * 100 : 0;
              const monthlyInterest = a.interest.enabled ? estimateMonthlyInterest(a) : 0;
              return (
                <Link
                  key={a.id}
                  to="/accounts"
                  className="group rounded-xl border border-white/[0.07] bg-white/[0.025] p-3 transition hover:border-white/15 hover:bg-white/[0.05]"
                >
                  <div className="flex items-start gap-2.5">
                    <span
                      className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border"
                      style={{ color: a.color, borderColor: `${a.color}40`, background: `${a.color}18` }}
                    >
                      <Icon name={a.icon} size={15} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="truncate text-[13.5px] font-medium text-slate-100">{a.name}</span>
                        <span className="num shrink-0 text-[13.5px] font-semibold text-slate-100">
                          {fmtMoney(a.balance, a.currency, { hide, compact: true })}
                        </span>
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-slate-500">
                        {a.currency !== base && <span>≈ {fmtMoney(inBase, base, { hide, compact: true })}</span>}
                        {a.interest.enabled && (
                          <span className="text-mint-400">{fmtPercent(a.interest.annualRate, 1)} годовых</span>
                        )}
                        {a.interest.monthlyTopUp > 0 && (
                          <span>+{fmtMoney(a.interest.monthlyTopUp, a.currency, { hide, compact: true })}/мес</span>
                        )}
                      </div>
                      <div className="mt-2 flex items-center gap-2">
                        <Progress value={Math.max(0, share)} color={a.color} height={5} />
                        <span className="num w-10 shrink-0 text-right text-[10px] text-slate-500">{share.toFixed(0)}%</span>
                      </div>
                      {monthlyInterest > 0 && (
                        <div className="mt-1 text-[11px] text-mint-400/80">
                          +{fmtMoney(monthlyInterest, a.currency, { hide })} процентов в месяц
                        </div>
                      )}
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        </Card>

        <Card>
          <SectionHeader
            title="Ближайшие события"
            subtitle="Что произойдёт в ближайшие две недели"
            icon="CalendarDays"
            right={
              <Link to="/calendar" className="btn-ghost btn-sm">
                <Icon name="CalendarDays" size={14} />
              </Link>
            }
          />
          <EventsList events={upcoming} showDate showRelative dense emptyText="Ничего не запланировано" max={12} />
          {upcoming.length > 0 && (
            <div className="mt-3 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2 text-[11px] text-slate-400">
              Осталось потратить в этом периоде:{' '}
              <b className="num text-slate-100">{fmtMoney(remainingPlanned, base, { hide, compact: true })}</b>
            </div>
          )}
        </Card>
      </div>

      {/* ------------------ расходы по категориям + подписки ------------------ */}
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <SectionHeader
            title="Расходы по категориям"
            subtitle={`Период: ${period.label}`}
            icon="PieChart"
            right={
              <Link to="/analytics" className="btn-ghost btn-sm">
                Отчёты <Icon name="ChevronRight" size={14} />
              </Link>
            }
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <CategoryDonut data={expenseSlices} currency={base} hide={hide} height={230} />
            </div>
            <div className="space-y-2.5">
              {topCategories.map((c) => {
                const budget = data.categories.find((x) => x.id === c.categoryId)?.budgetMonthly;
                const pct = budget ? (c.value / budget) * 100 : 0;
                return (
                  <div key={c.categoryId}>
                    <div className="mb-1 flex items-center justify-between gap-2 text-[12.5px]">
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: c.color }} />
                        <span className="truncate text-slate-300">{c.name}</span>
                      </span>
                      <span className="num shrink-0 font-medium text-slate-100">
                        {fmtMoney(c.value, base, { hide, compact: true })}
                      </span>
                    </div>
                    {budget ? (
                      <>
                        <Progress value={c.value} max={budget} color={c.color} height={5} />
                        <div className="mt-1 flex justify-between text-[10.5px] text-slate-500">
                          <span>лимит {fmtMoney(budget, base, { hide, compact: true })}</span>
                          <span className={pct > 100 ? 'text-rose-400' : pct > 80 ? 'text-amberx-400' : 'text-slate-500'}>
                            {pct.toFixed(0)}%
                          </span>
                        </div>
                      </>
                    ) : null}
                  </div>
                );
              })}
              {!topCategories.length && <div className="py-8 text-center text-xs text-slate-500">Нет данных за период</div>}
            </div>
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <SectionHeader
              title="Подписки"
              subtitle={`${data.subscriptions.filter((s) => s.active).length} активных`}
              icon="Repeat"
              right={
                <Link to="/subscriptions" className="btn-ghost btn-sm">
                  <Icon name="ChevronRight" size={14} />
                </Link>
              }
            />
            <div className="mb-3 flex items-baseline gap-2">
              <span className="num text-2xl font-bold text-slate-50">{fmtMoney(subsMonthly, base, { hide, compact: true })}</span>
              <span className="text-xs text-slate-500">в месяц</span>
              <span className="ml-auto text-xs text-slate-500">
                {fmtMoney(subsMonthly * 12, base, { hide, compact: true })} в год
              </span>
            </div>
            <EventsList events={nextSubs} showDate dense emptyText="Нет активных подписок" />
          </Card>

          <Card>
            <SectionHeader
              title="Кредиты"
              subtitle={`Общий долг: ${fmtMoney(totalDebt, base, { hide, compact: true })}`}
              icon="CreditCard"
              right={
                <Link to="/credits" className="btn-ghost btn-sm">
                  <Icon name="ChevronRight" size={14} />
                </Link>
              }
            />
            <EventsList events={nextPayments} showDate dense emptyText="Нет активных кредитов" />
            {creditCards.map((c) => {
              const g = graceInfo(c);
              if (!g) return null;
              return (
                <div
                  key={c.id}
                  className={clsx(
                    'mt-2 flex items-center gap-2 rounded-xl border px-3 py-2 text-[11.5px]',
                    g.daysLeft <= 7 ? 'border-rose-500/30 bg-rose-500/10 text-rose-300' : 'border-mint-500/25 bg-mint-500/10 text-mint-400',
                  )}
                >
                  <Icon name="ShieldCheck" size={14} />
                  <span>
                    {c.name}: {g.daysLeft} дн. беспроцентного периода
                  </span>
                </div>
              );
            })}
          </Card>
        </div>
      </div>

      {/* ------------------------------ годовой обзор -------------------------- */}
      <Card>
        <SectionHeader
          title="Год в цифрах"
          subtitle="Доходы, расходы и чистый денежный поток по месяцам"
          icon="ChartLine"
        />
        <YearOverview />
      </Card>

      {/* --------------------------- кредиты подробно -------------------------- */}
      {loans.length > 0 && (
        <Card>
          <SectionHeader title="Кредиты и рассрочки" subtitle="Платежи, остаток и переплата" icon="Landmark" />
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {loans.map((c) => {
              const s = creditSummary(c);
              return (
                <Link
                  key={c.id}
                  to="/credits"
                  className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3.5 transition hover:border-white/15 hover:bg-white/[0.05]"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2 text-[13px] font-medium text-slate-100">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: c.color }} />
                      {c.name}
                    </span>
                    <Badge tone="slate">{fmtPercent(c.annualRate, 1)}</Badge>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[11.5px]">
                    <div>
                      <div className="text-slate-500">Платёж</div>
                      <div className="num font-semibold text-slate-100">
                        {fmtMoney(s.monthlyPayment, c.currency, { hide, compact: true })}
                      </div>
                    </div>
                    <div>
                      <div className="text-slate-500">Остаток</div>
                      <div className="num font-semibold text-slate-100">
                        {fmtMoney(s.debt, c.currency, { hide, compact: true })}
                      </div>
                    </div>
                  </div>
                  {s.payoffDate && (
                    <div className="mt-2 text-[11px] text-slate-500">
                      Закрытие: {ymLabel(ymOf(s.payoffDate))} · переплата{' '}
                      {fmtMoney(s.overpayment, c.currency, { hide, compact: true })}
                    </div>
                  )}
                </Link>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}

/* --------------------------- годовой обзор (график) ------------------------- */

function YearOverview() {
  const ctx = useCtx();
  const settings = useStore((s) => s.data.settings);
  const base = settings.baseCurrency;
  const hide = settings.hideBalances;
  const today = todayISO();

  const events = useEvents(toISO(addMonths(fromISO(today), -11)), toISO(addMonths(fromISO(today), 1)));

  const rows = useMemo(() => {
    const map = new Map<string, { income: number; expense: number }>();
    let ym = addYM(ymOf(today), -11);
    for (let i = 0; i < 13; i++) {
      map.set(ym, { income: 0, expense: 0 });
      ym = addYM(ym, 1);
    }
    for (const e of events) {
      const key = ymOf(e.date);
      const row = map.get(key);
      if (!row) continue;
      const v = convert(e.amount, e.currency, base, ctx.rates);
      if (v >= 0) row.income += v;
      else row.expense += -v;
    }
    return [...map.entries()].map(([ym, v]) => ({
      ym,
      label: ymLabel(ym, true).replace('.', ''),
      income: Math.round(v.income),
      expense: Math.round(v.expense),
      net: Math.round(v.income - v.expense),
    }));
  }, [events, base, ctx.rates, today]);

  const max = Math.max(1, ...rows.map((r) => Math.max(r.income, r.expense)));

  return (
    <div>
      <div className="flex h-[180px] items-end gap-1.5">
        {rows.map((r) => (
          <div key={r.ym} className="group flex flex-1 flex-col items-center gap-1">
            <div className="flex h-[150px] w-full items-end justify-center gap-[3px]">
              <div
                className="w-1/2 rounded-t-md bg-gradient-to-t from-mint-600/40 to-mint-400 transition-all group-hover:from-mint-500"
                style={{ height: `${(r.income / max) * 100}%` }}
                title={`Доходы: ${fmtMoney(r.income, base, { hide })}`}
              />
              <div
                className="w-1/2 rounded-t-md bg-gradient-to-t from-rose-600/40 to-rose-500 transition-all group-hover:from-rose-500"
                style={{ height: `${(r.expense / max) * 100}%` }}
                title={`Расходы: ${fmtMoney(r.expense, base, { hide })}`}
              />
            </div>
            <span className={clsx('text-[9.5px]', r.ym === ymOf(today) ? 'font-bold text-brand-300' : 'text-slate-600')}>
              {r.label.slice(0, 3)}
            </span>
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center justify-center gap-4 text-[11px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-mint-400" /> доходы
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm bg-rose-500" /> расходы
        </span>
      </div>
    </div>
  );
}
