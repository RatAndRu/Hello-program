/* Рендер всех страниц в jsdom — ловим runtime-ошибки без браузера. */
import { JSDOM } from 'jsdom';

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://localhost/',
  pretendToBeVisual: true,
});

const g = globalThis as unknown as Record<string, unknown>;
g.window = dom.window;
g.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true, writable: true });
g.HTMLElement = dom.window.HTMLElement;
g.Element = dom.window.Element;
g.Node = dom.window.Node;
g.Event = dom.window.Event;
g.KeyboardEvent = dom.window.KeyboardEvent;
g.MouseEvent = dom.window.MouseEvent;
g.getComputedStyle = dom.window.getComputedStyle;
g.requestAnimationFrame = (cb: FrameRequestCallback) => setTimeout(() => cb(Date.now()), 0) as unknown as number;
g.cancelAnimationFrame = (id: number) => clearTimeout(id);
g.localStorage = dom.window.localStorage;
g.fetch = async () => {
  throw new Error('offline');
};
dom.window.scrollTo = () => {};

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
g.ResizeObserver = ResizeObserverStub;
(dom.window as unknown as Record<string, unknown>).ResizeObserver = ResizeObserverStub;
(dom.window as unknown as Record<string, unknown>).matchMedia = () => ({
  matches: false,
  media: '',
  addEventListener() {},
  removeEventListener() {},
  addListener() {},
  removeListener() {},
  dispatchEvent() {
    return false;
  },
});

Object.defineProperty(dom.window.HTMLElement.prototype, 'clientWidth', { value: 900, configurable: true });
Object.defineProperty(dom.window.HTMLElement.prototype, 'clientHeight', { value: 400, configurable: true });
Object.defineProperty(dom.window.HTMLElement.prototype, 'offsetWidth', { value: 900, configurable: true });
Object.defineProperty(dom.window.HTMLElement.prototype, 'offsetHeight', { value: 400, configurable: true });
dom.window.HTMLElement.prototype.getBoundingClientRect = function () {
  return { width: 900, height: 400, top: 0, left: 0, right: 900, bottom: 400, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
};

const IGNORE = [
  "Not implemented: Window's scrollTo()",
  'Future Flag Warning',
  'React Router will begin wrapping',
  'not wrapped in act', // шум тестового окружения: асинхронные обновления вне act()
  'Not implemented: navigation', // jsdom не умеет переходить по ссылкам
];
const errors: string[] = [];
const remember = (msg: string) => {
  if (!IGNORE.some((i) => msg.includes(i))) errors.push(msg);
};
const origError = console.error;
console.error = (...args: unknown[]) => remember(args.map(String).join(' '));
console.warn = (...args: unknown[]) => remember('WARN: ' + args.map(String).join(' '));

const { createElement, StrictMode } = await import('react');
const { createRoot } = await import('react-dom/client');
const { MemoryRouter } = await import('react-router-dom');
const App = (await import('../src/App')).default;
const { useStore } = await import('../src/store/useStore');
const { buildDemoState } = await import('../src/store/demo');
const { emptyState } = await import('../src/store/defaults');
const { STATE_KEY } = await import('../src/store/db');

const demo = buildDemoState();
let failed = 0;

interface Mounted {
  container: HTMLElement;
  root: ReturnType<typeof createRoot>;
  html: () => string;
  bodyHtml: () => string;
  buttons: () => HTMLButtonElement[];
  click: (text: string) => Promise<void>;
  unmount: () => void;
}

/** Монтируем страницу: данные подкладываем в localStorage, как это делает браузер */
async function mount(route: string, seed: 'demo' | 'empty' = 'demo'): Promise<Mounted> {
  dom.window.localStorage.clear();
  if (seed === 'demo') dom.window.localStorage.setItem(STATE_KEY, JSON.stringify(demo));
  useStore.setState({ data: emptyState(), hydrated: false, ratesStatus: 'idle' });

  const container = dom.window.document.createElement('div');
  dom.window.document.body.appendChild(container);
  const root = createRoot(container);
  root.render(
    createElement(StrictMode, null, createElement(MemoryRouter, { initialEntries: [route] }, createElement(App))),
  );
  await new Promise((r) => setTimeout(r, 160));

  return {
    container,
    root,
    html: () => container.innerHTML,
    bodyHtml: () => dom.window.document.body.innerHTML,
    buttons: () => [...container.querySelectorAll('button')] as HTMLButtonElement[],
    click: async (text: string) => {
      const nodes = [...container.querySelectorAll('button, a[href]')] as HTMLElement[];
      const btn = nodes.find((b) => (b.textContent ?? '').trim().toLowerCase().includes(text.toLowerCase()));
      if (!btn) throw new Error(`кнопка «${text}» не найдена`);
      btn.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
      await new Promise((r) => setTimeout(r, 160));
    },
    unmount: () => {
      root.unmount();
      container.remove();
    },
  };
}

/* --------------------------- рендер всех страниц ---------------------------- */
console.log('Рендер страниц (демо-данные)');
const routes = ['/', '/calendar', '/incomes', '/expenses', '/accounts', '/subscriptions', '/credits', '/converter', '/analytics', '/settings'];

for (const route of routes) {
  const before = errors.length;
  const page = await mount(route);
  const html = page.html();
  const ok = html.length > 3000 && errors.length === before;
  if (!ok) failed++;
  console.log(
    `${ok ? '✓' : '✗'} ${route.padEnd(16)} ${String(html.length).padStart(7)} симв.  кнопок: ${String(page.buttons().length).padStart(3)}  ошибок: ${errors.length - before}`,
  );
  errors.slice(before, before + 4).forEach((e) => console.log('     → ' + e.slice(0, 400)));
  page.unmount();
}

/* ------------------------------ пустое состояние ---------------------------- */
console.log('\nПустое состояние (onboarding)');
{
  const before = errors.length;
  const page = await mount('/', 'empty');
  const ok = page.html().includes('Добро пожаловать') && errors.length === before;
  if (!ok) failed++;
  console.log(`${ok ? '✓' : '✗'} онбординг показан: ${page.html().includes('Добро пожаловать')}`);
  errors.slice(before, before + 3).forEach((e) => console.log('     → ' + e.slice(0, 300)));
  page.unmount();
}

/* -------------------------------- интерактив -------------------------------- */
console.log('\nИнтерактив');
async function testClick(route: string, text: string, expect?: string) {
  const before = errors.length;
  const page = await mount(route);
  let ok = true;
  let note = '';
  try {
    await page.click(text);
    if (expect && !page.bodyHtml().includes(expect)) {
      ok = false;
      note = `ожидаемый текст «${expect}» не найден`;
    }
  } catch (e) {
    ok = false;
    note = e instanceof Error ? e.message : String(e);
  }
  if (errors.length !== before) ok = false;
  if (!ok) failed++;
  console.log(`${ok ? '✓' : '✗'} ${route.padEnd(15)} клик «${text}»${expect ? ` → «${expect}»` : ''}${note ? ` (${note})` : ''}`);
  errors.slice(before, before + 3).forEach((e) => console.log('     → ' + e.slice(0, 300)));
  page.unmount();
}

await testClick('/incomes', 'Добавить доход', 'Новый источник дохода');
await testClick('/incomes', 'Корректировки по месяцам');
await testClick('/accounts', 'Добавить счёт', 'Новый счёт');
await testClick('/subscriptions', 'Добавить', 'Новая подписка');
await testClick('/credits', 'Добавить кредит', 'Новый кредит');
await testClick('/expenses', 'Добавить', 'Новая операция');
await testClick('/', 'Операция', 'Быстрое добавление');
await testClick('/settings', 'Создать копию');
await testClick('/credits', 'График платежей', 'Проценты');
await testClick('/analytics', 'Операции', 'операций');
await testClick('/converter', 'Обновить из ЦБ РФ');
await testClick('/converter', 'Ручные курсы', 'Ручной курс имеет приоритет');

/* -------------------------- действия с данными ------------------------------ */
console.log('\nОперации со стором');
{
  const before = errors.length;
  const page = await mount('/incomes');
  const incomesBefore = useStore.getState().data.incomes.length;
  const id = useStore.getState().addIncome({ name: 'Тестовый доход', amount: 50_000 });
  const added = useStore.getState().data.incomes.length === incomesBefore + 1;
  useStore.getState().setMonthOverride(id, useStore.getState().data.incomes[0].startYM, { amount: 77_000 });
  const overridden = Boolean(useStore.getState().data.incomes.find((i) => i.id === id)?.overrides[useStore.getState().data.incomes[0].startYM]?.amount === 77_000);
  useStore.getState().deleteIncome(id);
  const removed = useStore.getState().data.incomes.length === incomesBefore;
  const ok = added && overridden && removed && errors.length === before;
  if (!ok) failed++;
  console.log(`${ok ? '✓' : '✗'} add / override / delete источника дохода (add=${added}, override=${overridden}, delete=${removed})`);
  page.unmount();
}
{
  const before = errors.length;
  const page = await mount('/accounts');
  const accId = useStore.getState().addAccount({ name: 'Тест', balance: 1000, interest: { ...useStore.getState().data.accounts[0].interest, enabled: true, annualRate: 10, capitalization: 'monthly' } });
  const created = useStore.getState().data.accounts.some((a) => a.id === accId);
  useStore.getState().updateAccount(accId, { balance: 2000 });
  const updated = useStore.getState().data.accounts.find((a) => a.id === accId)?.balance === 2000;
  useStore.getState().deleteAccount(accId);
  const deleted = !useStore.getState().data.accounts.some((a) => a.id === accId);
  const ok = created && updated && deleted && errors.length === before;
  if (!ok) failed++;
  console.log(`${ok ? '✓' : '✗'} add / update / delete счёта (create=${created}, update=${updated}, delete=${deleted})`);
  page.unmount();
}
{
  // jsdom не умеет переходить по ссылкам, поэтому проверяем только их наличие
  const before = errors.length;
  const page = await mount('/');
  const txCount = useStore.getState().data.transactions.length;
  const links = [...page.container.querySelectorAll('a[href]')].map((a) => a.getAttribute('href'));
  const hasNav = links.includes('/calendar') && links.includes('/analytics') && links.includes('/incomes');
  const ok = hasNav && txCount > 0 && errors.length === before;
  if (!ok) failed++;
  console.log(`${ok ? '✓' : '✗'} навигация с обзора (ссылок: ${links.length}, операций: ${txCount})`);
  errors.slice(before, before + 3).forEach((e) => console.log('     → ' + e.slice(0, 300)));
  page.unmount();
}

console.log(failed === 0 ? '\n✅ Все проверки интерфейса пройдены' : `\n❌ Проблем: ${failed}`);
process.exit(failed === 0 ? 0 : 1);
