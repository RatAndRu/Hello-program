import {
  spriteNames,
  clone,
  COLS,
  ROWS,
  tileAt,
  type World,
  type GameState,
  type Action,
  type Condition,
  type Entity,
  type Quest,
} from "./model";

export interface Effect {
  message?: string;
  openWindow?: string;
  sound?: "collect" | "success" | "hit";
}
export interface Result {
  state: GameState;
  effects: Effect[];
  changed: boolean;
}
const cap = (n: number) => Math.max(0, Math.min(999999, Math.floor(n)));
export function addLog(s: GameState, text: string) {
  s.log = [text, ...s.log].slice(0, 40);
}
export function changeStat(
  world: World,
  s: GameState,
  id: string,
  value: number,
  op: "add" | "set",
) {
  const def = world.stats.find((d) => d.id === id);
  if (!def) return;
  const next = op === "add" ? (s.stats[id] ?? def.initial) + value : value;
  s.stats[id] = Math.max(
    def.min,
    Math.min(def.max, Math.round(next * 100) / 100),
  );
}
export function giveItem(s: GameState, id: string, count = 1) {
  s.inventory[id] = cap((s.inventory[id] || 0) + count);
}
export function takeItem(s: GameState, id: string, count = 1): boolean {
  if ((s.inventory[id] || 0) < count) return false;
  s.inventory[id] -= count;
  if (!s.inventory[id]) delete s.inventory[id];
  return true;
}
export function matches(s: GameState, c: Condition): boolean {
  switch (c.type) {
    case "stat": {
      const v = s.stats[c.stat] ?? 0;
      return c.op === "gte"
        ? v >= c.value
        : c.op === "lte"
          ? v <= c.value
          : v === c.value;
    }
    case "item":
      return (s.inventory[c.item] || 0) >= c.count;
    case "quest":
      return s.quests[c.quest] === c.status;
    case "flag":
      return !!s.flags[c.flag] === c.value;
  }
}
export function applyActions(
  world: World,
  state: GameState,
  actions: Action[],
): Result {
  const s = clone(state);
  const effects: Effect[] = [];
  // Bounded, data-only interpreter. Never evaluates user-supplied JavaScript.
  for (const a of actions.slice(0, 50)) {
    switch (a.type) {
      case "stat":
        changeStat(world, s, a.stat, a.value, a.op);
        break;
      case "item":
        if (a.op === "give") giveItem(s, a.item, a.count);
        else takeItem(s, a.item, a.count);
        break;
      case "message":
        effects.push({ message: a.text });
        addLog(s, a.text);
        break;
      case "window":
        if (world.windows.some((w) => w.id === a.window))
          effects.push({ openWindow: a.window });
        break;
      case "flag":
        s.flags[a.flag] = a.value;
        break;
      case "quest":
        if (world.quests.some((q) => q.id === a.quest))
          s.quests[a.quest] = a.status;
        break;
      case "teleport": {
        const x = Math.round(a.x),
          y = Math.round(a.y);
        const blocked = world.entities.some(
          (e) =>
            e.id !== "hero" &&
            e.solid &&
            e.x === x &&
            e.y === y &&
            !s.removed.includes(e.id) &&
            !s.opened.includes(e.id),
        );
        if (
          x >= 1 &&
          x < COLS - 1 &&
          y >= 1 &&
          y < ROWS - 1 &&
          !["water", "tree"].includes(tileAt(x, y)) &&
          !blocked
        ) {
          s.x = x;
          s.y = y;
        } else
          effects.push({
            message: "Точка перемещения недоступна. Выбери свободную клетку.",
          });
        break;
      }
    }
  }
  return {
    state: s,
    effects,
    changed: JSON.stringify(s) !== JSON.stringify(state),
  };
}
export function runRules(
  world: World,
  state: GameState,
  type: string,
  target: string,
): Result {
  let s = clone(state);
  const effects: Effect[] = [];
  let changed = false;
  for (const r of world.rules.slice(0, 100)) {
    if (
      !r.enabled ||
      r.trigger.type !== type ||
      (r.trigger.target !== "*" && r.trigger.target !== target)
    )
      continue;
    if (!r.conditions.every((c) => matches(s, c))) continue;
    const result = applyActions(world, s, r.actions);
    s = result.state;
    effects.push(...result.effects);
    changed ||= result.changed;
  }
  return { state: s, effects, changed };
}
export function canStand(
  world: World,
  s: GameState,
  x: number,
  y: number,
): boolean {
  if (
    x < 1 ||
    y < 1 ||
    x >= COLS - 1 ||
    y >= ROWS - 1 ||
    ["water", "tree"].includes(tileAt(x, y))
  )
    return false;
  return !world.entities.some(
    (e) =>
      e.solid &&
      e.x === x &&
      e.y === y &&
      !s.removed.includes(e.id) &&
      !s.opened.includes(e.id),
  );
}
export function collect(
  world: World,
  state: GameState,
  entity: Entity,
): Result {
  let s = clone(state);
  const effects: Effect[] = [];
  if (s.removed.includes(entity.id) || !entity.itemId)
    return { state: s, effects, changed: false };
  s.removed.push(entity.id);
  giveItem(s, entity.itemId, 1);
  const item = world.items.find((i) => i.id === entity.itemId);
  const text = `Найдено: ${item?.name || entity.name} × 1`;
  addLog(s, text);
  effects.push({ message: text, sound: "collect" });
  const result = runRules(world, s, "collect", entity.itemId);
  return {
    state: result.state,
    effects: [...effects, ...result.effects],
    changed: true,
  };
}
export function move(
  world: World,
  state: GameState,
  dx: number,
  dy: number,
): Result {
  const x = state.x + dx,
    y = state.y + dy;
  if (!canStand(world, state, x, y))
    return { state, effects: [], changed: false };
  let s = clone(state);
  s.x = x;
  s.y = y;
  s.steps++;
  const item = world.entities.find(
    (e) =>
      e.kind === "item" && e.x === x && e.y === y && !s.removed.includes(e.id),
  );
  if (item) return collect(world, s, item);
  return { state: s, effects: [], changed: true };
}
export function findPath(
  world: World,
  state: GameState,
  tx: number,
  ty: number,
): [number, number][] {
  const queue: { x: number; y: number; path: [number, number][] }[] = [
    { x: state.x, y: state.y, path: [] },
  ];
  const seen = new Set([`${state.x},${state.y}`]);
  for (let i = 0; i < queue.length && i < COLS * ROWS; i++) {
    const p = queue[i];
    if (p.x === tx && p.y === ty) return p.path;
    for (const [dx, dy] of [
      [1, 0],
      [-1, 0],
      [0, 1],
      [0, -1],
    ]) {
      const x = p.x + dx,
        y = p.y + dy,
        key = `${x},${y}`;
      if (seen.has(key) || !canStand(world, state, x, y)) continue;
      seen.add(key);
      queue.push({ x, y, path: [...p.path, [dx, dy]] });
    }
  }
  return [];
}
export function nearestInteraction(
  world: World,
  s: GameState,
): Entity | undefined {
  return world.entities
    .filter(
      (e) =>
        !s.removed.includes(e.id) &&
        Math.abs(e.x - s.x) + Math.abs(e.y - s.y) <= 1,
    )
    .sort(
      (a, b) =>
        (a.kind === "decoration" ? 1 : 0) - (b.kind === "decoration" ? 1 : 0),
    )[0];
}
export function completeQuest(
  world: World,
  state: GameState,
  q: Quest,
): Result {
  let s = clone(state);
  if (s.quests[q.id] !== "active" || !takeItem(s, q.itemId, q.count))
    return {
      state,
      effects: [{ message: "Для выполнения задания не хватает предметов." }],
      changed: false,
    };
  s.quests[q.id] = "completed";
  changeStat(world, s, "coins", q.coins, "add");
  changeStat(world, s, "xp", q.xp, "add");
  if (q.rewardItemId) giveItem(s, q.rewardItemId, 1);
  const text = `Задание «${q.name}» выполнено! +${q.coins} монет, +${q.xp} опыта.`;
  addLog(s, text);
  return {
    state: s,
    effects: [{ message: text, sound: "success" }],
    changed: true,
  };
}
export function interact(world: World, state: GameState, e: Entity): Result {
  let s = clone(state);
  const effects: Effect[] = [];
  if (s.removed.includes(e.id)) return { state, effects, changed: false };
  if (Math.abs(e.x - s.x) + Math.abs(e.y - s.y) > 1)
    return {
      state,
      effects: [{ message: "Подойди поближе к объекту." }],
      changed: false,
    };
  if (e.kind === "item") return collect(world, s, e);
  if (e.kind === "chest" && !s.opened.includes(e.id)) {
    s.opened.push(e.id);
    const r = e.reward;
    if (r) {
      changeStat(world, s, "coins", r.coins, "add");
      changeStat(world, s, "xp", r.xp, "add");
      if (r.itemId) giveItem(s, r.itemId, 1);
    }
    const text = `Сундук открыт! +${r?.coins || 0} монет, +${r?.xp || 0} опыта.`;
    addLog(s, text);
    effects.push({ message: text, sound: "success" });
  } else if (e.kind === "gate" && !s.opened.includes(e.id)) {
    if (e.keyId && s.inventory[e.keyId]) {
      s.opened.push(e.id);
      const text = "Проход открыт! Впереди — новые открытия.";
      addLog(s, text);
      effects.push({ message: text, sound: "success" });
    } else effects.push({ message: e.dialogue || "Тебе нужен ключ." });
  } else if (e.kind === "npc" && e.questId) {
    const q = world.quests.find((q) => q.id === e.questId);
    if (
      q &&
      s.quests[q.id] === "active" &&
      (s.inventory[q.itemId] || 0) >= q.count
    )
      return completeQuest(world, s, q);
  }
  const result = runRules(world, s, "interact", e.id);
  return {
    state: result.state,
    effects: [...effects, ...result.effects],
    changed:
      result.changed || JSON.stringify(result.state) !== JSON.stringify(state),
  };
}
export function attack(world: World, state: GameState, e: Entity): Result {
  let s = clone(state);
  if (s.removed.includes(e.id)) return { state, effects: [], changed: false };
  if ((s.stats.hp || 0) <= 0)
    return {
      state,
      effects: [{ message: "Сначала восстанови здоровье ягодами." }],
      changed: false,
    };
  const enemy = s.entityStats[e.id] || { ...e.stats };
  const damage = Math.max(1, (s.stats.attack || 1) - (enemy.defense || 0));
  enemy.hp = Math.max(0, (enemy.hp || 1) - damage);
  s.entityStats[e.id] = enemy;
  let text = `Твой удар: −${damage} здоровья противника.`;
  if (enemy.hp <= 0) {
    s.removed.push(e.id);
    changeStat(world, s, "xp", 15, "add");
    changeStat(world, s, "coins", 8, "add");
    text = `${e.name} повержен! +15 опыта, +8 монет.`;
    const r = runRules(world, s, "defeat", e.id);
    s = r.state;
    addLog(s, text);
    return {
      state: s,
      effects: [{ message: text, sound: "success" }, ...r.effects],
      changed: true,
    };
  }
  const back = Math.max(1, (enemy.attack || 1) - (s.stats.defense || 0));
  changeStat(world, s, "hp", -back, "add");
  text += ` Ответный удар: −${back} здоровья.`;
  addLog(s, text);
  return {
    state: s,
    effects: [{ message: text, sound: "hit" }],
    changed: true,
  };
}
export function useItem(world: World, state: GameState, id: string): Result {
  const item = world.items.find((i) => i.id === id);
  if (!item || !state.inventory[id])
    return {
      state,
      effects: [{ message: "Этого предмета нет в рюкзаке." }],
      changed: false,
    };
  if (item.kind !== "consumable" && item.kind !== "equipment")
    return { state, effects: [{ message: item.description }], changed: false };
  const s = clone(state);
  if (item.kind === "consumable") takeItem(s, id, 1);
  const a = applyActions(world, s, item.actions);
  const b = runRules(world, a.state, "use", id);
  addLog(
    b.state,
    `${item.kind === "equipment" ? "Применено" : "Использовано"}: ${item.name}`,
  );
  return {
    state: b.state,
    effects: [...a.effects, ...b.effects],
    changed: true,
  };
}

export function validateWorld(w: World): string[] {
  try {
    return validateWorldDetails(w);
  } catch {
    return ["Структура мира повреждена. Проверь поля и вложенные объекты."];
  }
}

function validateWorldDetails(w: World): string[] {
  const errors: string[] = [];
  if (!w || w.schemaVersion !== 1) return ["Неподдерживаемая версия мира."];
  if (typeof w.name !== "string" || !w.name.trim() || w.name.length > 80)
    errors.push("Название мира: от 1 до 80 символов.");
  for (const [name, arr] of Object.entries({
    объекты: w.entities,
    предметы: w.items,
    характеристики: w.stats,
    задания: w.quests,
    правила: w.rules,
    кнопки: w.buttons,
    окна: w.windows,
    изображения: w.assets,
  })) {
    if (!Array.isArray(arr) || arr.length > 200) {
      errors.push(`Некорректный раздел: ${name}.`);
      continue;
    }
    const ids = arr.map((v: { id: string }) => v?.id);
    if (
      ids.some(
        (id) =>
          typeof id !== "string" ||
          !/^[a-zA-Z0-9_-]{1,90}$/.test(id) ||
          ["__proto__", "constructor", "prototype"].includes(id),
      ) ||
      new Set(ids).size !== ids.length
    )
      errors.push(`Некорректные или повторяющиеся идентификаторы: ${name}.`);
  }
  if (errors.length) return errors;
  if (
    !Number.isInteger(w.revision) ||
    w.revision < 1 ||
    !["forest", "sunset", "ocean"].includes(w.theme) ||
    !spriteNames.includes(w.heroSprite)
  )
    errors.push("Некорректные версия, тема или графика героя.");
  if (
    ["hp", "energy", "coins", "xp", "attack", "defense"].some(
      (id) => !w.stats.some((stat) => stat.id === id),
    )
  )
    errors.push("В мире должны сохраняться шесть базовых характеристик героя.");
  if (
    w.assets.reduce(
      (sum, a) => sum + (typeof a?.data === "string" ? a.data.length : 0),
      0,
    ) > 12000000
  )
    errors.push("Общий объём графики слишком большой.");
  const has = (arr: { id: string }[], id?: string) =>
    !!id && arr.some((v) => v.id === id);
  const num = (n: unknown, min = 0, max = 999999) =>
    typeof n === "number" && Number.isFinite(n) && n >= min && n <= max;
  const text = (s: unknown, max = 2000) =>
    typeof s === "string" && s.length <= max;
  for (const a of w.assets)
    if (
      !text(a.name, 100) ||
      !text(a.data, 2500000) ||
      !/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(a.data)
    )
      errors.push(`Недопустимое изображение: ${a.name}`);
  for (const s of w.stats)
    if (
      !text(s.name, 60) ||
      !s.name.trim() ||
      !num(s.initial) ||
      !num(s.min) ||
      !num(s.max) ||
      !/^#[0-9a-fA-F]{6}$/.test(s.color) ||
      typeof s.visible !== "boolean" ||
      !["heart", "zap", "coins", "star", "shield", "sword"].includes(s.icon) ||
      s.min > s.max ||
      s.initial < s.min ||
      s.initial > s.max
    )
      errors.push(`Некорректная характеристика: ${s.name}`);
  for (const e of w.entities) {
    if (
      !text(e.name, 80) ||
      !e.name.trim() ||
      typeof e.solid !== "boolean" ||
      !spriteNames.includes(e.sprite) ||
      !["npc", "item", "chest", "enemy", "gate", "decoration"].includes(
        e.kind,
      ) ||
      !Number.isInteger(e.x) ||
      !Number.isInteger(e.y) ||
      !num(e.x, 1, COLS - 2) ||
      !num(e.y, 1, ROWS - 2) ||
      ["water", "tree"].includes(tileAt(e.x, e.y))
    )
      errors.push(`Объект «${e.name}»: неверное имя или позиция.`);
    if (e.assetId && !has(w.assets, e.assetId))
      errors.push(`Изображение объекта «${e.name}» не найдено.`);
    if (e.kind === "item" && !has(w.items, e.itemId))
      errors.push(`У объекта «${e.name}» не выбран предмет.`);
    if (e.kind === "npc" && e.questId && !has(w.quests, e.questId))
      errors.push(`Задание персонажа «${e.name}» не найдено.`);
    if (e.kind === "gate" && e.keyId && !has(w.items, e.keyId))
      errors.push(`Ключ ворот «${e.name}» не найден.`);
    if (e.reward?.itemId && !has(w.items, e.reward.itemId))
      errors.push(`Награда объекта «${e.name}» не найдена.`);
    if (!e.stats || Object.values(e.stats).some((v) => !num(v)))
      errors.push(`Некорректные числа у объекта «${e.name}».`);
    if (!text(e.dialogue)) errors.push(`Слишком длинный диалог: ${e.name}`);
  }
  const solids = w.entities.filter((e) => e.solid);
  if (
    solids.some((e, i) =>
      solids.slice(i + 1).some((o) => o.x === e.x && o.y === e.y),
    )
  )
    errors.push("Два твёрдых объекта стоят на одной клетке.");
  for (const i of w.items)
    if (
      !text(i.name, 80) ||
      !i.name.trim() ||
      !spriteNames.includes(i.sprite) ||
      !["material", "consumable", "key", "equipment"].includes(i.kind) ||
      !text(i.description) ||
      (i.assetId && !has(w.assets, i.assetId))
    )
      errors.push(`Некорректный предмет: ${i.name}`);
  for (const q of w.quests)
    if (
      !text(q.name, 80) ||
      !q.name.trim() ||
      !text(q.description) ||
      !has(w.items, q.itemId) ||
      !num(q.count, 1, 999) ||
      !Number.isInteger(q.count) ||
      !num(q.coins) ||
      !num(q.xp) ||
      (q.rewardItemId && !has(w.items, q.rewardItemId))
    )
      errors.push(`Некорректное задание: ${q.name}`);
  const checkAction = (a: Action) => {
    if (!a || typeof a !== "object") {
      errors.push("Пустое действие.");
      return;
    }
    switch (a.type) {
      case "stat":
        if (
          !has(w.stats, a.stat) ||
          !num(a.value, -999999) ||
          !["add", "set"].includes(a.op)
        )
          errors.push(
            "Действие ссылается на неизвестную характеристику или число.",
          );
        break;
      case "item":
        if (
          !has(w.items, a.item) ||
          !num(a.count, 1, 999) ||
          !Number.isInteger(a.count) ||
          !["give", "take"].includes(a.op)
        )
          errors.push(
            "Действие ссылается на неизвестный предмет или количество.",
          );
        break;
      case "message":
        if (!text(a.text)) errors.push("Некорректный текст сообщения.");
        break;
      case "window":
        if (!has(w.windows, a.window))
          errors.push("Действие открывает несуществующее окно.");
        break;
      case "quest":
        if (
          !has(w.quests, a.quest) ||
          !["available", "active", "completed"].includes(a.status)
        )
          errors.push("Действие ссылается на неизвестное задание.");
        break;
      case "flag":
        if (
          !text(a.flag, 80) ||
          !/^[a-zA-Z0-9_-]+$/.test(a.flag) ||
          ["__proto__", "constructor", "prototype"].includes(a.flag) ||
          typeof a.value !== "boolean"
        )
          errors.push("Некорректный флаг.");
        break;
      case "teleport":
        if (
          !Number.isInteger(a.x) ||
          !Number.isInteger(a.y) ||
          !num(a.x, 1, COLS - 2) ||
          !num(a.y, 1, ROWS - 2)
        )
          errors.push("Некорректная точка перемещения.");
        break;
      default:
        errors.push("Неизвестный тип действия.");
    }
  };
  const checkCondition = (c: Condition) => {
    if (!c || typeof c !== "object") {
      errors.push("Пустое условие.");
      return;
    }
    switch (c.type) {
      case "stat":
        if (
          !has(w.stats, c.stat) ||
          !num(c.value, -999999) ||
          !["gte", "lte", "eq"].includes(c.op)
        )
          errors.push("Некорректное условие характеристики.");
        break;
      case "item":
        if (!has(w.items, c.item) || !num(c.count, 1, 999))
          errors.push("Некорректное условие предмета.");
        break;
      case "quest":
        if (
          !has(w.quests, c.quest) ||
          !["available", "active", "completed"].includes(c.status)
        )
          errors.push("Некорректное условие задания.");
        break;
      case "flag":
        if (
          !text(c.flag, 80) ||
          !/^[a-zA-Z0-9_-]+$/.test(c.flag) ||
          ["__proto__", "constructor", "prototype"].includes(c.flag) ||
          typeof c.value !== "boolean"
        )
          errors.push("Некорректное условие флага.");
        break;
      default:
        errors.push("Неизвестное условие.");
    }
  };
  const checkButton = (b: (typeof w.buttons)[number]) => {
    if (
      !text(b.label, 60) ||
      !b.label.trim() ||
      !["sparkles", "book", "heart", "compass", "gift"].includes(b.icon) ||
      !Array.isArray(b.actions) ||
      b.actions.length > 20
    )
      errors.push("Некорректная кнопка.");
    else b.actions.forEach(checkAction);
  };
  w.buttons.forEach(checkButton);
  for (const window of w.windows) {
    if (
      !text(window.title, 80) ||
      !window.title.trim() ||
      !text(window.text, 6000) ||
      !Array.isArray(window.stats) ||
      window.stats.some((id) => !has(w.stats, id)) ||
      (window.imageId && !has(w.assets, window.imageId)) ||
      !Array.isArray(window.buttons) ||
      window.buttons.length > 12
    )
      errors.push(`Некорректное окно: ${window.title}`);
    else window.buttons.forEach(checkButton);
  }
  for (const i of w.items) {
    if (!Array.isArray(i.actions) || i.actions.length > 20)
      errors.push(`Некорректные эффекты: ${i.name}`);
    else i.actions.forEach(checkAction);
  }
  for (const r of w.rules) {
    if (
      !text(r.name, 80) ||
      !r.name.trim() ||
      typeof r.enabled !== "boolean" ||
      !r.trigger ||
      !["interact", "use", "button", "collect", "defeat"].includes(
        r.trigger.type,
      ) ||
      !text(r.trigger.target, 90) ||
      !Array.isArray(r.conditions) ||
      r.conditions.length > 10 ||
      !Array.isArray(r.actions) ||
      !r.actions.length ||
      r.actions.length > 20
    )
      errors.push(`Некорректное правило: ${r.name}`);
    else {
      r.conditions.forEach(checkCondition);
      r.actions.forEach(checkAction);
      const options =
        r.trigger.type === "interact" || r.trigger.type === "defeat"
          ? w.entities
          : r.trigger.type === "button"
            ? [...w.buttons, ...w.windows.flatMap((window) => window.buttons)]
            : w.items;
      if (r.trigger.target !== "*" && !has(options, r.trigger.target))
        errors.push(
          `Событие правила «${r.name}» ссылается на удалённый объект.`,
        );
    }
  }
  if (w.backgroundId && !has(w.assets, w.backgroundId))
    errors.push("Фон мира не найден.");
  if (w.heroAssetId && !has(w.assets, w.heroAssetId))
    errors.push("Изображение героя не найдено.");
  return [...new Set(errors)];
}
