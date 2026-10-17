import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { useStore } from '../store/useStore';
import { useEvents } from '../store/useEngine';
import {
  AmountInput,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  Field,
  IconButton,
  Input,
  Modal,
  Progress,
  SectionHeader,
  Segmented,
  Select,
} from '../components/ui/primitives';
import { Icon } from '../components/Icon';
import { convert } from '../lib/rates';
import { fmtMoney, fmtPercent } from '../lib/format';
import { fmtDate, fromISO, nowYM, toISO, todayISO, ymLabel, ymOf, addMonths } from '../lib/dates';
import {
  cardSchedule,
  creditSummary,
  graceInfo,
  loanSchedule,
  minPayment,
  minPaymentOutlook,
} from '../lib/credit';
import type { Credit, CreditKind, PaymentType, RepayMode } from '../types';
import { uid } from '../lib/id';
import { toast } from '../store/useToast';

const KINDS: { value: CreditKind; label: string; icon: string; hint: string }[] = [
  { value: 'loan', label: 'Кредит', icon: 'Landmark', hint: 'Аннуитетный или дифференцированный платёж' },
  { value: 'credit_card', label: 'Кредитная карта', icon: 'CreditCard', hint: 'Лимит, минимальный платёж, беспроцентный период' },
  { value: 'installment', label: 'Рассрочка', icon: 'Receipt', hint: 'Обычно без процентов' },
];

/* ============================ карточка кредитки ============================== */

function CreditCardWidget({ credit, onEdit }: { credit: Credit; onEdit: () => void }) {
  const data = useStore((s) => s.data);
  const updateCredit = useStore((s) => s.updateCredit);
  const base = data.settings.baseCurrency;
  const hide = data.settings.hideBalances;
  const rates = { rates: data.rates?.rates ?? {}, base: data.rates?.base ?? base, manual: data.settings.manualRates };

  const debt = credit.used ?? 0;
  const limit = credit.limit ?? 0;
  const usedPct = limit > 0 ? (debt / limit) * 100 : 0;
  const grace = graceInfo(credit);
  const min = minPayment(credit, debt);
  const interestIfMin = debt * (credit.annualRate / 100 / 12);
  const account = data.accounts.find((a) => a.id === credit.accountId);

  const schedule = useMemo(() => cardSchedule(credit, todayISO(), toISO(addMonths(fromISO(todayISO()), 6))), [credit]);

  return (
    <Card className="lg:col-span-2">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span
            className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border"
            style={{ color: credit.color, borderColor: `${credit.color}40`, background: `${credit.color}18` }}
          >
            <Icon name="CreditCard" size={19} />
          </span>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-[15px] font-semibold text-slate-100">{credit.name}</h3>
              <Badge tone="red">{fmtPercent(credit.annualRate, 1)}</Badge>
              {account && <Badge tone="slate">{account.name}</Badge>}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 text-[11.5px] text-slate-400">
              <span>
                Задолженность: <b className="num text-slate-100">{fmtMoney(debt, credit.currency, { hide })}</b>
              </span>
              {limit > 0 && (
                <span>
                  Лимит: <b className="num text-slate-200">{fmtMoney(limit, credit.currency, { hide, compact: true })}</b>
                </span>
              )}
              {credit.statementDay && <span>выписка {credit.statementDay}-го</span>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <IconButton icon="Pencil" label="Изменить" onClick={onEdit} />
          <IconButton
            icon={credit.active ? 'EyeOff' : 'Eye'}
            label={credit.active ? 'Деактивировать' : 'Активировать'}
            onClick={() => updateCredit(credit.id, { active: !credit.active })}
          />
        </div>
      </div>

      {limit > 0 && (
        <div className="mt-3">
          <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
            <span>Использовано {usedPct.toFixed(0)}% лимита</span>
            <span className="num">свободно {fmtMoney(Math.max(0, limit - debt), credit.currency, { hide, compact: true })}</span>
          </div>
          <Progress value={debt} max={limit} color={usedPct > 80 ? '#f43f5e' : credit.color} height={8} />
        </div>
      )}

      {/* -------------------------- беспроцентный период ------------------------- */}
      {grace && (
        <div
          className={clsx(
            'mt-3 rounded-xl border p-3',
            grace.daysLeft <= 7
              ? 'border-rose-500/30 bg-rose-500/[0.08]'
              : grace.daysLeft <= 20
                ? 'border-amberx-500/30 bg-amberx-500/[0.07]'
                : 'border-mint-500/25 bg-mint-500/[0.07]',
          )}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="flex items-center gap-2 text-[13px] font-semibold text-slate-100">
              <Icon name="ShieldCheck" size={15} className="text-mint-400" />
              Беспроцентный период
            </span>
            <span
              className={clsx(
                'num text-[13px] font-bold',
                grace.daysLeft <= 7 ? 'text-rose-400' : grace.daysLeft <= 20 ? 'text-amberx-400' : 'text-mint-400',
              )}
            >
              {grace.daysLeft} дн.
            </span>
          </div>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            <div>
              <div className="text-[10.5px] uppercase tracking-wide text-slate-400">Выписка</div>
              <div className="num text-[13px] text-slate-100">{fmtDate(grace.statementDate, 'd MMM')}</div>
            </div>
            <div>
              <div className="text-[10.5px] uppercase tracking-wide text-slate-400">Погасить до</div>
              <div className="num text-[13px] font-semibold text-slate-100">{fmtDate(grace.paymentDate, 'd MMM yyyy')}</div>
            </div>
            <div>
              <div className="text-[10.5px] uppercase tracking-wide text-slate-400">Чтобы без процентов</div>
              <div className="num text-[13px] font-semibold text-mint-400">
                {fmtMoney(grace.toAvoidInterest, credit.currency, { hide })}
              </div>
            </div>
          </div>
          <div className="mt-2 text-[11px] text-slate-500">
            Длина грейс-периода: {credit.graceDays ?? 0} дн. от даты выписки
          </div>
        </div>
      )}

      {/* ------------------------------ как гасим -------------------------------- */}
      <div className="mt-3 rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <span className="text-[12.5px] font-medium text-slate-200">Как планируем гасить</span>
          <Segmented
            size="sm"
            value={credit.repayMode}
            onChange={(v) => updateCredit(credit.id, { repayMode: v as RepayMode })}
            options={[
              { value: 'full', label: 'Полностью', icon: 'ShieldCheck' },
              { value: 'min', label: 'Минимум', icon: 'Coins' },
              { value: 'custom', label: 'Своя сумма', icon: 'Pencil' },
            ]}
          />
        </div>

        {credit.repayMode === 'custom' && (
          <div className="mb-2 w-44">
            <AmountInput
              value={credit.customRepayAmount}
              onChange={(v) => updateCredit(credit.id, { customRepayAmount: v })}
              suffix={credit.currency}
            />
          </div>
        )}

        <div className="grid gap-2 sm:grid-cols-3">
          <div>
            <div className="text-[10.5px] uppercase tracking-wide text-slate-500">Платёж</div>
            <div className="num text-[14px] font-semibold text-slate-100">
              {fmtMoney(
                credit.repayMode === 'full' ? debt : credit.repayMode === 'custom' ? (credit.customRepayAmount ?? 0) : min,
                credit.currency,
                { hide },
              )}
            </div>
          </div>
          <div>
            <div className="text-[10.5px] uppercase tracking-wide text-slate-500">Минимальный</div>
            <div className="num text-[14px] text-slate-300">{fmtMoney(min, credit.currency, { hide })}</div>
          </div>
          <div>
            <div className="text-[10.5px] uppercase tracking-wide text-slate-500">
              {credit.repayMode === 'full' ? 'Процентов' : 'Процентов в месяц'}
            </div>
            <div className={clsx('num text-[14px]', credit.repayMode === 'full' ? 'text-mint-400' : 'text-rose-400')}>
              {credit.repayMode === 'full' ? '0' : fmtMoney(interestIfMin, credit.currency, { hide })}
            </div>
          </div>
        </div>

        {credit.repayMode !== 'full' && debt > 0 && (
          <div className="mt-2 flex items-center gap-2 rounded-lg border border-amberx-500/25 bg-amberx-500/10 px-2.5 py-1.5 text-[11.5px] text-amberx-400">
            <Icon name="AlertTriangle" size={13} />
            При оплате минимума долг закроется примерно через{' '}
            {(() => {
              const o = minPaymentOutlook(credit, 240);
              return Number.isFinite(o.monthsToClose) ? `${o.monthsToClose} мес.` : 'очень нескоро';
            })()}{' '}
            с переплатой{' '}
            {fmtMoney(minPaymentOutlook(credit, 240).paidInterest, credit.currency, { hide, compact: true })}
          </div>
        )}
      </div>

      {schedule.length > 0 && (
        <div className="mt-3">
          <div className="mb-1.5 text-[11px] uppercase tracking-wide text-slate-500">Платежи по карте</div>
          <div className="space-y-1">
            {schedule.slice(0, 4).map((r, i) => (
              <div key={i} className="flex items-center justify-between gap-2 rounded-lg bg-white/[0.03] px-2.5 py-1.5 text-[12px]">
                <span className="num text-slate-400">{fmtDate(r.date, 'd MMM yyyy')}</span>
                <span className="flex items-center gap-3">
                  {r.interest > 0 && <span className="num text-rose-400/80">проценты {Math.round(r.interest).toLocaleString('ru-RU')}</span>}
                  <span className="num font-semibold text-slate-100">{fmtMoney(r.payment, credit.currency, { hide })}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="mt-2 text-[11px] text-slate-500">
        ≈ {fmtMoney(convert(debt, credit.currency, base, rates), base, { hide, compact: true })} в базовой валюте
      </div>
    </Card>
  );
}

/* ============================== карточка кредита ============================= */

function LoanCard({ credit, onEdit }: { credit: Credit; onEdit: () => void }) {
  const data = useStore((s) => s.data);
  const updateCredit = useStore((s) => s.updateCredit);
  const deleteCredit = useStore((s) => s.deleteCredit);
  const hide = data.settings.hideBalances;
  const [showSchedule, setShowSchedule] = useState(false);
  const [confirm, setConfirm] = useState(false);

  const rows = useMemo(() => loanSchedule(credit), [credit]);
  const summary = useMemo(() => creditSummary(credit), [credit]);
  const account = data.accounts.find((a) => a.id === credit.accountId);
  const paid = credit.principal - summary.debt;
  const paidPct = credit.principal > 0 ? (paid / credit.principal) * 100 : 0;

  return (
    <Card>
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-3">
          <span
            className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border"
            style={{ color: credit.color, borderColor: `${credit.color}40`, background: `${credit.color}18` }}
          >
            <Icon name={credit.kind === 'installment' ? 'Receipt' : 'Landmark'} size={19} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-[15px] font-semibold text-slate-100">{credit.name}</h3>
              <Badge tone={credit.annualRate === 0 ? 'green' : 'red'}>
                {credit.annualRate === 0 ? 'без %' : fmtPercent(credit.annualRate, 1)}
              </Badge>
            </div>
            <div className="mt-0.5 text-[11.5px] text-slate-400">
              {credit.termMonths} мес · платёж {credit.paymentDay}-го · {account?.name ?? '—'}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <IconButton icon="Pencil" label="Изменить" onClick={onEdit} />
          <IconButton
            icon={credit.active ? 'EyeOff' : 'Eye'}
            label={credit.active ? 'Деактивировать' : 'Активировать'}
            onClick={() => updateCredit(credit.id, { active: !credit.active })}
          />
          <IconButton icon="Trash2" label="Удалить" onClick={() => setConfirm(true)} className="hover:text-rose-400" />
        </div>
      </div>

      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
          <span>Выплачено {paidPct.toFixed(0)}% тела</span>
          <span className="num">
            остаток {fmtMoney(summary.debt, credit.currency, { hide, compact: true })} из{' '}
            {fmtMoney(credit.principal, credit.currency, { hide, compact: true })}
          </span>
        </div>
        <Progress value={paid} max={credit.principal} color={credit.color} height={8} />
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <MiniStat label="Платёж" value={fmtMoney(summary.monthlyPayment, credit.currency, { hide, compact: true })} />

        <MiniStat
          label="Следующий"
          value={summary.nextPayment ? fmtDate(summary.nextPayment.date, 'd MMM') : '—'}
        />
        <MiniStat label="Переплата" value={fmtMoney(summary.overpayment, credit.currency, { hide, compact: true })} tone="rose" />
        <MiniStat
          label="Закрытие"
          value={summary.payoffDate ? ymLabel(ymOf(summary.payoffDate)) : '—'}
        />
      </div>

      {credit.extraPayment > 0 && (
        <div className="mt-2 flex items-center gap-2 rounded-lg border border-mint-500/20 bg-mint-500/[0.07] px-2.5 py-1.5 text-[11.5px] text-mint-400">
          <Icon name="Zap" size={13} />
          Досрочное погашение +{fmtMoney(credit.extraPayment, credit.currency, { hide, compact: true })} к каждому платежу
        </div>
      )}

      <button
        onClick={() => setShowSchedule((v) => !v)}
        className="mt-3 flex w-full items-center justify-between rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2 text-[12.5px] text-slate-300 transition hover:bg-white/[0.05]"
      >
        <span className="flex items-center gap-2">
          <Icon name="Layers" size={14} className="text-brand-300" />
          График платежей ({rows.length})
        </span>
        <Icon name={showSchedule ? 'ChevronUp' : 'ChevronDown'} size={15} />
      </button>

      {showSchedule && (
        <div className="mt-2 max-h-[320px] overflow-auto rounded-xl border border-white/[0.07] animate-slide-up">
          <table className="table">
            <thead>
              <tr>
                <th className="w-12">№</th>
                <th>Дата</th>
                <th className="text-right">Платёж</th>
                <th className="text-right">Проценты</th>
                <th className="text-right">Долг</th>
                <th className="text-right">Остаток</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.index} className={r.date < todayISO() ? 'opacity-45' : ''}>
                  <td className="num text-slate-500">{r.index}</td>
                  <td className="num whitespace-nowrap">{fmtDate(r.date, 'd.MM.yy')}</td>
                  <td className="num text-right font-medium">{fmtMoney(r.payment, credit.currency, { hide, cents: false })}</td>
                  <td className="num text-right text-rose-400/80">{fmtMoney(r.interest, credit.currency, { hide, cents: false })}</td>
                  <td className="num text-right text-slate-400">{fmtMoney(r.principal, credit.currency, { hide, cents: false })}</td>
                  <td className="num text-right font-semibold">{fmtMoney(r.balance, credit.currency, { hide, cents: false })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={() => {
          deleteCredit(credit.id);
          setConfirm(false);
        }}
        title={`Удалить «${credit.name}»?`}
        description="Кредит будет удалён из планирования."
      />
    </Card>
  );
}

function MiniStat({ label, value, tone }: { label: string; value: React.ReactNode; tone?: 'rose' | 'mint' }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.025] px-2.5 py-2">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div
        className={clsx(
          'num text-[13px] font-semibold',
          tone === 'rose' ? 'text-rose-400' : tone === 'mint' ? 'text-mint-400' : 'text-slate-100',
        )}
      >
        {value}
      </div>
    </div>
  );
}

/* ================================= модалка =================================== */

function CreditModal({ open, onClose, credit }: { open: boolean; onClose: () => void; credit?: Credit }) {
  const data = useStore((s) => s.data);
  const addCredit = useStore((s) => s.addCredit);
  const updateCredit = useStore((s) => s.updateCredit);

  const [draft, setDraft] = useState<Credit>(() => credit ?? blank(data.settings.baseCurrency, data.accounts[0]?.id));
  const set = (patch: Partial<Credit>) => setDraft((d) => ({ ...d, ...patch }));
  const isCard = draft.kind === 'credit_card';
  const rows = draft.kind !== 'credit_card' ? loanSchedule(draft) : [];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={credit ? `Кредит: ${credit.name}` : 'Новый кредит'}
      subtitle="Платежи, проценты и беспроцентный период"
      icon="CreditCard"
      width="max-w-3xl"
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button
            variant="primary"
            icon="Check"
            onClick={() => {
              if (!draft.name.trim()) {
                toast.error('Укажите название');
                return;
              }
              const payload = { ...draft, name: draft.name.trim() };
              if (credit) updateCredit(credit.id, payload);
              else addCredit(payload);
              onClose();
            }}
          >
            {credit ? 'Сохранить' : 'Добавить'}
          </Button>
        </>
      }
    >
      <div className="mb-4">
        <div className="label">Тип</div>
        <div className="grid gap-2 sm:grid-cols-3">
          {KINDS.map((k) => (
            <button
              key={k.value}
              onClick={() => set({ kind: k.value, annualRate: k.value === 'installment' ? 0 : draft.annualRate })}
              className={clsx(
                'rounded-xl border p-3 text-left transition',
                draft.kind === k.value
                  ? 'border-brand-400/50 bg-brand-400/10'
                  : 'border-white/[0.07] bg-white/[0.02] hover:bg-white/[0.05]',
              )}
            >
              <div className="flex items-center gap-2 text-[13px] font-medium text-slate-100">
                <Icon name={k.icon} size={15} className={draft.kind === k.value ? 'text-brand-300' : 'text-slate-500'} />
                {k.label}
              </div>
              <div className="mt-0.5 text-[11px] text-slate-500">{k.hint}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Название" className="sm:col-span-2">
          <Input data-autofocus value={draft.name} onChange={(e) => set({ name: e.target.value })} placeholder="Например: Автокредит" />
        </Field>

        <Field label="Счёт списания">
          <Select value={draft.accountId} onChange={(e) => set({ accountId: e.target.value })}>
            {data.accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.currency})
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Валюта">
          <Select value={draft.currency} onChange={(e) => set({ currency: e.target.value })}>
            {[...new Set([draft.currency, 'RUB', 'USD', 'EUR'])].map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        </Field>

        {isCard ? (
          <>
            <Field label="Кредитный лимит">
              <AmountInput value={draft.limit} onChange={(v) => set({ limit: v })} suffix={draft.currency} />
            </Field>
            <Field label="Задолженность" hint="сколько должны сейчас">
              <AmountInput value={draft.used} onChange={(v) => set({ used: v })} suffix={draft.currency} />
            </Field>
            <Field label="Годовая ставка" hint="если не погасить в грейс-период">
              <AmountInput value={draft.annualRate} onChange={(v) => set({ annualRate: v })} suffix="%" />
            </Field>
            <Field label="Длина беспроцентного периода, дней">
              <Input
                type="number"
                min={0}
                value={draft.graceDays ?? ''}
                onChange={(e) => set({ graceDays: Number(e.target.value) || undefined })}
              />
            </Field>
            <Field label="День выписки">
              <Input
                type="number"
                min={1}
                max={31}
                value={draft.statementDay ?? ''}
                onChange={(e) => set({ statementDay: Number(e.target.value) || undefined })}
              />
            </Field>
            <Field label="Крайний день платежа" hint="обычно выписка + грейс-период">
              <Input
                type="number"
                min={1}
                max={31}
                value={draft.gracePaymentDay ?? ''}
                onChange={(e) => set({ gracePaymentDay: Number(e.target.value) || undefined })}
              />
            </Field>
            <Field label="Минимальный платёж, %">
              <AmountInput
                value={draft.minPaymentPercent}
                onChange={(v) => set({ minPaymentPercent: v })}
                suffix="%"
                placeholder="5"
              />
            </Field>
            <Field label="Минимальный платёж, не менее">
              <AmountInput
                value={draft.minPaymentFixed}
                onChange={(v) => set({ minPaymentFixed: v })}
                suffix={draft.currency}
                placeholder="0"
              />
            </Field>
          </>
        ) : (
          <>
            <Field label="Сумма кредита">
              <AmountInput value={draft.principal} onChange={(v) => set({ principal: v })} suffix={draft.currency} />
            </Field>
            <Field label="Годовая ставка">
              <AmountInput value={draft.annualRate} onChange={(v) => set({ annualRate: v })} suffix="%" />
            </Field>
            <Field label="Срок, месяцев">
              <Input type="number" min={1} value={draft.termMonths} onChange={(e) => set({ termMonths: Math.max(1, Number(e.target.value)) })} />
            </Field>
            <Field label="Дата выдачи">
              <Input type="date" value={draft.startDate} onChange={(e) => set({ startDate: e.target.value })} />
            </Field>
            <Field label="День платежа">
              <Input type="number" min={1} max={31} value={draft.paymentDay} onChange={(e) => set({ paymentDay: Math.max(1, Number(e.target.value)) })} />
            </Field>
            <Field label="Тип платежа">
              <Select value={draft.paymentType} onChange={(e) => set({ paymentType: e.target.value as PaymentType })}>
                <option value="annuity">Аннуитетный (равными долями)</option>
                <option value="differentiated">Дифференцированный (убывающий)</option>
              </Select>
            </Field>
            <Field label="Остаток долга" hint="если кредит уже выплачивается">
              <AmountInput value={draft.currentBalance} onChange={(v) => set({ currentBalance: v || undefined })} suffix={draft.currency} />
            </Field>
            <Field label="Досрочное погашение, + к платежу">
              <AmountInput value={draft.extraPayment || undefined} onChange={(v) => set({ extraPayment: v })} suffix={draft.currency} />
            </Field>
          </>
        )}

        <Field label="Заметка" className="sm:col-span-2">
          <Input value={draft.note ?? ''} onChange={(e) => set({ note: e.target.value })} />
        </Field>
      </div>

      {!isCard && rows.length > 0 && (
        <div className="mt-4 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
          <div className="mb-2 text-[12.5px] font-medium text-slate-200">Предварительный расчёт</div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MiniStat label="Платёж" value={fmtMoney(rows[0].payment + (draft.extraPayment || 0), draft.currency, { compact: true })} />
            <MiniStat label="Проценты всего" value={fmtMoney(rows.reduce((s, r) => s + r.interest, 0), draft.currency, { compact: true })} tone="rose" />
            <MiniStat label="Платежей" value={String(rows.length)} />
            <MiniStat label="Закрытие" value={ymLabel(ymOf(rows[rows.length - 1].date))} />
          </div>
        </div>
      )}
    </Modal>
  );
}

function blank(currency: string, accountId?: string): Credit {
  return {
    id: uid('cr'),
    name: '',
    kind: 'loan',
    accountId: accountId ?? '',
    currency,
    principal: 0,
    annualRate: 12,
    termMonths: 36,
    startDate: todayISO(),
    paymentDay: 15,
    paymentType: 'annuity',
    repayMode: 'min',
    extraPayment: 0,
    color: '#f43f5e',
    active: true,
  };
}

/* ================================= страница ================================== */

export default function Credits() {
  const data = useStore((s) => s.data);
  const base = data.settings.baseCurrency;
  const hide = data.settings.hideBalances;
  const rates = { rates: data.rates?.rates ?? {}, base: data.rates?.base ?? base, manual: data.settings.manualRates };

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Credit | undefined>();

  const today = todayISO();
  const events = useEvents(today, toISO(addMonths(fromISO(today), 3)));

  const cards = data.credits.filter((c) => c.kind === 'credit_card');
  const loans = data.credits.filter((c) => c.kind !== 'credit_card');

  const totalDebt = useMemo(
    () =>
      data.credits
        .filter((c) => c.active)
        .reduce((s, c) => s + convert(c.kind === 'credit_card' ? (c.used ?? 0) : (c.currentBalance ?? c.principal), c.currency, base, rates), 0),
    [data.credits, base, rates],
  );

  const monthlyPayments = useMemo(
    () =>
      data.credits
        .filter((c) => c.active)
        .reduce((s, c) => s + convert(creditSummary(c).monthlyPayment + (c.extraPayment || 0), c.currency, base, rates), 0),
    [data.credits, base, rates],
  );

  const totalOverpayment = useMemo(
    () =>
      data.credits
        .filter((c) => c.active && c.kind !== 'credit_card')
        .reduce((s, c) => s + convert(creditSummary(c).overpayment, c.currency, base, rates), 0),
    [data.credits, base, rates],
  );

  const upcoming = useMemo(() => events.filter((e) => e.sourceType === 'credit').slice(0, 10), [events]);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">Общий долг</div>
          <div className="num mt-1 text-2xl font-bold text-rose-400">{fmtMoney(totalDebt, base, { hide, compact: true })}</div>
          <div className="mt-1 text-[11px] text-slate-500">{data.credits.filter((c) => c.active).length} активных обязательств</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">Платежи в месяц</div>
          <div className="num mt-1 text-2xl font-bold text-slate-50">{fmtMoney(monthlyPayments, base, { hide, compact: true })}</div>
          <div className="mt-1 text-[11px] text-slate-500">по всем кредитам и картам</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">Переплата вперёме</div>
          <div className="num mt-1 text-2xl font-bold text-amberx-400">{fmtMoney(totalOverpayment, base, { hide, compact: true })}</div>
          <div className="mt-1 text-[11px] text-slate-500">проценты до закрытия</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">Ближайший платёж</div>
          {upcoming[0] ? (
            <>
              <div className="num mt-1 text-2xl font-bold text-brand-300">
                {fmtMoney(Math.abs(convert(upcoming[0].amount, upcoming[0].currency, base, rates)), base, { hide, compact: true })}
              </div>
              <div className="mt-1 text-[11px] text-slate-500">
                {upcoming[0].title} · {fmtDate(upcoming[0].date, 'd MMM')}
              </div>
            </>
          ) : (
            <div className="mt-1 text-2xl font-bold text-slate-600">—</div>
          )}
        </Card>
      </div>

      <Card>
        <SectionHeader
          title="Кредитные карты"
          subtitle="Беспроцентный период, минимальный платёж, стратегия погашения"
          icon="CreditCard"
          right={
            <Button
              variant="primary"
              size="sm"
              icon="Plus"
              onClick={() => {
                setEditing(blank(base, data.accounts[0]?.id));
                setEditing({ ...blank(base, data.accounts[0]?.id), kind: 'credit_card', graceDays: 55, statementDay: 5, gracePaymentDay: 25, minPaymentPercent: 5, limit: 100000, used: 0 });
                setModalOpen(true);
              }}
            >
              Добавить карту
            </Button>
          }
        />
        {cards.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {cards.map((c) => (
              <CreditCardWidget key={c.id} credit={c} onEdit={() => { setEditing(c); setModalOpen(true); }} />
            ))}
          </div>
        ) : (
          <EmptyState
            icon="CreditCard"
            title="Кредитных карт нет"
            description="Добавьте карту, чтобы видеть остаток беспроцентного периода и не платить проценты."
          />
        )}
      </Card>

      <Card>
        <SectionHeader
          title="Кредиты и рассрочки"
          subtitle="График платежей, переплата и дата закрытия"
          icon="Landmark"
          right={
            <Button
              variant="primary"
              size="sm"
              icon="Plus"
              onClick={() => {
                setEditing(undefined);
                setModalOpen(true);
              }}
            >
              Добавить кредит
            </Button>
          }
        />
        {loans.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {loans.map((c) => (
              <LoanCard key={c.id} credit={c} onEdit={() => { setEditing(c); setModalOpen(true); }} />
            ))}
          </div>
        ) : (
          <EmptyState icon="Landmark" title="Кредитов нет" description="Ипотека, автокредит, рассрочка — всё в одном месте." />
        )}
      </Card>

      {upcoming.length > 0 && (
        <Card>
          <SectionHeader title="Календарь платежей" subtitle="Ближайшие 3 месяца" icon="CalendarDays" />
          <div className="overflow-x-auto">
            <table className="table min-w-[560px]">
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Кредит</th>
                  <th className="text-right">Платёж</th>
                  <th className="text-right">в т.ч. проценты</th>
                </tr>
              </thead>
              <tbody>
                {upcoming.map((e, i) => (
                  <tr key={`${e.sourceKey}-${i}`}>
                    <td className="num whitespace-nowrap">{fmtDate(e.date, 'd MMM yyyy')}</td>
                    <td className="text-[13px]">{e.title}</td>
                    <td className="num text-right font-semibold">{fmtMoney(Math.abs(e.amount), e.currency, { hide })}</td>
                    <td className="num text-right text-rose-400/80">
                      {e.parts?.interest ? fmtMoney(e.parts.interest, e.currency, { hide }) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <CreditModal open={modalOpen} onClose={() => setModalOpen(false)} credit={editing ?? undefined} key={editing?.id ?? 'new'} />
    </div>
  );
}

export { nowYM };
