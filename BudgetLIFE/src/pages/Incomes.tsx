import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { useStore } from '../store/useStore';
import { useCtx, useEvents } from '../store/useEngine';
import {
  AmountInput,
  Button,
  Card,
  ConfirmDialog,
  Field,
  IconButton,
  Input,
  Modal,
  SectionHeader,
  Select,
  Toggle,
  Badge,
  EmptyState,
  ColorPicker,
  IconPicker,
} from '../components/ui/primitives';
import { Icon, ICON_NAMES } from '../components/Icon';
import { incomeActiveInMonth, incomeMonthPayments } from '../lib/engine';
import { convert } from '../lib/rates';
import { fmtMoney, fmtPercent } from '../lib/format';
import {
  addYM,
  fmtDate,
  nowYM,
  todayISO,
  ymLabel,
  ymOf,
  ymRange,
} from '../lib/dates';
import type { CashflowEvent, IncomeSource, PayDay, PayDayRule, YM } from '../types';
import { uid } from '../lib/id';
import { PALETTE } from '../store/defaults';

const KINDS: { value: IncomeSource['kind']; label: string; icon: string }[] = [
  { value: 'salary', label: 'Зарплата', icon: 'Briefcase' },
  { value: 'advance', label: 'Аванс', icon: 'Wallet' },
  { value: 'freelance', label: 'Фриланс / сдельно', icon: 'Laptop' },
  { value: 'rental', label: 'Аренда', icon: 'Building2' },
  { value: 'dividends', label: 'Дивиденды', icon: 'TrendingUp' },
  { value: 'social', label: 'Пособия / пенсия', icon: 'HeartPulse' },
  { value: 'other', label: 'Прочее', icon: 'MoreHorizontal' },
];

const RULE_LABEL: Record<PayDayRule, string> = {
  exact: 'без переноса',
  prevWorkday: 'перенос на ближайший рабочий день назад',
  nextWorkday: 'перенос на следующий рабочий день',
};

/* ============================ карточка источника ============================= */

function IncomeCard({ source, onEdit }: { source: IncomeSource; onEdit: () => void }) {
  const data = useStore((s) => s.data);
  const updateIncome = useStore((s) => s.updateIncome);
  const deleteIncome = useStore((s) => s.deleteIncome);
  const setMonthOverride = useStore((s) => s.setMonthOverride);
  const setPayDayOverride = useStore((s) => s.setPayDayOverride);
  const toggleEventDone = useStore((s) => s.toggleEventDone);
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [monthsCount, setMonthsCount] = useState(6);

  const settings = data.settings;
  const hide = settings.hideBalances;
  const account = data.accounts.find((a) => a.id === source.accountId);
  const today = todayISO();
  const thisYM = nowYM();
  const months = useMemo(() => ymRange(thisYM, addYM(thisYM, monthsCount - 1)), [thisYM, monthsCount]);

  const kindMeta = KINDS.find((k) => k.value === source.kind)!;
  const taxRate = source.tax?.enabled ? (source.tax.rate ?? 0) : 0;
  const monthlyNet = source.amount * (1 - taxRate / 100);

  const upcoming = useMemo(() => {
    const out: { ym: YM; payments: ReturnType<typeof incomeMonthPayments> }[] = [];
    let ym = thisYM;
    for (let i = 0; i < 4; i++) {
      if (!incomeActiveInMonth(source, ym)) {
        ym = addYM(ym, 1);
        continue;
      }
      const payments = incomeMonthPayments(source, ym).filter((p) => p.date >= today);
      if (payments.length) out.push({ ym, payments });
      ym = addYM(ym, 1);
    }
    return out;
  }, [source, thisYM, today]);

  const isDone = (ym: YM, pdId: string, date: string) =>
    data.transactions.some(
      (t) => t.sourceKey === `income:${source.id}:${ym}:${pdId}` && t.status === 'done' && t.date === date,
    );

  const markPayment = (ym: YM, pay: { id: string; date: string; amount: number }) => {
    const event: CashflowEvent = {
      id: `income:${source.id}:${ym}:${pay.id}`,
      date: pay.date,
      title: source.name,
      amount: pay.amount,
      currency: source.currency,
      accountId: source.accountId,
      kind: 'income',
      sourceType: 'income',
      sourceId: source.id,
      sourceKey: `income:${source.id}:${ym}:${pay.id}`,
      categoryId: source.categoryId,
      status: 'planned',
    };
    toggleEventDone(event);
  };

  const yearTotal = useMemo(
    () =>
      ymRange(thisYM, addYM(thisYM, 11)).reduce((sum, ym) => {
        if (!incomeActiveInMonth(source, ym)) return sum;
        return sum + incomeMonthPayments(source, ym).reduce((s, p) => s + p.amount, 0);
      }, 0),
    [source, thisYM],
  );

  return (
    <Card className={clsx('transition', !source.active && 'opacity-60')}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border"
            style={{ color: '#10d19a', borderColor: '#10d19a33', background: '#10d19a18' }}
          >
            <Icon name={kindMeta.icon} size={18} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-[15px] font-semibold text-slate-100">{source.name}</h3>
              <Badge tone="green">{kindMeta.label}</Badge>
              {source.variable && (
                <Badge tone="amber" icon="AlertTriangle">
                  сумма плавает
                </Badge>
              )}
              {!source.active && <Badge tone="slate">не активен</Badge>}
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11.5px] text-slate-400">
              <span>{account?.name ?? '—'}</span>
              {taxRate > 0 && <span>налог {fmtPercent(taxRate, 0)}</span>}
              <span>с {ymLabel(source.startYM, true)}</span>
              {source.endYM && <span>до {ymLabel(source.endYM, true)}</span>}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1.5">
          <div className="text-right">
            <div className="num text-[17px] font-bold text-slate-50">
              {fmtMoney(monthlyNet, source.currency, { hide, compact: true })}
            </div>
            <div className="text-[10.5px] text-slate-500">
              в месяц{taxRate > 0 ? ' на руки' : ''} · {fmtMoney(yearTotal, source.currency, { hide, compact: true })} в год
            </div>
          </div>
          <IconButton icon="Pencil" label="Изменить" onClick={onEdit} />
          <IconButton
            icon={source.active ? 'Eye' : 'EyeOff'}
            label={source.active ? 'Деактивировать' : 'Активировать'}
            onClick={() => updateIncome(source.id, { active: !source.active })}
          />
          <IconButton icon="Trash2" label="Удалить" onClick={() => setConfirm(true)} className="hover:text-rose-400" />
        </div>
      </div>

      {/* ---------------------------- график выплат ---------------------------- */}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {source.payDays.map((pd) => (
          <span
            key={pd.id}
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.05] px-2 py-1 text-[11.5px] text-slate-300"
          >
            <Icon name="CalendarDays" size={12} className="text-brand-300" />
            <b className="text-slate-100">{pd.label || 'выплата'}</b>
            <span className="text-slate-500">{describeDay(pd.day)}</span>
            {pd.amount != null && (
              <span className="num text-mint-400">{fmtMoney(pd.amount, source.currency, { hide, cents: false, compact: true })}</span>
            )}
            {pd.amount == null && pd.share != null && <span className="text-slate-500">{(pd.share * 100).toFixed(0)}%</span>}
          </span>
        ))}
      </div>

      {/* -------------------------- ближайшие выплаты -------------------------- */}
      {upcoming.length > 0 && (
        <div className="mt-3 rounded-xl border border-white/[0.07] bg-white/[0.02] p-2.5">
          <div className="mb-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-500">Ближайшие выплаты</div>
          <div className="space-y-1">
            {upcoming.slice(0, 2).map(({ ym, payments }) => (
              <div key={ym} className="flex flex-wrap items-baseline gap-x-2 text-[12px]">
                <span className="w-20 shrink-0 text-slate-500">{ymLabel(ym, true)}</span>
                {payments.map((p) => {
                  const done = isDone(ym, p.id, p.date);
                  return (
                    <button
                      key={p.id}
                      onClick={() => markPayment(ym, p)}
                      className={clsx(
                        'inline-flex items-center gap-1.5 rounded-lg border px-2 py-0.5 transition',
                        done
                          ? 'border-mint-500/40 bg-mint-500/15 text-mint-400'
                          : 'border-white/10 bg-white/[0.04] text-slate-300 hover:border-mint-400/40 hover:bg-mint-500/10',
                      )}
                      title={done ? 'Отменить отметку' : 'Отметить полученным'}
                    >
                      <Icon name={done ? 'Check' : 'Clock'} size={11} />
                      <span className="num">{fmtDate(p.date, 'd MMM')}</span>
                      <span className="num font-semibold">{fmtMoney(p.amount, source.currency, { hide, cents: false, compact: true })}</span>
                      {p.tentative && <Icon name="AlertTriangle" size={11} className="text-amberx-400" />}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ------------------------ корректировки по месяцам ---------------------- */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="mt-3 flex w-full items-center justify-between rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2 text-[12.5px] text-slate-300 transition hover:bg-white/[0.05]"
      >
        <span className="flex items-center gap-2">
          <Icon name="SlidersHorizontal" size={14} className="text-brand-300" />
          Корректировки по месяцам
          <span className="text-[11px] text-slate-500">перенос дат, суммы, пропуск</span>
        </span>
        <Icon name={open ? 'ChevronUp' : 'ChevronDown'} size={15} />
      </button>

      {open && (
        <div className="mt-2 animate-slide-up overflow-hidden rounded-xl border border-white/[0.07]">
          <div className="overflow-x-auto">
            <table className="table min-w-[680px]">
              <thead>
                <tr>
                  <th className="w-28">Месяц</th>
                  <th>Выплаты (дата и сумма)</th>
                  <th className="w-36">Сумма за месяц</th>
                  <th className="w-24 text-center">Нет выплаты</th>
                </tr>
              </thead>
              <tbody>
                {months.map((ym) => {
                  const ov = source.overrides?.[ym];
                  const skipped = Boolean(ov?.skip);
                  const payments = incomeMonthPayments(source, ym);
                  return (
                    <tr key={ym} className={skipped ? 'opacity-50' : ''}>
                      <td>
                        <div className="font-medium capitalize text-slate-200">{ymLabel(ym, true)}</div>
                        {ov?.amount != null && <div className="text-[10px] text-brand-300">скорректирован</div>}
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-1.5">
                          {payments.map((p) => {
                            const done = isDone(ym, p.id, p.date);
                            const pdo = ov?.payDays?.find((x) => x.id === p.id);
                            return (
                              <div key={p.id} className="flex items-center gap-1">
                                <input
                                  type="date"
                                  value={p.date}
                                  onChange={(e) => setPayDayOverride(source.id, ym, { id: p.id, date: e.target.value })}
                                  className="input w-[124px] px-2 py-1 text-[11.5px]"
                                />
                                <div className="w-[92px]">
                                  <AmountInput
                                    value={pdo?.amount ?? (ov?.amount != null ? p.amount : undefined)}
                                    onChange={(v) =>
                                      setPayDayOverride(source.id, ym, { id: p.id, amount: v || undefined })
                                    }
                                    placeholder={Math.round(p.amount).toLocaleString('ru-RU')}
                                    className="px-2 py-1 text-[11.5px]"
                                  />
                                </div>
                                <button
                                  onClick={() => setPayDayOverride(source.id, ym, { id: p.id, skipped: !pdo?.skipped })}
                                  className={clsx(
                                    'grid h-6 w-6 place-items-center rounded-md border transition',
                                    pdo?.skipped
                                      ? 'border-rose-500/40 bg-rose-500/15 text-rose-400'
                                      : 'border-white/10 text-slate-500 hover:text-slate-200',
                                  )}
                                  title={pdo?.skipped ? 'Вернуть выплату' : 'Отменить выплату в этом месяце'}
                                >
                                  <Icon name={pdo?.skipped ? 'X' : 'Check'} size={12} />
                                </button>
                                <button
                                  onClick={() => markPayment(ym, p)}
                                  className={clsx(
                                    'grid h-6 w-6 place-items-center rounded-md border transition',
                                    done
                                      ? 'border-mint-500/40 bg-mint-500/15 text-mint-400'
                                      : 'border-white/10 text-slate-500 hover:border-mint-400/50 hover:text-mint-400',
                                  )}
                                  title={done ? 'Отменить: ещё не получено' : 'Отметить: уже получил'}
                                >
                                  <Icon name="Coins" size={12} />
                                </button>
                              </div>
                            );
                          })}
                          {!payments.length && <span className="text-[11.5px] text-slate-500">нет выплат в этом месяце</span>}
                        </div>
                      </td>
                      <td>
                        <AmountInput
                          value={ov?.amount}
                          onChange={(v) => setMonthOverride(source.id, ym, v ? { amount: v } : null)}
                          placeholder={Math.round(monthlyNet).toLocaleString('ru-RU')}
                          className="px-2 py-1 text-[12px]"
                        />
                      </td>
                      <td className="text-center">
                        <button
                          onClick={() => setMonthOverride(source.id, ym, skipped ? null : { skip: true })}
                          className={clsx(
                            'mx-auto grid h-6 w-10 place-items-center rounded-md border transition',
                            skipped ? 'border-rose-500/40 bg-rose-500/15 text-rose-400' : 'border-white/10 text-slate-600 hover:text-slate-300',
                          )}
                        >
                          <Icon name={skipped ? 'X' : 'Minus'} size={13} />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between gap-2 border-t border-white/[0.07] bg-white/[0.02] px-3 py-2">
            <span className="text-[11px] text-slate-500">
              Пустое поле = базовая сумма. Даты можно двигать в каждом месяце отдельно.
            </span>
            <Button size="sm" variant="ghost" icon="Plus" onClick={() => setMonthsCount((c) => c + 6)}>
              Ещё 6 месяцев
            </Button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={() => {
          deleteIncome(source.id);
          setConfirm(false);
        }}
        title={`Удалить «${source.name}»?`}
        description="Источник дохода и связанные с ним факт-операции будут удалены. Базовые настройки счетов не затронуты."
      />
    </Card>
  );
}

function describeDay(day: number): string {
  if (day === -1) return 'в последний день';
  if (day === -2) return 'в предпоследний день';
  return `${day}-го числа`;
}

/* ============================== модальное окно =============================== */

function IncomeModal({ open, onClose, source }: { open: boolean; onClose: () => void; source?: IncomeSource }) {
  const data = useStore((s) => s.data);
  const addIncome = useStore((s) => s.addIncome);
  const updateIncome = useStore((s) => s.updateIncome);

  const [draft, setDraft] = useState<IncomeSource>(() => source ?? blank(data.settings.baseCurrency, data.accounts[0]?.id));
  const [showIcon, setShowIcon] = useState(false);

  const set = (patch: Partial<IncomeSource>) => setDraft((d) => ({ ...d, ...patch }));

  const shareTotal = draft.payDays.reduce((s, p) => s + (p.amount == null ? (p.share ?? 0) : 0), 0);

  const submit = () => {
    if (!draft.name.trim()) return;
    const payload: Partial<IncomeSource> = {
      ...draft,
      amount: Math.max(0, draft.amount),
      payDays: draft.payDays.length ? draft.payDays : [{ id: uid('pd'), label: 'Выплата', day: 10, rule: 'prevWorkday' }],
    };
    if (source) updateIncome(source.id, payload);
    else addIncome(payload);
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={source ? 'Источник дохода' : 'Новый источник дохода'}
      subtitle="Несколько дней выплат, плавающие даты, корректировка сумм по месяцам"
      icon="TrendingUp"
      width="max-w-3xl"
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" icon="Check" onClick={submit}>
            {source ? 'Сохранить' : 'Добавить'}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Название" className="sm:col-span-2">
          <Input data-autofocus value={draft.name} onChange={(e) => set({ name: e.target.value })} placeholder="Например: Зарплата в ООО «Ромашка»" />
        </Field>

        <Field label="Тип дохода">
          <Select value={draft.kind} onChange={(e) => set({ kind: e.target.value as IncomeSource['kind'] })}>
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Счёт зачисления">
          <Select value={draft.accountId} onChange={(e) => set({ accountId: e.target.value })}>
            {data.accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.currency})
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Сумма в месяц">
          <AmountInput value={draft.amount} onChange={(v) => set({ amount: v })} suffix={draft.currency} />
        </Field>

        <Field label="Валюта">
          <Select value={draft.currency} onChange={(e) => set({ currency: e.target.value })}>
            {[...new Set([draft.currency, ...data.accounts.map((a) => a.currency), 'RUB', 'USD', 'EUR'])].map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Категория">
          <Select value={draft.categoryId ?? ''} onChange={(e) => set({ categoryId: e.target.value || undefined })}>
            <option value="">Без категории</option>
            {data.categories
              .filter((c) => c.kind === 'income')
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </Select>
        </Field>

        <Field label="Первый месяц">
          <Input
            type="month"
            value={draft.startYM}
            onChange={(e) => set({ startYM: e.target.value || draft.startYM })}
          />
        </Field>

        <Field label="Последний месяц" hint="Оставьте пустым, если доход постоянный">
          <Input
            type="month"
            value={draft.endYM ?? ''}
            onChange={(e) => set({ endYM: e.target.value || undefined })}
          />
        </Field>

        <div className="sm:col-span-2">
          <Toggle
            checked={draft.variable}
            onChange={(v) => set({ variable: v })}
            label="Сумма меняется от месяца к месяцу"
            hint="Для сдельной работы и фриланса: в календаре сумма будет помечена как «уточнить»"
          />
        </div>

        <div className="sm:col-span-2">
          <Toggle
            checked={draft.tax?.enabled ?? false}
            onChange={(v) => set({ tax: { enabled: v, rate: draft.tax?.rate ?? 13 } })}
            label="Удерживается налог"
            hint="Например НДФЛ 13% — в план попадёт сумма на руки"
          />
          {draft.tax?.enabled && (
            <div className="mt-2 w-40">
              <AmountInput value={draft.tax.rate} onChange={(v) => set({ tax: { enabled: true, rate: v } })} suffix="%" />
            </div>
          )}
        </div>
      </div>

      {/* ------------------------------ дни выплат ------------------------------ */}
      <div className="mt-5">
        <div className="mb-2 flex items-center justify-between">
          <div>
            <h4 className="text-[13.5px] font-semibold text-slate-100">Дни выплат</h4>
            <p className="text-[11.5px] text-slate-500">
              Можно добавить несколько: аванс и зарплата, несколько заказчиков, премии
            </p>
          </div>
          <Button
            size="sm"
            variant="soft"
            icon="Plus"
            onClick={() =>
              set({
                payDays: [
                  ...draft.payDays,
                  { id: uid('pd'), label: `Выплата ${draft.payDays.length + 1}`, day: 20, rule: 'prevWorkday' },
                ],
              })
            }
          >
            Добавить день
          </Button>
        </div>

        <div className="space-y-2">
          {draft.payDays.map((pd, i) => (
            <div key={pd.id} className="grid items-end gap-2 rounded-xl border border-white/[0.07] bg-white/[0.02] p-2.5 sm:grid-cols-[1fr_120px_150px_150px_32px]">
              <Field label="Название">
                <Input value={pd.label} onChange={(e) => updatePayDay(i, { label: e.target.value })} placeholder="Аванс" />
              </Field>
              <Field label="День">
                <Input
                  type="number"
                  min={-2}
                  max={31}
                  value={pd.day}
                  onChange={(e) => updatePayDay(i, { day: Number(e.target.value) })}
                  title={pd.day < 0 ? describeDay(pd.day) : undefined}
                />
              </Field>
              <Field label="Доля, %" hint="или фикс. сумма">
                <AmountInput
                  value={pd.share != null ? pd.share * 100 : undefined}
                  onChange={(v) => updatePayDay(i, { share: v / 100, amount: undefined })}
                  placeholder="поровну"
                  suffix="%"
                />
              </Field>
              <Field label="Фикс. сумма">
                <AmountInput
                  value={pd.amount}
                  onChange={(v) => updatePayDay(i, { amount: v || undefined })}
                  placeholder="—"
                  suffix={draft.currency}
                />
              </Field>
              <div className="flex items-center gap-1 pb-1">
                <select
                  className="select px-2 py-2 text-[11px]"
                  value={pd.rule}
                  onChange={(e) => updatePayDay(i, { rule: e.target.value as PayDayRule })}
                  title={`Если выплата выпадает на выходной: ${RULE_LABEL[pd.rule]}`}
                >
                  <option value="prevWorkday">← рабочий</option>
                  <option value="nextWorkday">рабочий →</option>
                  <option value="exact">без переноса</option>
                </select>
                <IconButton
                  icon="Trash2"
                  label="Удалить"
                  onClick={() => set({ payDays: draft.payDays.filter((p) => p.id !== pd.id) })}
                  className="hover:text-rose-400"
                />
              </div>
            </div>
          ))}
        </div>

        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11.5px]">
          <span className={clsx(shareTotal > 1.0001 ? 'text-rose-400' : 'text-slate-500')}>
            Доли: {(shareTotal * 100).toFixed(0)}%
            {shareTotal > 1.0001 && ' — больше 100%, проверьте'}
            {shareTotal > 0 && shareTotal < 0.9999 && ' — остаток распределится поровну'}
          </span>
          <span className="text-slate-500">
            {draft.payDays.length > 0 && (
              <>
                Пример на {ymLabel(nowYM(), true)}:{' '}
                {(() => {
                  const payments = incomeMonthPayments({ ...draft, active: true }, nowYM());
                  return payments
                    .map((p) => `${fmtDate(p.date, 'd MMM')}: ${Math.round(p.amount).toLocaleString('ru-RU')}`)
                    .join(' · ');
                })()}
              </>
            )}
          </span>
        </div>

        <div className="mt-4">
          <Field label="Заметка">
            <Input value={draft.note ?? ''} onChange={(e) => set({ note: e.target.value })} placeholder="Любые детали" />
          </Field>
        </div>

        {showIcon && (
          <div className="mt-3 space-y-3">
            <div>
              <div className="label">Цвет</div>
              <ColorPicker value={draft.categoryId ?? PALETTE[0]} onChange={() => undefined} colors={PALETTE} />
            </div>
            <div>
              <div className="label">Иконка</div>
              <IconPicker
                value="Wallet"
                onChange={() => undefined}
                names={ICON_NAMES.slice(0, 48)}
              />
            </div>
          </div>
        )}
        <button className="mt-3 text-[11px] text-slate-500 hover:text-slate-300" onClick={() => setShowIcon((v) => !v)}>
          {showIcon ? 'Скрыть оформление' : 'Оформление (цвет и иконка)'}
        </button>
      </div>
    </Modal>
  );

  function updatePayDay(i: number, patch: Partial<PayDay>) {
    setDraft((d) => ({ ...d, payDays: d.payDays.map((p, idx) => (idx === i ? { ...p, ...patch } : p)) }));
  }
}

function blank(currency: string, accountId?: string): IncomeSource {
  return {
    id: uid('inc'),
    name: '',
    kind: 'salary',
    accountId: accountId ?? '',
    currency,
    amount: 0,
    variable: false,
    payDays: [{ id: uid('pd'), label: 'Зарплата', day: 20, rule: 'prevWorkday' }],
    startYM: nowYM(),
    active: true,
    overrides: {},
    order: 0,
  };
}

/* ================================= страница ================================== */

export default function Incomes() {
  const data = useStore((s) => s.data);
  const ctx = useCtx();
  const settings = data.settings;
  const base = settings.baseCurrency;
  const hide = settings.hideBalances;
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<IncomeSource | undefined>();

  const nowYMv = nowYM();
  const events = useEvents(`${nowYMv}-01`, `${addYM(nowYMv, 11)}-31`);

  const monthlyPlan = useMemo(() => {
    let sum = 0;
    for (const src of data.incomes) {
      if (!src.active) continue;
      for (const p of incomeMonthPayments(src, nowYMv)) {
        sum += convert(p.amount, src.currency, base, ctx.rates);
      }
    }
    return sum;
  }, [data.incomes, base, ctx.rates, nowYMv]);

  const yearPlan = useMemo(() => {
    let sum = 0;
    for (const src of data.incomes) {
      if (!src.active) continue;
      for (let i = 0; i < 12; i++) {
        const ym = addYM(nowYMv, i);
        for (const p of incomeMonthPayments(src, ym)) sum += convert(p.amount, src.currency, base, ctx.rates);
      }
    }
    return sum;
  }, [data.incomes, base, ctx.rates, nowYMv]);

  const paidThisMonth = useMemo(
    () =>
      events
        .filter((e) => e.sourceType === 'income' && e.status === 'done' && ymOf(e.date) === nowYMv)
        .reduce((s, e) => s + convert(e.amount, e.currency, base, ctx.rates), 0),
    [events, base, ctx.rates, nowYMv],
  );

  const months = useMemo(() => ymRange(nowYMv, addYM(nowYMv, 5)), [nowYMv]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">План на месяц</div>
          <div className="num mt-1 text-2xl font-bold text-slate-50">{fmtMoney(monthlyPlan, base, { hide, compact: true })}</div>
          <div className="mt-1 text-[11px] text-slate-500">{ymLabel(nowYMv)}</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">Уже получено</div>
          <div className="num mt-1 text-2xl font-bold text-mint-400">{fmtMoney(paidThisMonth, base, { hide, compact: true })}</div>
          <div className="mt-1 text-[11px] text-slate-500">
            {monthlyPlan > 0 ? `${((paidThisMonth / monthlyPlan) * 100).toFixed(0)}% от плана месяца` : '—'}
          </div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">План на 12 месяцев</div>
          <div className="num mt-1 text-2xl font-bold text-slate-50">{fmtMoney(yearPlan, base, { hide, compact: true })}</div>
          <div className="mt-1 text-[11px] text-slate-500">{data.incomes.filter((i) => i.active).length} активных источников</div>
        </Card>
      </div>

      <Card>
        <SectionHeader
          title="Источники дохода"
          subtitle="Зарплата с авансом, сдельная работа, аренда, дивиденды — с корректировкой дат и сумм по месяцам"
          icon="TrendingUp"
          right={
            <Button
              variant="primary"
              icon="Plus"
              onClick={() => {
                setEditing(undefined);
                setModalOpen(true);
              }}
            >
              Добавить доход
            </Button>
          }
        />

        {data.incomes.length ? (
          <div className="space-y-3">
            {[...data.incomes]
              .sort((a, b) => a.order - b.order)
              .map((src) => (
                <IncomeCard
                  key={src.id}
                  source={src}
                  onEdit={() => {
                    setEditing(src);
                    setModalOpen(true);
                  }}
                />
              ))}
          </div>
        ) : (
          <EmptyState
            icon="TrendingUp"
            title="Пока нет источников дохода"
            description="Добавьте зарплату — укажите день аванса и день зарплаты, а сумму потом можно корректировать в каждом месяце отдельно."
            action={
              <Button
                variant="primary"
                icon="Plus"
                onClick={() => {
                  setEditing(undefined);
                  setModalOpen(true);
                }}
              >
                Добавить доход
              </Button>
            }
          />
        )}
      </Card>

      {/* ------------------------- сетка выплат на полгода ------------------------ */}
      {data.incomes.length > 0 && (
        <Card pad={false}>
          <div className="p-4 pb-2">
            <SectionHeader title="Сетка выплат" subtitle="Все поступления по месяцам — план и факт" icon="CalendarDays" />
          </div>
          <div className="overflow-x-auto">
            <table className="table min-w-[720px]">
              <thead>
                <tr>
                  <th>Месяц</th>
                  {data.incomes
                    .filter((i) => i.active)
                    .map((i) => (
                      <th key={i.id}>{i.name}</th>
                    ))}
                  <th className="text-right">Итого</th>
                </tr>
              </thead>
              <tbody>
                {months.map((ym) => {
                  let total = 0;
                  return (
                    <tr key={ym}>
                      <td className="font-medium capitalize text-slate-200">{ymLabel(ym, true)}</td>
                      {data.incomes
                        .filter((i) => i.active)
                        .map((src) => {
                          const payments = incomeMonthPayments(src, ym);
                          const sum = payments.reduce((s, p) => s + convert(p.amount, src.currency, base, ctx.rates), 0);
                          total += sum;
                          return (
                            <td key={src.id}>
                              {payments.length ? (
                                <div className="space-y-0.5">
                                  {payments.map((p) => (
                                    <div key={p.id} className="flex items-center gap-2">
                                      <span className="num text-[11px] text-slate-400">{fmtDate(p.date, 'd MMM')}</span>
                                      <span className="num text-[12px] font-medium text-slate-100">
                                        {fmtMoney(p.amount, src.currency, { hide, cents: false, compact: true, tight: true })}
                                      </span>
                                      {p.tentative && <Icon name="AlertTriangle" size={11} className="text-amberx-400" />}
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <span className="text-slate-600">—</span>
                              )}
                            </td>
                          );
                        })}
                      <td className="num text-right font-semibold text-slate-100">
                        {fmtMoney(total, base, { hide, cents: false, compact: true, tight: true })}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <IncomeModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        source={editing}
        key={editing?.id ?? 'new'}
      />
    </div>
  );
}
