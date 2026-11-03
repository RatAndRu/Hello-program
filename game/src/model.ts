export type SpriteName =
  | "hero"
  | "gardener"
  | "slime"
  | "apple"
  | "berry"
  | "key"
  | "coin"
  | "chest"
  | "gate"
  | "sword"
  | "flower"
  | "sign"
  | "tree";
export type EntityKind =
  "npc" | "item" | "chest" | "enemy" | "gate" | "decoration";
export type Action =
  | { type: "stat"; stat: string; op: "add" | "set"; value: number }
  | { type: "item"; item: string; op: "give" | "take"; count: number }
  | { type: "message"; text: string }
  | { type: "window"; window: string }
  | { type: "flag"; flag: string; value: boolean }
  | { type: "quest"; quest: string; status: QuestStatus }
  | { type: "teleport"; x: number; y: number };
export type Condition =
  | { type: "stat"; stat: string; op: "gte" | "lte" | "eq"; value: number }
  | { type: "item"; item: string; count: number }
  | { type: "quest"; quest: string; status: QuestStatus }
  | { type: "flag"; flag: string; value: boolean };
export interface Rule {
  id: string;
  name: string;
  enabled: boolean;
  trigger: {
    type: "interact" | "use" | "button" | "collect" | "defeat";
    target: string;
  };
  conditions: Condition[];
  actions: Action[];
}
export interface StatDef {
  id: string;
  name: string;
  initial: number;
  min: number;
  max: number;
  color: string;
  icon: "heart" | "zap" | "coins" | "star" | "shield" | "sword";
  visible: boolean;
}
export interface ItemDef {
  id: string;
  name: string;
  description: string;
  sprite: SpriteName;
  assetId?: string;
  kind: "material" | "consumable" | "key" | "equipment";
  actions: Action[];
}
export interface Entity {
  id: string;
  name: string;
  kind: EntityKind;
  x: number;
  y: number;
  sprite: SpriteName;
  assetId?: string;
  solid: boolean;
  dialogue: string;
  itemId?: string;
  questId?: string;
  keyId?: string;
  reward?: { coins: number; xp: number; itemId?: string };
  stats: Record<string, number>;
}
export type QuestStatus = "available" | "active" | "completed";
export interface Quest {
  id: string;
  name: string;
  description: string;
  itemId: string;
  count: number;
  coins: number;
  xp: number;
  rewardItemId?: string;
}
export interface CustomButton {
  id: string;
  label: string;
  icon: "sparkles" | "book" | "heart" | "compass" | "gift";
  actions: Action[];
}
export interface CustomWindow {
  id: string;
  title: string;
  text: string;
  imageId?: string;
  stats: string[];
  buttons: CustomButton[];
}
export interface Asset {
  id: string;
  name: string;
  data: string;
}
export interface World {
  schemaVersion: 1;
  id: string;
  name: string;
  revision: number;
  theme: "forest" | "sunset" | "ocean";
  backgroundId?: string;
  heroSprite: SpriteName;
  heroAssetId?: string;
  entities: Entity[];
  items: ItemDef[];
  stats: StatDef[];
  quests: Quest[];
  rules: Rule[];
  buttons: CustomButton[];
  windows: CustomWindow[];
  assets: Asset[];
}
export interface GameState {
  x: number;
  y: number;
  stats: Record<string, number>;
  inventory: Record<string, number>;
  quests: Record<string, QuestStatus>;
  flags: Record<string, boolean>;
  entityStats: Record<string, Record<string, number>>;
  removed: string[];
  opened: string[];
  log: string[];
  steps: number;
}
export interface Snapshot {
  id: string;
  date: string;
  label: string;
  world: World;
  state: GameState;
}
export interface SaveData {
  world: World;
  state: GameState;
  draft: World | null;
  snapshots: Snapshot[];
}
export const COLS = 18;
export const ROWS = 12;
export const uid = (prefix = "id") =>
  `${prefix}-${crypto.randomUUID().slice(0, 8)}`;
export const clone = <T>(value: T): T => structuredClone(value);
export const START = { x: 4, y: 7 };

export function createWorld(): World {
  return {
    schemaVersion: 1,
    id: "iskra-island",
    name: "Остров искр",
    revision: 1,
    theme: "forest",
    heroSprite: "hero",
    stats: [
      {
        id: "hp",
        name: "Здоровье",
        initial: 100,
        min: 0,
        max: 100,
        color: "#d77969",
        icon: "heart",
        visible: true,
      },
      {
        id: "energy",
        name: "Энергия",
        initial: 80,
        min: 0,
        max: 100,
        color: "#d9ad55",
        icon: "zap",
        visible: true,
      },
      {
        id: "coins",
        name: "Монеты",
        initial: 0,
        min: 0,
        max: 999999,
        color: "#c69b43",
        icon: "coins",
        visible: true,
      },
      {
        id: "xp",
        name: "Опыт",
        initial: 0,
        min: 0,
        max: 999999,
        color: "#759b83",
        icon: "star",
        visible: true,
      },
      {
        id: "attack",
        name: "Сила атаки",
        initial: 12,
        min: 0,
        max: 999,
        color: "#9a88ae",
        icon: "sword",
        visible: true,
      },
      {
        id: "defense",
        name: "Защита",
        initial: 2,
        min: 0,
        max: 999,
        color: "#7f9cac",
        icon: "shield",
        visible: true,
      },
    ],
    items: [
      {
        id: "apple",
        name: "Спелое яблоко",
        description: "Растёт на острове. Садовник мечтает собрать корзину.",
        sprite: "apple",
        kind: "material",
        actions: [],
      },
      {
        id: "key",
        name: "Ключ от рощи",
        description: "Открывает ворота на другой берег реки.",
        sprite: "key",
        kind: "key",
        actions: [],
      },
      {
        id: "berry",
        name: "Лесная ягода",
        description: "Восстанавливает 20 здоровья. Используется из рюкзака.",
        sprite: "berry",
        kind: "consumable",
        actions: [
          { type: "stat", stat: "hp", op: "add", value: 20 },
          { type: "message", text: "Вкус леса! Здоровье восстановлено на 20." },
        ],
      },
      {
        id: "crystal",
        name: "Искра острова",
        description: "Тёплый кристалл из древнего сундука.",
        sprite: "coin",
        kind: "material",
        actions: [],
      },
    ],
    entities: [
      {
        id: "gardener",
        name: "Садовник Мир",
        kind: "npc",
        x: 5,
        y: 5,
        sprite: "gardener",
        solid: true,
        dialogue:
          "О, новый хранитель острова! Принеси мне три спелых яблока. Я отдам тебе ключ от рощи — там спрятана настоящая искра приключений.",
        questId: "apples",
        stats: {},
      },
      {
        id: "apple-1",
        name: "Спелое яблоко",
        kind: "item",
        x: 3,
        y: 6,
        sprite: "apple",
        solid: false,
        dialogue: "",
        itemId: "apple",
        stats: {},
      },
      {
        id: "apple-2",
        name: "Спелое яблоко",
        kind: "item",
        x: 7,
        y: 8,
        sprite: "apple",
        solid: false,
        dialogue: "",
        itemId: "apple",
        stats: {},
      },
      {
        id: "apple-3",
        name: "Спелое яблоко",
        kind: "item",
        x: 8,
        y: 4,
        sprite: "apple",
        solid: false,
        dialogue: "",
        itemId: "apple",
        stats: {},
      },
      {
        id: "berry-1",
        name: "Лесная ягода",
        kind: "item",
        x: 9,
        y: 7,
        sprite: "berry",
        solid: false,
        dialogue: "",
        itemId: "berry",
        stats: {},
      },
      {
        id: "slime",
        name: "Озорной слизень",
        kind: "enemy",
        x: 9,
        y: 9,
        sprite: "slime",
        solid: true,
        dialogue: "Слизень подпрыгивает и преграждает путь.",
        stats: { hp: 28, attack: 7, defense: 1 },
      },
      {
        id: "gate",
        name: "Ворота в рощу",
        kind: "gate",
        x: 12,
        y: 6,
        sprite: "gate",
        solid: true,
        dialogue: "За воротами шумит древняя роща. Нужен ключ садовника.",
        keyId: "key",
        stats: {},
      },
      {
        id: "chest",
        name: "Сундук хранителя",
        kind: "chest",
        x: 15,
        y: 5,
        sprite: "chest",
        solid: true,
        dialogue: "Внутри что-то тихо светится.",
        reward: { coins: 40, xp: 50, itemId: "crystal" },
        stats: {},
      },
      {
        id: "sign",
        name: "Указатель",
        kind: "decoration",
        x: 4,
        y: 4,
        sprite: "sign",
        solid: true,
        dialogue:
          "Добро пожаловать на Остров искр! Двигайся стрелками или нажимай на карту. E — взаимодействие. В мастерской можно изменить этот мир.",
        stats: {},
      },
    ],
    quests: [
      {
        id: "apples",
        name: "Яблочный помощник",
        description: "Помоги садовнику Миру собрать три спелых яблока.",
        itemId: "apple",
        count: 3,
        coins: 25,
        xp: 30,
        rewardItemId: "key",
      },
    ],
    rules: [
      {
        id: "welcome-rule",
        name: "Маленькое открытие",
        enabled: true,
        trigger: { type: "button", target: "explore" },
        conditions: [],
        actions: [
          { type: "stat", stat: "xp", op: "add", value: 5 },
          {
            type: "message",
            text: "Ты исследовал остров. +5 опыта! Каждое открытие делает тебя сильнее.",
          },
        ],
      },
    ],
    buttons: [
      {
        id: "journal",
        label: "Мой дневник",
        icon: "book",
        actions: [{ type: "window", window: "diary" }],
      },
      { id: "explore", label: "Исследовать", icon: "compass", actions: [] },
    ],
    windows: [
      {
        id: "diary",
        title: "Дневник хранителя",
        text: "Сегодня я прибыл на Остров искр. Садовник говорит, что мир можно не только исследовать, но и менять. Начну с яблок, а потом придумаю собственную историю.",
        imageId: undefined,
        stats: ["xp", "coins"],
        buttons: [],
      },
    ],
    assets: [],
  };
}
export function createState(world: World): GameState {
  return {
    ...START,
    stats: Object.fromEntries(world.stats.map((s) => [s.id, s.initial])),
    inventory: { berry: 1 },
    quests: Object.fromEntries(world.quests.map((q) => [q.id, "available"])),
    flags: {},
    entityStats: Object.fromEntries(
      world.entities.map((e) => [e.id, { ...e.stats }]),
    ),
    removed: [],
    opened: [],
    log: ["Ты прибыл на Остров искр. Твоя история начинается!"],
    steps: 0,
  };
}
export function reconcileState(world: World, old: GameState): GameState {
  const s = clone(old);
  for (const def of world.stats) {
    if (s.stats[def.id] === undefined) s.stats[def.id] = def.initial;
    s.stats[def.id] = Math.max(def.min, Math.min(def.max, s.stats[def.id]));
  }
  for (const q of world.quests)
    if (!s.quests[q.id]) s.quests[q.id] = "available";
  for (const e of world.entities)
    if (!s.entityStats[e.id]) s.entityStats[e.id] = { ...e.stats };
  if (tileAt(s.x, s.y) === "water" || tileAt(s.x, s.y) === "tree") {
    s.x = START.x;
    s.y = START.y;
  }
  return s;
}

export type Tile = "grass" | "path" | "water" | "bridge" | "tree" | "flowers";
export function tileAt(x: number, y: number): Tile {
  if (x < 0 || y < 0 || x >= COLS || y >= ROWS) return "tree";
  if (x === 12 && y !== 6) return "water";
  if (x === 12 && y === 6) return "bridge";
  if (y === 6 && x > 1 && x < 17) return "path";
  if (x === 5 && y >= 3 && y <= 8) return "path";
  if ((x === 8 && y >= 4 && y <= 6) || (x === 15 && y >= 5 && y <= 6))
    return "path";
  if (x === 0 || y === 0 || x === COLS - 1 || y === ROWS - 1) return "tree";
  const trees = [
    [2, 2],
    [3, 2],
    [7, 2],
    [9, 2],
    [10, 3],
    [2, 9],
    [3, 10],
    [6, 10],
    [10, 10],
    [14, 2],
    [15, 2],
    [16, 9],
    [14, 9],
    [15, 10],
    [2, 4],
    [16, 3],
  ];
  if (trees.some(([a, b]) => a === x && b === y)) return "tree";
  if ((x * 7 + y * 11) % 13 === 0) return "flowers";
  return "grass";
}
export const spriteNames: SpriteName[] = [
  "hero",
  "gardener",
  "slime",
  "apple",
  "berry",
  "key",
  "coin",
  "chest",
  "gate",
  "sword",
  "flower",
  "sign",
  "tree",
];
export const spriteLabels: Record<SpriteName, string> = {
  hero: "Хранитель",
  gardener: "Садовник",
  slime: "Слизень",
  apple: "Яблоко",
  berry: "Ягоды",
  key: "Ключ",
  coin: "Кристалл",
  chest: "Сундук",
  gate: "Ворота",
  sword: "Меч",
  flower: "Цветок",
  sign: "Указатель",
  tree: "Дерево",
};
export const kindLabels: Record<EntityKind, string> = {
  npc: "Персонаж",
  item: "Предмет на карте",
  chest: "Сундук",
  enemy: "Противник",
  gate: "Ворота",
  decoration: "Объект / диалог",
};
export const questLabels: Record<QuestStatus, string> = {
  available: "Можно получить",
  active: "В процессе",
  completed: "Выполнено",
};
