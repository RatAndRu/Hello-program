import clsx from 'clsx';
import type { CashflowEvent } from '../types';
import { useStore } from '../store/useStore';
import { Icon } from './Icon';
import { Badge } from './ui/primitives';
import { fmtMoney } from '../lib/format';
import { fmtDateShort, humanRelative } from '../lib/dates';

const SOURCE_LABEL: Record<string, string> = {
  income: 'Доход',
  subscription: 'Подписка',
  credit: 'Кредит',
  planned: 'План',
  interest: 'Проценты',
  topup: 'Пополнение',
  manual: 'Операция',
};

const SOURCE_ICON: Record<string, string> = {
  income: 'TrendingUp',
  subscription: 'Repeat',
  credit: 'CreditCard',
  planned: 'Receipt',
  interest: 'Percent',
  topup: 'PlusCircle',
  manual: 'Wallet',
};

export function EventIcon({ event, size = 15 }: { event: CashflowEvent; size?: number }) {
  const color = event.color ?? (event.amount >= 0 ? '#10d19a' : '#fb7d8e');
  const name = event.icon || SOURCE_ICON[event.sourceType] || 'Circle';
  return (
    <span
      className="grid shrink-0 place-items-center rounded-lg border"
      style={{
        width: size + 16,
        height: size + 16,
        color,
        borderColor: `${color}33`,
        background: `${color}18`,
      }}
    >
      <Icon name={name} size={size} />
    </span>
  );
}

export function EventRow({
  event,
  showDate = false,
  showRelative = false,
  onSelect,
  className,
  dense = false,
}: {
  event: CashflowEvent;
  showDate?: boolean;
  showRelative?: boolean;
  onSelect?: (e: CashflowEvent) => void;
  className?: string;
  dense?: boolean;
}) {
  const accounts = useStore((s) => s.data.accounts);
  const categories = useStore((s) => s.data.categories);
  const settings = useStore((s) => s.data.settings);
  const toggleEventDone = useStore((s) => s.toggleEventDone);

  const account = accounts.find((a) => a.id === event.accountId);
  const category = categories.find((c) => c.id === event.categoryId);
  const income = event.amount >= 0;

  return (
    <div
      className={clsx(
        'group flex items-center gap-3 rounded-xl border border-transparent px-2 transition',
        dense ? 'py-1.5' : 'py-2',
        'hover:border-white/10 hover:bg-white/[0.045]',
        event.status === 'done' && 'opacity-70',
        className,
      )}
    >
      <button
        onClick={() => toggleEventDone(event)}
        title={event.status === 'done' ? 'Вернуть в план' : 'Отметить: уже произошло'}
        className={clsx(
          'grid h-5 w-5 shrink-0 place-items-center rounded-md border transition',
          event.status === 'done'
            ? 'border-mint-500/50 bg-mint-500/20 text-mint-400'
            : 'border-white/15 text-transparent hover:border-mint-400/60 hover:bg-mint-500/10 hover:text-mint-400/60',
        )}
      >
        <Icon name="Check" size={12} strokeWidth={3} />
      </button>

      <EventIcon event={event} size={dense ? 13 : 15} />

      <button
        onClick={() => onSelect?.(event)}
        className="min-w-0 flex-1 text-left"
        disabled={!onSelect}
      >
        <div className="flex items-center gap-2">
          <span
            className={clsx(
              'truncate text-[13.5px] font-medium',
              event.status === 'done' ? 'text-slate-400 line-through decoration-slate-600' : 'text-slate-100',
            )}
          >
            {event.title}
          </span>
          {event.tentative && (
            <Badge tone="amber" icon="AlertTriangle">
              уточнить
            </Badge>
          )}
          {event.status === 'done' && <Badge tone="green">факт</Badge>}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-slate-500">
          <span>{SOURCE_LABEL[event.sourceType] ?? event.sourceType}</span>
          {category && (
            <>
              <span className="text-slate-700">•</span>
              <span style={{ color: `${category.color}cc` }}>{category.name}</span>
            </>
          )}
          {account && (
            <>
              <span className="text-slate-700">•</span>
              <span className="truncate">{account.name}</span>
            </>
          )}
          {event.parts?.interest ? (
            <>
              <span className="text-slate-700">•</span>
              <span>проценты {Math.round(event.parts.interest).toLocaleString('ru-RU')}</span>
            </>
          ) : null}
          {showRelative && (
            <>
              <span className="text-slate-700">•</span>
              <span>{humanRelative(event.date)}</span>
            </>
          )}
        </div>
      </button>

      {showDate && (
        <span className="num shrink-0 text-[11px] text-slate-500">{fmtDateShort(event.date)}</span>
      )}

      <span
        className={clsx(
          'num shrink-0 whitespace-nowrap text-[13.5px] font-semibold',
          income ? 'text-mint-400' : 'text-slate-200',
        )}
      >
        {income ? '+' : '−'}
        {fmtMoney(Math.abs(event.amount), event.currency, { hide: settings.hideBalances })}
      </span>
    </div>
  );
}

export function EventsList({
  events,
  emptyText = 'Событий нет',
  onSelect,
  showDate,
  showRelative,
  dense,
  max,
}: {
  events: CashflowEvent[];
  emptyText?: string;
  onSelect?: (e: CashflowEvent) => void;
  showDate?: boolean;
  showRelative?: boolean;
  dense?: boolean;
  max?: number;
}) {
  const list = max ? events.slice(0, max) : events;
  if (!list.length) {
    return <div className="px-2 py-6 text-center text-xs text-slate-500">{emptyText}</div>;
  }
  return (
    <div className="space-y-0.5">
      {list.map((e) => (
        <EventRow
          key={`${e.sourceKey}-${e.date}-${e.accountId}-${e.amount}`}
          event={e}
          onSelect={onSelect}
          showDate={showDate}
          showRelative={showRelative}
          dense={dense}
        />
      ))}
    </div>
  );
}
