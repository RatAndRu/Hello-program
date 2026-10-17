import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { useStore } from '../store/useStore';
import { useCtx, useProjection } from '../store/useEngine';
import {
  AmountInput,
  Badge,
  Button,
  Card,
  ColorPicker,
  ConfirmDialog,
  EmptyState,
  Field,
  IconButton,
  IconPicker,
  Input,
  Modal,
  Progress,
  SectionHeader,
  Select,
  Toggle,
} from '../components/ui/primitives';
import { ICON_NAMES, Icon } from '../components/Icon';
import { ACCOUNT_TYPES, PALETTE, emptyInterest, newAccount } from '../store/defaults';
import { convert } from '../lib/rates';
import { fmtMoney, fmtPercent } from '../lib/format';
import { addMonths, fromISO, nowYM, toISO, todayISO, ymLabel, ymOf } from '../lib/dates';
import { estimateMonthlyInterest } from '../lib/engine';
import { Sparkline } from '../components/charts';
import type { Account, AccountType, Capitalization, Currency } from '../types';
import { CURRENCY_OPTIONS } from '../lib/format';

const CAP_OPTIONS: { value: Capitalization; label: string; hint: string }[] = [
  { value: 'none', label: 'Без процентов', hint: 'Проценты не начисляются' },
  { value: 'daily', label: 'Ежедневно', hint: 'Начисление и зачисление каждый день — максимальная капитализация' },
  { value: 'monthly', label: 'Раз в месяц', hint: 'Проценты начисляются каждый день, зачисляются раз в месяц' },
  { value: 'quarterly', label: 'Раз в квартал', hint: 'Зачисление 4 раза в год' },
  { value: 'yearly', label: 'Раз в год', hint: 'Зачисление раз в год' },
  { value: 'endOfTerm', label: 'В конце срока', hint: 'Для вкладов: вся сумма процентов в дату закрытия' },
];

/* ============================== карточка счёта =============================== */

function AccountCard({ account, onEdit }: { account: Account; onEdit: () => void }) {
  const data = useStore((s) => s.data);
  const updateAccount = useStore((s) => s.updateAccount);
  const deleteAccount = useStore((s) => s.deleteAccount);
  const ctx = useCtx();
  const [confirm, setConfirm] = useState(false);
  const [details, setDetails] = useState(false);
  const settings = data.settings;
  const base = settings.baseCurrency;
  const hide = settings.hideBalances;

  const inBase = convert(account.balance, account.currency, base, ctx.rates);
  const monthly = account.interest.enabled ? estimateMonthlyInterest(account) : 0;
  const yearInterest = monthly * 12;
  const total = data.accounts
    .filter((a) => a.includeInTotal && !a.archived)
    .reduce((s, a) => s + convert(a.balance, a.currency, base, ctx.rates), 0);
  const share = total !== 0 ? (inBase / total) * 100 : 0;
  const meta = ACCOUNT_TYPES[account.type];

  /* прогноз по счёту на 12 месяцев */
  const projection = useProjection(todayISO(), toISO(addMonths(fromISO(todayISO()), 12)));
  const series = useMemo(() => projection.days.map((d) => d.byAccount[account.id] ?? 0), [projection.days, account.id]);
  const grow = series.length > 1 ? series[series.length - 1] - series[0] : 0;

  const capLabel = CAP_OPTIONS.find((c) => c.value === account.interest.capitalization)?.label ?? '';

  return (
    <Card className={clsx('flex flex-col', account.archived && 'opacity-60')}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border text-[18px]"
            style={{ color: account.color, borderColor: `${account.color}40`, background: `${account.color}18` }}
          >
            <Icon name={account.icon || meta.icon} size={19} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-[15px] font-semibold text-slate-100">{account.name}</h3>
              <Badge tone="slate">{meta.label}</Badge>
              {account.archived && <Badge tone="slate">в архиве</Badge>}
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2.5 text-[11.5px] text-slate-400">
              <span className="num">{fmtMoney(account.balance, account.currency, { hide })}</span>
              {account.currency !== base && (
                <span className="text-slate-500">≈ {fmtMoney(inBase, base, { hide, compact: true })}</span>
              )}
              {!account.includeInTotal && <span className="text-amberx-400">не в общем балансе</span>}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <IconButton icon="Pencil" label="Изменить" onClick={onEdit} />
          <IconButton
            icon={account.archived ? 'RotateCcw' : 'Inbox'}
            label={account.archived ? 'Вернуть из архива' : 'В архив'}
            onClick={() => updateAccount(account.id, { archived: !account.archived })}
          />
          <IconButton icon="Trash2" label="Удалить" onClick={() => setConfirm(true)} className="hover:text-rose-400" />
        </div>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <Progress value={Math.max(0, share)} color={account.color} height={6} />
        <span className="num w-11 shrink-0 text-right text-[10.5px] text-slate-500">{share.toFixed(0)}%</span>
      </div>

      {account.interest.enabled && account.interest.annualRate > 0 && (
        <div className="mt-3 grid grid-cols-3 gap-2 rounded-xl border border-mint-500/20 bg-mint-500/[0.06] p-2.5">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400">Ставка</div>
            <div className="num text-[13px] font-semibold text-mint-400">{fmtPercent(account.interest.annualRate, 1)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400">В месяц</div>
            <div className="num text-[13px] font-semibold text-slate-100">
              {fmtMoney(monthly, account.currency, { hide, compact: true })}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-400">В год</div>
            <div className="num text-[13px] font-semibold text-slate-100">
              {fmtMoney(yearInterest, account.currency, { hide, compact: true })}
            </div>
          </div>
          <div className="col-span-3 mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
            <span className="flex items-center gap-1">
              <Icon name="RefreshCw" size={11} /> {capLabel}
              {account.interest.payoutDay && account.interest.capitalization !== 'daily' && ` · ${account.interest.payoutDay}-го`}
            </span>
            {account.interest.payoutMode === 'payout' && (
              <span className="flex items-center gap-1">
                <Icon name="ArrowRight" size={11} />
                выплата на {data.accounts.find((a) => a.id === account.interest.payoutAccountId)?.name ?? 'счёт'}
              </span>
            )}
            {account.interest.monthlyTopUp > 0 && (
              <span className="flex items-center gap-1">
                <Icon name="PlusCircle" size={11} />
                пополнение {fmtMoney(account.interest.monthlyTopUp, account.currency, { hide, cents: false, compact: true })} с{' '}
                {account.interest.topUpDay}-го
              </span>
            )}
          </div>
        </div>
      )}

      {series.length > 1 && (
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
            <span>Прогноз на 12 месяцев</span>
            <span className={clsx('num font-medium', grow >= 0 ? 'text-mint-400' : 'text-rose-400')}>
              {grow >= 0 ? '+' : '−'}
              {fmtMoney(Math.abs(grow), account.currency, { hide, cents: false, compact: true, tight: true })}
            </span>
          </div>
          <Sparkline values={series} color={account.color} height={44} />
        </div>
      )}

      {account.note && (
        <p className="mt-2 line-clamp-2 text-[11.5px] text-slate-500">{account.note}</p>
      )}

      <button
        onClick={() => setDetails((v) => !v)}
        className="mt-2 text-[11px] text-slate-500 hover:text-slate-300"
      >
        {details ? 'Скрыть детали' : 'Подробности и расчёт процентов'}
      </button>

      {details && (
        <div className="mt-2 space-y-1.5 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3 text-[11.5px] animate-slide-up">
          <Row label="Валюта" value={account.currency} />
          <Row label="Учитывается в общем балансе" value={account.includeInTotal ? 'да' : 'нет'} />
          {account.creditLimit ? <Row label="Кредитный лимит" value={fmtMoney(account.creditLimit, account.currency, { hide })} /> : null}
          {account.interest.termStart && <Row label="Открыт" value={account.interest.termStart} />}
          {account.interest.termEnd && <Row label="Закрытие" value={account.interest.termEnd} />}
          <Row
            label="Эффективная доходность за год"
            value={
              account.balance > 0
                ? fmtPercent((yearInterest / Math.max(1, account.balance)) * 100, 2)
                : '—'
            }
          />
          <Row
            label="Через 12 месяцев (прогноз)"
            value={fmtMoney(series[series.length - 1] ?? account.balance, account.currency, { hide, compact: true })}
          />
        </div>
      )}

      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={() => {
          deleteAccount(account.id);
          setConfirm(false);
        }}
        title={`Удалить счёт «${account.name}»?`}
        description="Все операции по этому счёту тоже будут удалены. Это действие необратимо."
      />
    </Card>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-slate-500">{label}</span>
      <span className="num font-medium text-slate-200">{value}</span>
    </div>
  );
}

/* =============================== модалка счёта =============================== */

function AccountModal({ open, onClose, account }: { open: boolean; onClose: () => void; account?: Account }) {
  const data = useStore((s) => s.data);
  const addAccount = useStore((s) => s.addAccount);
  const updateAccount = useStore((s) => s.updateAccount);

  const [draft, setDraft] = useState<Account>(() => account ?? newAccount({ currency: data.settings.baseCurrency }));
  const [tab, setTab] = useState<'main' | 'interest' | 'look'>('main');

  const set = (patch: Partial<Account>) => setDraft((d) => ({ ...d, ...patch }));
  const setInterest = (patch: Partial<Account['interest']>) =>
    setDraft((d) => ({ ...d, interest: { ...d.interest, ...patch } }));

  const monthly = draft.interest.enabled ? estimateMonthlyInterest(draft) : 0;

  const submit = () => {
    const payload = { ...draft, name: draft.name.trim() || 'Счёт' };
    if (account) updateAccount(account.id, payload);
    else addAccount(payload);
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={account ? `Счёт: ${account.name}` : 'Новый счёт'}
      subtitle="Баланс, проценты на остаток, капитализация и автопополнение"
      icon="Wallet"
      width="max-w-3xl"
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" icon="Check" onClick={submit}>
            {account ? 'Сохранить' : 'Создать счёт'}
          </Button>
        </>
      }
    >
      <div className="mb-4 flex gap-1.5">
        {(['main', 'interest', 'look'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={clsx(
              'rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition',
              tab === t ? 'bg-white/[0.12] text-white' : 'text-slate-400 hover:bg-white/[0.06]',
            )}
          >
            {t === 'main' ? 'Основное' : t === 'interest' ? 'Проценты' : 'Оформление'}
          </button>
        ))}
      </div>

      {tab === 'main' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Название" className="sm:col-span-2">
            <Input data-autofocus value={draft.name} onChange={(e) => set({ name: e.target.value })} placeholder="Например: Карта Тинькофф" />
          </Field>

          <Field label="Тип счёта" hint={ACCOUNT_TYPES[draft.type].hint}>
            <Select
              value={draft.type}
              onChange={(e) => {
                const type = e.target.value as AccountType;
                set({ type, icon: ACCOUNT_TYPES[type].icon, color: ACCOUNT_TYPES[type].color });
              }}
            >
              {Object.entries(ACCOUNT_TYPES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Валюта">
            <Select value={draft.currency} onChange={(e) => set({ currency: e.target.value as Currency })}>
              {CURRENCY_OPTIONS.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code} — {c.label}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Текущий баланс">
            <AmountInput value={draft.balance} onChange={(v) => set({ balance: v })} suffix={draft.currency} />
          </Field>

          {draft.type === 'credit' && (
            <Field label="Кредитный лимит">
              <AmountInput
                value={draft.creditLimit}
                onChange={(v) => set({ creditLimit: v })}
                suffix={draft.currency}
              />
            </Field>
          )}

          <div className="sm:col-span-2">
            <Toggle
              checked={draft.includeInTotal}
              onChange={(v) => set({ includeInTotal: v })}
              label="Учитывать в общем балансе"
              hint="Выключите, если не хотите видеть этот счёт в сводке"
            />
          </div>

          <Field label="Заметка" className="sm:col-span-2">
            <Input value={draft.note ?? ''} onChange={(e) => set({ note: e.target.value })} placeholder="Любые детали" />
          </Field>
        </div>
      )}

      {tab === 'interest' && (
        <div className="space-y-4">
          <Toggle
            checked={draft.interest.enabled}
            onChange={(v) => setInterest({ enabled: v })}
            label="Начисляются проценты"
            hint="Вклад, накопительный счёт или процент на остаток"
          />

          {draft.interest.enabled && (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Годовая ставка">
                  <AmountInput value={draft.interest.annualRate} onChange={(v) => setInterest({ annualRate: v })} suffix="%" />
                </Field>

                <Field label="Капитализация" hint={CAP_OPTIONS.find((c) => c.value === draft.interest.capitalization)?.hint}>
                  <Select
                    value={draft.interest.capitalization}
                    onChange={(e) => setInterest({ capitalization: e.target.value as Capitalization })}
                  >
                    {CAP_OPTIONS.map((c) => (
                      <option key={c.value} value={c.value}>
                        {c.label}
                      </option>
                    ))}
                  </Select>
                </Field>

                {draft.interest.capitalization !== 'none' && draft.interest.capitalization !== 'daily' && (
                  <Field label="День зачисления процентов" hint="По умолчанию — последний день месяца">
                    <Input
                      type="number"
                      min={1}
                      max={31}
                      value={draft.interest.payoutDay ?? ''}
                      onChange={(e) => setInterest({ payoutDay: e.target.value ? Number(e.target.value) : undefined })}
                      placeholder="последний день"
                    />
                  </Field>
                )}

                <Field label="Что делать с процентами">
                  <Select
                    value={draft.interest.payoutMode}
                    onChange={(e) => setInterest({ payoutMode: e.target.value as 'compound' | 'payout' })}
                  >
                    <option value="compound">Капитализация (остаются на счёте)</option>
                    <option value="payout">Выплачивать на другой счёт</option>
                  </Select>
                </Field>

                {draft.interest.payoutMode === 'payout' && (
                  <Field label="Счёт для выплаты процентов">
                    <Select
                      value={draft.interest.payoutAccountId ?? ''}
                      onChange={(e) => setInterest({ payoutAccountId: e.target.value || undefined })}
                    >
                      <option value="">Выберите счёт</option>
                      {data.accounts
                        .filter((a) => a.id !== draft.id)
                        .map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                    </Select>
                  </Field>
                )}

                {draft.interest.capitalization === 'endOfTerm' && (
                  <Field label="Дата окончания вклада">
                    <Input
                      type="date"
                      value={draft.interest.termEnd ?? ''}
                      onChange={(e) => setInterest({ termEnd: e.target.value || undefined })}
                    />
                  </Field>
                )}
              </div>

              <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-[13px] font-semibold text-slate-200">Автопополнение</span>
                  <span className="text-[11px] text-slate-500">учтётся в прогнозе и календаре</span>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <Field label="Сумма в месяц">
                    <AmountInput
                      value={draft.interest.monthlyTopUp || undefined}
                      onChange={(v) => setInterest({ monthlyTopUp: v })}
                      suffix={draft.currency}
                    />
                  </Field>
                  <Field label="День пополнения">
                    <Input
                      type="number"
                      min={1}
                      max={31}
                      value={draft.interest.topUpDay || ''}
                      onChange={(e) => setInterest({ topUpDay: Number(e.target.value) || 1 })}
                    />
                  </Field>
                  <Field label="Начиная с месяца">
                    <Input
                      type="month"
                      value={draft.interest.topUpStartYM ?? ''}
                      onChange={(e) => setInterest({ topUpStartYM: e.target.value || undefined })}
                    />
                  </Field>
                </div>
              </div>

              <div className="rounded-xl border border-mint-500/20 bg-mint-500/[0.07] p-3">
                <div className="mb-1.5 text-[11px] uppercase tracking-wide text-slate-400">Расчёт</div>
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <div className="num text-[15px] font-semibold text-mint-400">
                      {fmtMoney(monthly, draft.currency, { cents: false, compact: true })}
                    </div>
                    <div className="text-[10.5px] text-slate-500">в месяц</div>
                  </div>
                  <div>
                    <div className="num text-[15px] font-semibold text-slate-100">
                      {fmtMoney(monthly * 12, draft.currency, { cents: false, compact: true })}
                    </div>
                    <div className="text-[10.5px] text-slate-500">за год</div>
                  </div>
                  <div>
                    <div className="num text-[15px] font-semibold text-slate-100">
                      {fmtMoney(
                        draft.balance + monthly * 12 + (draft.interest.monthlyTopUp || 0) * 12,
                        draft.currency,
                        { cents: false, compact: true },
                      )}
                    </div>
                    <div className="text-[10.5px] text-slate-500">баланс через год</div>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {tab === 'look' && (
        <div className="space-y-4">
          <div>
            <div className="label">Цвет</div>
            <ColorPicker value={draft.color} onChange={(c) => set({ color: c })} colors={PALETTE} />
          </div>
          <div>
            <div className="label">Иконка</div>
            <IconPicker value={draft.icon} onChange={(n) => set({ icon: n })} names={ICON_NAMES} color={draft.color} />
          </div>
        </div>
      )}
    </Modal>
  );
}

/* ============================== модалка перевода ============================= */

function TransferModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const data = useStore((s) => s.data);
  const addTransaction = useStore((s) => s.addTransaction);
  const [from, setFrom] = useState(data.accounts[0]?.id ?? '');
  const [to, setTo] = useState(data.accounts[1]?.id ?? data.accounts[0]?.id ?? '');
  const [amount, setAmount] = useState<number>(0);
  const [date, setDate] = useState(todayISO());
  const [status, setStatus] = useState<'planned' | 'done'>('planned');

  const fromAcc = data.accounts.find((a) => a.id === from);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Перевод между счетами"
      icon="ArrowLeftRight"
      width="max-w-lg"
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button
            variant="primary"
            icon="Check"
            onClick={() => {
              if (!amount || !from || !to || from === to) return;
              addTransaction({
                title: 'Перевод между счетами',
                amount: -Math.abs(amount),
                date,
                accountId: from,
                toAccountId: to,
                kind: 'transfer',
                status,
                sourceType: status === 'planned' ? 'planned' : 'manual',
                currency: fromAcc?.currency,
              });
              onClose();
            }}
          >
            Перевести
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Откуда">
          <Select value={from} onChange={(e) => setFrom(e.target.value)}>
            {data.accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.currency})
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Куда">
          <Select value={to} onChange={(e) => setTo(e.target.value)}>
            {data.accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.currency})
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Сумма">
          <AmountInput value={amount} onChange={setAmount} suffix={fromAcc?.currency} />
        </Field>
        <Field label="Дата">
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Статус" className="sm:col-span-2">
          <Select value={status} onChange={(e) => setStatus(e.target.value as 'planned' | 'done')}>
            <option value="planned">Запланирован</option>
            <option value="done">Уже выполнен</option>
          </Select>
        </Field>
      </div>
      {from === to && <div className="field-error">Выберите разные счета</div>}
    </Modal>
  );
}

/* ================================= страница ================================== */

export default function Accounts() {
  const data = useStore((s) => s.data);
  const ctx = useCtx();
  const settings = data.settings;
  const base = settings.baseCurrency;
  const hide = settings.hideBalances;
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Account | undefined>();
  const [transferOpen, setTransferOpen] = useState(false);
  const [showArchived, setShowArchived] = useState(false);

  const today = todayISO();
  const projection = useProjection(today, toISO(addMonths(fromISO(today), 12)));

  const totals = useMemo(() => {
    const byCurrency = new Map<string, number>();
    let total = 0;
    for (const a of data.accounts) {
      if (!a.includeInTotal || a.archived) continue;
      const v = convert(a.balance, a.currency, base, ctx.rates);
      total += v;
      byCurrency.set(a.currency, (byCurrency.get(a.currency) ?? 0) + a.balance);
    }
    return { total, byCurrency: [...byCurrency.entries()].sort((x, y) => y[1] - x[1]) };
  }, [data.accounts, base, ctx.rates]);

  const passiveMonthly = useMemo(
    () =>
      data.accounts
        .filter((a) => a.interest.enabled && !a.archived)
        .reduce((s, a) => s + convert(estimateMonthlyInterest(a), a.currency, base, ctx.rates), 0),
    [data.accounts, base, ctx.rates],
  );

  const totalSeries = projection.days.map((d) => d.balance);
  const yearGrowth = totalSeries.length > 1 ? totalSeries[totalSeries.length - 1] - totalSeries[0] : 0;

  const accounts = data.accounts.filter((a) => showArchived || !a.archived);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 xl:grid-cols-4">
        <Card className="xl:col-span-2">
          <div className="flex items-start justify-between">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-slate-400">Общий баланс</div>
              <div className="num mt-1 text-3xl font-bold tracking-tight text-slate-50">
                {fmtMoney(totals.total, base, { hide, compact: true })}
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {totals.byCurrency.map(([cur, v]) => (
                  <span key={cur} className="chip num">
                    {fmtMoney(v, cur, { hide, cents: false, compact: true, tight: true })}
                  </span>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Button variant="primary" size="sm" icon="Plus" onClick={() => { setEditing(undefined); setModalOpen(true); }}>
                Счёт
              </Button>
              <Button variant="ghost" size="sm" icon="ArrowLeftRight" onClick={() => setTransferOpen(true)}>
                Перевод
              </Button>
            </div>
          </div>
          <div className="mt-4">
            <Sparkline values={totalSeries} color="#38c3f5" height={56} />
            <div className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
              <span>Прогноз на 12 месяцев</span>
              <span className={clsx('num font-medium', yearGrowth >= 0 ? 'text-mint-400' : 'text-rose-400')}>
                {yearGrowth >= 0 ? '+' : '−'}
                {fmtMoney(Math.abs(yearGrowth), base, { hide, cents: false, compact: true, tight: true })}
              </span>
            </div>
          </div>
        </Card>

        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">Пассивный доход</div>
          <div className="num mt-1 text-2xl font-bold text-mint-400">
            {fmtMoney(passiveMonthly, base, { hide, compact: true })}
          </div>
          <div className="mt-1 text-[11.5px] text-slate-500">в месяц по всем счетам</div>
          <div className="mt-3 space-y-1 text-[11.5px]">
            {data.accounts
              .filter((a) => a.interest.enabled && a.interest.annualRate > 0)
              .sort((a, b) => b.interest.annualRate - a.interest.annualRate)
              .slice(0, 4)
              .map((a) => (
                <div key={a.id} className="flex items-center justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: a.color }} />
                    <span className="truncate text-slate-400">{a.name}</span>
                  </span>
                  <span className="num shrink-0 text-slate-300">{fmtPercent(a.interest.annualRate, 1)}</span>
                </div>
              ))}
          </div>
        </Card>

        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">Пополнения в месяц</div>
          <div className="num mt-1 text-2xl font-bold text-brand-300">
            {fmtMoney(
              data.accounts
                .filter((a) => !a.archived)
                .reduce((s, a) => s + convert(a.interest.monthlyTopUp || 0, a.currency, base, ctx.rates), 0),
              base,
              { hide, compact: true },
            )}
          </div>
          <div className="mt-1 text-[11.5px] text-slate-500">сумма автопополнений</div>
          <div className="mt-3 text-[11.5px] text-slate-400">
            {(() => {
              const count = data.accounts.filter((a) => (a.interest.monthlyTopUp || 0) > 0).length;
              return count ? `${count} сч${count === 1 ? 'ёт' : 'ета'} пополняется автоматически` : 'Автопополнений нет';
            })()}
          </div>
        </Card>
      </div>

      <Card>
        <SectionHeader
          title="Мои счета"
          subtitle={`${accounts.length} сч${accounts.length === 1 ? 'ёт' : 'етов'} · прогноз и проценты по каждому`}
          icon="Wallet"
          right={
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" onClick={() => setShowArchived((v) => !v)} icon={showArchived ? 'Eye' : 'EyeOff'}>
                {showArchived ? 'Скрыть архив' : 'Показать архив'}
              </Button>
              <Button
                variant="primary"
                size="sm"
                icon="Plus"
                onClick={() => {
                  setEditing(undefined);
                  setModalOpen(true);
                }}
              >
                Добавить счёт
              </Button>
            </div>
          }
        />

        {accounts.length ? (
          <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
            {accounts.map((a) => (
              <AccountCard
                key={a.id}
                account={a}
                onEdit={() => {
                  setEditing(a);
                  setModalOpen(true);
                }}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            icon="Wallet"
            title="Нет ни одного счёта"
            description="Добавьте карту, наличные или вклад — дальше можно будет настроить проценты, пополнения и прогноз."
            action={
              <Button
                variant="primary"
                icon="Plus"
                onClick={() => {
                  setEditing(undefined);
                  setModalOpen(true);
                }}
              >
                Добавить счёт
              </Button>
            }
          />
        )}
      </Card>

      <AccountModal open={modalOpen} onClose={() => setModalOpen(false)} account={editing} key={editing?.id ?? 'new'} />
      <TransferModal open={transferOpen} onClose={() => setTransferOpen(false)} />
    </div>
  );
}

export { emptyInterest, ymLabel, ymOf, nowYM };
