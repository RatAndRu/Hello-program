import {
  useEffect,
  useRef,
  useId,
  Children,
  cloneElement,
  isValidElement,
  type ReactNode,
  type ReactElement,
} from "react";
import {
  X,
  Plus,
  Trash2,
  ChevronDown,
  Heart,
  Zap,
  Coins,
  Star,
  Shield,
  Sword,
  Sparkles,
  BookOpen,
  Compass,
  Gift,
} from "lucide-react";
import type { World, Action, Condition, StatDef, CustomButton } from "../model";
import { uid } from "../model";

export const statIcons = {
  heart: Heart,
  zap: Zap,
  coins: Coins,
  star: Star,
  shield: Shield,
  sword: Sword,
};
export const buttonIcons = {
  sparkles: Sparkles,
  book: BookOpen,
  heart: Heart,
  compass: Compass,
  gift: Gift,
};
export function StatIcon({
  stat,
  size = 16,
}: {
  stat: StatDef;
  size?: number;
}) {
  const Icon = statIcons[stat.icon] || Star;
  return <Icon size={size} />;
}
export function Field({
  label,
  hint,
  children,
  wide = false,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const id = useId();
  return (
    <div className={`field ${wide ? "wide" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {Children.map(children, (child) =>
        isValidElement(child)
          ? cloneElement(child as ReactElement<Record<string, unknown>>, {
              id,
              "aria-label": label,
            })
          : child,
      )}
      {hint && <small>{hint}</small>}
    </div>
  );
}
export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className="toggle-label">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="toggle-track" />
      <span>{label}</span>
    </label>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    const handle = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close.current();
      }
      if (e.key === "Tab") {
        const list = ref.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
        );
        if (!list?.length) return;
        const first = list[0],
          last = list[list.length - 1];
        if (
          e.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === ref.current)
        ) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handle);
    return () => {
      document.removeEventListener("keydown", handle);
      document.body.style.overflow = oldOverflow;
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`modal ${wide ? "modal-wide" : ""}`}
      >
        <header className="modal-head">
          <h2>{title}</h2>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Закрыть окно"
          >
            <X size={20} />
          </button>
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}
export function Empty({
  icon,
  title,
  text,
  action,
}: {
  icon?: ReactNode;
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon || <Sparkles size={28} />}</div>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}
export function NumberInput({
  value,
  onChange,
  min = 0,
  max = 999999,
  step = 1,
  ...rest
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  id?: string;
  "aria-label"?: string;
}) {
  return (
    <input
      {...rest}
      type="number"
      value={value}
      min={min}
      max={max}
      step={step}
      onChange={(e) =>
        onChange(Math.max(min, Math.min(max, Number(e.target.value) || 0)))
      }
    />
  );
}
export function AssetSelect({
  world,
  value,
  onChange,
  label = "Изображение",
}: {
  world: World;
  value?: string;
  onChange: (v?: string) => void;
  label?: string;
}) {
  return (
    <Field label={label}>
      <select
        value={value || ""}
        onChange={(e) => onChange(e.target.value || undefined)}
      >
        <option value="">Встроенная графика</option>
        {world.assets.map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function ActionEditor({
  world,
  actions,
  onChange,
  compact = false,
}: {
  world: World;
  actions: Action[];
  onChange: (a: Action[]) => void;
  compact?: boolean;
}) {
  const update = (i: number, a: Action) =>
    onChange(actions.map((old, j) => (i === j ? a : old)));
  const add = () => {
    if (actions.length < 20)
      onChange([...actions, { type: "message", text: "Новое открытие!" }]);
  };
  return (
    <div className={`action-editor ${compact ? "compact" : ""}`}>
      {actions.map((a, i) => (
        <div className="action-row" key={i}>
          <span className="action-number">{i + 1}</span>
          <div className="action-fields">
            <select
              aria-label={`Действие ${i + 1}: тип`}
              value={a.type}
              onChange={(e) => {
                const type = e.target.value;
                const next: Action =
                  type === "stat"
                    ? {
                        type,
                        stat: world.stats[0]?.id || "",
                        op: "add",
                        value: 1,
                      }
                    : type === "item"
                      ? {
                          type,
                          item: world.items[0]?.id || "",
                          op: "give",
                          count: 1,
                        }
                      : type === "window"
                        ? { type, window: world.windows[0]?.id || "" }
                        : type === "flag"
                          ? { type, flag: "opened", value: true }
                          : type === "quest"
                            ? {
                                type,
                                quest: world.quests[0]?.id || "",
                                status: "active",
                              }
                            : type === "teleport"
                              ? { type, x: 4, y: 7 }
                              : { type: "message", text: "" };
                update(i, next);
              }}
            >
              <option value="message">Показать сообщение</option>
              <option value="stat">Изменить характеристику</option>
              <option value="item">Выдать / забрать предмет</option>
              <option value="window">Открыть окно</option>
              <option value="quest">Изменить задание</option>
              <option value="flag">Запомнить событие</option>
              <option value="teleport">Переместить героя</option>
            </select>
            {a.type === "message" && (
              <input
                aria-label="Текст сообщения"
                value={a.text}
                maxLength={2000}
                placeholder="Что увидит игрок?"
                onChange={(e) => update(i, { ...a, text: e.target.value })}
              />
            )}
            {a.type === "stat" && (
              <div className="inline-fields">
                <select
                  aria-label="Характеристика"
                  value={a.stat}
                  onChange={(e) => update(i, { ...a, stat: e.target.value })}
                >
                  {world.stats.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Операция"
                  value={a.op}
                  onChange={(e) =>
                    update(i, { ...a, op: e.target.value as "add" | "set" })
                  }
                >
                  <option value="add">Изменить на</option>
                  <option value="set">Установить</option>
                </select>
                <NumberInput
                  value={a.value}
                  min={-999999}
                  onChange={(value) => update(i, { ...a, value })}
                />
              </div>
            )}
            {a.type === "item" && (
              <div className="inline-fields">
                <select
                  aria-label="Предмет"
                  value={a.item}
                  onChange={(e) => update(i, { ...a, item: e.target.value })}
                >
                  {world.items.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Операция с предметом"
                  value={a.op}
                  onChange={(e) =>
                    update(i, { ...a, op: e.target.value as "give" | "take" })
                  }
                >
                  <option value="give">Выдать</option>
                  <option value="take">Забрать</option>
                </select>
                <NumberInput
                  value={a.count}
                  min={1}
                  max={999}
                  onChange={(count) => update(i, { ...a, count })}
                />
              </div>
            )}
            {a.type === "window" && (
              <select
                aria-label="Окно"
                value={a.window}
                onChange={(e) => update(i, { ...a, window: e.target.value })}
              >
                <option value="">Выбери окно</option>
                {world.windows.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.title}
                  </option>
                ))}
              </select>
            )}
            {a.type === "quest" && (
              <div className="inline-fields">
                <select
                  aria-label="Задание"
                  value={a.quest}
                  onChange={(e) => update(i, { ...a, quest: e.target.value })}
                >
                  {world.quests.map((q) => (
                    <option key={q.id} value={q.id}>
                      {q.name}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Состояние задания"
                  value={a.status}
                  onChange={(e) =>
                    update(i, { ...a, status: e.target.value as "active" })
                  }
                >
                  <option value="available">Можно получить</option>
                  <option value="active">В процессе</option>
                  <option value="completed">Выполнено</option>
                </select>
              </div>
            )}
            {a.type === "flag" && (
              <div className="inline-fields">
                <input
                  aria-label="Название события"
                  value={a.flag}
                  placeholder="например, secret_found"
                  onChange={(e) =>
                    update(i, {
                      ...a,
                      flag: e.target.value.replace(/[^a-zA-Z0-9_-]/g, ""),
                    })
                  }
                />
                <Toggle
                  checked={a.value}
                  onChange={(value) => update(i, { ...a, value })}
                  label="Произошло"
                />
              </div>
            )}
            {a.type === "teleport" && (
              <div className="inline-fields">
                <Field label="X">
                  <NumberInput
                    value={a.x}
                    min={1}
                    max={16}
                    onChange={(x) => update(i, { ...a, x })}
                  />
                </Field>
                <Field label="Y">
                  <NumberInput
                    value={a.y}
                    min={1}
                    max={10}
                    onChange={(y) => update(i, { ...a, y })}
                  />
                </Field>
              </div>
            )}
          </div>
          <button
            className="icon-button danger-hover"
            aria-label={`Удалить действие ${i + 1}`}
            onClick={() => onChange(actions.filter((_, j) => i !== j))}
          >
            <Trash2 size={15} />
          </button>
        </div>
      ))}
      <button
        className="text-button"
        onClick={add}
        disabled={actions.length >= 20}
      >
        <Plus size={15} /> Добавить действие
      </button>
    </div>
  );
}
export function ConditionEditor({
  world,
  conditions,
  onChange,
}: {
  world: World;
  conditions: Condition[];
  onChange: (c: Condition[]) => void;
}) {
  const update = (i: number, c: Condition) =>
    onChange(conditions.map((old, j) => (i === j ? c : old)));
  return (
    <div className="condition-editor">
      {conditions.map((c, i) => (
        <div className="condition-row" key={i}>
          <span className="condition-label">{i ? "И" : "ЕСЛИ"}</span>
          <div className="action-fields">
            <select
              aria-label="Тип условия"
              value={c.type}
              onChange={(e) =>
                update(
                  i,
                  e.target.value === "stat"
                    ? {
                        type: "stat",
                        stat: world.stats[0]?.id || "",
                        op: "gte",
                        value: 1,
                      }
                    : e.target.value === "item"
                      ? {
                          type: "item",
                          item: world.items[0]?.id || "",
                          count: 1,
                        }
                      : e.target.value === "quest"
                        ? {
                            type: "quest",
                            quest: world.quests[0]?.id || "",
                            status: "active",
                          }
                        : { type: "flag", flag: "opened", value: true },
                )
              }
            >
              <option value="stat">Характеристика</option>
              <option value="item">Предмет в рюкзаке</option>
              <option value="quest">Состояние задания</option>
              <option value="flag">Событие произошло</option>
            </select>
            {c.type === "stat" && (
              <div className="inline-fields">
                <select
                  aria-label="Характеристика условия"
                  value={c.stat}
                  onChange={(e) => update(i, { ...c, stat: e.target.value })}
                >
                  {world.stats.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Сравнение"
                  value={c.op}
                  onChange={(e) =>
                    update(i, { ...c, op: e.target.value as "gte" })
                  }
                >
                  <option value="gte">Не меньше</option>
                  <option value="lte">Не больше</option>
                  <option value="eq">Равно</option>
                </select>
                <NumberInput
                  value={c.value}
                  min={-999999}
                  onChange={(value) => update(i, { ...c, value })}
                />
              </div>
            )}
            {c.type === "item" && (
              <div className="inline-fields">
                <select
                  aria-label="Предмет условия"
                  value={c.item}
                  onChange={(e) => update(i, { ...c, item: e.target.value })}
                >
                  {world.items.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <NumberInput
                  value={c.count}
                  min={1}
                  max={999}
                  onChange={(count) => update(i, { ...c, count })}
                />
              </div>
            )}
            {c.type === "quest" && (
              <div className="inline-fields">
                <select
                  aria-label="Задание условия"
                  value={c.quest}
                  onChange={(e) => update(i, { ...c, quest: e.target.value })}
                >
                  {world.quests.map((q) => (
                    <option key={q.id} value={q.id}>
                      {q.name}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Состояние"
                  value={c.status}
                  onChange={(e) =>
                    update(i, { ...c, status: e.target.value as "active" })
                  }
                >
                  <option value="available">Можно получить</option>
                  <option value="active">В процессе</option>
                  <option value="completed">Выполнено</option>
                </select>
              </div>
            )}
            {c.type === "flag" && (
              <div className="inline-fields">
                <input
                  aria-label="Событие условия"
                  value={c.flag}
                  onChange={(e) =>
                    update(i, {
                      ...c,
                      flag: e.target.value.replace(/[^a-zA-Z0-9_-]/g, ""),
                    })
                  }
                />
                <Toggle
                  label="Произошло"
                  checked={c.value}
                  onChange={(value) => update(i, { ...c, value })}
                />
              </div>
            )}
          </div>
          <button
            className="icon-button danger-hover"
            aria-label="Удалить условие"
            onClick={() => onChange(conditions.filter((_, j) => j !== i))}
          >
            <Trash2 size={15} />
          </button>
        </div>
      ))}
      <button
        className="text-button"
        disabled={conditions.length >= 10}
        onClick={() =>
          onChange([
            ...conditions,
            {
              type: "stat",
              stat: world.stats[0]?.id || "",
              op: "gte",
              value: 1,
            },
          ])
        }
      >
        <Plus size={15} /> Добавить условие
      </button>
    </div>
  );
}
export function ButtonEditor({
  world,
  button,
  onChange,
}: {
  world: World;
  button: CustomButton;
  onChange: (b: CustomButton) => void;
}) {
  return (
    <div className="button-editor">
      <div className="form-grid">
        <Field label="Название кнопки">
          <input
            value={button.label}
            maxLength={60}
            onChange={(e) => onChange({ ...button, label: e.target.value })}
          />
        </Field>
        <Field label="Значок">
          <select
            value={button.icon}
            onChange={(e) =>
              onChange({
                ...button,
                icon: e.target.value as CustomButton["icon"],
              })
            }
          >
            <option value="sparkles">Искра</option>
            <option value="book">Книга</option>
            <option value="heart">Сердце</option>
            <option value="compass">Компас</option>
            <option value="gift">Подарок</option>
          </select>
        </Field>
      </div>
      <div className="subsection-title">
        <ChevronDown size={15} /> Что делает кнопка
      </div>
      <ActionEditor
        world={world}
        actions={button.actions}
        onChange={(actions) => onChange({ ...button, actions })}
        compact
      />
      <p className="muted small">
        Кнопка выполняет действия по порядку. Чтобы связать её с правилом,
        выбери событие «Нажатие кнопки» в разделе «Правила».
      </p>
    </div>
  );
}
