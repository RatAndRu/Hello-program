import { useMemo, useState } from 'react';
import clsx from 'clsx';
import { useStore } from '../store/useStore';
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
  SectionHeader,
  Select,
  Segmented,
  Toggle,
} from '../components/ui/primitives';
import { ICON_NAMES, Icon } from '../components/Icon';
import { convert } from '../lib/rates';
import { fmtMoney } from '../lib/format';
import {
  addCycles,
  addMonths,
  cycleDays,
  cycleLabel,
  fmtDate,
  fromISO,
  humanRelative,
  toISO,
  todayISO,
} from '../lib/dates';
import type { CycleUnit, Subscription } from '../types';
import { PALETTE } from '../store/defaults';
import { uid } from '../lib/id';
import { toast } from '../store/useToast';

const DEFAULT_ICONS = ['Repeat', 'Clapperboard', 'Music', 'Cloud', 'Dumbbell', 'Sparkles', 'Gamepad2', 'Tv', 'Book', 'ShoppingCart'];

/** Ближайшая дата списания (не раньше today) */
export function nextChargeDate(sub: Subscription, ref = todayISO()): string {
  if (!sub.active) return '';
  let date = sub.startDate;
  let guard = 0;
  while (date < ref && guard++ < 800) {
    date = addCycles(date, Math.max(1, sub.cycle.every), sub.cycle.unit, 1);
  }
  if (sub.endDate && date > sub.endDate) return '';
  return date;
}

function monthlyEquivalent(sub: Subscription, rates: { rates: Record<string, number>; base: string; manual?: Record<string, number> }, base: string): number {
  const amount = convert(sub.amount, sub.currency, base, rates);
  return amount * (30.4375 / cycleDays(Math.max(1, sub.cycle.every), sub.cycle.unit));
}

/* ============================== карточка подписки ============================ */

function SubCard({ sub, onEdit }: { sub: Subscription; onEdit: () => void }) {
  const data = useStore((s) => s.data);
  const updateSubscription = useStore((s) => s.updateSubscription);
  const deleteSubscription = useStore((s) => s.deleteSubscription);
  const settings = data.settings;
  const base = settings.baseCurrency;
  const hide = settings.hideBalances;
  const rates = { rates: data.rates?.rates ?? {}, base: data.rates?.base ?? base, manual: settings.manualRates };
  const [confirm, setConfirm] = useState(false);

  const next = nextChargeDate(sub);
  const perMonth = monthlyEquivalent(sub, rates, base);
  const perYear = perMonth * 12;
  const account = data.accounts.find((a) => a.id === sub.accountId);
  const category = data.categories.find((c) => c.id === sub.categoryId);
  const inTrial = sub.trialUntil && sub.trialUntil >= todayISO();
  const ended = sub.endDate && sub.endDate < todayISO();

  return (
    <Card className={clsx('flex flex-col transition', !sub.active && 'opacity-60')}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-3">
          <span
            className="grid h-11 w-11 shrink-0 place-items-center rounded-xl border text-[18px]"
            style={{ color: sub.color, borderColor: `${sub.color}40`, background: `${sub.color}18` }}
          >
            <Icon name={sub.icon || 'Repeat'} size={19} />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-[15px] font-semibold text-slate-100">{sub.name}</h3>
              {!sub.active && <Badge tone="slate">отключена</Badge>}
              {inTrial && <Badge tone="amber" icon="Gift">пробный период</Badge>}
              {ended && <Badge tone="slate">завершена</Badge>}
              {!sub.autoRenew && sub.active && <Badge tone="amber" icon="Bell">без автопродления</Badge>}
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2.5 text-[11.5px] text-slate-400">
              <span className="num font-medium text-slate-200">
                {fmtMoney(sub.amount, sub.currency, { hide })}
              </span>
              <span>· {cycleLabel(sub.cycle.every, sub.cycle.unit)}</span>
              {category && <span>· {category.name}</span>}
              {account && <span>· {account.name}</span>}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <IconButton icon="Pencil" label="Изменить" onClick={onEdit} />
          <IconButton
            icon={sub.active ? 'EyeOff' : 'Eye'}
            label={sub.active ? 'Приостановить' : 'Возобновить'}
            onClick={() => updateSubscription(sub.id, { active: !sub.active })}
          />
          <IconButton icon="Trash2" label="Удалить" onClick={() => setConfirm(true)} className="hover:text-rose-400" />
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 rounded-xl border border-white/[0.07] bg-white/[0.025] p-2.5 text-center">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">В месяц</div>
          <div className="num text-[13px] font-semibold text-slate-100">
            {fmtMoney(perMonth, base, { hide, cents: false, compact: true })}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">В год</div>
          <div className="num text-[13px] font-semibold text-slate-100">
            {fmtMoney(perYear, base, { hide, cents: false, compact: true })}
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-wide text-slate-500">Списание</div>
          <div className="num text-[13px] font-semibold text-brand-300">
            {next ? fmtDate(next, 'd MMM') : '—'}
          </div>
        </div>
      </div>

      {next && (
        <div className="mt-2 flex items-center gap-1.5 text-[11.5px] text-slate-500">
          <Icon name="Clock" size={12} />
          {humanRelative(next)}
          {sub.remindDays > 0 && <> · напомнить за {sub.remindDays} дн.</>}
        </div>
      )}

      {sub.note && <p className="mt-2 line-clamp-2 text-[11.5px] text-slate-500">{sub.note}</p>}

      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={() => {
          deleteSubscription(sub.id);
          setConfirm(false);
        }}
        title={`Удалить подписку «${sub.name}»?`}
        description="Подписка и связанные с ней факт-списания будут удалены."
      />
    </Card>
  );
}

/* ================================ модалка ==================================== */

function SubModal({ open, onClose, sub }: { open: boolean; onClose: () => void; sub?: Subscription }) {
  const data = useStore((s) => s.data);
  const addSubscription = useStore((s) => s.addSubscription);
  const updateSubscription = useStore((s) => s.updateSubscription);

  const [draft, setDraft] = useState<Subscription>(
    () =>
      sub ?? {
        id: uid('sub'),
        name: '',
        amount: 0,
        currency: data.settings.baseCurrency,
        cycle: { every: 1, unit: 'month' },
        startDate: todayISO(),
        accountId: data.accounts[0]?.id ?? '',
        active: true,
        autoRenew: true,
        remindDays: 1,
        priceHistory: [],
        color: PALETTE[Math.floor(Math.random() * PALETTE.length)],
        icon: 'Repeat',
      },
  );

  const set = (patch: Partial<Subscription>) => setDraft((d) => ({ ...d, ...patch }));
  const next = nextChargeDate({ ...draft, active: true });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={sub ? `Подписка: ${sub.name}` : 'Новая подписка'}
      subtitle="Регулярные списания: сервисы, связь, спортзал, ЖКХ"
      icon="Repeat"
      width="max-w-2xl"
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
              if (sub) updateSubscription(sub.id, payload);
              else addSubscription(payload);
              onClose();
            }}
          >
            {sub ? 'Сохранить' : 'Добавить'}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Название" className="sm:col-span-2">
          <Input data-autofocus value={draft.name} onChange={(e) => set({ name: e.target.value })} placeholder="Например: Яндекс Плюс" />
        </Field>

        <Field label="Сумма списания">
          <AmountInput value={draft.amount} onChange={(v) => set({ amount: v })} suffix={draft.currency} />
        </Field>

        <Field label="Валюта">
          <Select value={draft.currency} onChange={(e) => set({ currency: e.target.value })}>
            {[...new Set([draft.currency, 'RUB', 'USD', 'EUR', 'KZT'])].map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="Как часто">
          <div className="flex gap-2">
            <Input
              type="number"
              min={1}
              value={draft.cycle.every}
              onChange={(e) => set({ cycle: { ...draft.cycle, every: Math.max(1, Number(e.target.value)) } })}
              className="w-20"
            />
            <Select
              value={draft.cycle.unit}
              onChange={(e) => set({ cycle: { ...draft.cycle, unit: e.target.value as CycleUnit } })}
            >
              <option value="day">дней</option>
              <option value="week">недель</option>
              <option value="month">месяцев</option>
              <option value="year">лет</option>
            </Select>
          </div>
        </Field>

        <Field label="Дата первого списания">
          <Input type="date" value={draft.startDate} onChange={(e) => set({ startDate: e.target.value })} />
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

        <Field label="Категория">
          <Select value={draft.categoryId ?? ''} onChange={(e) => set({ categoryId: e.target.value || undefined })}>
            <option value="">Без категории</option>
            {data.categories
              .filter((c) => c.kind === 'expense')
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </Select>
        </Field>

        <Field label="Напомнить за, дней">
          <Input
            type="number"
            min={0}
            value={draft.remindDays}
            onChange={(e) => set({ remindDays: Math.max(0, Number(e.target.value)) })}
          />
        </Field>

        <Field label="Окончание" hint="необязательно">
          <Input type="date" value={draft.endDate ?? ''} onChange={(e) => set({ endDate: e.target.value || undefined })} />
        </Field>

        <Field label="Пробный период до" hint="до этой даты списаний не будет">
          <Input type="date" value={draft.trialUntil ?? ''} onChange={(e) => set({ trialUntil: e.target.value || undefined })} />
        </Field>

        <div className="sm:col-span-2">
          <Toggle
            checked={draft.autoRenew}
            onChange={(v) => set({ autoRenew: v })}
            label="Автопродление"
            hint="Выключите, если подписка не продлевается сама"
          />
        </div>

        <Field label="Заметка" className="sm:col-span-2">
          <Input value={draft.note ?? ''} onChange={(e) => set({ note: e.target.value })} />
        </Field>

        <div className="sm:col-span-2 grid gap-3 sm:grid-cols-2">
          <div>
            <div className="label">Цвет</div>
            <ColorPicker value={draft.color} onChange={(c) => set({ color: c })} colors={PALETTE} />
          </div>
          <div>
            <div className="label">Иконка</div>
            <IconPicker value={draft.icon} onChange={(i) => set({ icon: i })} names={[...new Set([...DEFAULT_ICONS, ...ICON_NAMES.slice(0, 24)])]} color={draft.color} />
          </div>
        </div>
      </div>

      {next && (
        <div className="mt-3 rounded-xl border border-brand-400/25 bg-brand-400/10 px-3 py-2 text-[12px] text-brand-200">
          Ближайшее списание: <b className="num">{fmtDate(next, 'd MMMM yyyy')}</b> · дальше{' '}
          {fmtDate(addCycles(next, Math.max(1, draft.cycle.every), draft.cycle.unit, 1), 'd MMM')}
        </div>
      )}
    </Modal>
  );
}

/* ================================= страница ================================== */

export default function Subscriptions() {
  const data = useStore((s) => s.data);
  const settings = data.settings;
  const base = settings.baseCurrency;
  const hide = settings.hideBalances;
  const rates = { rates: data.rates?.rates ?? {}, base: data.rates?.base ?? base, manual: settings.manualRates };

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Subscription | undefined>();
  const [filter, setFilter] = useState<'active' | 'all'>('active');
  const [sort, setSort] = useState<'next' | 'amount' | 'name'>('amount');

  const list = useMemo(() => {
    const arr = data.subscriptions.filter((s) => (filter === 'active' ? s.active : true));
    arr.sort((a, b) => {
      if (sort === 'amount') return monthlyEquivalent(b, rates, base) - monthlyEquivalent(a, rates, base);
      if (sort === 'name') return a.name.localeCompare(b.name, 'ru');
      return (nextChargeDate(a) || '9999').localeCompare(nextChargeDate(b) || '9999');
    });
    return arr;
  }, [data.subscriptions, filter, sort, rates, base]);

  const totals = useMemo(() => {
    const active = data.subscriptions.filter((s) => s.active);
    const month = active.reduce((s, sub) => s + monthlyEquivalent(sub, rates, base), 0);
    return { month, year: month * 12, count: active.length };
  }, [data.subscriptions, rates, base]);

  /* календарь списаний на 6 месяцев */
  const timeline = useMemo(() => {
    const today = todayISO();
    const until = toISO(addMonths(fromISO(today), 6));
    const out: { date: string; sub: Subscription; amountBase: number }[] = [];
    for (const sub of data.subscriptions) {
      if (!sub.active) continue;
      let date = nextChargeDate(sub, today);
      let guard = 0;
      while (date && date <= until && guard++ < 60) {
        if (date >= today) {
          if (!sub.trialUntil || date > sub.trialUntil) {
            out.push({ date, sub, amountBase: convert(sub.amount, sub.currency, base, rates) });
          }
        }
        date = addCycles(date, Math.max(1, sub.cycle.every), sub.cycle.unit, 1);
        if (sub.endDate && date > sub.endDate) break;
      }
    }
    return out.sort((a, b) => a.date.localeCompare(b.date));
  }, [data.subscriptions, base, rates]);

  const nextPayments = timeline.slice(0, 8);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">Подписки в месяц</div>
          <div className="num mt-1 text-2xl font-bold text-slate-50">{fmtMoney(totals.month, base, { hide, compact: true })}</div>
          <div className="mt-1 text-[11px] text-slate-500">{totals.count} активных подписок</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">В год</div>
          <div className="num mt-1 text-2xl font-bold text-rose-400">{fmtMoney(totals.year, base, { hide, compact: true })}</div>
          <div className="mt-1 text-[11px] text-slate-500">если ничего не менять</div>
        </Card>
        <Card>
          <div className="text-[11px] uppercase tracking-wider text-slate-400">Ближайшее списание</div>
          {nextPayments[0] ? (
            <>
              <div className="num mt-1 text-2xl font-bold text-brand-300">
                {fmtMoney(nextPayments[0].amountBase, base, { hide, compact: true })}
              </div>
              <div className="mt-1 text-[11px] text-slate-500">
                {nextPayments[0].sub.name} · {fmtDate(nextPayments[0].date, 'd MMM')} ({humanRelative(nextPayments[0].date)})
              </div>
            </>
          ) : (
            <div className="mt-1 text-2xl font-bold text-slate-600">—</div>
          )}
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card>
          <SectionHeader
            title="Мои подписки"
            subtitle="Сервисы, связь, спортзал, регулярные платежи"
            icon="Repeat"
            right={
              <div className="flex items-center gap-2">
                <Segmented
                  size="sm"
                  value={filter}
                  onChange={setFilter}
                  options={[
                    { value: 'active', label: 'Активные' },
                    { value: 'all', label: 'Все' },
                  ]}
                />
                <Select value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} className="w-auto py-1.5 text-[12.5px]">
                  <option value="amount">по сумме</option>
                  <option value="next">по дате</option>
                  <option value="name">по названию</option>
                </Select>
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

          {list.length ? (
            <div className="grid gap-3 lg:grid-cols-2">
              {list.map((s) => (
                <SubCard
                  key={s.id}
                  sub={s}
                  onEdit={() => {
                    setEditing(s);
                    setModalOpen(true);
                  }}
                />
              ))}
            </div>
          ) : (
            <EmptyState
              icon="Repeat"
              title="Подписок пока нет"
              description="Добавьте сервисы, которыми пользуетесь регулярно — приложение само рассчитает, сколько вы тратите в месяц и в год."
              action={
                <Button
                  variant="primary"
                  icon="Plus"
                  onClick={() => {
                    setEditing(undefined);
                    setModalOpen(true);
                  }}
                >
                  Добавить подписку
                </Button>
              }
            />
          )}
        </Card>

        <Card>
          <SectionHeader title="Календарь списаний" subtitle="Ближайшие полгода" icon="CalendarDays" />
          <div className="space-y-1">
            {nextPayments.map((p, i) => (
              <div key={`${p.sub.id}-${p.date}-${i}`} className="flex items-center gap-2.5 rounded-xl px-2 py-1.5 transition hover:bg-white/[0.04]">
                <span
                  className="grid h-7 w-7 shrink-0 place-items-center rounded-lg"
                  style={{ color: p.sub.color, background: `${p.sub.color}22` }}
                >
                  <Icon name={p.sub.icon} size={13} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12.5px] text-slate-200">{p.sub.name}</span>
                  <span className="num text-[10.5px] text-slate-500">{fmtDate(p.date, 'd MMM yyyy')}</span>
                </span>
                <span className="num shrink-0 text-[12.5px] font-semibold text-slate-100">
                  {fmtMoney(p.amountBase, base, { hide, cents: false, compact: true, tight: true })}
                </span>
              </div>
            ))}
            {!nextPayments.length && <div className="py-8 text-center text-xs text-slate-500">Списаний не ожидается</div>}
          </div>

          {timeline.length > 0 && (
            <div className="mt-3 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2 text-[11.5px] text-slate-400">
              Всего за полгода:{' '}
              <b className="num text-slate-100">
                {fmtMoney(timeline.reduce((s, p) => s + p.amountBase, 0), base, { hide, compact: true })}
              </b>{' '}
              ({timeline.length} списаний)
            </div>
          )}
        </Card>
      </div>

      <SubModal open={modalOpen} onClose={() => setModalOpen(false)} sub={editing} key={editing?.id ?? 'new'} />
    </div>
  );
}

export { monthlyEquivalent };
