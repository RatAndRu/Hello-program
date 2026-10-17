import { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { Toaster } from './components/ui/Toaster';
import { useStore } from './store/useStore';
import { EmptyState } from './components/ui/primitives';
import { ErrorBoundary } from './components/ErrorBoundary';
import Dashboard from './pages/Dashboard';
import CalendarPage from './pages/CalendarPage';
import Incomes from './pages/Incomes';
import Expenses from './pages/Expenses';
import Accounts from './pages/Accounts';
import Subscriptions from './pages/Subscriptions';
import Credits from './pages/Credits';
import Converter from './pages/Converter';
import Analytics from './pages/Analytics';
import SettingsPage from './pages/SettingsPage';

function Onboarding() {
  const loadDemo = useStore((s) => s.loadDemo);
  const addAccount = useStore((s) => s.addAccount);

  return (
    <div className="mx-auto max-w-2xl">
      <div className="card card-pad animate-slide-up">
        <div className="mb-5 flex items-center gap-3">
          <img src="/icons/icon.svg" alt="" className="h-11 w-11 rounded-xl shadow-glow" />
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              Добро пожаловать в <span className="grad-text">BudgetLIFE</span>
            </h1>
            <p className="text-sm text-slate-400">Ваш личный центр управления деньгами</p>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <button
            onClick={loadDemo}
            className="rounded-2xl border border-white/10 bg-gradient-to-br from-brand-500/15 to-mint-500/10 p-5 text-left transition hover:border-brand-400/40 hover:from-brand-500/25"
          >
            <div className="mb-2 grid h-9 w-9 place-items-center rounded-lg bg-brand-400/20 text-brand-300">
              <span className="text-lg">✨</span>
            </div>
            <div className="text-sm font-semibold text-slate-100">Загрузить демо-данные</div>
            <p className="mt-1 text-xs leading-relaxed text-slate-400">
              Готовый пример: 7 счетов, зарплата с авансом, сдельный фриланс, подписки, кредиты и год истории операций
            </p>
          </button>

          <button
            onClick={() => {
              addAccount({ name: 'Основная карта', type: 'card', currency: 'RUB', balance: 0, icon: 'CreditCard' });
              useStore.getState().patchSettings({ onboarded: true });
            }}
            className="rounded-2xl border border-white/10 bg-white/[0.03] p-5 text-left transition hover:border-white/25 hover:bg-white/[0.06]"
          >
            <div className="mb-2 grid h-9 w-9 place-items-center rounded-lg bg-white/[0.07] text-slate-300">
              <span className="text-lg">🧾</span>
            </div>
            <div className="text-sm font-semibold text-slate-100">Начать с чистого листа</div>
            <p className="mt-1 text-xs leading-relaxed text-slate-400">
              Создадим первый счёт, а доходы, подписки и кредиты добавите по ходу
            </p>
          </button>
        </div>

        <div className="mt-5 rounded-xl border border-white/[0.07] bg-white/[0.02] p-4 text-xs leading-relaxed text-slate-400">
          Все данные хранятся <b className="text-slate-200">только в вашем браузере</b> (IndexedDB). Никаких серверов и
          отправки данных наружу — можно работать офлайн и в любой момент сделать экспорт в JSON.
        </div>
      </div>
    </div>
  );
}

function Boot() {
  return (
    <div className="grid h-[70vh] place-items-center">
      <div className="h-10 w-10 animate-spin rounded-full border-2 border-brand-400/25 border-t-brand-400" />
    </div>
  );
}

/**
 * Заголовок окна: «Раздел — BudgetLIFE».
 * В отдельном окне приложения (start.vbs) по заголовку работает фокус уже
 * открытого окна, а в панели задач видно, какой раздел сейчас открыт.
 */
const TITLES: Record<string, string> = {
  '/': 'Обзор',
  '/calendar': 'Календарь',
  '/incomes': 'Доходы',
  '/expenses': 'Расходы',
  '/accounts': 'Счета',
  '/subscriptions': 'Подписки',
  '/credits': 'Кредиты',
  '/converter': 'Конвертер',
  '/analytics': 'Аналитика',
  '/settings': 'Настройки',
};

function PageTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    document.title = `${TITLES[pathname] ?? 'BudgetLIFE'} — BudgetLIFE`;
  }, [pathname]);
  return null;
}

export default function App() {
  const hydrated = useStore((s) => s.hydrated);
  const hydrate = useStore((s) => s.hydrate);
  const accounts = useStore((s) => s.data.accounts);
  const onboarded = useStore((s) => s.data.settings.onboarded);

  useEffect(() => {
    void hydrate();
  }, [hydrate]);

  if (!hydrated) return <Boot />;

  return (
    <ErrorBoundary>
      <PageTitle />
      <Routes>
        <Route element={<AppShell />}>
          <Route
            path="/"
            element={accounts.length || onboarded ? <Dashboard /> : <Onboarding />}
          />
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="/incomes" element={<Incomes />} />
          <Route path="/expenses" element={<Expenses />} />
          <Route path="/accounts" element={<Accounts />} />
          <Route path="/subscriptions" element={<Subscriptions />} />
          <Route path="/credits" element={<Credits />} />
          <Route path="/converter" element={<Converter />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route
            path="*"
            element={
              <EmptyState
                title="Страница не найдена"
                description="Проверьте адрес или вернитесь на главную"
                action={<a className="btn-primary" href="/">На главную</a>}
              />
            }
          />
        </Route>
        <Route path="/index.html" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster />
    </ErrorBoundary>
  );
}
