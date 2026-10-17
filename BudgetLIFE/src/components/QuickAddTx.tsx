import { useMemo, useState } from 'react';
import { useStore } from '../store/useStore';
import { toast } from '../store/useToast';
import { AmountInput, Button, Field, Input, Segmented, Select, Toggle } from './ui/primitives';
import { Icon } from './Icon';
import { CURRENCY_OPTIONS } from '../lib/format';
import { addCycles, todayISO } from '../lib/dates';
import { uid } from '../lib/id';

export function QuickAddTx({ onDone, defaultDate }: { onDone?: () => void; defaultDate?: string }) {
  const data = useStore((s) => s.data);
  const addTransaction = useStore((s) => s.addTransaction);

  const [kind, setKind] = useState<'expense' | 'income' | 'transfer'>('expense');
  const [title, setTitle] = useState('');
  const [amount, setAmount] = useState<number>(0);
  const [date, setDate] = useState(defaultDate ?? todayISO());
  const [accountId, setAccountId] = useState(data.accounts[0]?.id ?? '');
  const [toAccountId, setToAccountId] = useState(data.accounts[1]?.id ?? data.accounts[0]?.id ?? '');
  const [categoryId, setCategoryId] = useState<string>('');
  const [status, setStatus] = useState<'planned' | 'done'>('planned');
  const [repeat, setRepeat] = useState(false);
  const [every, setEvery] = useState(1);
  const [unit, setUnit] = useState<'day' | 'week' | 'month' | 'year'>('month');

  const account = data.accounts.find((a) => a.id === accountId);
  const categories = useMemo(
    () => data.categories.filter((c) => c.kind === (kind === 'income' ? 'income' : 'expense')),
    [data.categories, kind],
  );

  const submit = () => {
    if (!accountId) {
      toast.error('Нет счетов', 'Сначала добавьте хотя бы один счёт');
      return;
    }
    if (!amount) {
      toast.error('Укажите сумму');
      return;
    }
    const sign = kind === 'income' ? 1 : -1;
    const id = addTransaction({
      id: uid('tx'),
      title: title.trim() || (kind === 'transfer' ? 'Перевод' : kind === 'income' ? 'Доход' : 'Расход'),
      amount: Math.abs(amount) * sign,
      date,
      accountId,
      toAccountId: kind === 'transfer' ? toAccountId : undefined,
      categoryId: kind === 'transfer' ? undefined : categoryId || undefined,
      kind,
      status,
      sourceType: status === 'planned' ? 'planned' : 'manual',
      recurrence: repeat && status === 'planned' ? { every: Math.max(1, every), unit } : undefined,
      currency: account?.currency ?? data.settings.baseCurrency,
    });
    void id;
    toast.success('Операция добавлена', repeat && status === 'planned' ? `Повторяется ${every} × ${unit}` : undefined);
    onDone?.();
  };

  return (
    <div className="space-y-4">
      <Segmented
        value={kind}
        onChange={setKind}
        options={[
          { value: 'expense', label: 'Расход', icon: 'TrendingDown' },
          { value: 'income', label: 'Доход', icon: 'TrendingUp' },
          { value: 'transfer', label: 'Перевод', icon: 'ArrowLeftRight' },
        ]}
      />

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Название" className="sm:col-span-2">
          <Input
            data-autofocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={kind === 'transfer' ? 'Перевод между счетами' : 'Например: продукты, аренда, премия'}
          />
        </Field>

        <Field label="Сумма">
          <AmountInput value={amount} onChange={setAmount} suffix={account?.currency ?? data.settings.baseCurrency} />
        </Field>

        <Field label="Дата">
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>

        <Field label={kind === 'transfer' ? 'Откуда' : 'Счёт'}>
          <Select value={accountId} onChange={(e) => setAccountId(e.target.value)}>
            {data.accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.currency})
              </option>
            ))}
          </Select>
        </Field>

        {kind === 'transfer' ? (
          <Field label="Куда">
            <Select value={toAccountId} onChange={(e) => setToAccountId(e.target.value)}>
              {data.accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.currency})
                </option>
              ))}
            </Select>
          </Field>
        ) : (
          <Field label="Категория">
            <Select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
              <option value="">Без категории</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
        )}

        <Field label="Статус" className="sm:col-span-2">
          <Segmented
            value={status}
            onChange={setStatus}
            options={[
              { value: 'planned', label: 'План', icon: 'CalendarDays' },
              { value: 'done', label: 'Факт (уже произошло)', icon: 'CheckCircle2' },
            ]}
          />
        </Field>
      </div>

      {status === 'planned' && (
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
          <Toggle checked={repeat} onChange={setRepeat} label="Повторять" hint="Например, аренда или ЖКХ каждый месяц" />
          {repeat && (
            <div className="mt-3 flex flex-wrap items-end gap-3">
              <Field label="Каждые" className="w-24">
                <Input type="number" min={1} value={every} onChange={(e) => setEvery(Math.max(1, Number(e.target.value)))} />
              </Field>
              <Field label="Период" className="w-40">
                <Select value={unit} onChange={(e) => setUnit(e.target.value as typeof unit)}>
                  <option value="day">дней</option>
                  <option value="week">недель</option>
                  <option value="month">месяцев</option>
                  <option value="year">лет</option>
                </Select>
              </Field>
              <div className="pb-2 text-xs text-slate-500">
                Следующее: {addCycles(date, Math.max(1, every), unit, 1)}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="flex items-center justify-between gap-3 pt-1">
        <div className="text-xs text-slate-500">
          Горячая клавиша: <kbd className="rounded border border-white/15 bg-white/[0.06] px-1.5 py-0.5 font-mono">Ctrl</kbd> +{' '}
          <kbd className="rounded border border-white/15 bg-white/[0.06] px-1.5 py-0.5 font-mono">K</kbd>
        </div>
        <div className="flex gap-2">
          <Button onClick={onDone}>Отмена</Button>
          <Button variant="primary" icon="Check" onClick={submit}>
            Добавить
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Значок валюты для выбранного счёта */
export function AccountCurrency({ currency }: { currency: string }) {
  return <span className="text-slate-400">{CURRENCY_OPTIONS.find((c) => c.code === currency)?.symbol ?? currency}</span>;
}

export function QuickAddIcon() {
  return <Icon name="Plus" size={16} />;
}
