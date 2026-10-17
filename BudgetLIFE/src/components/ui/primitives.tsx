import clsx from 'clsx';
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';
import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from '../Icon';
import { amountToInput, parseAmount } from '../../lib/format';

/* ============================== Карточки ================================ */

export function Card({
  className,
  children,
  hover,
  pad = true,
  ...rest
}: {
  className?: string;
  children: ReactNode;
  hover?: boolean;
  pad?: boolean;
} & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={clsx('card', hover && 'card-hover', pad && 'card-pad', className)} {...rest}>
      {children}
    </div>
  );
}

export function SectionHeader({
  title,
  subtitle,
  icon,
  right,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: string;
  right?: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx('mb-3 flex items-start justify-between gap-3', className)}>
      <div className="flex items-start gap-2.5">
        {icon && (
          <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-white/10 bg-white/[0.05] text-brand-300">
            <Icon name={icon} size={16} />
          </span>
        )}
        <div>
          <h2 className="text-[15px] font-semibold leading-tight text-slate-100">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs leading-snug text-slate-400">{subtitle}</p>}
        </div>
      </div>
      {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
    </div>
  );
}

/* =============================== Кнопки ================================= */

type BtnVariant = 'primary' | 'mint' | 'ghost' | 'soft' | 'danger';

export function Button({
  variant = 'ghost',
  size,
  className,
  children,
  icon,
  ...rest
}: {
  variant?: BtnVariant;
  size?: 'sm' | 'md';
  icon?: string;
  children?: ReactNode;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const map: Record<BtnVariant, string> = {
    primary: 'btn-primary',
    mint: 'btn-mint',
    ghost: 'btn-ghost',
    soft: 'btn-soft',
    danger: 'btn-danger',
  };
  return (
    <button className={clsx(map[variant], size === 'sm' && 'btn-sm', className)} {...rest}>
      {icon && <Icon name={icon} size={size === 'sm' ? 14 : 16} />}
      {children}
    </button>
  );
}

export function IconButton({
  icon,
  label,
  className,
  size = 16,
  ...rest
}: { icon: string; label?: string; size?: number } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={clsx('btn-icon border border-white/10 bg-white/[0.05] text-slate-300 hover:bg-white/[0.12] hover:text-white', className)}
      title={label}
      aria-label={label}
      {...rest}
    >
      <Icon name={icon} size={size} />
    </button>
  );
}

/* =============================== Поля =================================== */

export function Field({
  label,
  hint,
  error,
  children,
  className,
  required,
}: {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  children: ReactNode;
  className?: string;
  required?: boolean;
}) {
  return (
    <div className={className}>
      {label && (
        <label className="label">
          {label}
          {required && <span className="ml-0.5 text-rose-400">*</span>}
        </label>
      )}
      {children}
      {error ? <div className="field-error">{error}</div> : hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

export const Input = ({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) => (
  <input className={clsx('input', className)} {...rest} />
);

export const Textarea = ({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) => (
  <textarea className={clsx('textarea', className)} {...rest} />
);

export function Select({
  className,
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & { children: ReactNode }) {
  return (
    <select className={clsx('select', className)} {...rest}>
      {children}
    </select>
  );
}

/** Числовое поле с разделителями и поддержкой «1 250,50» */
export function AmountInput({
  value,
  onChange,
  suffix,
  className,
  placeholder = '0',
  ...rest
}: {
  value: number | undefined;
  onChange: (v: number) => void;
  suffix?: ReactNode;
  className?: string;
  placeholder?: string;
} & Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'>) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className="relative">
      <input
        ref={ref}
        className={clsx('input-mono', suffix && 'pr-12', className)}
        value={amountToInput(value)}
        inputMode="decimal"
        placeholder={placeholder}
        onChange={(e) => onChange(parseAmount(e.target.value))}
        onFocus={(e) => e.currentTarget.select()}
        {...rest}
      />
      {suffix && (
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium text-slate-400">
          {suffix}
        </span>
      )}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between gap-3 rounded-xl border border-white/[0.07] bg-white/[0.03] px-3 py-2.5 text-left transition hover:bg-white/[0.06]"
    >
      <span className="min-w-0">
        <span className="block text-sm text-slate-200">{label}</span>
        {hint && <span className="mt-0.5 block text-xs text-slate-500">{hint}</span>}
      </span>
      <span
        className={clsx(
          'relative h-6 w-11 shrink-0 rounded-full transition',
          checked ? 'bg-gradient-to-r from-brand-400 to-mint-500' : 'bg-white/10',
        )}
      >
        <span
          className={clsx(
            'absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all',
            checked ? 'left-[22px]' : 'left-0.5',
          )}
        />
      </span>
    </button>
  );
}

/** Сегментированный переключатель */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  size = 'md',
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode; icon?: string }[];
  size?: 'sm' | 'md';
  className?: string;
}) {
  return (
    <div className={clsx('inline-flex rounded-xl border border-white/10 bg-ink-900/60 p-1', className)}>
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={clsx(
            'inline-flex items-center gap-1.5 rounded-lg font-medium transition',
            size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3 py-1.5 text-[13px]',
            value === o.value
              ? 'bg-gradient-to-br from-brand-400/90 to-brand-600/90 text-ink-950 shadow'
              : 'text-slate-400 hover:bg-white/[0.06] hover:text-slate-200',
          )}
        >
          {o.icon && <Icon name={o.icon} size={size === 'sm' ? 13 : 15} />}
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* =============================== Чипы =================================== */

export function Chip({
  children,
  active,
  onClick,
  color,
  className,
  icon,
}: {
  children: ReactNode;
  active?: boolean;
  onClick?: () => void;
  color?: string;
  className?: string;
  icon?: string;
}) {
  const Comp = onClick ? 'button' : 'span';
  return (
    <Comp
      onClick={onClick}
      className={clsx('chip', active && 'chip-active', onClick && 'cursor-pointer hover:border-white/25', className)}
      style={color && !active ? { borderColor: `${color}55`, color, background: `${color}18` } : undefined}
    >
      {icon && <Icon name={icon} size={13} />}
      {children}
    </Comp>
  );
}

export function Badge({
  children,
  tone = 'slate',
  className,
  icon,
}: {
  children: ReactNode;
  tone?: 'slate' | 'green' | 'red' | 'amber' | 'brand' | 'violet';
  className?: string;
  icon?: string;
}) {
  const tones: Record<string, string> = {
    slate: 'bg-white/[0.07] text-slate-300',
    green: 'bg-mint-500/15 text-mint-400',
    red: 'bg-rose-500/15 text-rose-400',
    amber: 'bg-amberx-500/15 text-amberx-400',
    brand: 'bg-brand-400/15 text-brand-300',
    violet: 'bg-viola-500/15 text-viola-400',
  };
  return (
    <span className={clsx('badge-soft', tones[tone], className)}>
      {icon && <Icon name={icon} size={12} />}
      {children}
    </span>
  );
}

/* ============================== Прогресс ================================ */

export function Progress({
  value,
  max = 100,
  color = '#38c3f5',
  height = 8,
  showOverflow = true,
}: {
  value: number;
  max?: number;
  color?: string;
  height?: number;
  showOverflow?: boolean;
}) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  const over = pct > 100;
  return (
    <div className="w-full overflow-hidden rounded-full bg-white/[0.07]" style={{ height }}>
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{
          width: `${Math.min(100, Math.max(0, pct))}%`,
          background: over && showOverflow ? 'linear-gradient(90deg,#fbbf5c,#f43f5e)' : `linear-gradient(90deg,${color}88,${color})`,
        }}
      />
    </div>
  );
}

/* ============================== Пустое состояние ========================= */

export function EmptyState({
  icon = 'Inbox',
  title,
  description,
  action,
  className,
}: {
  icon?: string;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx('flex flex-col items-center justify-center px-6 py-12 text-center', className)}>
      <div className="mb-3 grid h-14 w-14 place-items-center rounded-2xl border border-white/10 bg-white/[0.04] text-slate-500">
        <Icon name={icon} size={24} />
      </div>
      <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-xs leading-relaxed text-slate-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/* ================================ Модалка =============================== */

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  width = 'max-w-2xl',
  icon,
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  width?: string;
  icon?: string;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    setTimeout(() => panelRef.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus(), 50);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto p-4 sm:items-center">
      <div
        className="fixed inset-0 bg-ink-950/80 backdrop-blur-sm animate-fade-in"
        onClick={onClose}
        aria-hidden
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        className={clsx(
          'relative z-10 my-auto w-full animate-slide-up rounded-2xl border border-white/10 bg-ink-900/95 shadow-2xl ring-glass',
          width,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-white/[0.07] px-5 py-4">
          <div className="flex items-start gap-3">
            {icon && (
              <span className="mt-0.5 grid h-9 w-9 place-items-center rounded-xl border border-white/10 bg-white/[0.05] text-brand-300">
                <Icon name={icon} size={17} />
              </span>
            )}
            <div>
              <h3 className="text-base font-semibold text-slate-100">{title}</h3>
              {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
            </div>
          </div>
          <IconButton icon="X" label="Закрыть" onClick={onClose} />
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <div className="flex items-center justify-end gap-2 border-t border-white/[0.07] bg-ink-950/40 px-5 py-3.5">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmText = 'Удалить',
  danger = true,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: ReactNode;
  description?: ReactNode;
  confirmText?: string;
  danger?: boolean;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      icon="AlertTriangle"
      width="max-w-md"
      footer={
        <>
          <Button onClick={onClose}>Отмена</Button>
          <Button variant={danger ? 'danger' : 'primary'} icon={danger ? 'Trash2' : 'Check'} onClick={onConfirm}>
            {confirmText}
          </Button>
        </>
      }
    >
      <p className="text-sm leading-relaxed text-slate-300">{description}</p>
    </Modal>
  );
}

/* ============================ Цвета и иконки ============================= */

export function ColorPicker({ value, onChange, colors }: { value: string; onChange: (c: string) => void; colors: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {colors.map((c) => (
        <button
          key={c}
          type="button"
          onClick={() => onChange(c)}
          className={clsx(
            'h-7 w-7 rounded-lg border transition hover:scale-110',
            value === c ? 'border-white ring-2 ring-white/30' : 'border-white/10',
          )}
          style={{ background: c }}
          aria-label={c}
        />
      ))}
    </div>
  );
}

export function IconPicker({
  value,
  onChange,
  names,
  color,
}: {
  value: string;
  onChange: (n: string) => void;
  names: string[];
  color?: string;
}) {
  return (
    <div className="grid max-h-52 grid-cols-8 gap-1.5 overflow-y-auto rounded-xl border border-white/[0.07] bg-ink-950/50 p-2">
      {names.map((n) => (
        <button
          key={n}
          type="button"
          onClick={() => onChange(n)}
          title={n}
          className={clsx(
            'grid h-8 w-8 place-items-center rounded-lg border transition',
            value === n ? 'border-white/40 bg-white/15' : 'border-white/[0.06] hover:bg-white/[0.08]',
          )}
          style={{ color: value === n ? color : undefined }}
        >
          <Icon name={n} size={16} />
        </button>
      ))}
    </div>
  );
}
