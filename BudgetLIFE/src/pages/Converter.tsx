import { useEffect, useMemo, useState } from 'react';
import clsx from 'clsx';
import { useStore } from '../store/useStore';
import { AmountInput, Badge, Button, Card, Field, IconButton, SectionHeader, Select, Segmented } from '../components/ui/primitives';
import { Icon } from '../components/Icon';
import { CURRENCY_OPTIONS } from '../lib/format';
import { convert, hasRate, pairHistory, PROVIDERS, rateText } from '../lib/rates';
import { fmtMoney, fmtNumber } from '../lib/format';
import { fmtDate } from '../lib/dates';
import { Sparkline } from '../components/charts';
import { toast } from '../store/useToast';
import type { RatesProvider } from '../types';

export default function Converter() {
  const data = useStore((s) => s.data);
  const setManualRate = useStore((s) => s.setManualRate);
  const refreshRates = useStore((s) => s.refreshRates);
  const patchSettings = useStore((s) => s.patchSettings);
  const ratesStatus = useStore((s) => s.ratesStatus);
  const ratesError = useStore((s) => s.ratesError);

  const settings = data.settings;
  const base = settings.baseCurrency;
  const rates = { rates: data.rates?.rates ?? {}, base: data.rates?.base ?? base, manual: settings.manualRates };

  const [amount, setAmount] = useState<number>(1000);
  const [from, setFrom] = useState(base === 'USD' ? 'RUB' : 'USD');
  const [to, setTo] = useState(base);
  const [tab, setTab] = useState<'convert' | 'table' | 'manual'>('convert');
  const [editingManual, setEditingManual] = useState<string | null>(null);

  // история пары для спарклайна
  const history = useMemo(() => pairHistory(from, to, base), [from, to, base, data.rates?.fetchedAt]);
  const result = convert(amount, from, to, rates);
  const haveRate = hasRate(from, to, rates);

  /* какие валюты показывать в таблице: используемые в приложении + популярные */
  const usedCurrencies = useMemo(() => {
    const set = new Set<string>([base, from, to]);
    data.accounts.forEach((a) => set.add(a.currency));
    data.subscriptions.forEach((s) => set.add(s.currency));
    data.credits.forEach((c) => set.add(c.currency));
    data.incomes.forEach((i) => set.add(i.currency));
    ['RUB', 'USD', 'EUR', 'CNY', 'KZT', 'TRY', 'GBP', 'JPY'].forEach((c) => set.add(c));
    return [...set];
  }, [data, base, from, to]);

  useEffect(() => {
    if (ratesStatus === 'error' && ratesError) {
      // показываем один раз при открытии страницы
    }
  }, [ratesStatus, ratesError]);

  const swap = () => {
    setFrom(to);
    setTo(from);
  };

  const delta = history.length > 1 ? ((history[history.length - 1] - history[0]) / history[0]) * 100 : NaN;

  return (
    <div className="space-y-4">
      {/* -------------------------------- конвертер ------------------------------- */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <SectionHeader
            title="Конвертер валют"
            subtitle="Курсы подтягиваются из интернета; при отсутствии сети используются кэш и ручные курсы"
            icon="ArrowLeftRight"
            right={
              <div className="flex items-center gap-2">
                <Select
                  value={settings.ratesProvider}
                  onChange={(e) => {
                    patchSettings({ ratesProvider: e.target.value as RatesProvider });
                    if (e.target.value !== 'manual') void refreshRates(e.target.value as RatesProvider);
                  }}
                  className="w-auto min-w-[190px] py-1.5 text-[12.5px]"
                >
                  <option value="auto">Авто (перебор источников)</option>
                  {PROVIDERS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                  <option value="manual">Только ручные курсы</option>
                </Select>
                <IconButton
                  icon="RefreshCw"
                  label="Обновить курсы"
                  onClick={async () => {
                    await refreshRates();
                    if (useStore.getState().ratesStatus === 'error') {
                      toast.error('Не удалось обновить курсы', 'Проверьте подключение к интернету или задайте курс вручную');
                    } else {
                      toast.success('Курсы обновлены');
                    }
                  }}
                  className={clsx(ratesStatus === 'loading' && 'animate-spin')}
                />
              </div>
            }
          />

          <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-end">
            <Field label="У меня есть">
              <AmountInput value={amount} onChange={setAmount} className="text-[15px]" />
              <div className="mt-2">
                <Select value={from} onChange={(e) => setFrom(e.target.value)}>
                  {usedCurrencies.map((c) => (
                    <option key={c} value={c}>
                      {c} — {CURRENCY_OPTIONS.find((x) => x.code === c)?.label ?? c}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {[100, 1000, 10_000, 100_000].map((v) => (
                  <button key={v} onClick={() => setAmount(v)} className="chip hover:border-white/25">
                    {fmtNumber(v)}
                  </button>
                ))}
              </div>
            </Field>

            <div className="flex justify-center pb-1 sm:pb-9">
              <button
                onClick={swap}
                className="grid h-11 w-11 place-items-center rounded-xl border border-white/10 bg-white/[0.06] text-slate-300 transition hover:border-brand-400/50 hover:bg-brand-400/15 hover:text-brand-200"
                aria-label="Поменять местами"
              >
                <Icon name="ArrowLeftRight" size={18} />
              </button>
            </div>

            <Field label="Получу">
              <div className="rounded-xl border border-brand-400/25 bg-brand-400/[0.07] px-3 py-2">
                <div className="num truncate text-[22px] font-bold leading-tight text-slate-50">
                  {fmtMoney(result, to, { cents: Math.abs(result) < 100 })}
                </div>
              </div>
              <div className="mt-2">
                <Select value={to} onChange={(e) => setTo(e.target.value)}>
                  {usedCurrencies.map((c) => (
                    <option key={c} value={c}>
                      {c} — {CURRENCY_OPTIONS.find((x) => x.code === c)?.label ?? c}
                    </option>
                  ))}
                </Select>
              </div>
            </Field>
          </div>

          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 py-2.5">
              <div className="text-[10.5px] uppercase tracking-wide text-slate-500">Курс</div>
              <div className="num text-[14px] font-semibold text-slate-100">
                1 {from} = {rateText(from, to, rates)} {to}
              </div>
            </div>
            <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 py-2.5">
              <div className="text-[10.5px] uppercase tracking-wide text-slate-500">Обратный курс</div>
              <div className="num text-[14px] font-semibold text-slate-100">
                1 {to} = {rateText(to, from, rates)} {from}
              </div>
            </div>
            <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 py-2.5">
              <div className="text-[10.5px] uppercase tracking-wide text-slate-500">
                Динамика {history.length > 1 ? `за ${history.length} точек` : 'история'}
              </div>
              {history.length > 1 ? (
                <div className="flex items-center gap-2">
                  <span className={clsx('num text-[14px] font-semibold', delta >= 0 ? 'text-mint-400' : 'text-rose-400')}>
                    {delta >= 0 ? '+' : '−'}
                    {Math.abs(delta).toFixed(2)} %
                  </span>
                  <div className="w-24">
                    <Sparkline values={history} color={delta >= 0 ? '#10d19a' : '#f43f5e'} height={26} />
                  </div>
                </div>
              ) : (
                <div className="text-[14px] text-slate-500">накопится со временем</div>
              )}
            </div>
          </div>

          {!haveRate && (
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-amberx-500/25 bg-amberx-500/10 px-3 py-2 text-[12px] text-amberx-400">
              <Icon name="AlertTriangle" size={14} />
              Для этой пары нет курса. Задайте его вручную на вкладке «Ручные курсы» или обновите данные.
            </div>
          )}

          {ratesError && (
            <div className="mt-3 flex items-start gap-2 rounded-xl border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-300">
              <Icon name="AlertTriangle" size={14} className="mt-0.5" />
              <span>
                {ratesError}
                {!data.rates && ' — работаем на ручных курсах (1:1)'}
              </span>
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11.5px] text-slate-500">
            <Icon name="Clock" size={13} />
            {data.rates ? (
              <>
                Обновлено: {new Date(data.rates.fetchedAt).toLocaleString('ru-RU')} · дата курса: {fmtDate(data.rates.date, 'd MMMM yyyy')} ·
                источник: <b className="text-slate-300">{PROVIDERS.find((p) => p.id === data.rates?.provider)?.name ?? data.rates.provider}</b>
              </>
            ) : (
              'Курсы ещё не загружены — нажмите «Обновить»'
            )}
          </div>
        </Card>

        {/* ---------------------------- быстрая таблица --------------------------- */}
        <Card>
          <SectionHeader title="Курсы к базовой валюте" subtitle={`База: ${base}`} icon="Coins" />
          <div className="space-y-1">
            {usedCurrencies
              .filter((c) => c !== base)
              .map((c) => {
                const v = convert(1, base, c, rates);
                const known = hasRate(base, c, rates);
                return (
                  <div key={c} className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 transition hover:bg-white/[0.04]">
                    <span className="flex items-center gap-2">
                      <span className="grid h-6 w-6 place-items-center rounded-md bg-white/[0.06] text-[10px] font-bold text-slate-300">
                        {c.slice(0, 2)}
                      </span>
                      <span className="text-[12.5px] text-slate-300">{c}</span>
                    </span>
                    <span className={clsx('num text-[12.5px]', known ? 'font-medium text-slate-100' : 'text-slate-600')}>
                      {known ? v.toLocaleString('ru-RU', { maximumFractionDigits: v < 1 ? 6 : 4 }) : 'нет курса'}
                    </span>
                  </div>
                );
              })}
          </div>
        </Card>
      </div>

      {/* ------------------------------ ручные курсы ------------------------------ */}
      <Card>
        <SectionHeader
          title="Ручные курсы"
          subtitle="Заполните, если нужен фиксированный курс или нет доступа к интернету"
          icon="Pencil"
          right={
            <Segmented
              size="sm"
              value={tab}
              onChange={setTab}
              options={[
                { value: 'convert', label: 'Конвертер' },
                { value: 'table', label: 'Все валюты' },
                { value: 'manual', label: 'Ручные курсы' },
              ]}
            />
          }
        />

        {tab === 'manual' && (
          <div className="overflow-x-auto">
            <table className="table min-w-[520px]">
              <thead>
                <tr>
                  <th>Валюта</th>
                  <th className="w-52">Курс: 1 {base} = </th>
                  <th>Источник</th>
                  <th className="w-32" />
                </tr>
              </thead>
              <tbody>
                {usedCurrencies
                  .filter((c) => c !== base)
                  .map((c) => {
                    const manual = settings.manualRates?.[c];
                    const auto = data.rates?.rates?.[c];
                    return (
                      <tr key={c}>
                        <td className="font-medium text-slate-200">{c}</td>
                        <td>
                          {editingManual === c ? (
                            <AmountInput
                              value={manual}
                              onChange={(v) => setManualRate(c, v)}
                              placeholder={auto ? String(auto) : '0'}
                              className="py-1 text-[12.5px]"
                            />
                          ) : (
                            <span className={clsx('num', manual ? 'text-brand-300' : 'text-slate-400')}>
                              {manual ? manual.toLocaleString('ru-RU', { maximumFractionDigits: 6 }) : '—'}
                            </span>
                          )}
                        </td>
                        <td className="text-[12px] text-slate-500">
                          {manual ? (
                            <Badge tone="brand">вручную</Badge>
                          ) : auto ? (
                            <span className="num">авто: {auto.toLocaleString('ru-RU', { maximumFractionDigits: 6 })}</span>
                          ) : (
                            'нет данных'
                          )}
                        </td>
                        <td>
                          <div className="flex justify-end gap-1">
                            <Button size="sm" variant={editingManual === c ? 'primary' : 'ghost'} onClick={() => setEditingManual(editingManual === c ? null : c)}>
                              {editingManual === c ? 'Готово' : 'Изменить'}
                            </Button>
                            {manual && (
                              <IconButton
                                icon="RotateCcw"
                                size={13}
                                label="Сбросить на автоматический"
                                onClick={() => setManualRate(c, 0)}
                              />
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
            <div className="mt-2 text-[11.5px] text-slate-500">
              Ручной курс имеет приоритет над загруженным. Чтобы вернуть автоматический курс — нажмите «Сбросить».
            </div>
          </div>
        )}

        {tab === 'table' && (
          <div className="overflow-x-auto">
            <table className="table min-w-[520px]">
              <thead>
                <tr>
                  <th>Валюта</th>
                  <th className="text-right">1 {base} =</th>
                  <th className="text-right">1 единица = {base}</th>
                  <th>Статус</th>
                </tr>
              </thead>
              <tbody>
                {CURRENCY_OPTIONS.filter((c) => usedCurrencies.includes(c.code) || c.crypto)
                  .map((c) => {
                    const direct = convert(1, base, c.code, rates);
                    const inverse = convert(1, c.code, base, rates);
                    const known = hasRate(base, c.code, rates);
                    return (
                      <tr key={c.code}>
                        <td>
                          <div className="flex items-center gap-2">
                            <span className="grid h-6 w-6 place-items-center rounded-md bg-white/[0.06] text-[10px] font-bold text-slate-300">
                              {c.symbol}
                            </span>
                            <span className="text-[12.5px] text-slate-200">{c.label}</span>
                          </div>
                        </td>
                        <td className="num text-right">{known ? direct.toLocaleString('ru-RU', { maximumFractionDigits: 6 }) : '—'}</td>
                        <td className="num text-right font-medium">{known ? inverse.toLocaleString('ru-RU', { maximumFractionDigits: 6 }) : '—'}</td>
                        <td>
                          {known ? (
                            <Badge tone="green">актуально</Badge>
                          ) : (
                            <Badge tone="amber">нет курса</Badge>
                          )}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'convert' && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { name: 'ЦБ РФ', note: 'Официальный курс Банка России', icon: 'Landmark' },
              { name: 'ЕЦБ', note: 'Курс Европейского центробанка', icon: 'Building2' },
              { name: 'ExchangeRate API', note: 'Мировые валюты', icon: 'Globe' },
              { name: 'Ручные курсы', note: 'Ваши значения, приоритет выше', icon: 'Pencil' },
            ].map((p) => (
              <div key={p.name} className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
                <div className="flex items-center gap-2 text-[13px] font-medium text-slate-100">
                  <Icon name={p.icon} size={15} className="text-brand-300" />
                  {p.name}
                </div>
                <p className="mt-1 text-[11.5px] text-slate-500">{p.note}</p>
                {p.name === 'ЦБ РФ' && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="mt-2"
                    onClick={async () => {
                      await refreshRates('cbr');
                      toast.info('Запрос к ЦБ РФ выполнен');
                    }}
                  >
                    Обновить из ЦБ РФ
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* ------------------------ калькулятор «сколько это» ---------------------- */}
      <Card>
        <SectionHeader
          title="Быстрый пересчёт"
          subtitle={`Сумма ${fmtMoney(amount, from)} в других валютах`}
          icon="Calculator"
        />
        <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {usedCurrencies.map((c) => (
            <div key={c} className="rounded-xl border border-white/[0.07] bg-white/[0.025] px-3 py-2.5">
              <div className="text-[10.5px] uppercase tracking-wide text-slate-500">{c}</div>
              <div className="num text-[14px] font-semibold text-slate-100">
                {hasRate(from, c, rates) ? fmtMoney(convert(amount, from, c, rates), c, { cents: false, compact: true }) : '—'}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
