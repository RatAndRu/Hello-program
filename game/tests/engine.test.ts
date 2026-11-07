import { describe, it, expect } from "vitest";
import {
  createWorld,
  createState,
  clone,
  reconcileState,
  tileAt,
} from "../src/model";
import {
  validateWorld,
  move,
  findPath,
  canStand,
  collect,
  interact,
  completeQuest,
  useItem,
  attack,
  runRules,
  applyActions,
} from "../src/engine";
import { validateSave } from "../src/storage";

describe("safe world schema", () => {
  it("starter world passes validation and every collectible is reachable", () => {
    const w = createWorld(),
      s = createState(w);
    expect(validateWorld(w)).toEqual([]);
    for (const e of w.entities.filter(
      (e) => e.kind === "item" && (e.theme ?? w.theme) === s.theme,
    ))
      expect(findPath(w, s, e.x, e.y).length).toBeGreaterThan(0);
    expect(findPath(w, s, 15, 5)).toEqual([]);
  });
  it("rejects unknown actions, broken references, duplicate IDs and invalid positions", () => {
    const w = createWorld();
    w.rules[0].actions = [{ type: "execute", code: "alert(1)" } as never];
    expect(validateWorld(w).length).toBeGreaterThan(0);
    const a = createWorld();
    a.items[0].id = a.items[1].id;
    expect(validateWorld(a).length).toBeGreaterThan(0);
    const b = createWorld();
    b.entities[0].x = 12;
    expect(validateWorld(b).some((e) => e.includes("позиция"))).toBe(true);
    const c = createWorld();
    c.windows[0].stats = ["missing"];
    expect(validateWorld(c).length).toBeGreaterThan(0);
  });
  it("does not evaluate code contained in text or allow prototype keys", () => {
    const w = createWorld(),
      s = createState(w);
    const result = applyActions(w, s, [
      { type: "message", text: "<img src=x onerror=alert(1)>" },
    ]);
    expect(result.effects[0].message).toBe("<img src=x onerror=alert(1)>");
    expect(result.state.stats).toEqual(s.stats);
    const bad = clone(w);
    bad.stats[0].id = "__proto__";
    expect(validateWorld(bad).length).toBeGreaterThan(0);
  });
  it("validates imported progress", () => {
    const w = createWorld(),
      s = createState(w);
    expect(
      validateSave({ world: w, state: s, draft: null, snapshots: [] }).state,
    ).toEqual(s);
    s.stats.hp = NaN;
    expect(() =>
      validateSave({ world: w, state: s, draft: null, snapshots: [] }),
    ).toThrow();
  });
});
describe("castle location", () => {
  it("castle objects belong to the castle and are validated there", () => {
    const w = createWorld();
    const castle = w.entities.filter((e) => e.theme === "castle");
    expect(castle.length).toBeGreaterThan(8);
    for (const e of castle) expect(validateWorld(w)).toEqual([]);
    const s = createState(w);
    for (const e of castle.filter((v) => v.kind !== "item"))
      expect(interact(w, { ...s, x: e.x, y: e.y + 1 }, e).effects).toEqual([
        { message: "Этот объект находится в другой локации." },
      ]);
    expect(findPath(w, s, 15, 5)).toEqual([]);
  });
  it("entering the castle switches location, portal works both ways", () => {
    const w = createWorld();
    const gate = w.entities.find((e) => e.id === "castle-gate")!;
    const exit = w.entities.find((e) => e.id === "castle-exit")!;
    let s = createState(w);
    s.x = gate.x + 1;
    s.y = gate.y;
    s = interact(w, s, gate).state;
    expect(s.theme).toBe("castle");
    expect([s.x, s.y]).toEqual([9, 8]);
    expect(canStand(w, s, 0, 1)).toBe(false);
    expect(canStand(w, s, 9, 7)).toBe(true);
    expect(canStand(w, createState(w), 12, 3)).toBe(false);
    expect(canStand(w, s, 12, 3)).toBe(true);
    const ember = w.entities.find((e) => e.id === "ember-1")!;
    const collected = interact(
      w,
      { ...s, x: ember.x - 1, y: ember.y },
      ember,
    ).state;
    expect(collected.inventory.ember).toBe(1);
    s = interact(w, { ...collected, x: exit.x + 1, y: exit.y }, exit).state;
    expect(s.theme).toBe("forest");
    expect([s.x, s.y]).toEqual([5, 4]);
  });
  it("lighting the lanterns needs three embers and pays once", () => {
    const w = createWorld();
    const lantern = w.entities.find((e) => e.id === "lantern-1")!;
    let s = createState(w);
    s.theme = "castle";
    s.x = lantern.x + 1;
    s.y = lantern.y;
    s = interact(w, s, lantern).state;
    expect(s.flags["lanterns-lit"]).toBeFalsy();
    s.inventory.ember = 3;
    const result = interact(w, s, lantern);
    expect(result.state.flags["lanterns-lit"]).toBe(true);
    expect(result.state.stats.xp).toBe(15);
    expect(result.effects.some((e) => e.openWindow === "castle-notes")).toBe(
      true,
    );
    const again = interact(w, result.state, lantern);
    expect(again.state.stats.xp).toBe(15);
    expect(again.effects).toEqual([]);
  });
  it("teleport accepts a location and rejects walls in the target location", () => {
    const w = createWorld();
    const s = createState(w);
    const moved = applyActions(w, s, [
      { type: "teleport", x: 9, y: 5, theme: "castle" },
    ]);
    expect(moved.state.theme).toBe("castle");
    expect([moved.state.x, moved.state.y]).toEqual([9, 5]);
    const wall = applyActions(w, s, [
      { type: "teleport", x: 0, y: 0, theme: "castle" },
    ]);
    expect(wall.state.theme).toBe("forest");
    expect(wall.effects.length).toBe(1);
  });
});

describe("manor garden with Rem, Ram, Emilia and Puck", () => {
  it("places every guest in the garden and keeps them off the island", () => {
    const w = createWorld();
    expect(validateWorld(w)).toEqual([]);
    for (const id of ["rem", "ram", "emilia", "puck", "roswaal"]) {
      const npc = w.entities.find((e) => e.id === id)!;
      expect(npc.theme).toBe("garden");
      expect(["npc"]).toContain(npc.kind);
      expect(tileAt(npc.x, npc.y, "garden")).not.toBe("hedge");
    }
    expect(
      w.entities.filter((e) => e.theme === "garden").length,
    ).toBeGreaterThanOrEqual(14);
  });
  it("garden portal works both ways and keeps the hero inside the walls", () => {
    const w = createWorld();
    const gate = w.entities.find((e) => e.id === "garden-gate")!;
    const exit = w.entities.find((e) => e.id === "garden-exit")!;
    let s = createState(w);
    s.x = gate.x - 1;
    s.y = gate.y;
    s = interact(w, s, gate).state;
    expect(s.theme).toBe("garden");
    expect([s.x, s.y]).toEqual([9, 9]);
    expect(canStand(w, s, 2, 2, "garden")).toBe(false);
    const rose = w.entities.find((e) => e.id === "rose-1")!;
    s = interact(w, { ...s, x: rose.x + 1, y: rose.y }, rose).state;
    expect(s.inventory.rose).toBe(1);
    s = interact(w, { ...s, x: exit.x + 1, y: exit.y }, exit).state;
    expect(s.theme).toBe("forest");
  });
  it("rose quest pays once and the spirit contract is reusable equipment", () => {
    const w = createWorld();
    const rem = w.entities.find((e) => e.id === "rem")!;
    const quest = w.quests.find((q) => q.id === "roses")!;
    let s = createState(w);
    s.theme = "garden";
    s.x = rem.x + 1;
    s.y = rem.y;
    s.quests.roses = "active";
    s.inventory.rose = 4;
    s = interact(w, s, rem).state;
    expect(s.quests.roses).toBe("completed");
    expect(s.stats.coins).toBe(20);
    expect(s.inventory["ice-crystal"]).toBe(1);
    const contract = useItem(
      w,
      { ...s, inventory: { ...s.inventory, "spirit-contract": 1 } },
      "spirit-contract",
    ).state;
    expect(contract.stats.attack).toBe(15);
    expect(contract.stats.defense).toBe(3);
    expect(contract.inventory["spirit-contract"]).toBe(1);
    expect(quest.count).toBe(4);
  });
});

describe("game mechanics", () => {
  it("movement cannot cross water, trees or solid entities and never mutates input", () => {
    const w = createWorld(),
      s = createState(w),
      before = clone(s);
    expect(move(w, { ...s, x: 11, y: 3 }, 1, 0).changed).toBe(false);
    expect(move(w, { ...s, x: 5, y: 6 }, 0, -1).changed).toBe(false);
    expect(canStand(w, s, 0, 0)).toBe(false);
    expect(move(w, s, 1, 0).state.x).toBe(5);
    expect(s).toEqual(before);
    expect(tileAt(12, 6)).toBe("bridge");
  });
  it("quest has atomic item consumption and exactly-once rewards", () => {
    const w = createWorld(),
      q = w.quests[0];
    let s = createState(w);
    expect(completeQuest(w, s, q).changed).toBe(false);
    s.quests[q.id] = "active";
    s.inventory.apple = 3;
    const result = completeQuest(w, s, q);
    s = result.state;
    expect(s.inventory.apple).toBeUndefined();
    expect(s.inventory.key).toBe(1);
    expect(s.stats.coins).toBe(25);
    expect(s.stats.xp).toBe(30);
    expect(s.quests[q.id]).toBe("completed");
    expect(completeQuest(w, s, q).state.stats.coins).toBe(25);
  });
  it("gate requires key and chest cannot be looted twice", () => {
    const w = createWorld(),
      gate = w.entities.find((e) => e.kind === "gate")!,
      chest = w.entities.find((e) => e.kind === "chest")!;
    let s = createState(w);
    s.x = gate.x - 1;
    s.y = gate.y;
    expect(interact(w, s, gate).state.opened).not.toContain(gate.id);
    s.inventory.key = 1;
    s = interact(w, s, gate).state;
    expect(s.opened).toContain(gate.id);
    s.x = chest.x;
    s.y = chest.y + 1;
    s = interact(w, s, chest).state;
    expect(s.stats.coins).toBe(40);
    expect(s.inventory.crystal).toBe(1);
    expect(interact(w, s, chest).state.stats.coins).toBe(40);
  });
  it("consumables consume one, equipment applies a persistent effect without consumption", () => {
    const w = createWorld();
    let s = createState(w);
    s.stats.hp = 50;
    s = useItem(w, s, "berry").state;
    expect(s.stats.hp).toBe(70);
    expect(s.inventory.berry).toBeUndefined();
    w.items.push({
      id: "charm",
      name: "Талисман",
      description: "",
      kind: "equipment",
      sprite: "coin",
      actions: [{ type: "stat", stat: "defense", op: "add", value: 3 }],
    });
    s.inventory.charm = 1;
    s = useItem(w, s, "charm").state;
    expect(s.stats.defense).toBe(5);
    expect(s.inventory.charm).toBe(1);
  });
  it("custom rule conditions, flags and nested window buttons work", () => {
    const w = createWorld();
    let s = createState(w);
    const b = (w.windows[0].buttons[0] = {
      id: "diary-btn",
      label: "Test",
      icon: "book",
      actions: [],
    });
    w.rules.push({
      id: "custom",
      name: "Test",
      enabled: true,
      trigger: { type: "button", target: b.id },
      conditions: [{ type: "flag", flag: "claimed", value: false }],
      actions: [
        { type: "stat", stat: "coins", op: "add", value: 7 },
        { type: "flag", flag: "claimed", value: true },
        { type: "window", window: "diary" },
      ],
    });
    expect(validateWorld(w)).toEqual([]);
    s = runRules(w, s, "button", b.id).state;
    expect(s.stats.coins).toBe(7);
    s = runRules(w, s, "button", b.id).state;
    expect(s.stats.coins).toBe(7);
  });
  it("bounded stats, enemy rewards and new stat migration", () => {
    const w = createWorld();
    let s = createState(w);
    const e = w.entities.find((e) => e.kind === "enemy")!;
    s.x = e.x - 1;
    s.y = e.y;
    for (let i = 0; i < 5 && !s.removed.includes(e.id); i++)
      s = attack(w, s, e).state;
    expect(s.removed).toContain(e.id);
    expect(s.stats.xp).toBe(15);
    expect(s.stats.hp).toBeGreaterThan(0);
    s = applyActions(w, s, [
      { type: "stat", stat: "hp", op: "add", value: 500 },
    ]).state;
    expect(s.stats.hp).toBe(100);
    w.stats.push({
      id: "luck",
      name: "Удача",
      initial: 4,
      min: 0,
      max: 10,
      color: "#aabbcc",
      icon: "star",
      visible: true,
    });
    expect(reconcileState(w, s).stats.luck).toBe(4);
  });
  it("collectibles disappear once and test state remains independent", () => {
    const w = createWorld(),
      s = createState(w),
      e = w.entities.find((e) => e.kind === "item")!;
    const result = collect(w, s, e);
    expect(result.state.inventory.apple).toBe(1);
    expect(collect(w, result.state, e).state.inventory.apple).toBe(1);
    expect(s.inventory.apple).toBeUndefined();
  });
});
