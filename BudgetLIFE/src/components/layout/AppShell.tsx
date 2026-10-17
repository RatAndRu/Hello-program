import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import clsx from 'clsx';
import { Icon } from '../Icon';
import { Button, IconButton, Modal } from '../ui/primitives';
import { useStore } from '../../store/useStore';
import { useInstall, useOnline } from '../../hooks/useInstall';
import { QuickAddTx } from '../QuickAddTx';
import { fmtDate } from '../../lib/dates';

export interface NavItem {
  to: string;
  label: string;
  icon: string;
  hint: string;
  group: 'Планирование' | 'Деньги' | 'Анализ';
}

export const NAV: NavItem[] = [
  { to: '/', label: 'Обзор', icon: 'LayoutDashboard', hint: 'Сводка на сегодня', group: 'Планирование' },
  { to: '/calendar', label: 'Календарь', icon: 'CalendarDays', hint: 'Выплаты и списания по дням', group: 'Планирование' },
  { to: '/incomes', label: 'Доходы', icon: 'TrendingUp', hint: 'Зарплаты, авансы, подработки', group: 'Планирование' },
  { to: '/expenses', label: 'План расходов', icon: 'Receipt', hint: 'Что и когда планируем тратить', group: 'Планирование' },
  { to: '/accounts', label: 'Счета', icon: 'Wallet', hint: 'Балансы, проценты, пополнения', group: 'Деньги' },
  { to: '/subscriptions', label: 'Подписки', icon: 'Repeat', hint: 'Регулярные списания', group: 'Деньги' },
  { to: '/credits', label: 'Кредиты', icon: 'CreditCard', hint: 'Платежи и беспроцентный период', group: 'Деньги' },
  { to: '/converter', label: 'Конвертер', icon: 'ArrowLeftRight', hint: 'Актуальные курсы валют', group: 'Деньги' },
  { to: '/analytics', label: 'Аналитика', icon: 'ChartLine', hint: 'Графики и отчёты', group: 'Анализ' },
  { to: '/settings', label: 'Настройки', icon: 'Settings', hint: 'Данные, курсы, импорт', group: 'Анализ' },
];

const GROUPS: NavItem['group'][] = ['Планирование', 'Деньги', 'Анализ'];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { canInstall, installed, promptInstall } = useInstall();
  const online = useOnline();

  return (
    <aside className="flex h-full w-[248px] shrink-0 flex-col border-r border-white/[0.06] bg-ink-950/60 backdrop-blur-xl">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <img src="/icons/icon.svg" alt="" className="h-9 w-9 rounded-xl shadow-glow" />
        <div className="leading-tight">
          <div className="text-[15px] font-extrabold tracking-tight">
            Budget<span className="grad-text">LIFE</span>
          </div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">планировщик бюджета</div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4">
        {GROUPS.map((group) => (
          <div key={group} className="mb-4">
            <div className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">{group}</div>
            <ul className="space-y-0.5">
              {NAV.filter((n) => n.group === group).map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === '/'}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      clsx(
                        'group flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-[13.5px] transition',
                        isActive
                          ? 'bg-gradient-to-r from-brand-500/20 to-transparent text-white shadow-[inset_2px_0_0_0_#38c3f5]'
                          : 'text-slate-400 hover:bg-white/[0.05] hover:text-slate-100',
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <Icon
                          name={item.icon}
                          size={16}
                          className={clsx('shrink-0 transition', isActive ? 'text-brand-300' : 'text-slate-500 group-hover:text-slate-300')}
                        />
                        <span className="truncate font-medium">{item.label}</span>
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-white/[0.06] p-3">
        {canInstall && (
          <Button
            variant="primary"
            size="sm"
            icon="Download"
            className="mb-2 w-full"
            onClick={async () => {
              await promptInstall();
            }}
          >
            Установить приложение
          </Button>
        )}
        {installed && (
          <div className="mb-2 flex items-center gap-2 rounded-lg border border-mint-500/25 bg-mint-500/10 px-2.5 py-2 text-[11px] text-mint-400">
            <Icon name="CheckCircle2" size={14} />
            Приложение установлено
          </div>
        )}
        <div className="flex items-center justify-between px-1 text-[11px] text-slate-500">
          <span className="flex items-center gap-1.5">
            <span className={clsx('h-1.5 w-1.5 rounded-full', online ? 'bg-mint-500' : 'bg-amberx-500')} />
            {online ? 'Онлайн' : 'Офлайн-режим'}
          </span>
          <span>v1.0</span>
        </div>
      </div>
    </aside>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const location = useLocation();
  const current = NAV.find((n) => (n.to === '/' ? location.pathname === '/' : location.pathname.startsWith(n.to)));
  const settings = useStore((s) => s.data.settings);
  const rates = useStore((s) => s.data.rates);
  const patchSettings = useStore((s) => s.patchSettings);
  const ratesStatus = useStore((s) => s.ratesStatus);
  const refreshRates = useStore((s) => s.refreshRates);
  const [quickAdd, setQuickAdd] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setQuickAdd(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <header className="glass-bar flex items-center justify-between gap-3 px-4 py-3 sm:px-6">
      <div className="flex min-w-0 items-center gap-3">
        <button
          onClick={onMenu}
          className="grid h-9 w-9 place-items-center rounded-xl border border-white/10 bg-white/[0.04] text-slate-300 lg:hidden"
          aria-label="Меню"
        >
          <Icon name="Menu" size={17} />
        </button>
        <div className="min-w-0">
          <h1 className="truncate text-[17px] font-semibold tracking-tight text-slate-50">{current?.label ?? 'BudgetLIFE'}</h1>
          <p className="hidden truncate text-xs text-slate-500 sm:block">{current?.hint}</p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => void refreshRates()}
          title={
            rates
              ? `Курсы обновлены: ${new Date(rates.fetchedAt).toLocaleString('ru-RU')}${rates.date ? ` (${fmtDate(rates.date)})` : ''}`
              : 'Курсы не загружены'
          }
          className={clsx(
            'hidden items-center gap-2 rounded-xl border px-2.5 py-1.5 text-[11px] transition md:flex',
            ratesStatus === 'loading'
              ? 'border-brand-400/30 bg-brand-400/10 text-brand-300'
              : rates
                ? 'border-white/10 bg-white/[0.04] text-slate-400 hover:text-slate-200'
                : 'border-amberx-500/30 bg-amberx-500/10 text-amberx-400',
          )}
        >
          <Icon name={ratesStatus === 'loading' ? 'RefreshCw' : 'ArrowLeftRight'} size={13} className={ratesStatus === 'loading' ? 'animate-spin' : ''} />
          {ratesStatus === 'loading' ? 'Обновляю…' : rates ? `Курсы: ${fmtDate(rates.date, 'd MMM')}` : 'Нет курсов'}
        </button>

        <IconButton
          icon={settings.hideBalances ? 'EyeOff' : 'Eye'}
          label={settings.hideBalances ? 'Показать суммы' : 'Скрыть суммы'}
          onClick={() => patchSettings({ hideBalances: !settings.hideBalances })}
        />
        <Button variant="primary" size="sm" icon="Plus" onClick={() => setQuickAdd(true)} className="hidden sm:inline-flex">
          Операция
        </Button>
        <IconButton icon="Plus" label="Добавить операцию" onClick={() => setQuickAdd(true)} className="sm:hidden" />
      </div>

      <Modal open={quickAdd} onClose={() => setQuickAdd(false)} title="Новая операция" subtitle="Быстрое добавление дохода или расхода" icon="Plus">
        <QuickAddTx onDone={() => setQuickAdd(false)} />
      </Modal>
    </header>
  );
}

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo({ top: 0 });
  }, [location.pathname]);

  return (
    <div className="relative z-10 flex min-h-screen">
      {/* десктопная навигация */}
      <div className="sticky top-0 hidden h-screen lg:block">
        <Sidebar />
      </div>

      {/* мобильная/планшетная шторка */}
      {menuOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-ink-950/70 backdrop-blur-sm" onClick={() => setMenuOpen(false)} />
          <div className="relative h-full w-[264px] animate-slide-up">
            <Sidebar onNavigate={() => setMenuOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setMenuOpen(true)} />
        <main className="mx-auto w-full max-w-[1560px] flex-1 px-4 py-5 sm:px-6 sm:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
