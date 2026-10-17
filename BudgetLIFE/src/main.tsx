import React from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './index.css';

const rootEl = document.getElementById('root');
if (rootEl) {
  createRoot(rootEl).render(
    <React.StrictMode>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <App />
      </BrowserRouter>
    </React.StrictMode>,
  );
  // убираем стартовую заглушку
  requestAnimationFrame(() => document.getElementById('boot')?.remove());
}

// Регистрация service worker (PWA)
async function setupPWA() {
  try {
    const { registerSW } = await import('virtual:pwa-register');
    const updateSW = registerSW({
      immediate: true,
      onNeedRefresh() {
        if (confirm('Доступна новая версия BudgetLIFE. Обновить страницу?')) {
          void updateSW(true);
        }
      },
      onOfflineReady() {
        console.info('[BudgetLIFE] приложение готово к работе офлайн');
      },
      onRegisterError(error) {
        console.warn('[BudgetLIFE] ошибка регистрации SW:', error);
      },
    });
  } catch {
    /* SW недоступен в dev-сборке — не критично */
  }
}

void setupPWA();
