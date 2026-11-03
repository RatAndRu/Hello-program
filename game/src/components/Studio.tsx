import { useRef, useState } from "react";
import {
  Globe2,
  Users,
  Gem,
  ChartNoAxesCombined,
  ScrollText,
  Workflow,
  PanelsTopLeft,
  ImagePlus,
  History,
  Plus,
  ArrowLeft,
  Check,
  FlaskConical,
  Undo2,
  Redo2,
  Copy,
  Trash2,
  MapPin,
  Upload,
  Download,
  Save,
  Sparkles,
  ChevronRight,
  Settings2,
  Info,
  RotateCcw,
  Layers,
  MousePointer2,
  Palette,
} from "lucide-react";
import {
  type World,
  type Entity,
  type ItemDef,
  type StatDef,
  type Quest,
  type Rule,
  type CustomWindow,
  type Snapshot,
  type SpriteName,
  uid,
  clone,
  spriteNames,
  spriteLabels,
  kindLabels,
  createState,
} from "../model";
import { validateWorld } from "../engine";
import { downloadWorld, readImage } from "../storage";
import { Sprite } from "./Sprite";
import { GameMap } from "./GameMap";
import {
  Field,
  NumberInput,
  Toggle,
  AssetSelect,
  ActionEditor,
  ConditionEditor,
  ButtonEditor,
  Empty,
  StatIcon,
} from "./UI";

export type StudioSection =
  | "world"
  | "entities"
  | "items"
  | "stats"
  | "quests"
  | "rules"
  | "interface"
  | "graphics"
  | "history";
const sections = [
  { id: "world", label: "Мир и карта", icon: Globe2 },
  { id: "entities", label: "Персонажи и объекты", icon: Users },
  { id: "items", label: "Предметы", icon: Gem },
  { id: "stats", label: "Характеристики", icon: ChartNoAxesCombined },
  { id: "quests", label: "Задания", icon: ScrollText },
  { id: "rules", label: "Правила", icon: Workflow },
  { id: "interface", label: "Кнопки и окна", icon: PanelsTopLeft },
  { id: "graphics", label: "Графика", icon: ImagePlus },
  { id: "history", label: "История и копии", icon: History },
] as const;
interface Props {
  world: World;
  onChange: (w: World) => void;
  onBack: () => void;
  onTest: () => void;
  onPublish: () => void;
  onDiscard: () => void;
  dirty: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  snapshots: Snapshot[];
  onSnapshot: (label: string) => void;
  onRestore: (s: Snapshot) => void;
  onExport: () => void;
  notify: (s: string) => void;
  section: StudioSection;
  setSection: (s: StudioSection) => void;
}
export function Studio(props: Props) {
  const { world, onChange, section, setSection } = props;
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [placing, setPlacing] = useState(false);
  const [filter, setFilter] = useState("all");
  const [interfaceTab, setInterfaceTab] = useState<"buttons" | "windows">(
    "buttons",
  );
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const backgroundRef = useRef<HTMLInputElement>(null);
  const errors = validateWorld(world);
  const update = (patch: Partial<World>) => onChange({ ...world, ...patch });
  const asset = (id?: string) => world.assets.find((a) => a.id === id)?.data;
  const select = (id: string, target: StudioSection = section) =>
    setSelected((s) => ({ ...s, [target]: id }));
  const go = (s: StudioSection) => {
    setSection(s);
    setFilter("all");
    setPlacing(false);
  };
  const add = (type: StudioSection) => {
    const id = uid(type.slice(0, 3));
    if (type === "entities") {
      const kind = filter === "all" ? "npc" : (filter as Entity["kind"]);
      const e: Entity = {
        id,
        name: kind === "npc" ? "Новый персонаж" : "Новый объект",
        kind,
        x: 6,
        y: 7,
        sprite:
          kind === "npc"
            ? "gardener"
            : kind === "enemy"
              ? "slime"
              : kind === "chest"
                ? "chest"
                : "flower",
        solid: kind !== "item",
        dialogue: "Привет, хранитель! У этого острова ещё много тайн.",
        stats: kind === "enemy" ? { hp: 25, attack: 6, defense: 1 } : {},
      };
      if (kind === "item") e.itemId = world.items[0]?.id;
      update({ entities: [...world.entities, e] });
      setPlacing(true);
    } else if (type === "items")
      update({
        items: [
          ...world.items,
          {
            id,
            name: "Новый предмет",
            description: "Расскажи историю этого предмета.",
            sprite: "coin",
            kind: "material",
            actions: [],
          },
        ],
      });
    else if (type === "stats")
      update({
        stats: [
          ...world.stats,
          {
            id,
            name: "Новая характеристика",
            initial: 0,
            min: 0,
            max: 100,
            color: "#8b9e77",
            icon: "star",
            visible: true,
          },
        ],
      });
    else if (type === "quests") {
      if (!world.items.length) {
        props.notify("Сначала создай предмет для задания.");
        return;
      }
      update({
        quests: [
          ...world.quests,
          {
            id,
            name: "Новое задание",
            description: "Что нужно сделать герою?",
            itemId: world.items[0].id,
            count: 3,
            coins: 10,
            xp: 15,
          },
        ],
      });
    } else if (type === "rules")
      update({
        rules: [
          ...world.rules,
          {
            id,
            name: "Новое правило",
            enabled: true,
            trigger: { type: "interact", target: world.entities[0]?.id || "*" },
            conditions: [],
            actions: [
              { type: "message", text: "Мир отреагировал на твоё действие!" },
            ],
          },
        ],
      });
    else if (type === "interface") {
      if (interfaceTab === "buttons")
        update({
          buttons: [
            ...world.buttons,
            {
              id,
              label: "Новая кнопка",
              icon: "sparkles",
              actions: [{ type: "message", text: "Кнопка работает!" }],
            },
          ],
        });
      else
        update({
          windows: [
            ...world.windows,
            {
              id,
              title: "Новое окно",
              text: "Здесь начинается новая история.",
              stats: [],
              buttons: [],
            },
          ],
        });
    }
    select(id);
  };
  const remove = (type: keyof World, id: string) => {
    if (
      type === "stats" &&
      ["hp", "energy", "coins", "xp", "attack", "defense"].includes(id)
    ) {
      props.notify(
        "Базовую характеристику нельзя удалить, но можно скрыть из карточки героя.",
      );
      return;
    }
    const arrays: Record<string, string> = {
      entities:
        "Объект будет удалён. Связанные правила нужно будет исправить перед публикацией.",
      items: "Предмет будет удалён из определений мира.",
      stats: "Характеристика будет удалена.",
      quests: "Задание будет удалено.",
      rules: "Правило будет удалено.",
      buttons: "Кнопка будет удалена.",
      windows: "Окно будет удалено.",
      assets:
        "Изображение будет удалено. Сначала замени его у использующих объектов.",
    };
    if (
      confirm(
        `${arrays[type as string] || "Удалить элемент?"} Это изменение пока можно отменить.`,
      )
    ) {
      update({
        [type]: (world[type] as { id: string }[]).filter((v) => v.id !== id),
      } as Partial<World>);
      setSelected((s) => ({ ...s, [section]: "" }));
    }
  };
  const duplicateEntity = (e: Entity) => {
    const copy = {
      ...clone(e),
      id: uid("ent"),
      name: `${e.name} (копия)`,
      x: Math.min(16, e.x + 1),
    };
    update({ entities: [...world.entities, copy] });
    select(copy.id);
    setPlacing(true);
  };
  const upload = async (files: FileList | null, background = false) => {
    if (!files?.length) return;
    if (
      world.assets.length + Math.min(files.length, background ? 1 : 10) >
      30
    ) {
      props.notify("В мире может быть до 30 изображений.");
      return;
    }
    setUploading(true);
    try {
      const added = [];
      for (const file of Array.from(files).slice(0, background ? 1 : 10)) {
        const data = await readImage(file, background);
        added.push({ id: uid("img"), name: file.name.slice(0, 100), data });
      }
      if (
        world.assets.reduce((sum, a) => sum + a.data.length, 0) +
          added.reduce((sum, a) => sum + a.data.length, 0) >
        12000000
      )
        throw new Error(
          "Общий объём графики достигнут. Удали ненужные изображения или используй файлы меньшего размера.",
        );
      onChange({
        ...world,
        assets: [...world.assets, ...added],
        ...(background ? { backgroundId: added[0].id } : {}),
      });
      props.notify(
        background
          ? "Фон обновлён в черновике."
          : "Графика добавлена. Теперь выбери её у персонажа, предмета или окна.",
      );
    } catch (e) {
      props.notify(
        e instanceof Error ? e.message : "Не удалось загрузить изображение.",
      );
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };
  const renderList = (
    rows: {
      id: string;
      name: string;
      subtitle?: string;
      sprite?: SpriteName;
      assetId?: string;
    }[],
  ) => (
    <div className="object-list">
      {rows
        .filter(
          (r) =>
            filter === "all" ||
            world.entities.find((e) => e.id === r.id)?.kind === filter,
        )
        .map((r) => (
          <button
            key={r.id}
            className={`object-list-row ${selected[section] === r.id ? "selected" : ""}`}
            onClick={() => {
              select(r.id);
              if (section === "entities") setPlacing(true);
            }}
          >
            {r.sprite ? (
              <Sprite name={r.sprite} src={asset(r.assetId)} />
            ) : (
              <span className="list-letter">{r.name.slice(0, 1)}</span>
            )}
            <span>
              <strong>{r.name || "Без названия"}</strong>
              <small>{r.subtitle || "Настроить"}</small>
            </span>
            <ChevronRight size={15} />
          </button>
        ))}
      {!rows.length && (
        <p className="list-empty">Пока пусто. Создай первый элемент.</p>
      )}
    </div>
  );
  const entity = world.entities.find((e) => e.id === selected.entities);
  const item = world.items.find((e) => e.id === selected.items);
  const stat = world.stats.find((e) => e.id === selected.stats);
  const quest = world.quests.find((e) => e.id === selected.quests);
  const rule = world.rules.find((e) => e.id === selected.rules);
  const panel = world.windows.find((e) => e.id === selected.interface);
  const button = world.buttons.find((e) => e.id === selected.interface);
  const patchEntity = (patch: Partial<Entity>) =>
    entity &&
    update({
      entities: world.entities.map((e) =>
        e.id === entity.id ? { ...e, ...patch } : e,
      ),
    });
  const currentSection = sections.find((s) => s.id === section)!;
  const triggerOptions = rule
    ? rule.trigger.type === "interact" || rule.trigger.type === "defeat"
      ? world.entities.map((e) => ({ id: e.id, name: e.name }))
      : rule.trigger.type === "button"
        ? [...world.buttons, ...world.windows.flatMap((w) => w.buttons)].map(
            (e) => ({ id: e.id, name: e.label }),
          )
        : world.items.map((e) => ({ id: e.id, name: e.name }))
    : [];
  return (
    <div className="studio-page animate-in">
      <div className="page-heading studio-heading">
        <div>
          <div className="eyebrow">
            <Sparkles size={13} /> ТВОИ ИДЕИ СТАНОВЯТСЯ ИГРОЙ
          </div>
          <h1>
            Мастерская мира<span className="draft-badge">Черновик</span>
          </h1>
          <p>
            Меняй всё под себя. Основное приключение останется нетронутым до
            публикации.
          </p>
        </div>
        <div className="heading-actions">
          <button
            className="button secondary"
            onClick={props.onTest}
            disabled={!!errors.length}
          >
            <FlaskConical size={17} /> Проверить
          </button>
          <button
            className="button primary"
            onClick={props.onPublish}
            disabled={!props.dirty || !!errors.length}
          >
            <Check size={17} /> Опубликовать в мире
          </button>
        </div>
      </div>
      <div className="studio-layout">
        <aside className="studio-nav">
          <span className="nav-caption">СОЗДАВАЙ</span>
          {sections.map((s) => (
            <button
              key={s.id}
              className={section === s.id ? "active" : ""}
              onClick={() => go(s.id)}
            >
              <s.icon size={18} />
              <span>{s.label}</span>
              {s.id === "rules" && <small>{world.rules.length}</small>}
            </button>
          ))}
          <div className="studio-nav-note">
            <Layers size={20} />
            <strong>Ты — соавтор мира</strong>
            <p>Новые возможности собираются из блоков. Без кода.</p>
          </div>
        </aside>
        <div className="studio-content">
          <div className="studio-toolbar">
            <div className="toolbar-title">
              <currentSection.icon size={19} />
              <h2>{currentSection.label}</h2>
            </div>
            <div className="studio-tools">
              <button
                className="icon-button"
                title="Отменить изменение черновика"
                aria-label="Отменить изменение"
                disabled={!props.canUndo}
                onClick={props.onUndo}
              >
                <Undo2 size={17} />
              </button>
              <button
                className="icon-button"
                title="Повторить изменение"
                aria-label="Повторить изменение"
                disabled={!props.canRedo}
                onClick={props.onRedo}
              >
                <Redo2 size={17} />
              </button>
              <span className="toolbar-divider" />
              <button
                className="text-button"
                onClick={props.onDiscard}
                disabled={!props.dirty}
              >
                <RotateCcw size={15} /> Сбросить черновик
              </button>
            </div>
          </div>
          {!!errors.length && (
            <div className="validation-box" role="status">
              <Info size={18} />
              <div>
                <strong>Перед проверкой нужно поправить:</strong>
                <ul>
                  {errors.slice(0, 6).map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
                {errors.length > 6 && <small>И ещё {errors.length - 6}.</small>}
              </div>
            </div>
          )}
          {section === "world" && (
            <div className="studio-section">
              <div className="form-grid world-name-grid">
                <Field label="Название мира">
                  <input
                    value={world.name}
                    maxLength={80}
                    onChange={(e) => update({ name: e.target.value })}
                  />
                </Field>
                <Field label="Цветовая атмосфера">
                  <select
                    value={world.theme}
                    onChange={(e) =>
                      update({ theme: e.target.value as World["theme"] })
                    }
                  >
                    <option value="forest">Лесное утро</option>
                    <option value="sunset">Золотой закат</option>
                    <option value="ocean">Прохладный берег</option>
                  </select>
                </Field>
              </div>
              <GameMap
                world={world}
                state={createState(world)}
                editor
                onTile={(x, y) => {
                  const s = createState(world);
                  s.x = x;
                  s.y = y;
                  downloadPosition(x, y);
                }}
                onEntity={(id) => {
                  go("entities");
                  select(id, "entities");
                  setPlacing(true);
                }}
              />
              <div className="info-strip">
                <MousePointer2 size={17} />
                <span>
                  Чтобы изменить карту, выбери объект в разделе «Персонажи и
                  объекты» и нажми на новую клетку.
                </span>
              </div>
              <div className="subsection-title">
                <Palette size={17} /> Оформление героя
              </div>
              <div className="form-grid">
                <Field label="Внешность">
                  <select
                    value={world.heroSprite}
                    onChange={(e) =>
                      update({
                        heroSprite: e.target.value as SpriteName,
                        heroAssetId: undefined,
                      })
                    }
                  >
                    {spriteNames.map((s) => (
                      <option key={s} value={s}>
                        {spriteLabels[s]}
                      </option>
                    ))}
                  </select>
                </Field>
                <AssetSelect
                  world={world}
                  value={world.heroAssetId}
                  onChange={(heroAssetId) => update({ heroAssetId })}
                  label="Или своё изображение героя"
                />
              </div>
            </div>
          )}
          {section === "entities" && (
            <>
              <div className="section-actions">
                <div className="filter-tabs">
                  {[
                    ["all", "Все"],
                    ["npc", "Персонажи"],
                    ["enemy", "Противники"],
                    ["item", "Предметы"],
                    ["decoration", "Объекты"],
                  ].map(([id, name]) => (
                    <button
                      key={id}
                      className={filter === id ? "active" : ""}
                      onClick={() => setFilter(id)}
                    >
                      {name}
                    </button>
                  ))}
                </div>
                <button
                  className="button small primary"
                  disabled={world.entities.length >= 150}
                  onClick={() => add("entities")}
                >
                  <Plus size={15} /> Создать
                </button>
              </div>
              <div className="editor-split">
                <div>
                  {renderList(
                    world.entities.map((e) => ({
                      id: e.id,
                      name: e.name,
                      subtitle: kindLabels[e.kind],
                      sprite: e.sprite,
                      assetId: e.assetId,
                    })),
                  )}
                </div>
                <div className="editor-detail">
                  {entity ? (
                    <>
                      <div className="detail-heading">
                        <Sprite
                          name={entity.sprite}
                          src={asset(entity.assetId)}
                        />
                        <div>
                          <span className="eyebrow">
                            {kindLabels[entity.kind]}
                          </span>
                          <h3>{entity.name || "Новый объект"}</h3>
                        </div>
                        <button
                          className="icon-button"
                          title="Дублировать"
                          aria-label="Дублировать объект"
                          onClick={() => duplicateEntity(entity)}
                        >
                          <Copy size={17} />
                        </button>
                        <button
                          className="icon-button danger-hover"
                          aria-label="Удалить объект"
                          onClick={() => remove("entities", entity.id)}
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
                      <div className="form-grid">
                        <Field label="Имя">
                          <input
                            value={entity.name}
                            maxLength={80}
                            onChange={(e) =>
                              patchEntity({ name: e.target.value })
                            }
                          />
                        </Field>
                        <Field label="Тип объекта">
                          <select
                            value={entity.kind}
                            onChange={(e) =>
                              patchEntity({
                                kind: e.target.value as Entity["kind"],
                              })
                            }
                          >
                            {Object.entries(kindLabels).map(([id, label]) => (
                              <option key={id} value={id}>
                                {label}
                              </option>
                            ))}
                          </select>
                        </Field>
                        <Field label="Встроенная графика">
                          <select
                            value={entity.sprite}
                            onChange={(e) =>
                              patchEntity({
                                sprite: e.target.value as SpriteName,
                                assetId: undefined,
                              })
                            }
                          >
                            {spriteNames.map((s) => (
                              <option key={s} value={s}>
                                {spriteLabels[s]}
                              </option>
                            ))}
                          </select>
                        </Field>
                        <AssetSelect
                          world={world}
                          value={entity.assetId}
                          onChange={(assetId) => patchEntity({ assetId })}
                        />
                      </div>
                      <button
                        className={`placement-button ${placing ? "active" : ""}`}
                        onClick={() => setPlacing(!placing)}
                      >
                        <MapPin size={17} />
                        <span>
                          {placing
                            ? "Нажми на клетку мини-карты"
                            : "Изменить положение на карте"}
                        </span>
                        <strong>
                          {entity.x}, {entity.y}
                        </strong>
                      </button>
                      <div className="mini-map-wrap">
                        <GameMap
                          world={world}
                          state={createState(world)}
                          editor
                          selectedId={entity.id}
                          placing={placing}
                          onTile={(x, y) => {
                            if (placing) {
                              patchEntity({ x, y });
                              setPlacing(false);
                              props.notify("Объект перемещён в черновике.");
                            } else {
                              const e = world.entities.find(
                                (e) => e.x === x && e.y === y,
                              );
                              if (e) select(e.id);
                            }
                          }}
                        />
                      </div>
                      <Field label="Реплика / описание взаимодействия">
                        <textarea
                          rows={3}
                          value={entity.dialogue}
                          maxLength={2000}
                          onChange={(e) =>
                            patchEntity({ dialogue: e.target.value })
                          }
                        />
                      </Field>
                      <Toggle
                        checked={entity.solid}
                        onChange={(solid) => patchEntity({ solid })}
                        label="Преграждает путь"
                      />
                      {entity.kind === "npc" && (
                        <Field label="Выдаёт задание">
                          <select
                            value={entity.questId || ""}
                            onChange={(e) =>
                              patchEntity({
                                questId: e.target.value || undefined,
                              })
                            }
                          >
                            <option value="">Без задания</option>
                            {world.quests.map((q) => (
                              <option key={q.id} value={q.id}>
                                {q.name}
                              </option>
                            ))}
                          </select>
                        </Field>
                      )}
                      {entity.kind === "item" && (
                        <Field label="Какой предмет подобрать">
                          <select
                            value={entity.itemId || ""}
                            onChange={(e) =>
                              patchEntity({ itemId: e.target.value })
                            }
                          >
                            <option value="">Выбери предмет</option>
                            {world.items.map((i) => (
                              <option key={i.id} value={i.id}>
                                {i.name}
                              </option>
                            ))}
                          </select>
                        </Field>
                      )}
                      {entity.kind === "gate" && (
                        <Field label="Предмет-ключ">
                          <select
                            value={entity.keyId || ""}
                            onChange={(e) =>
                              patchEntity({
                                keyId: e.target.value || undefined,
                              })
                            }
                          >
                            <option value="">Открыто без ключа</option>
                            {world.items.map((i) => (
                              <option key={i.id} value={i.id}>
                                {i.name}
                              </option>
                            ))}
                          </select>
                        </Field>
                      )}
                      {entity.kind === "chest" && (
                        <>
                          <div className="subsection-title">
                            Награда за открытие
                          </div>
                          <div className="form-grid">
                            <Field label="Монеты">
                              <NumberInput
                                value={entity.reward?.coins || 0}
                                onChange={(coins) =>
                                  patchEntity({
                                    reward: { xp: 0, ...entity.reward, coins },
                                  })
                                }
                              />
                            </Field>
                            <Field label="Опыт">
                              <NumberInput
                                value={entity.reward?.xp || 0}
                                onChange={(xp) =>
                                  patchEntity({
                                    reward: { coins: 0, ...entity.reward, xp },
                                  })
                                }
                              />
                            </Field>
                            <Field label="Предмет" wide>
                              <select
                                value={entity.reward?.itemId || ""}
                                onChange={(e) =>
                                  patchEntity({
                                    reward: {
                                      coins: 0,
                                      xp: 0,
                                      ...entity.reward,
                                      itemId: e.target.value || undefined,
                                    },
                                  })
                                }
                              >
                                <option value="">Без предмета</option>
                                {world.items.map((i) => (
                                  <option key={i.id} value={i.id}>
                                    {i.name}
                                  </option>
                                ))}
                              </select>
                            </Field>
                          </div>
                        </>
                      )}
                      <div className="subsection-title">
                        Характеристики объекта
                      </div>
                      <div className="form-grid">
                        {world.stats.map((s) => (
                          <Field key={s.id} label={s.name}>
                            <NumberInput
                              value={entity.stats[s.id] ?? 0}
                              max={s.max}
                              onChange={(v) =>
                                patchEntity({
                                  stats: { ...entity.stats, [s.id]: v },
                                })
                              }
                            />
                          </Field>
                        ))}
                      </div>
                      <div className="info-strip">
                        <Workflow size={16} />
                        <span>
                          Особое поведение настраивается в «Правилах»: событие
                          «Взаимодействие» → этот объект.
                        </span>
                      </div>
                    </>
                  ) : (
                    <Empty
                      icon={<Users size={28} />}
                      title="Кто живёт в твоём мире?"
                      text="Выбери объект слева или создай нового персонажа."
                    />
                  )}
                </div>
              </div>
            </>
          )}
          {section === "items" && (
            <>
              <div className="section-actions">
                <p className="muted">
                  Предметы можно находить, дарить и использовать.
                </p>
                <button
                  className="button small primary"
                  onClick={() => add("items")}
                >
                  <Plus size={15} /> Новый предмет
                </button>
              </div>
              <div className="editor-split">
                <div>
                  {renderList(
                    world.items.map((i) => ({
                      ...i,
                      subtitle:
                        i.kind === "consumable"
                          ? "Расходуемый"
                          : i.kind === "key"
                            ? "Ключевой предмет"
                            : "Предмет",
                    })),
                  )}
                </div>
                <div className="editor-detail">
                  {item ? (
                    <>
                      <div className="detail-heading">
                        <Sprite name={item.sprite} src={asset(item.assetId)} />
                        <h3>{item.name}</h3>
                        <button
                          className="icon-button danger-hover"
                          aria-label="Удалить предмет"
                          onClick={() => remove("items", item.id)}
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
                      <div className="form-grid">
                        <Field label="Название">
                          <input
                            value={item.name}
                            maxLength={80}
                            onChange={(e) =>
                              update({
                                items: world.items.map((i) =>
                                  i.id === item.id
                                    ? { ...i, name: e.target.value }
                                    : i,
                                ),
                              })
                            }
                          />
                        </Field>
                        <Field label="Тип">
                          <select
                            value={item.kind}
                            onChange={(e) =>
                              update({
                                items: world.items.map((i) =>
                                  i.id === item.id
                                    ? {
                                        ...i,
                                        kind: e.target.value as ItemDef["kind"],
                                      }
                                    : i,
                                ),
                              })
                            }
                          >
                            <option value="material">
                              Обычный / для задания
                            </option>
                            <option value="consumable">Используемый</option>
                            <option value="key">Ключ</option>
                            <option value="equipment">
                              Снаряжение / постоянный эффект
                            </option>
                          </select>
                        </Field>
                        <Field label="Графика">
                          <select
                            value={item.sprite}
                            onChange={(e) =>
                              update({
                                items: world.items.map((i) =>
                                  i.id === item.id
                                    ? {
                                        ...i,
                                        sprite: e.target.value as SpriteName,
                                        assetId: undefined,
                                      }
                                    : i,
                                ),
                              })
                            }
                          >
                            {spriteNames.map((s) => (
                              <option key={s} value={s}>
                                {spriteLabels[s]}
                              </option>
                            ))}
                          </select>
                        </Field>
                        <AssetSelect
                          world={world}
                          value={item.assetId}
                          onChange={(assetId) =>
                            update({
                              items: world.items.map((i) =>
                                i.id === item.id ? { ...i, assetId } : i,
                              ),
                            })
                          }
                        />
                      </div>
                      <Field label="Описание">
                        <textarea
                          rows={3}
                          value={item.description}
                          onChange={(e) =>
                            update({
                              items: world.items.map((i) =>
                                i.id === item.id
                                  ? { ...i, description: e.target.value }
                                  : i,
                              ),
                            })
                          }
                        />
                      </Field>
                      <div className="subsection-title">
                        <Sparkles size={16} /> Что происходит при использовании
                      </div>
                      <p className="muted small">
                        Для расходуемого предмета одна штука списывается
                        автоматически. Эффекты ниже сработают при нажатии
                        «Использовать» в рюкзаке.
                      </p>
                      <ActionEditor
                        world={world}
                        actions={item.actions}
                        onChange={(actions) =>
                          update({
                            items: world.items.map((i) =>
                              i.id === item.id ? { ...i, actions } : i,
                            ),
                          })
                        }
                      />
                      <button
                        className="button secondary"
                        onClick={() => {
                          const id = uid("ent");
                          update({
                            entities: [
                              ...world.entities,
                              {
                                id,
                                name: item.name,
                                kind: "item",
                                x: 6,
                                y: 7,
                                sprite: item.sprite,
                                assetId: item.assetId,
                                solid: false,
                                dialogue: "",
                                itemId: item.id,
                                stats: {},
                              },
                            ],
                          });
                          go("entities");
                          select(id, "entities");
                          setPlacing(true);
                        }}
                      >
                        <MapPin size={16} /> Разместить на карте
                      </button>
                    </>
                  ) : (
                    <Empty
                      icon={<Gem size={28} />}
                      title="У каждой вещи своя история"
                      text="Создай предмет, настрой его эффекты и положи на карту."
                    />
                  )}
                </div>
              </div>
            </>
          )}
          {section === "stats" && (
            <>
              <div className="section-actions">
                <p className="muted">
                  Характеристики героя и объектов. Новые появятся в игре и
                  редакторе правил.
                </p>
                <button
                  className="button small primary"
                  onClick={() => add("stats")}
                >
                  <Plus size={15} /> Новая характеристика
                </button>
              </div>
              <div className="editor-split">
                <div className="object-list">
                  {world.stats.map((s) => (
                    <button
                      key={s.id}
                      className={`object-list-row ${stat?.id === s.id ? "selected" : ""}`}
                      onClick={() => select(s.id)}
                    >
                      <span
                        className="stat-list-icon"
                        style={{ color: s.color }}
                      >
                        <StatIcon stat={s} size={20} />
                      </span>
                      <span>
                        <strong>{s.name}</strong>
                        <small>Начальное значение: {s.initial}</small>
                      </span>
                      <ChevronRight size={15} />
                    </button>
                  ))}
                </div>
                <div className="editor-detail">
                  {stat ? (
                    <>
                      <div className="detail-heading">
                        <StatIcon stat={stat} size={26} />
                        <h3>{stat.name}</h3>
                        <button
                          className="icon-button danger-hover"
                          aria-label="Удалить характеристику"
                          onClick={() => remove("stats", stat.id)}
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
                      <div className="form-grid">
                        {(
                          [
                            ["name", "Название"],
                            ["id", "Технический идентификатор"],
                          ] as const
                        ).map(([key, label]) => (
                          <Field
                            key={key}
                            label={label}
                            hint={
                              key === "id"
                                ? "Создаётся автоматически. Для общения с героем используй название, а не этот идентификатор."
                                : undefined
                            }
                          >
                            <input
                              value={stat[key]}
                              disabled={
                                key === "id" ||
                                [
                                  "hp",
                                  "energy",
                                  "coins",
                                  "xp",
                                  "attack",
                                  "defense",
                                ].includes(stat.id)
                              }
                              onChange={(e) => {
                                const value =
                                  key === "id"
                                    ? e.target.value.replace(
                                        /[^a-zA-Z0-9_-]/g,
                                        "",
                                      )
                                    : e.target.value;
                                update({
                                  stats: world.stats.map((s) =>
                                    s.id === stat.id
                                      ? { ...s, [key]: value }
                                      : s,
                                  ),
                                });
                              }}
                            />
                          </Field>
                        ))}
                        <Field label="Начальное значение">
                          <NumberInput
                            value={stat.initial}
                            onChange={(initial) =>
                              update({
                                stats: world.stats.map((s) =>
                                  s.id === stat.id ? { ...s, initial } : s,
                                ),
                              })
                            }
                          />
                        </Field>
                        <Field label="Минимум">
                          <NumberInput
                            value={stat.min}
                            onChange={(min) =>
                              update({
                                stats: world.stats.map((s) =>
                                  s.id === stat.id ? { ...s, min } : s,
                                ),
                              })
                            }
                          />
                        </Field>
                        <Field label="Максимум">
                          <NumberInput
                            value={stat.max}
                            onChange={(max) =>
                              update({
                                stats: world.stats.map((s) =>
                                  s.id === stat.id ? { ...s, max } : s,
                                ),
                              })
                            }
                          />
                        </Field>
                        <Field label="Цвет">
                          <input
                            type="color"
                            value={stat.color}
                            onChange={(e) =>
                              update({
                                stats: world.stats.map((s) =>
                                  s.id === stat.id
                                    ? { ...s, color: e.target.value }
                                    : s,
                                ),
                              })
                            }
                          />
                        </Field>
                        <Field label="Значок">
                          <select
                            value={stat.icon}
                            onChange={(e) =>
                              update({
                                stats: world.stats.map((s) =>
                                  s.id === stat.id
                                    ? {
                                        ...s,
                                        icon: e.target.value as StatDef["icon"],
                                      }
                                    : s,
                                ),
                              })
                            }
                          >
                            <option value="star">Звезда</option>
                            <option value="heart">Сердце</option>
                            <option value="zap">Молния</option>
                            <option value="coins">Монета</option>
                            <option value="shield">Щит</option>
                            <option value="sword">Меч</option>
                          </select>
                        </Field>
                      </div>
                      <Toggle
                        checked={stat.visible}
                        onChange={(visible) =>
                          update({
                            stats: world.stats.map((s) =>
                              s.id === stat.id ? { ...s, visible } : s,
                            ),
                          })
                        }
                        label="Показывать в карточке героя"
                      />
                      <div className="info-strip">
                        <Info size={16} />
                        <span>
                          Изменения характеристик применяются к герою после
                          публикации. Правила могут менять их прямо во время
                          игры.
                        </span>
                      </div>
                    </>
                  ) : (
                    <Empty
                      title="Что делает героя сильнее?"
                      text="Добавь удачу, репутацию, магическую силу — любую числовую характеристику."
                    />
                  )}
                </div>
              </div>
            </>
          )}
          {section === "quests" && (
            <>
              <div className="section-actions">
                <p className="muted">
                  Задания на сбор: цель, награда и персонаж.
                </p>
                <button
                  className="button small primary"
                  onClick={() => add("quests")}
                >
                  <Plus size={15} /> Новое задание
                </button>
              </div>
              <div className="editor-split">
                <div>
                  {renderList(
                    world.quests.map((q) => ({
                      ...q,
                      subtitle: `${q.count} × предмет · ${q.coins} монет`,
                    })),
                  )}
                </div>
                <div className="editor-detail">
                  {quest ? (
                    <>
                      <div className="detail-heading">
                        <ScrollText size={26} />
                        <h3>{quest.name}</h3>
                        <button
                          className="icon-button danger-hover"
                          aria-label="Удалить задание"
                          onClick={() => remove("quests", quest.id)}
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
                      <Field label="Название">
                        <input
                          value={quest.name}
                          onChange={(e) =>
                            update({
                              quests: world.quests.map((q) =>
                                q.id === quest.id
                                  ? { ...q, name: e.target.value }
                                  : q,
                              ),
                            })
                          }
                        />
                      </Field>
                      <Field label="Описание">
                        <textarea
                          rows={3}
                          value={quest.description}
                          onChange={(e) =>
                            update({
                              quests: world.quests.map((q) =>
                                q.id === quest.id
                                  ? { ...q, description: e.target.value }
                                  : q,
                              ),
                            })
                          }
                        />
                      </Field>
                      <div className="form-grid">
                        <Field label="Что принести">
                          <select
                            value={quest.itemId}
                            onChange={(e) =>
                              update({
                                quests: world.quests.map((q) =>
                                  q.id === quest.id
                                    ? { ...q, itemId: e.target.value }
                                    : q,
                                ),
                              })
                            }
                          >
                            {world.items.map((i) => (
                              <option key={i.id} value={i.id}>
                                {i.name}
                              </option>
                            ))}
                          </select>
                        </Field>
                        <Field label="Сколько">
                          <NumberInput
                            value={quest.count}
                            min={1}
                            max={999}
                            onChange={(count) =>
                              update({
                                quests: world.quests.map((q) =>
                                  q.id === quest.id ? { ...q, count } : q,
                                ),
                              })
                            }
                          />
                        </Field>
                        <Field label="Награда: монеты">
                          <NumberInput
                            value={quest.coins}
                            onChange={(coins) =>
                              update({
                                quests: world.quests.map((q) =>
                                  q.id === quest.id ? { ...q, coins } : q,
                                ),
                              })
                            }
                          />
                        </Field>
                        <Field label="Награда: опыт">
                          <NumberInput
                            value={quest.xp}
                            onChange={(xp) =>
                              update({
                                quests: world.quests.map((q) =>
                                  q.id === quest.id ? { ...q, xp } : q,
                                ),
                              })
                            }
                          />
                        </Field>
                        <Field label="Награда: предмет" wide>
                          <select
                            value={quest.rewardItemId || ""}
                            onChange={(e) =>
                              update({
                                quests: world.quests.map((q) =>
                                  q.id === quest.id
                                    ? {
                                        ...q,
                                        rewardItemId:
                                          e.target.value || undefined,
                                      }
                                    : q,
                                ),
                              })
                            }
                          >
                            <option value="">Без предмета</option>
                            {world.items.map((i) => (
                              <option key={i.id} value={i.id}>
                                {i.name}
                              </option>
                            ))}
                          </select>
                        </Field>
                      </div>
                      <div className="info-strip">
                        <Users size={17} />
                        <span>
                          Чтобы задание можно было получить, выбери его в
                          настройках персонажа. Герой принимает задание в
                          диалоге и сдаёт предметы там же.
                        </span>
                      </div>
                    </>
                  ) : (
                    <Empty
                      icon={<ScrollText size={28} />}
                      title="Дай герою цель"
                      text="Создай задание и свяжи его с персонажем."
                    />
                  )}
                </div>
              </div>
            </>
          )}
          {section === "rules" && (
            <>
              <div className="section-actions">
                <p className="muted">
                  Когда происходит событие → если выполнены условия → сделать
                  действия.
                </p>
                <button
                  className="button small primary"
                  onClick={() => add("rules")}
                >
                  <Plus size={15} /> Новое правило
                </button>
              </div>
              <div className="editor-split rules-split">
                <div>
                  {renderList(
                    world.rules.map((r) => ({
                      ...r,
                      subtitle: r.enabled ? "Включено" : "Выключено",
                    })),
                  )}
                </div>
                <div className="editor-detail">
                  {rule ? (
                    <>
                      <div className="detail-heading">
                        <Workflow size={25} />
                        <h3>{rule.name}</h3>
                        <button
                          className="icon-button danger-hover"
                          aria-label="Удалить правило"
                          onClick={() => remove("rules", rule.id)}
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
                      <Field label="Название правила">
                        <input
                          value={rule.name}
                          onChange={(e) =>
                            update({
                              rules: world.rules.map((r) =>
                                r.id === rule.id
                                  ? { ...r, name: e.target.value }
                                  : r,
                              ),
                            })
                          }
                        />
                      </Field>
                      <Toggle
                        checked={rule.enabled}
                        onChange={(enabled) =>
                          update({
                            rules: world.rules.map((r) =>
                              r.id === rule.id ? { ...r, enabled } : r,
                            ),
                          })
                        }
                        label="Правило включено"
                      />
                      <div className="rule-block trigger-block">
                        <span className="rule-word">КОГДА</span>
                        <div className="form-grid">
                          <Field label="Событие">
                            <select
                              value={rule.trigger.type}
                              onChange={(e) => {
                                const type = e.target
                                  .value as Rule["trigger"]["type"];
                                const target =
                                  type === "button"
                                    ? world.buttons[0]?.id || "*"
                                    : type === "interact" || type === "defeat"
                                      ? world.entities[0]?.id || "*"
                                      : world.items[0]?.id || "*";
                                update({
                                  rules: world.rules.map((r) =>
                                    r.id === rule.id
                                      ? { ...r, trigger: { type, target } }
                                      : r,
                                  ),
                                });
                              }}
                            >
                              <option value="interact">
                                Взаимодействие с объектом
                              </option>
                              <option value="use">
                                Использование предмета
                              </option>
                              <option value="button">Нажатие кнопки</option>
                              <option value="collect">Подбор предмета</option>
                              <option value="defeat">
                                Победа над противником
                              </option>
                            </select>
                          </Field>
                          <Field label="Источник события">
                            <select
                              value={rule.trigger.target}
                              onChange={(e) =>
                                update({
                                  rules: world.rules.map((r) =>
                                    r.id === rule.id
                                      ? {
                                          ...r,
                                          trigger: {
                                            ...r.trigger,
                                            target: e.target.value,
                                          },
                                        }
                                      : r,
                                  ),
                                })
                              }
                            >
                              <option value="*">Любой</option>
                              {triggerOptions.map((o) => (
                                <option key={o.id} value={o.id}>
                                  {o.name}
                                </option>
                              ))}
                            </select>
                          </Field>
                        </div>
                      </div>
                      <div className="rule-block conditions-block">
                        <span className="rule-word">ЕСЛИ</span>
                        <p className="muted small">
                          Все условия должны совпасть. Без условий правило
                          срабатывает всегда.
                        </p>
                        <ConditionEditor
                          world={world}
                          conditions={rule.conditions}
                          onChange={(conditions) =>
                            update({
                              rules: world.rules.map((r) =>
                                r.id === rule.id ? { ...r, conditions } : r,
                              ),
                            })
                          }
                        />
                      </div>
                      <div className="rule-block actions-block">
                        <span className="rule-word">СДЕЛАТЬ</span>
                        <ActionEditor
                          world={world}
                          actions={rule.actions}
                          onChange={(actions) =>
                            update({
                              rules: world.rules.map((r) =>
                                r.id === rule.id ? { ...r, actions } : r,
                              ),
                            })
                          }
                        />
                      </div>
                    </>
                  ) : (
                    <Empty
                      icon={<Workflow size={28} />}
                      title="Научи мир отвечать"
                      text="Например: когда подобрано яблоко, если собрано три — выдать награду."
                    />
                  )}
                </div>
              </div>
            </>
          )}
          {section === "interface" && (
            <>
              <div className="section-actions">
                <div className="filter-tabs">
                  <button
                    className={interfaceTab === "buttons" ? "active" : ""}
                    onClick={() => {
                      setInterfaceTab("buttons");
                      setSelected((s) => ({ ...s, interface: "" }));
                    }}
                  >
                    Кнопки действий
                  </button>
                  <button
                    className={interfaceTab === "windows" ? "active" : ""}
                    onClick={() => {
                      setInterfaceTab("windows");
                      setSelected((s) => ({ ...s, interface: "" }));
                    }}
                  >
                    Окна
                  </button>
                </div>
                <button
                  className="button small primary"
                  onClick={() => add("interface")}
                >
                  <Plus size={15} />{" "}
                  {interfaceTab === "buttons" ? "Новая кнопка" : "Новое окно"}
                </button>
              </div>
              <div className="editor-split">
                <div>
                  {renderList(
                    interfaceTab === "buttons"
                      ? world.buttons.map((b) => ({
                          ...b,
                          name: b.label,
                          subtitle: `${b.actions.length} действий`,
                        }))
                      : world.windows.map((w) => ({
                          ...w,
                          name: w.title,
                          subtitle: `${w.buttons.length} кнопок · ${w.stats.length} характеристик`,
                        })),
                  )}
                </div>
                <div className="editor-detail">
                  {interfaceTab === "buttons" ? (
                    button ? (
                      <>
                        <div className="detail-heading">
                          <PanelsTopLeft size={25} />
                          <h3>{button.label}</h3>
                          <button
                            className="icon-button danger-hover"
                            aria-label="Удалить кнопку"
                            onClick={() => remove("buttons", button.id)}
                          >
                            <Trash2 size={17} />
                          </button>
                        </div>
                        <ButtonEditor
                          world={world}
                          button={button}
                          onChange={(b) =>
                            update({
                              buttons: world.buttons.map((v) =>
                                v.id === b.id ? b : v,
                              ),
                            })
                          }
                        />
                        <div className="button-preview">
                          <span className="eyebrow">ПРЕДПРОСМОТР</span>
                          <button
                            className="quick-button"
                            onClick={() =>
                              props.notify(
                                "Так кнопка выглядит в игре. Её действия можно проверить в тестовом режиме.",
                              )
                            }
                          >
                            <Sparkles size={19} />
                            {button.label}
                          </button>
                        </div>
                      </>
                    ) : (
                      <Empty
                        title="Новая кнопка — новое действие"
                        text="Кнопки появятся под картой. Они могут открывать окна и запускать правила."
                      />
                    )
                  ) : panel ? (
                    <>
                      <div className="detail-heading">
                        <PanelsTopLeft size={25} />
                        <h3>{panel.title}</h3>
                        <button
                          className="icon-button danger-hover"
                          aria-label="Удалить окно"
                          onClick={() => remove("windows", panel.id)}
                        >
                          <Trash2 size={17} />
                        </button>
                      </div>
                      <Field label="Заголовок окна">
                        <input
                          value={panel.title}
                          maxLength={80}
                          onChange={(e) =>
                            update({
                              windows: world.windows.map((w) =>
                                w.id === panel.id
                                  ? { ...w, title: e.target.value }
                                  : w,
                              ),
                            })
                          }
                        />
                      </Field>
                      <Field label="Текст / история">
                        <textarea
                          rows={5}
                          maxLength={6000}
                          value={panel.text}
                          onChange={(e) =>
                            update({
                              windows: world.windows.map((w) =>
                                w.id === panel.id
                                  ? { ...w, text: e.target.value }
                                  : w,
                              ),
                            })
                          }
                        />
                      </Field>
                      <AssetSelect
                        world={world}
                        label="Иллюстрация окна"
                        value={panel.imageId}
                        onChange={(imageId) =>
                          update({
                            windows: world.windows.map((w) =>
                              w.id === panel.id ? { ...w, imageId } : w,
                            ),
                          })
                        }
                      />
                      <div className="subsection-title">
                        Показывать живые характеристики
                      </div>
                      <div className="stat-checkboxes">
                        {world.stats.map((s) => (
                          <Toggle
                            key={s.id}
                            label={s.name}
                            checked={panel.stats.includes(s.id)}
                            onChange={(checked) =>
                              update({
                                windows: world.windows.map((w) =>
                                  w.id === panel.id
                                    ? {
                                        ...w,
                                        stats: checked
                                          ? [...w.stats, s.id]
                                          : w.stats.filter((id) => id !== s.id),
                                      }
                                    : w,
                                ),
                              })
                            }
                          />
                        ))}
                      </div>
                      <div className="subsection-title">Кнопки внутри окна</div>
                      {panel.buttons.map((b) => (
                        <details className="nested-editor" key={b.id}>
                          <summary>
                            {b.label || "Новая кнопка"}
                            <button
                              className="icon-button danger-hover"
                              aria-label="Удалить кнопку окна"
                              onClick={(e) => {
                                e.preventDefault();
                                update({
                                  windows: world.windows.map((w) =>
                                    w.id === panel.id
                                      ? {
                                          ...w,
                                          buttons: w.buttons.filter(
                                            (v) => v.id !== b.id,
                                          ),
                                        }
                                      : w,
                                  ),
                                });
                              }}
                            >
                              <Trash2 size={15} />
                            </button>
                          </summary>
                          <ButtonEditor
                            world={world}
                            button={b}
                            onChange={(b) =>
                              update({
                                windows: world.windows.map((w) =>
                                  w.id === panel.id
                                    ? {
                                        ...w,
                                        buttons: w.buttons.map((v) =>
                                          v.id === b.id ? b : v,
                                        ),
                                      }
                                    : w,
                                ),
                              })
                            }
                          />
                        </details>
                      ))}
                      <button
                        className="text-button"
                        disabled={panel.buttons.length >= 12}
                        onClick={() =>
                          update({
                            windows: world.windows.map((w) =>
                              w.id === panel.id
                                ? {
                                    ...w,
                                    buttons: [
                                      ...w.buttons,
                                      {
                                        id: uid("btn"),
                                        label: "Продолжить",
                                        icon: "sparkles",
                                        actions: [
                                          {
                                            type: "message",
                                            text: "Приключение продолжается!",
                                          },
                                        ],
                                      },
                                    ],
                                  }
                                : w,
                            ),
                          })
                        }
                      >
                        <Plus size={15} /> Добавить кнопку в окно
                      </button>
                      <div className="info-strip">
                        <Info size={16} />
                        <span>
                          Чтобы открыть это окно, создай кнопку с действием
                          «Открыть окно» или используй его в правиле.
                        </span>
                      </div>
                    </>
                  ) : (
                    <Empty
                      title="Окно для твоей идеи"
                      text="Собери дневник, справку, магазин наград или экран персонажа из текста, графики, характеристик и кнопок."
                    />
                  )}
                </div>
              </div>
            </>
          )}
          {section === "graphics" && (
            <div className="studio-section">
              <div className="graphics-intro">
                <div>
                  <h3>Твой мир может выглядеть иначе</h3>
                  <p className="muted">
                    Загрузи свои PNG, JPEG или WebP. Используй их для героя,
                    объектов, предметов, окон и фона.
                  </p>
                </div>
                <div className="graphics-upload-buttons">
                  <button
                    className="button secondary"
                    onClick={() => backgroundRef.current?.click()}
                    disabled={uploading}
                  >
                    <ImagePlus size={16} /> Загрузить фон
                  </button>
                  <button
                    className="button primary"
                    onClick={() => fileRef.current?.click()}
                    disabled={uploading}
                  >
                    <Upload size={17} />
                    {uploading ? "Обработка…" : "Загрузить графику"}
                  </button>
                </div>
                <input
                  ref={backgroundRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  hidden
                  onChange={(e) => upload(e.target.files, true)}
                />
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  multiple
                  hidden
                  onChange={(e) => upload(e.target.files)}
                />
              </div>
              <div className="asset-grid">
                {world.assets.map((a) => (
                  <article className="asset-card" key={a.id}>
                    <div className="asset-preview">
                      <img src={a.data} alt={a.name} />
                    </div>
                    <div className="asset-meta">
                      <strong>{a.name}</strong>
                      <button
                        className="icon-button danger-hover"
                        aria-label={`Удалить ${a.name}`}
                        onClick={() => remove("assets", a.id)}
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                    <button
                      className="text-button"
                      onClick={() => {
                        update({ backgroundId: a.id });
                        props.notify(
                          "Фон выбран. Проверь мир перед публикацией.",
                        );
                      }}
                    >
                      <ImagePlus size={14} />{" "}
                      {world.backgroundId === a.id
                        ? "Выбрано как фон"
                        : "Сделать фоном"}
                    </button>
                  </article>
                ))}
                <button
                  className="asset-upload-card"
                  onClick={() => fileRef.current?.click()}
                  disabled={uploading}
                >
                  <Plus size={28} />
                  <strong>Добавить изображение</strong>
                  <span>До 8 МБ · автоматически сжимается</span>
                </button>
              </div>
              <div className="form-grid">
                <AssetSelect
                  world={world}
                  label="Фон карты"
                  value={world.backgroundId}
                  onChange={(backgroundId) => update({ backgroundId })}
                />
                <AssetSelect
                  world={world}
                  label="Изображение героя"
                  value={world.heroAssetId}
                  onChange={(heroAssetId) => update({ heroAssetId })}
                />
              </div>
              <div className="info-strip">
                <Info size={17} />
                <span>
                  Лучше всего подходят спрайты с прозрачным фоном. Изображения
                  хранятся внутри твоего мира и попадают в резервную копию.
                  Загружай только свои или разрешённые к использованию
                  материалы.
                </span>
              </div>
              <div className="subsection-title">
                Встроенный набор · 13 спрайтов
              </div>
              <div className="builtin-sprites">
                {spriteNames.map((s) => (
                  <div key={s}>
                    <Sprite name={s} />
                    <span>{spriteLabels[s]}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {section === "history" && (
            <div className="studio-section">
              <div className="backup-banner">
                <div className="backup-icon">
                  <History size={27} />
                </div>
                <div>
                  <h3>Экспериментируй спокойно</h3>
                  <p>
                    Перед публикацией мы сохраняем рабочую версию. Ещё лучше —
                    иметь копию в файле.
                  </p>
                </div>
                <button className="button secondary" onClick={props.onExport}>
                  <Download size={16} /> Скачать мир
                </button>
              </div>
              <div className="section-actions">
                <h3>Сохранённые версии</h3>
                <button
                  className="button small secondary"
                  onClick={() => props.onSnapshot("Ручная резервная копия")}
                >
                  <Save size={15} /> Сохранить копию
                </button>
              </div>
              <div className="snapshot-list">
                {props.snapshots.length ? (
                  props.snapshots.map((s) => (
                    <div className="snapshot-row" key={s.id}>
                      <span className="snapshot-dot">
                        <History size={18} />
                      </span>
                      <div>
                        <strong>{s.label}</strong>
                        <small>
                          {new Date(s.date).toLocaleString("ru-RU")} · версия{" "}
                          {s.world.revision} · {s.world.entities.length}{" "}
                          объектов
                        </small>
                      </div>
                      <button
                        className="button small secondary"
                        onClick={() => {
                          if (
                            confirm(
                              "Восстановить эту версию мира и прогресса? Текущее состояние сначала будет сохранено в копию.",
                            )
                          )
                            props.onRestore(s);
                        }}
                      >
                        <RotateCcw size={14} /> Восстановить
                      </button>
                    </div>
                  ))
                ) : (
                  <Empty
                    title="Здесь будет история мира"
                    text="Создай резервную копию сейчас или опубликуй первое изменение."
                  />
                )}
              </div>
              <p className="muted small">
                Храним до 8 последних версий в этом браузере. Очистка данных
                сайта удалит их — регулярно скачивай мир в файл.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
  function downloadPosition(x: number, y: number) {
    props.notify(
      `Клетка ${x}, ${y}. Для размещения выбери объект в разделе «Персонажи и объекты».`,
    );
  }
}
