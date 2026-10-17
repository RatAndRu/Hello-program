import clsx from 'clsx';
import { createPortal } from 'react-dom';
import { Icon } from '../Icon';
import { useToastStore } from '../../store/useToast';

const styles = {
  success: { icon: 'CheckCircle2', ring: 'border-mint-500/30', color: 'text-mint-400', bg: 'bg-mint-500/10' },
  error: { icon: 'XCircle', ring: 'border-rose-500/30', color: 'text-rose-400', bg: 'bg-rose-500/10' },
  warning: { icon: 'AlertTriangle', ring: 'border-amberx-500/30', color: 'text-amberx-400', bg: 'bg-amberx-500/10' },
  info: { icon: 'Info', ring: 'border-brand-400/30', color: 'text-brand-300', bg: 'bg-brand-400/10' },
};

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  if (typeof document === 'undefined') return null;

  return createPortal(
    <div className="pointer-events-none fixed bottom-4 right-4 z-[200] flex w-[min(92vw,380px)] flex-col gap-2">
      {toasts.map((t) => {
        const s = styles[t.kind];
        return (
          <div
            key={t.id}
            className={clsx(
              'pointer-events-auto flex items-start gap-3 rounded-xl border bg-ink-900/95 p-3 shadow-2xl backdrop-blur-xl animate-slide-up ring-glass',
              s.ring,
            )}
          >
            <span className={clsx('mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg', s.bg, s.color)}>
              <Icon name={s.icon} size={15} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold text-slate-100">{t.title}</p>
              {t.description && <p className="mt-0.5 whitespace-pre-line text-xs leading-snug text-slate-400">{t.description}</p>}
            </div>
            <button
              onClick={() => dismiss(t.id)}
              className="shrink-0 rounded-lg p-1 text-slate-500 transition hover:bg-white/10 hover:text-slate-200"
              aria-label="Закрыть"
            >
              <Icon name="X" size={14} />
            </button>
          </div>
        );
      })}
    </div>,
    document.body,
  );
}
