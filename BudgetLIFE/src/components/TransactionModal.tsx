import { useState } from 'react';
import { useStore } from '../store/useStore';
import { toast } from '../store/useToast';
import { AmountInput, Button, Field, Input, Modal, Segmented, Select } from './ui/primitives';
import { addCycles, todayISO } from '../lib/dates';
import type { Transaction } from '../types';

const RECURRENCE_LABEL: Record<string, string> = { day: 'дн.', week: 'нед.', month: 'мес.', year: 'г.' };

export function TransactionModal({
  open,
  onClose,
  tx,
  defaultDate,
  defaultKind = 'expense',
}: {
  open: boolean;
  onClose: () => void;
  tx?: Transaction;
  defaultDate?: string;
  defaultKind?: 'expense' | 'income' | 'transfer';
}) {
  const data = useStore((s) => s.data);
  const addTransaction = useStore((s) => s.addTransaction);
  const updateTransaction = useStore((s) => s.updateTransaction);
  const deleteTransaction = useStore((s) => s.deleteTransaction);

  const account0 = data.accounts[0];
  const [kind, setKind] = useState<'expense' | 'income' | 'transfer'>(tx?.kind ?? defaultKind);
  const [title, setTitle] = useState(tx?.title ?? '');
  const [amount, setAmount] = useState<number>(Math.abs(tx?.amount ?? 0));
  const [date, setDate] = useState(tx?.date ?? defaultDate ?? todayISO());
  const [accountId, setAccountId] = useState(tx?.accountId ?? account0?.id ?? '');
  const [toAccountId, setToAccountId] = useState(tx?.toAccountId ?? data.accounts[1]?.id ?? account0?.id ?? '');
  const [categoryId, setCategoryId] = useState(tx?.categoryId ?? '');
  const [status, setStatus] = useState<'planned' | 'done'>(tx?.status ?? 'planned');
  const [note, setNote] = useState(tx?.note ?? '');
  const [repeat, setRepeat] = useState(Boolean(tx?.recurrence));
  const [every, setEvery] = useState(tx?.recurrence?.every ?? 1);
  const [unit, setUnit] = useState<'day' | 'week' | 'month' | 'year'>(tx?.recurrence?.unit ?? 'month');
  const [until, setUntil] = useState(tx?.recurrence?.until ?? '');

  const account = data.accounts.find((a) => a.id === accountId);
  const categories = data.categories.filter((c) => c.kind === (kind === 'income' ? 'income' : 'expense'));

  const save = () => {
    if (!amount) {
      toast.error('Укажите сумму');
      return;
    }
    if (!accountId) {
      toast.error('Выберите счёт');
      return;
    }
    const sign = kind === 'income' ? 1 : -1;
    const payload: Partial<Transaction> = {
      title: title.trim() || (kind === 'transfer' ? 'Перевод' : kind === 'income' ? 'Доход' : 'Расход'),
      amount: Math.abs(amount) * sign,
      date,
      accountId,
      toAccountId: kind === 'transfer' ? toAccountId : undefined,
      categoryId: kind === 'transfer' ? undefined : categoryId || undefined,
      kind,
      status,
      note: note || undefined,
      currency: account?.currency ?? data.settings.baseCurrency,
      sourceType: status === 'planned' ? 'planned' : 'manual',
      recurrence: repeat && status === 'planned' && kind !== 'transfer' ? { every: Math.max(1, every), unit, until: until || undefined } : undefined,
    };
    if (tx) updateTransaction(tx.id, payload);
    else addTransaction(payload);
    toast.success(tx ? 'Изменения сохранены' : 'Операция добавлена');
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={tx ? 'Операция' : 'Новая операция'}
      subtitle={tx ? 'Измените детали или отметьте факт' : 'Плановая или фактическая операция'}
      icon={kind === 'income' ? 'TrendingUp' : kind === 'transfer' ? 'ArrowLeftRight' : 'Receipt'}
      width="max-w-2xl"
      footer={
        <>
          {tx && (
            <Button
              variant="danger"
              icon="Trash2"
              className="mr-auto"
              onClick={() => {
                deleteTransaction(tx.id);
                toast.success('Операция удалена');
                onClose();
              }}
            >
              Удалить
            </Button>
          )}
          <Button onClick={onClose}>Отмена</Button>
          <Button variant="primary" icon="Check" onClick={save}>
            {tx ? 'Сохранить' : 'Добавить'}
          </Button>
        </>
      }
    >
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
            <Input data-autofocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Например: аренда квартиры" />
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

          <Field label="Статус">
            <Segmented
              size="sm"
              value={status}
              onChange={setStatus}
              options={[
                { value: 'planned', label: 'План', icon: 'CalendarDays' },
                { value: 'done', label: 'Факт', icon: 'CheckCircle2' },
              ]}
            />
          </Field>

          <Field label="Заметка">
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Необязательно" />
          </Field>
        </div>

        {status === 'planned' && kind !== 'transfer' && (
          <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
            <label className="flex items-center gap-2 text-[13px] text-slate-200">
              <input type="checkbox" checked={repeat} onChange={(e) => setRepeat(e.target.checked)} className="h-4 w-4 rounded border-white/20 bg-ink-900" />
              Повторять (регулярный платёж)
            </label>
            {repeat && (
              <div className="mt-3 flex flex-wrap items-end gap-3">
                <Field label="Каждые" className="w-24">
                  <Input type="number" min={1} value={every} onChange={(e) => setEvery(Math.max(1, Number(e.target.value)))} />
                </Field>
                <Field label="Период" className="w-36">
                  <Select value={unit} onChange={(e) => setUnit(e.target.value as typeof unit)}>
                    <option value="day">дней</option>
                    <option value="week">недель</option>
                    <option value="month">месяцев</option>
                    <option value="year">лет</option>
                  </Select>
                </Field>
                <Field label="До даты" hint="необязательно">
                  <Input type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
                </Field>
                <div className="pb-2 text-xs text-slate-500">
                  {RECURRENCE_LABEL[unit]} · следующее: {addCycles(date, Math.max(1, every), unit, 1)}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
