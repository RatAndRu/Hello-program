import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Icon } from './Icon';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  info: string | null;
}

/** Ловим ошибки рендера, чтобы приложение не превращалось в белый экран */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    this.setState({ info: info.componentStack ?? null });
    console.error('[BudgetLIFE]', error, info);
  }

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="grid min-h-screen place-items-center p-6">
        <div className="card max-w-xl p-6">
          <div className="mb-3 flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl border border-rose-500/30 bg-rose-500/10 text-rose-400">
              <Icon name="AlertTriangle" size={20} />
            </span>
            <div>
              <h2 className="text-[16px] font-semibold text-slate-100">Что-то пошло не так</h2>
              <p className="text-[12px] text-slate-400">Интерфейс столкнулся с ошибкой, но данные не потеряны</p>
            </div>
          </div>

          <pre className="mb-4 max-h-40 overflow-auto rounded-xl border border-white/10 bg-ink-950/70 p-3 text-[11.5px] leading-relaxed text-rose-300">
            {error.message}
          </pre>

          {info && (
            <details className="mb-4 text-[11px] text-slate-500">
              <summary className="cursor-pointer">Подробности</summary>
              <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap">{info}</pre>
            </details>
          )}

          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" onClick={() => this.setState({ error: null, info: null })}>
              Попробовать снова
            </button>
            <button className="btn-ghost" onClick={() => window.location.reload()}>
              Перезагрузить
            </button>
            <a className="btn-ghost" href="/settings">
              Настройки и экспорт
            </a>
          </div>
        </div>
      </div>
    );
  }
}
