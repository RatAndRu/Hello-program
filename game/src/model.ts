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
  | "tree"
  | "knight"
  | "knight-gold"
  | "knight-dark"
  | "lantern"
  | "castle"
  | "banner"
  | "fountain"
  | "ember"
  | "rem"
  | "ram"
  | "emilia"
  | "puck"
  | "roswaal"
  | "rose"
  | "ice"
  | "contract";
export type EntityKind =
  "npc" | "item" | "chest" | "enemy" | "gate" | "decoration";
export type Action =
  | { type: "stat"; stat: string; op: "add" | "set"; value: number }
  | { type: "item"; item: string; op: "give" | "take"; count: number }
  | { type: "message"; text: string }
  | { type: "window"; window: string }
  | { type: "flag"; flag: string; value: boolean }
  | { type: "quest"; quest: string; status: QuestStatus }
  | { type: "teleport"; x: number; y: number; theme?: Theme }
  | { type: "location"; theme: Theme };
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
  /** Location this object belongs to; used for validation and the studio. */
  theme?: Theme;
  /** Optional picture that becomes this object's map tile. */
  backgroundId?: string;
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
  theme: Theme;
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
  /** Location the hero is currently in. */
  theme: Theme;
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
/** Small aliases kept for the editor UI. */
export const W = COLS;
export const H = ROWS;
export const START = { x: 4, y: 7 };
export const CASTLE_START = { x: 9, y: 8 };
/** Built-in island, one character per tile. Used by the map and the studio. */
export const ISLAND_ROWS = [
  "TTTTTTTTTTTT~TTTTT",
  "T...,.......~....T",
  "T.TT...T,T..~.TT.T",
  "T....#....T.~...TT",
  "T.T,.#..#...~...,T",
  "T....#.,#...~..#.T",
  "T.##########=####T",
  "T.,..#......~..,.T",
  "T....#,.....~....T",
  "T.T.......,.~.T.TT",
  "T,.T..T...T.~.,T.T",
  "TTTTTTTTTTTT~TTTTT",
] as const;
/** The castle courtyard: walls around, stone paving, flower beds. */
export const COURTYARD_ROWS = [
  "WWWWWWWWWWWWWWWWWW",
  "WSSSSSSSSSSSSSSSSW",
  "WSSSSSSSSSSSSSSSSW",
  "WSSSSSSSSSSSSSSSSW",
  "WSSSSSSSSSSSSSSSSW",
  "WSSSSSSSSSSSSSSSSW",
  "WSSSSSSSSSSSSSSSSW",
  "WSSSSSSSSSSSSSSSSW",
  "WSSSSffffSSSSSSSSW",
  "WSSSSSSSSSSSSSSSSW",
  "WSSSSSSSSSSSSSSSSW",
  "WWWWWWWWWWWWWWWWWW",
] as const;
/** Roswaal manor garden: gravel paths, rose beds and clipped hedges. */
export const GARDEN_ROWS = [
  "TTTTTTTTTTTTTTTTTT",
  "T,,,..######..,,,T",
  "T,gg,..####..,gg,T",
  "T,gg,...##...,gg,T",
  "T,,,...####...,,,T",
  "T..###.####.###..T",
  "T..###.####.###..T",
  "T,,,...####...,,,T",
  "T,gg,...##...,gg,T",
  "T,gg,..####..,gg,T",
  "T,,,..######..,,,T",
  "TTTTTTTTTTTTTTTTTT",
] as const;
const TILE_BY_CHAR: Record<string, Tile> = {
  ".": "grass",
  "#": "path",
  "~": "water",
  "=": "bridge",
  T: "tree",
  ",": "flowers",
  S: "stone",
  f: "flowers",
  W: "wall",
  g: "hedge",
};
/** Ground themes. A world uses one, single objects may use another. */
export type Theme =
  "forest" | "sunset" | "ocean" | "castle" | "night" | "garden";
export const themes: Theme[] = [
  "forest",
  "sunset",
  "ocean",
  "castle",
  "night",
  "garden",
];
export const themeLabels: Record<Theme, string> = {
  forest: "Лесное утро",
  sunset: "Золотой закат",
  ocean: "Прохладный берег",
  castle: "Каменный двор",
  night: "Ночь фонарей",
  garden: "Розовый сад",
};
/**
 * Shared tile lookup. The theme decides which ground a location uses, so the
 * same 18×12 map can hold both the forest and the castle courtyard.
 */
export function tileAt(x: number, y: number, theme: Theme = "forest"): Tile {
  if (x < 0 || y < 0 || x >= COLS || y >= ROWS) return "tree";
  const rows =
    theme === "castle"
      ? COURTYARD_ROWS
      : theme === "garden"
        ? GARDEN_ROWS
        : ISLAND_ROWS;
  const char = (rows[y] ?? "")[x] ?? ".";
  return TILE_BY_CHAR[char] ?? "grass";
}
export const locationNames: Record<Theme, string> = {
  forest: "Тихая роща",
  sunset: "Закатная поляна",
  ocean: "Прохладный берег",
  castle: "Замок фонарей",
  night: "Ночной двор",
  garden: "Розовый сад Розвааля",
};

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
      {
        id: "ember",
        name: "Тёплый огонёк",
        description:
          "Живой огонёк из замкового фонаря. Восстанавливает 15 энергии.",
        sprite: "ember",
        kind: "consumable",
        actions: [
          { type: "stat", stat: "energy", op: "add", value: 15 },
          { type: "message", text: "Огонёк согревает. Энергия +15." },
        ],
      },
      {
        id: "shard",
        name: "Осколок знамени",
        description: "Кусочек алого знамени Ордена фонарей.",
        sprite: "sword",
        kind: "material",
        actions: [],
      },
      {
        id: "castle-key",
        name: "Ключ фонарщика",
        description: "Открывает калитку во внутренний двор замка.",
        sprite: "key",
        kind: "key",
        actions: [],
      },
      {
        id: "rose",
        name: "Алая роза",
        description:
          "Роза из сада поместья. Рем и Рам считают, что она приносит удачу.",
        sprite: "rose",
        kind: "material",
        actions: [],
      },
      {
        id: "ice-crystal",
        name: "Ледяной кристалл",
        description:
          "Осколок льда Эмилии. Восстанавливает 25 здоровья и 10 энергии.",
        sprite: "ice",
        kind: "consumable",
        actions: [
          { type: "stat", stat: "hp", op: "add", value: 25 },
          { type: "stat", stat: "energy", op: "add", value: 10 },
          {
            type: "message",
            text: "Ледяная свежесть: здоровье +25, энергия +10.",
          },
        ],
      },
      {
        id: "spirit-contract",
        name: "Контракт духа",
        description:
          "Тёплый огонёк Пака. Постоянный эффект: сила атаки +3, защита +1.",
        sprite: "contract",
        kind: "equipment",
        actions: [
          { type: "stat", stat: "attack", op: "add", value: 3 },
          { type: "stat", stat: "defense", op: "add", value: 1 },
          {
            type: "message",
            text: "Пак довольно кивает. Сила атаки +3, защита +1.",
          },
        ],
      },
      {
        id: "lantern-charm",
        name: "Фонарный талисман",
        description:
          "Носится с собой: защита +2 и энергия +10. Снаряжение не тратится.",
        sprite: "lantern",
        kind: "equipment",
        actions: [
          { type: "stat", stat: "defense", op: "add", value: 2 },
          { type: "stat", stat: "energy", op: "add", value: 10 },
          {
            type: "message",
            text: "Талисман закреплён: защита +2, энергия +10.",
          },
        ],
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
        id: "castle-gate",
        name: "Вход в замок",
        kind: "decoration",
        x: 6,
        y: 4,
        sprite: "castle",
        solid: true,
        dialogue:
          "За воротами светятся фонари. Фонарщик Тео ждёт во дворе и просит помощи с огоньками.",
        stats: {},
      },
      {
        id: "castle-exit",
        theme: "castle",
        name: "Ворота на остров",
        kind: "decoration",
        x: 2,
        y: 9,
        sprite: "gate",
        solid: true,
        dialogue:
          "За воротами снова шумит остров. Можно вернуться к садовнику.",
        stats: {},
      },
      {
        id: "castle-hall",
        theme: "castle",
        name: "Замок фонарей",
        kind: "decoration",
        x: 9,
        y: 2,
        sprite: "castle",
        solid: true,
        dialogue:
          "Высокие окна, каменные арки и гербы Ордена фонарей. Здесь решались судьбы острова.",
        stats: {},
      },
      {
        id: "castle-banner-l",
        theme: "castle",
        name: "Знамя Ордена",
        kind: "decoration",
        x: 4,
        y: 2,
        sprite: "banner",
        solid: false,
        dialogue: "Алое полотно с серебряным фонарём — герб Ордена.",
        stats: {},
      },
      {
        id: "castle-banner-r",
        theme: "castle",
        name: "Знамя Ордена",
        kind: "decoration",
        x: 14,
        y: 2,
        sprite: "banner",
        solid: false,
        dialogue: "Второе знамя. Краска на нём ещё свежая.",
        stats: {},
      },
      {
        id: "lantern-master",
        theme: "castle",
        name: "Фонарщик Тео",
        kind: "npc",
        x: 3,
        y: 3,
        sprite: "gardener",
        solid: true,
        dialogue:
          "Фонари гаснут один за другим. Зажги три огонька в замке — и я открою тебе внутренний двор.",
        questId: "lanterns",
        stats: {},
      },
      {
        id: "ember-1",
        theme: "castle",
        name: "Тёплый огонёк",
        kind: "item",
        x: 14,
        y: 3,
        sprite: "ember",
        solid: false,
        dialogue: "",
        itemId: "ember",
        stats: {},
      },
      {
        id: "ember-2",
        theme: "castle",
        name: "Тёплый огонёк",
        kind: "item",
        x: 15,
        y: 6,
        sprite: "ember",
        solid: false,
        dialogue: "",
        itemId: "ember",
        stats: {},
      },
      {
        id: "ember-3",
        theme: "castle",
        name: "Тёплый огонёк",
        kind: "item",
        x: 13,
        y: 9,
        sprite: "ember",
        solid: false,
        dialogue: "",
        itemId: "ember",
        stats: {},
      },
      {
        id: "knight-ivar",
        theme: "castle",
        name: "Рыцарь Ивар",
        kind: "npc",
        x: 7,
        y: 4,
        sprite: "knight",
        solid: true,
        dialogue:
          "Мой щит потускнел без огня. Раздобудь осколок знамени, и я расскажу тебе о замке.",
        questId: "banner",
        stats: {},
      },
      {
        id: "banner-cache",
        theme: "castle",
        name: "Старое знамя",
        kind: "chest",
        x: 15,
        y: 7,
        sprite: "banner",
        solid: true,
        dialogue: "Алое знамя Ордена фонарей, покрытое пылью.",
        reward: { coins: 12, xp: 10, itemId: "shard" },
        stats: {},
      },
      {
        id: "knight-vela",
        theme: "castle",
        name: "Рыцарь Вела",
        kind: "npc",
        x: 12,
        y: 4,
        sprite: "knight-gold",
        solid: true,
        dialogue:
          "Я охраняю внутренний двор. Не люблю болтовню без пользы — покажи характер.",
        stats: { hp: 46, attack: 9, defense: 3 },
      },
      {
        id: "knight-mor",
        theme: "castle",
        name: "Тёмный рыцарь Мор",
        kind: "enemy",
        x: 14,
        y: 9,
        sprite: "knight-dark",
        solid: true,
        dialogue: "Фонари — глупость. Погаси их, и замок станет тихим.",
        stats: { hp: 52, attack: 10, defense: 4 },
      },
      {
        id: "lantern-1",
        theme: "castle",
        name: "Фонарь у ворот",
        kind: "decoration",
        x: 6,
        y: 3,
        sprite: "lantern",
        solid: true,
        dialogue: "Тёплый свет дрожит на ветру. Фонарь явно ждёт огонька.",
        stats: {},
      },
      {
        id: "lantern-2",
        theme: "castle",
        name: "Фонарь на площади",
        kind: "decoration",
        x: 10,
        y: 6,
        sprite: "lantern",
        solid: true,
        dialogue: "Стекло фонаря пыльное, но целое.",
        stats: {},
      },
      {
        id: "lantern-3",
        theme: "castle",
        name: "Фонарь у фонтана",
        kind: "decoration",
        x: 11,
        y: 9,
        sprite: "lantern",
        solid: true,
        dialogue: "Здесь кто-то написал: «Свет возвращается тем, кто делится».",
        stats: {},
      },
      {
        id: "fountain",
        theme: "castle",
        name: "Фонтан искр",
        kind: "decoration",
        x: 8,
        y: 6,
        sprite: "fountain",
        solid: true,
        dialogue: "Вода светится. Кажется, фонтан помнит всех хранителей.",
        stats: {},
      },
      {
        id: "garden-gate",
        name: "Калитка в поместье",
        kind: "decoration",
        x: 15,
        y: 8,
        sprite: "gate",
        solid: true,
        dialogue:
          "За калиткой цветут розы, а на скамье у фонтана сидит девушка с длинными серебристыми волосами.",
        stats: {},
      },
      {
        id: "garden-exit",
        theme: "garden",
        name: "Выход из сада",
        kind: "decoration",
        x: 1,
        y: 9,
        sprite: "gate",
        solid: true,
        dialogue: "Тропинка ведёт обратно на остров.",
        stats: {},
      },
      {
        id: "rem",
        theme: "garden",
        name: "Рем",
        kind: "npc",
        x: 5,
        y: 3,
        sprite: "rem",
        solid: true,
        dialogue:
          "Добро пожаловать в поместье! Я Рем. Мы с сестрой следим за садом. Не хочешь собрать алые розы? Они нужны для чая госпожи Эмилии.",
        questId: "roses",
        stats: {},
      },
      {
        id: "ram",
        theme: "garden",
        name: "Рам",
        kind: "npc",
        x: 12,
        y: 3,
        sprite: "ram",
        solid: true,
        dialogue:
          "Рам. Да, мы близнецы. Собери мне два ледяных кристалла — и чай получится по-настоящему холодным.",
        questId: "tea",
        stats: {},
      },
      {
        id: "roswaal",
        theme: "garden",
        name: "Розвааль",
        kind: "npc",
        x: 9,
        y: 2,
        sprite: "roswaal",
        solid: true,
        dialogue:
          "Ах, новый гость! Поместье всегда открыто для тех, кто не боится роз. Мои служанки проводят тебя.",
        stats: {},
      },
      {
        id: "emilia",
        theme: "garden",
        name: "Эмилия",
        kind: "npc",
        x: 9,
        y: 8,
        sprite: "emilia",
        solid: true,
        dialogue:
          "Я Эмилия. Пак говорит, что в саду завёлся дух, который ворует ледяные кристаллы. Поможешь разобраться?",
        questId: "ice",
        stats: {},
      },
      {
        id: "puck",
        theme: "garden",
        name: "Пак",
        kind: "npc",
        x: 8,
        y: 5,
        sprite: "puck",
        solid: false,
        dialogue:
          "Я не кот! Я дух. Хотя гладить можно. Липп-липп! Если поможешь Эмилии, я заключу с тобой контракт.",
        stats: {},
      },
      {
        id: "ice-1",
        theme: "garden",
        name: "Ледяной кристалл",
        kind: "item",
        x: 3,
        y: 6,
        sprite: "ice",
        solid: false,
        dialogue: "",
        itemId: "ice-crystal",
        stats: {},
      },
      {
        id: "ice-2",
        theme: "garden",
        name: "Ледяной кристалл",
        kind: "item",
        x: 14,
        y: 6,
        sprite: "ice",
        solid: false,
        dialogue: "",
        itemId: "ice-crystal",
        stats: {},
      },
      {
        id: "rose-1",
        theme: "garden",
        name: "Алая роза",
        kind: "item",
        x: 2,
        y: 4,
        sprite: "rose",
        solid: false,
        dialogue: "",
        itemId: "rose",
        stats: {},
      },
      {
        id: "rose-2",
        theme: "garden",
        name: "Алая роза",
        kind: "item",
        x: 5,
        y: 8,
        sprite: "rose",
        solid: false,
        dialogue: "",
        itemId: "rose",
        stats: {},
      },
      {
        id: "rose-3",
        theme: "garden",
        name: "Алая роза",
        kind: "item",
        x: 12,
        y: 8,
        sprite: "rose",
        solid: false,
        dialogue: "",
        itemId: "rose",
        stats: {},
      },
      {
        id: "rose-4",
        theme: "garden",
        name: "Алая роза",
        kind: "item",
        x: 15,
        y: 4,
        sprite: "rose",
        solid: false,
        dialogue: "",
        itemId: "rose",
        stats: {},
      },
      {
        id: "garden-sign",
        theme: "garden",
        name: "Табличка у входа",
        kind: "decoration",
        x: 4,
        y: 9,
        sprite: "sign",
        solid: false,
        dialogue:
          "«Поместье Розвааля. Рем и Рам — близняшки-служанки, Эмилия — дух-полуэльфийка, Пак — маленький дух, который не кот». Кто-то приписал снизу: «Пак точно кот».",
        stats: {},
      },
      {
        id: "garden-fountain",
        theme: "garden",
        name: "Фонтан поместья",
        kind: "decoration",
        x: 9,
        y: 6,
        sprite: "fountain",
        solid: true,
        dialogue:
          "В воде плавают лепестки роз. Пак утверждает, что фонтан шепчет.",
        stats: {},
      },
      {
        id: "garden-manor",
        theme: "garden",
        name: "Поместье Розвааля",
        kind: "decoration",
        x: 9,
        y: 3,
        sprite: "castle",
        solid: true,
        dialogue:
          "Особняк с башнями и витражами. Отсюда Розвааль управляет округой.",
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
      {
        id: "lanterns",
        name: "Три огонька",
        description:
          "Фонарщик Тео просит собрать три тёплых огонька в замковом дворе.",
        itemId: "ember",
        count: 3,
        coins: 30,
        xp: 25,
        rewardItemId: "castle-key",
      },
      {
        id: "roses",
        name: "Чай для госпожи",
        description:
          "Рем и Рам просят собрать четыре алые розы для чая Эмилии.",
        itemId: "rose",
        count: 4,
        coins: 20,
        xp: 20,
        rewardItemId: "ice-crystal",
      },
      {
        id: "tea",
        name: "Чай по-рамски",
        description:
          "Рам считает, что чай должен быть с розой и льдом. Принеси два ледяных кристалла.",
        itemId: "ice-crystal",
        count: 2,
        coins: 18,
        xp: 15,
      },
      {
        id: "ice",
        name: "Дух и лёд",
        description:
          "Эмилия просит принести два ледяных кристалла, пока Пак не растащил их все.",
        itemId: "ice-crystal",
        count: 2,
        coins: 25,
        xp: 30,
        rewardItemId: "spirit-contract",
      },
      {
        id: "banner",
        name: "Потерянное знамя",
        description:
          "Рыцарь Ивар хочет вернуть осколок знамени Ордена фонарей.",
        itemId: "shard",
        count: 1,
        coins: 15,
        xp: 20,
        rewardItemId: "lantern-charm",
      },
    ],
    rules: [
      {
        id: "enter-castle",
        name: "Войти в замок",
        enabled: true,
        trigger: { type: "interact", target: "castle-gate" },
        conditions: [],
        actions: [
          { type: "location", theme: "castle" },
          { type: "teleport", x: 9, y: 8 },
          {
            type: "message",
            text: "Ты вошёл в Замок фонарей. Во дворе пахнет воском и камнем.",
          },
        ],
      },
      {
        id: "leave-castle",
        name: "Вернуться на остров",
        enabled: true,
        trigger: { type: "interact", target: "castle-exit" },
        conditions: [],
        actions: [
          { type: "location", theme: "forest" },
          { type: "teleport", x: 5, y: 4 },
          { type: "message", text: "Ты снова на Острове искр." },
        ],
      },
      {
        id: "enter-garden",
        name: "Войти в сад поместья",
        enabled: true,
        trigger: { type: "interact", target: "garden-gate" },
        conditions: [],
        actions: [
          { type: "location", theme: "garden" },
          { type: "teleport", x: 9, y: 9 },
          {
            type: "message",
            text: "Ты вошёл в Розовый сад поместья. Пахнет чаем и алыми розами.",
          },
        ],
      },
      {
        id: "leave-garden",
        name: "Выйти из сада",
        enabled: true,
        trigger: { type: "interact", target: "garden-exit" },
        conditions: [],
        actions: [
          { type: "location", theme: "forest" },
          { type: "teleport", x: 14, y: 7 },
          { type: "message", text: "Ты вернулся на Остров искр." },
        ],
      },
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
      {
        id: "lanterns-lit",
        name: "Фонари зажглись",
        enabled: true,
        trigger: { type: "interact", target: "lantern-1" },
        conditions: [
          { type: "item", item: "ember", count: 3 },
          { type: "flag", flag: "lanterns-lit", value: false },
        ],
        actions: [
          { type: "flag", flag: "lanterns-lit", value: true },
          { type: "stat", stat: "xp", op: "add", value: 15 },
          {
            type: "window",
            window: "castle-notes",
          },
          {
            type: "message",
            text: "Три огонька вспыхнули разом. Фонари замка снова горят! +15 опыта.",
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
      {
        id: "lantern-map",
        label: "Замок фонарей",
        icon: "gift",
        actions: [{ type: "window", window: "castle-notes" }],
      },
      {
        id: "manor-notes",
        label: "Поместье Розвааля",
        icon: "heart",
        actions: [{ type: "window", window: "garden-notes" }],
      },
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
      {
        id: "castle-notes",
        title: "Заметки о замке",
        text: "Замок фонарей стоит на другом берегу. Фонарщик Тео ждёт у калитки, рыцари Ивар и Вела охраняют двор, а где-то в глубине притаился Тёмный Мор. Собери огоньки — и фонари снова загорятся.",
        stats: ["energy", "coins"],
        buttons: [],
      },
      {
        id: "garden-notes",
        title: "Гости поместья",
        text: "В саду живут Рем и Рам — близнецы-служанки, Эмилия — полуэльфийка с ледяной магией, и Пак, маленький дух, который очень похож на кота, но настаивает, что он не кот. Рем и Рам собирают алые розы, Эмилия ищет ледяные кристаллы, а Пак обещает контракт духа тому, кто поможет.",
        stats: ["hp", "energy"],
        buttons: [],
      },
    ],
    assets: [],
  };
}
export function createState(world: World): GameState {
  return {
    ...START,
    theme: world.theme,
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
  if (!s.theme || !themes.includes(s.theme)) s.theme = world.theme;
  if (BLOCKED_TILES.includes(tileAt(s.x, s.y, s.theme))) {
    s.x = START.x;
    s.y = START.y;
    s.theme = world.theme;
  }
  return s;
}

export type Tile =
  | "grass"
  | "path"
  | "water"
  | "bridge"
  | "stone"
  | "wall"
  | "hedge"
  | "tree"
  | "flowers";
/** Tiles the hero can never enter. */
export const BLOCKED_TILES: Tile[] = ["water", "tree", "wall", "hedge"];
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
  "knight",
  "knight-gold",
  "knight-dark",
  "lantern",
  "castle",
  "banner",
  "fountain",
  "ember",
  "rem",
  "ram",
  "emilia",
  "puck",
  "roswaal",
  "rose",
  "ice",
  "contract",
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
  knight: "Рыцарь",
  "knight-gold": "Рыцарь в золоте",
  "knight-dark": "Тёмный рыцарь",
  lantern: "Фонарь",
  castle: "Замок",
  banner: "Знамя",
  fountain: "Фонтан",
  ember: "Огонёк",
  rem: "Рем",
  ram: "Рам",
  emilia: "Эмилия",
  puck: "Пак",
  roswaal: "Розвааль",
  rose: "Роза",
  ice: "Ледяной кристалл",
  contract: "Контракт духа",
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
