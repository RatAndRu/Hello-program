/* Проверка ядра приложения без браузера: демо-данные → движок → проекция. */
import { buildDemoState } from '../src/store/demo';
import { buildEvents, project, incomeMonthPayments, estimateMonthlyInterest, categoryBreakdown, totalsOf } from '../src/lib/engine';
import { loanSchedule, creditSummary, graceInfo, cardSchedule, minPayment } from '../src/lib/credit';
import { convert } from '../src/lib/rates';
import { nowYM, todayISO, addYM, toISO, fromISO, addMonths, resolvePayDay } from '../src/lib/dates';
import type { EngineCtx } from '../src/lib/engine';

let failures = 0;
function check(name: string, cond: boolean, extra?: unknown) {
  if (cond) {
    console.log(`  ✓ ${name}`);
  } else {
    failures++;
    console.error(`  ✗ ${name}`, extra ?? '');
  }
}

console.log('Демо-данные');
const state = buildDemoState();
check('счета созданы', state.accounts.length === 7, state.accounts.length);
check('источники дохода', state.incomes.length === 3);
check('подписки', state.subscriptions.length === 8);
check('кредиты', state.credits.length === 3);
check('операции', state.transactions.length > 200, state.transactions.length);
check('все суммы конечны', state.transactions.every((t) => Number.isFinite(t.amount)));
check('все даты корректны', state.transactions.every((t) => /^\d{4}-\d{2}-\d{2}$/.test(t.date)));

const ctx: EngineCtx = {
  accounts: state.accounts,
  categories: state.categories,
  incomes: state.incomes,
  subscriptions: state.subscriptions,
  credits: state.credits,
  transactions: state.transactions,
  rates: { rates: {}, base: 'RUB' },
  baseCurrency: 'RUB',
};

console.log('\nДвижок: события');
const from = `${addYM(nowYM(), -2)}-01`;
const to = `${addYM(nowYM(), 3)}-28`;
const events = buildEvents(ctx, from, to);
check('события сгенерированы', events.length > 100, events.length);
check('даты в диапазоне', events.every((e) => e.date >= from && e.date <= to));
check('суммы конечны', events.every((e) => Number.isFinite(e.amount)));
check(
  'уникальные ключи',
  new Set(events.map((e) => e.sourceKey)).size === events.length,
  events.length - new Set(events.map((e) => e.sourceKey)).size,
);
check('есть события подписок', events.some((e) => e.sourceType === 'subscription'));
check('есть события кредитов', events.some((e) => e.sourceType === 'credit'));
check('есть события доходов', events.some((e) => e.sourceType === 'income'));
check('есть пополнения счетов', events.some((e) => e.sourceType === 'topup'));
check('есть факты', events.some((e) => e.status === 'done'));
check('плановые события преобладают', events.filter((e) => e.status === 'planned').length > 50);

console.log('\nДоходы: корректировки по месяцам');
const salary = state.incomes[0];
const payments = incomeMonthPayments(salary, nowYM());
check('две выплаты в месяце', payments.length === 2, payments.length);
check('аванс 7-го по корректировке', payments[0].date === resolvePayDay(nowYM(), 7, 'prevWorkday'), payments[0].date);
check('сумма аванса из корректировки', Math.round(payments[0].amount) === 88_000, payments[0].amount);
const prevMonth = incomeMonthPayments(salary, addYM(nowYM(), -1));
check('премия в прошлом месяце', Math.round(prevMonth.reduce((s, p) => s + p.amount, 0)) === Math.round(245_000 * 0.87), prevMonth);

const freelance = state.incomes[1];
check('сдельный доход помечен tentative', incomeMonthPayments(freelance, addYM(nowYM(), 4))[0].tentative === true);
check('сумма сдельного из override', Math.round(incomeMonthPayments(freelance, nowYM())[0].amount) === 52_000);

console.log('\nПроекция баланса');
const proj = project(ctx, todayISO(), to);
check('дни построены', proj.days.length > 100, proj.days.length);
check('балансы конечны', proj.days.every((d) => Number.isFinite(d.balance)));
check('учтены проценты', Object.keys(proj.interestByAccount).length > 0, Object.keys(proj.interestByAccount).length);
check('проценты положительны', Object.values(proj.interestByAccount).every((v) => v >= 0), proj.interestByAccount);
check('есть события процентов', proj.events.some((e) => e.sourceType === 'interest'));

const first = proj.days[0].balance;
const last = proj.days[proj.days.length - 1].balance;
check('баланс меняется со временем', Math.abs(last - first) > 1, { first, last });

console.log('\nКредиты');
const loan = state.credits.find((c) => c.kind === 'loan')!;
const schedule = loanSchedule(loan);
check('график платежей построен', schedule.length > 10, schedule.length);
check('платёж положительный', schedule[0].payment > 0, schedule[0].payment);
check('долг уменьшается', schedule[schedule.length - 1].balance < schedule[0].balance);
check('проценты убывают', schedule[schedule.length - 1].interest < schedule[0].interest);
const ls = creditSummary(loan);
check('остаток долга > 0', ls.debt > 0, ls.debt);
check('переплата > 0', ls.overpayment > 0, ls.overpayment);
check('дата закрытия в будущем', (ls.payoffDate ?? '') > todayISO(), ls.payoffDate);

const card = state.credits.find((c) => c.kind === 'credit_card')!;
const grace = graceInfo(card);
check('грейс-период рассчитан', Boolean(grace) && (grace?.daysLeft ?? 0) > 0, grace?.daysLeft);
check('минимальный платёж', minPayment(card) > 0, minPayment(card));
const cardRows = cardSchedule(card, todayISO(), to);
check('платежи по карте запланированы', cardRows.length >= 1, cardRows.length);
check('при полном погашении процентов нет', cardRows.every((r) => r.interest === 0));

const installment = state.credits.find((c) => c.kind === 'installment')!;
const instRows = loanSchedule(installment);
check('рассрочка без процентов', instRows.every((r) => r.interest === 0));

console.log('\nПроценты по счетам');
const deposit = state.accounts.find((a) => a.id === 'demo_acc_dep')!;
check('оценка процентов по вкладу', estimateMonthlyInterest(deposit) > 5000, estimateMonthlyInterest(deposit));
const savings = state.accounts.find((a) => a.id === 'demo_acc_save')!;
check('оценка процентов по накопительному', estimateMonthlyInterest(savings) > 3000, estimateMonthlyInterest(savings));

console.log('\nКонвертация и агрегаты');
const rates = { rates: { USD: 0.012, EUR: 0.011, RUB: 1 }, base: 'RUB' };
check('RUB → USD', Math.abs(convert(1000, 'RUB', 'USD', rates) - 12) < 0.001, convert(1000, 'RUB', 'USD', rates));
check('USD → RUB', Math.abs(convert(12, 'USD', 'RUB', rates) - 1000) < 0.001);
check('без курса — как есть', convert(500, 'KZT', 'RUB', rates) === 500);
const totals = totalsOf(events, ctx);
check('доходы > 0', totals.income > 0, totals.income);
check('расходы > 0', totals.expense > 0, totals.expense);
const breakdown = categoryBreakdown(events, ctx, 'expense');
check('разбивка по категориям', breakdown.length > 3, breakdown.length);
check('сумма долей = 100%', Math.abs(breakdown.reduce((s, b) => s + b.value, 0) - totals.expense) < 1);

console.log('\nДаты');
check('перенос с выходного назад', resolvePayDay('2026-11-01', 8, 'prevWorkday') === '2026-11-06', resolvePayDay('2026-11-01', 8, 'prevWorkday'));
check('последний день месяца', resolvePayDay('2026-02-01', -1, 'exact') === '2026-02-28', resolvePayDay('2026-02-01', -1, 'exact'));
check('сдвиг месяца', addYM('2026-12', 1) === '2027-01', addYM('2026-12', 1));
check('сдвиг месяца назад', addYM('2026-01', -1) === '2025-12', addYM('2026-01', -1));
check('добавление месяцев с клипом дня', toISO(addMonths(fromISO('2026-01-31'), 1)) === '2026-02-28', toISO(addMonths(fromISO('2026-01-31'), 1)));

console.log(failures === 0 ? '\n✅ Все проверки пройдены' : `\n❌ Ошибок: ${failures}`);
process.exit(failures === 0 ? 0 : 1);
