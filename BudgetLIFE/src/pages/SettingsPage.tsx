import { useEffect, useMemo, useRef, useState } from 'react';
import clsx from 'clsx';
import { useStore } from '../store/useStore';
import {
  AmountInput,
  Badge,
  Button,
  Card,
  ColorPicker,
  ConfirmDialog,
  Field,
  IconButton,
  IconPicker,
  Input,
  SectionHeader,
  Select,
  Toggle,
} from '../components/ui/primitives';
import { ICON_NAMES, Icon } from '../components/Icon';
import { CURRENCY_OPTIONS, fmtMoney } from '../lib/format';
import { PROVIDERS } from '../lib/rates';
import { deleteBackup, estimateUsage, getBackup, listBackups, saveBackup } from '../store/db';
import { PALETTE } from '../store/defaults';
import { toast } from '../store/useToast';
import { useInstall } from '../hooks/useInstall';
import type { Category } from '../types';

export default function SettingsPage() {
  const data = useStore((s) => s.data);
  const patchSettings = useStore((s) => s.patchSettings);
  const refreshRates = useStore((s) => s.refreshRates);
  const exportState = useStore((s) => s.exportState);
  const importState = useStore((s) => s.importState);
  const loadDemo = useStore((s) => s.loadDemo);
  const resetAll = useStore((s) => s.resetAll);
  const addCategory = useStore((s) => s.addCategory);
  const updateCategory = useStore((s) => s.updateCategory);
  const deleteCategory = useStore((s) => s.deleteCategory);
  const ratesStatus = useStore((s) => s.ratesStatus);
  const lastSavedAt = useStore((s) => s.lastSavedAt);
  const { canInstall, promptInstall, installed } = useInstall();

  const fileRef = useRef<HTMLInputElement>(null);
  const [backups, setBackups] = useState<{ id: number; createdAt: number; label: string }[]>([]);
  const [usage, setUsage] = useState<{ usage?: number; quota?: number }>({});
  const [confirmReset, setConfirmReset] = useState(false);
  const [newCat, setNewCat] = useState<{ name: string; kind: 'expense' | 'income'; color: string; icon: string }>({
    name: '',
    kind: 'expense',
    color: PALETTE[0],
    icon: 'Tag',
  });

  const settings = data.settings;

  const refreshBackups = async () => {
    setBackups(await listBackups());
    setUsage(await estimateUsage());
  };

  useEffect(() => {
    void refreshBackups();
  }, []);

  const download = () => {
    const blob = new Blob([exportState()], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `budgetlife-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success('Файл выгружен', 'Сохраните резервную копию в надёжном месте');
  };

  const upload = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const res = importState(String(reader.result ?? ''));
      if (res.ok) {
        toast.success('Данные загружены');
        void refreshBackups();
      } else {
        toast.error('Ошибка импорта', res.error);
      }
    };
    reader.readAsText(file);
  };

  const counts = useMemo(
    () => ({
      accounts: data.accounts.length,
      incomes: data.incomes.length,
      subscriptions: data.subscriptions.length,
      credits: data.credits.length,
      transactions: data.transactions.length,
      categories: data.categories.length,
    }),
    [data],
  );

  return (
    <div className="space-y-4">
      {/* -------------------------------- основные -------------------------------- */}
      <Card>
        <SectionHeader title="Основные настройки" subtitle="Валюта, периоды, приватность" icon="Settings" />
        <div className="grid gap-4 lg:grid-cols-2">
          <Field label="Базовая валюта" hint="В ней показываются все сводные суммы и графики">
            <Select
              value={settings.baseCurrency}
              onChange={(e) => {
                patchSettings({ baseCurrency: e.target.value });
                void refreshRates();
              }}
            >
              {CURRENCY_OPTIONS.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code} — {c.label}
                </option>
              ))}
            </Select>
          </Field>

          <Field
            label="Начало финансового месяца"
            hint="Например, 5-е, если бюджет живёт от аванса до аванса"
          >
            <Input
              type="number"
              min={1}
              max={28}
              value={settings.monthStartDay}
              onChange={(e) => patchSettings({ monthStartDay: Math.min(28, Math.max(1, Number(e.target.value) || 1)) })}
            />
          </Field>

          <Field label="Первый день недели в календаре">
            <Select
              value={String(settings.firstDayOfWeek)}
              onChange={(e) => patchSettings({ firstDayOfWeek: Number(e.target.value) as 0 | 1 | 7 })}
            >
              <option value="1">Понедельник</option>
              <option value="0">Воскресенье</option>
              <option value="7">Суббота</option>
            </Select>
          </Field>

          <div className="space-y-2">
            <Toggle
              checked={settings.hideBalances}
              onChange={(v) => patchSettings({ hideBalances: v })}
              label="Скрывать суммы"
              hint="Удобно, если заглядывают коллеги"
            />
            <Toggle
              checked={settings.showCents}
              onChange={(v) => patchSettings({ showCents: v })}
              label="Показывать копейки"
            />
          </div>
        </div>
      </Card>

      {/* --------------------------------- курсы ---------------------------------- */}
      <Card>
        <SectionHeader
          title="Курсы валют"
          subtitle="Источники подключаются прямо из браузера"
          icon="ArrowLeftRight"
          right={
            <Button
              size="sm"
              variant="ghost"
              icon="RefreshCw"
              onClick={async () => {
                await refreshRates();
                const st = useStore.getState();
                if (st.ratesStatus === 'error') toast.error('Не удалось обновить курсы', st.ratesError);
                else toast.success('Курсы обновлены');
              }}
              className={clsx(ratesStatus === 'loading' && 'animate-pulse-soft')}
            >
              Обновить сейчас
            </Button>
          }
        />

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {PROVIDERS.map((p) => {
            const active = data.rates?.provider === p.id;
            return (
              <div
                key={p.id}
                className={clsx(
                  'rounded-xl border p-3 transition',
                  active ? 'border-mint-500/40 bg-mint-500/[0.07]' : 'border-white/[0.07] bg-white/[0.02]',
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium text-slate-100">{p.name}</span>
                  {active ? <Badge tone="green">используется</Badge> : <Badge tone="slate">резерв</Badge>}
                </div>
                <p className="mt-1 text-[11.5px] text-slate-500">{p.note}</p>
              </div>
            );
          })}
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2">
            <div className="text-[10.5px] uppercase tracking-wide text-slate-500">Статус</div>
            <div className="text-[13px] text-slate-200">
              {ratesStatus === 'loading'
                ? 'обновление…'
                : data.rates
                  ? 'курсы загружены'
                  : 'курсы не загружены'}
            </div>
          </div>
          <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2">
            <div className="text-[10.5px] uppercase tracking-wide text-slate-500">Дата курса</div>
            <div className="text-[13px] text-slate-200">
              {data.rates ? new Date(data.rates.date).toLocaleDateString('ru-RU') : '—'}
            </div>
          </div>
          <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2">
            <div className="text-[10.5px] uppercase tracking-wide text-slate-500">Обновлено</div>
            <div className="text-[13px] text-slate-200">
              {data.rates ? new Date(data.rates.fetchedAt).toLocaleString('ru-RU') : '—'}
            </div>
          </div>
        </div>
      </Card>

      {/* ------------------------------- категории -------------------------------- */}
      <Card>
        <SectionHeader
          title="Категории"
          subtitle="Цвета, иконки и месячные лимиты"
          icon="Tag"
        />

        <div className="mb-4 rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
          <div className="mb-2 text-[12.5px] font-medium text-slate-200">Новая категория</div>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Название" className="min-w-[180px] flex-1">
              <Input value={newCat.name} onChange={(e) => setNewCat({ ...newCat, name: e.target.value })} placeholder="Например: Питомцы" />
            </Field>
            <Field label="Тип" className="w-36">
              <Select value={newCat.kind} onChange={(e) => setNewCat({ ...newCat, kind: e.target.value as 'expense' | 'income' })}>
                <option value="expense">Расход</option>
                <option value="income">Доход</option>
              </Select>
            </Field>
            <div>
              <div className="label">Цвет</div>
              <ColorPicker value={newCat.color} onChange={(c) => setNewCat({ ...newCat, color: c })} colors={PALETTE.slice(0, 8)} />
            </div>
            <Button
              variant="primary"
              icon="Plus"
              onClick={() => {
                if (!newCat.name.trim()) return;
                addCategory({ name: newCat.name.trim(), kind: newCat.kind, color: newCat.color, icon: newCat.icon });
                setNewCat({ ...newCat, name: '' });
                toast.success('Категория добавлена');
              }}
            >
              Добавить
            </Button>
          </div>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          {(['expense', 'income'] as const).map((kind) => (
            <div key={kind}>
              <div className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-slate-400">
                {kind === 'expense' ? 'Расходы' : 'Доходы'}
              </div>
              <div className="space-y-1">
                {data.categories
                  .filter((c) => c.kind === kind)
                  .sort((a, b) => a.order - b.order)
                  .map((c) => (
                    <CategoryRow
                      key={c.id}
                      category={c}
                      onSave={(patch) => updateCategory(c.id, patch)}
                      onDelete={() => deleteCategory(c.id)}
                    />
                  ))}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* --------------------------------- данные ---------------------------------- */}
      <Card>
        <SectionHeader
          title="Данные и резервные копии"
          subtitle="Всё хранится локально в браузере (IndexedDB)"
          icon="Database"
        />

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatBox label="Счетов" value={counts.accounts} />
          <StatBox label="Доходов" value={counts.incomes} />
          <StatBox label="Подписок" value={counts.subscriptions} />
          <StatBox label="Кредитов" value={counts.credits} />
          <StatBox label="Операций" value={counts.transactions} />
          <StatBox label="Категорий" value={counts.categories} />
          <StatBox
            label="Занято в хранилище"
            value={usage.usage ? `${(usage.usage / 1024 / 1024).toFixed(2)} МБ` : '—'}
          />
          <StatBox
            label="Сохранено"
            value={lastSavedAt ? new Date(lastSavedAt).toLocaleTimeString('ru-RU') : '—'}
          />
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="primary" icon="Download" onClick={download}>
            Экспорт в JSON
          </Button>
          <Button variant="ghost" icon="Upload" onClick={() => fileRef.current?.click()}>
            Импорт из JSON
          </Button>
          <Button
            variant="ghost"
            icon="Save"
            onClick={async () => {
              await saveBackup('Ручная копия', useStore.getState().data);
              await refreshBackups();
              toast.success('Резервная копия создана');
            }}
          >
            Создать копию
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) upload(f);
              e.target.value = '';
            }}
          />
        </div>

        {backups.length > 0 && (
          <div className="mt-4">
            <div className="mb-2 text-[12.5px] font-medium text-slate-300">Резервные копии</div>
            <div className="space-y-1">
              {backups.map((b) => (
                <div key={b.id} className="flex items-center justify-between gap-2 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2">
                  <span className="flex items-center gap-2 text-[12.5px] text-slate-300">
                    <Icon name="FileText" size={14} className="text-slate-500" />
                    {b.label}
                    <span className="num text-[11px] text-slate-500">
                      {new Date(b.createdAt).toLocaleString('ru-RU')}
                    </span>
                  </span>
                  <span className="flex gap-1">
                    <Button
                      size="sm"
                      variant="ghost"
                      icon="RotateCcw"
                      onClick={async () => {
                        const snapshot = await getBackup(b.id);
                        if (snapshot) {
                          const res = importState(JSON.stringify(snapshot));
                          toast[res.ok ? 'success' : 'error'](res.ok ? 'Копия восстановлена' : 'Ошибка', res.ok ? undefined : res.error);
                        }
                      }}
                    >
                      Восстановить
                    </Button>
                    <IconButton
                      icon="Trash2"
                      size={13}
                      label="Удалить копию"
                      onClick={async () => {
                        await deleteBackup(b.id);
                        await refreshBackups();
                      }}
                      className="hover:text-rose-400"
                    />
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      {/* ------------------------------- приложение -------------------------------- */}
      <Card>
        <SectionHeader title="Приложение" subtitle="Установка, демо-данные, сброс" icon="Sparkles" />

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
            <div className="flex items-center gap-2 text-[13px] font-medium text-slate-100">
              <Icon name="Download" size={15} className="text-brand-300" />
              Установка PWA
            </div>
            <p className="mt-1 text-[11.5px] leading-relaxed text-slate-500">
              Установите приложение, чтобы запускать его в отдельном окне без адресной строки — с ярлыка, из трея или
              через поиск. Работает и офлайн.
            </p>
            {canInstall ? (
              <Button size="sm" variant="primary" className="mt-2" icon="Download" onClick={() => void promptInstall()}>
                Установить
              </Button>
            ) : (
              <div className="mt-2 text-[11.5px] text-slate-500">
                {installed
                  ? 'Приложение уже установлено'
                  : 'Откройте меню браузера → «Установить приложение» (значок в адресной строке)'}
              </div>
            )}
          </div>

          <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3">
            <div className="flex items-center gap-2 text-[13px] font-medium text-slate-100">
              <Icon name="Sparkles" size={15} className="text-amberx-400" />
              Демо-данные
            </div>
            <p className="mt-1 text-[11.5px] leading-relaxed text-slate-500">
              Полный пример: счета с процентами, зарплата с авансом, сдельный доход, подписки, кредиты и год истории.
              Текущие данные будут заменены (старая копия сохранится).
            </p>
            <Button
              size="sm"
              variant="ghost"
              className="mt-2"
              icon="Sparkles"
              onClick={() => {
                loadDemo();
                toast.success('Демо-данные загружены');
              }}
            >
              Загрузить демо
            </Button>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-500/20 bg-rose-500/[0.05] p-3">
          <div>
            <div className="text-[13px] font-medium text-slate-100">Опасная зона</div>
            <p className="text-[11.5px] text-slate-500">Полностью очистить все данные и начать заново</p>
          </div>
          <Button variant="danger" icon="Trash2" onClick={() => setConfirmReset(true)}>
            Удалить все данные
          </Button>
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-3 text-[11.5px] text-slate-500">
          <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2">
            <b className="text-slate-300">Ctrl/⌘ + K</b> — быстрая операция
          </div>
          <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2">
            Двойной клик по дню в календаре — новая операция
          </div>
          <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2">
            Клик по кружку слева от события — отметить фактом
          </div>
        </div>
      </Card>

      <ConfirmDialog
        open={confirmReset}
        onClose={() => setConfirmReset(false)}
        onConfirm={() => {
          resetAll();
          setConfirmReset(false);
          toast.success('Все данные удалены');
        }}
        title="Удалить все данные?"
        description="Счета, доходы, подписки, кредиты и вся история операций будут стёрты. Сначала сделайте экспорт, если данные нужны."
      />
    </div>
  );
}

function StatBox({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2">
      <div className="text-[10.5px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="num text-[15px] font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function CategoryRow({
  category,
  onSave,
  onDelete,
}: {
  category: Category;
  onSave: (patch: Partial<Category>) => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.02]">
      <div className="flex items-center gap-2 px-2.5 py-2">
        <span
          className="grid h-7 w-7 shrink-0 place-items-center rounded-lg"
          style={{ color: category.color, background: `${category.color}22` }}
        >
          <Icon name={category.icon} size={14} />
        </span>
        <input
          value={category.name}
          onChange={(e) => onSave({ name: e.target.value })}
          className="min-w-0 flex-1 bg-transparent text-[13px] text-slate-200 outline-none"
        />
        {category.kind === 'expense' && category.budgetMonthly ? (
          <span className="num shrink-0 text-[11px] text-slate-500">
            лимит {fmtMoney(category.budgetMonthly, 'RUB', { cents: false, compact: true })}
          </span>
        ) : null}
        <IconButton icon="SlidersHorizontal" size={13} label="Настроить" onClick={() => setOpen((v) => !v)} />
        <IconButton icon="Trash2" size={13} label="Удалить" onClick={onDelete} className="hover:text-rose-400" />
      </div>
      {open && (
        <div className="space-y-3 border-t border-white/[0.06] p-3 animate-slide-up">
          <div>
            <div className="label">Цвет</div>
            <ColorPicker value={category.color} onChange={(c) => onSave({ color: c })} colors={PALETTE} />
          </div>
          <div>
            <div className="label">Иконка</div>
            <IconPicker value={category.icon} onChange={(i) => onSave({ icon: i })} names={ICON_NAMES} color={category.color} />
          </div>
          {category.kind === 'expense' && (
            <Field label="Лимит на месяц">
              <AmountInput
                value={category.budgetMonthly}
                onChange={(v) => onSave({ budgetMonthly: v || undefined })}
                placeholder="не задан"
                suffix="₽"
              />
            </Field>
          )}
        </div>
      )}
    </div>
  );
}
