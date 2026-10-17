import { readFileSync } from 'node:fs';
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

const APP_ID = 'budgetlife';
const APP_VERSION = (JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version?: string }).version ?? '0.0.0';

/**
 * Служебные маршруты стандарта SPECIALS в dev-режиме: /api/identity (личность)
 * и /api/health (готовность). Благодаря им start.vbs и tools/tray.py одинаково
 * находят приложение и в dev, и в продакшн-сборке: проверка не «порт занят»,
 * а «на порту именно BudgetLIFE».
 */
function identityEndpoints(): Plugin {
  const reply = (res: import('node:http').ServerResponse, data: unknown) => {
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.setHeader('Cache-Control', 'no-store');
    res.end(JSON.stringify(data, null, 2));
  };
  return {
    name: 'budgetlife-identity',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = (req.url ?? '').split('?')[0];
        const address = server.httpServer?.address();
        const port = typeof address === 'object' && address ? address.port : 0;
        if (path === '/api/identity') {
          return reply(res, {
            app_id: APP_ID, name: APP_NAME, version: APP_VERSION, mode: 'dev',
            pid: process.pid, port, url: `http://127.0.0.1:${port}/`,
          });
        }
        if (path === '/api/health') {
          return reply(res, {
            ok: true, app_id: APP_ID, version: APP_VERSION, mode: 'dev', port,
            uptime_ms: Math.round(process.uptime() * 1000),
          });
        }
        next();
      });
    },
  };
}

const APP_NAME = 'BudgetLIFE';
const APP_SHORT = 'BudgetLIFE';
const THEME = '#0b1020';

export default defineConfig({
  plugins: [
    react(),
    identityEndpoints(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'icons/*.png'],
      // PWA активен и в dev-режиме (чтобы приложение можно было установить из превью)
      devOptions: { enabled: true, type: 'module', navigateFallback: 'index.html' },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2,json}'],
        maximumFileSizeToCacheInBytes: 6 * 1024 * 1024,
        navigateFallback: 'index.html',
        runtimeCaching: [
          {
            // Курсы валют: сначала сеть, при отсутствии сети — кэш
            urlPattern: /^https:\/\/(www\.cbr-xml-daily\.ru|api\.frankfurter\.app|open\.er-api\.com|cdn\.jsdelivr\.net)\/.*/i,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'budgetlife-rates',
              networkTimeoutSeconds: 8,
              expiration: { maxEntries: 60, maxAgeSeconds: 60 * 60 * 24 * 7 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
      manifest: {
        name: `${APP_NAME} — планирование бюджета`,
        short_name: APP_SHORT,
        description:
          'Планирование бюджета: доходы, расходы, счета с процентами, подписки, кредиты, календарь выплат и конвертер валют.',
        theme_color: THEME,
        background_color: THEME,
        display: 'standalone',
        display_override: ['window-controls-overlay', 'standalone', 'minimal-ui'],
        orientation: 'any',
        start_url: '/',
        scope: '/',
        lang: 'ru-RU',
        dir: 'ltr',
        categories: ['finance', 'productivity', 'utilities'],
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          { src: 'icons/icon.ico', sizes: '256x256', type: 'image/x-icon', purpose: 'any' },
          { src: 'icons/icon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
        ],
        shortcuts: [
          { name: 'Календарь', url: '/calendar', description: 'Календарь выплат и списаний' },
          { name: 'Конвертер валют', url: '/converter', description: 'Актуальные курсы валют' },
          { name: 'Аналитика', url: '/analytics', description: 'Графики и отчёты' },
        ],
      },
    }),
  ],
  server: {
    host: '0.0.0.0',
    port: 5131,                 // свой блок портов (см. ports.json): 5130 — продакшн, 5131 — dev
    strictPort: false,
    cors: true,
    // Разрешаем доступ по внешнему хосту превью (https://5173-<sandbox>.e2b.app)
    allowedHosts: true,
    hmr: { clientPort: 443, protocol: 'wss' },
  },
  preview: {
    host: '0.0.0.0',
    port: 5132,                 // предпросмотр сборки — тоже в своём блоке
    cors: true,
    allowedHosts: true,
  },
  build: {
    target: 'es2020',
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
        },
      },
    },
  },
});
