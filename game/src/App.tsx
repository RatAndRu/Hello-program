import { useCallback, useEffect, useRef, useState } from "react";
import {
  Sparkles,
  Compass,
  Hammer,
  Backpack,
  BookOpen,
  Settings2,
  ChevronRight,
  ArrowUpRight,
  ArrowLeft,
  Download,
  Upload,
  Check,
  CloudDownload,
  CircleHelp,
  Leaf,
  ArrowUp,
  ArrowDown,
  ArrowRight,
  Heart,
  Zap,
  Coins,
  Star,
  ScrollText,
  Gift,
  X,
  FlaskConical,
  ShieldCheck,
  Swords,
  MessageCircle,
  MapPin,
  Volume2,
  VolumeX,
  RotateCcw,
  CheckCircle2,
  Clock3,
  WandSparkles,
  ExternalLink,
  AlertCircle,
  Flag,
  Keyboard,
  Plus,
} from "lucide-react";
import {
  createWorld,
  createState,
  clone,
  reconcileState,
  uid,
  type SaveData,
  type World,
  type GameState,
  type Snapshot,
  type Entity,
  type Action,
} from "./model";
import {
  validateWorld,
  type Result,
  move,
  findPath,
  nearestInteraction,
  interact,
  attack,
  useItem,
  applyActions,
  runRules,
  canStand,
} from "./engine";
import { loadSave, persistSave, downloadWorld, readImport } from "./storage";
import { Sprite } from "./components/Sprite";
import { GameMap } from "./components/GameMap";
import { Studio, type StudioSection } from "./components/Studio";
import { Modal, StatIcon, buttonIcons, Empty } from "./components/UI";

type Dialog = {
  type:
    | "inventory"
    | "character"
    | "quests"
    | "journal"
    | "help"
    | "settings"
    | "entity"
    | "window";
  id?: string;
} | null;
export default function App() {
  const [save, setSave] = useState<SaveData | null>(null);
  const [loadError, setLoadError] = useState("");
  const [saveStatus, setSaveStatus] = useState<
    "loading" | "saving" | "saved" | "error"
  >("loading");
  const [mode, setMode] = useState<"play" | "studio">("play");
  const [section, setSection] = useState<StudioSection>("entities");
  const [testing, setTesting] = useState(false);
  const [testState, setTestState] = useState<GameState | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [toast, setToast] = useState("");
  const [undoStack, setUndoStack] = useState<World[]>([]);
  const [redoStack, setRedoStack] = useState<World[]>([]);
  const [sound, setSound] = useState(false);
  const [importing, setImporting] = useState(false);
  const importRef = useRef<HTMLInputElement>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const walkToken = useRef(0);
  const lastMove = useRef(0);
  const stateRef = useRef<GameState | null>(null);
  const saveVersion = useRef(0);
  const latestSave = useRef<SaveData | null>(null);
  latestSave.current = save;
  const audioRef = useRef<AudioContext | null>(null);
  const world = testing && save?.draft ? save.draft : save?.world;
  const state = testing && testState ? testState : save?.state;
  stateRef.current = state || null;

  const notify = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 4800);
  }, []);
  useEffect(() => {
    let active = true;
    loadSave()
      .then((data) => {
        if (active) {
          setSave(data);
          setSaveStatus("saved");
        }
      })
      .catch((e) => {
        if (active) {
          setLoadError(
            e instanceof Error
              ? e.message
              : "Браузер запретил локальное хранилище.",
          );
          setSaveStatus("error");
        }
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    const flush = () => {
      if (latestSave.current)
        void persistSave(latestSave.current).catch(() => {});
    };
    const hidden = () => {
      if (document.visibilityState === "hidden") flush();
    };
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", hidden);
    return () => {
      window.removeEventListener("pagehide", flush);
      document.removeEventListener("visibilitychange", hidden);
    };
  }, []);
  useEffect(() => {
    if (!save) return;
    const version = ++saveVersion.current;
    setSaveStatus("saving");
    const timer = setTimeout(() => {
      persistSave(save)
        .then(() => {
          if (version === saveVersion.current) setSaveStatus("saved");
        })
        .catch(() => {
          if (version === saveVersion.current) {
            setSaveStatus("error");
            notify(
              "Не удалось сохранить в браузере. Скачай резервную копию через меню настроек.",
            );
          }
        });
    }, 250);
    return () => clearTimeout(timer);
  }, [save, notify]);
  useEffect(
    () => () => {
      walkToken.current++;
      if (toastTimer.current) clearTimeout(toastTimer.current);
      audioRef.current?.close();
    },
    [],
  );
  useEffect(() => {
    walkToken.current++;
  }, [mode, testing]);
  useEffect(() => {
    if (dialog) walkToken.current++;
  }, [dialog]);

  function playSound(kind: string) {
    if (!sound) return;
    try {
      const ctx = audioRef.current || new AudioContext();
      audioRef.current = ctx;
      void ctx.resume();
      const oscillator = ctx.createOscillator(),
        gain = ctx.createGain();
      oscillator.connect(gain);
      gain.connect(ctx.destination);
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(
        kind === "hit" ? 170 : kind === "success" ? 660 : 520,
        ctx.currentTime,
      );
      oscillator.frequency.exponentialRampToValueAtTime(
        kind === "hit" ? 90 : 880,
        ctx.currentTime + 0.12,
      );
      gain.gain.setValueAtTime(0.045, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.2);
      oscillator.start();
      oscillator.stop(ctx.currentTime + 0.21);
    } catch {
      /* Audio is optional; gameplay never depends on it. */
    }
  }
  function setGame(next: GameState) {
    stateRef.current = next;
    if (testing) setTestState(next);
    else setSave((s) => (s ? { ...s, state: next } : s));
  }
  function apply(result: Result, silent = false) {
    setGame(result.state);
    if (!silent) {
      const messages = result.effects.filter((e) => e.message);
      if (messages.length) notify(messages.map((e) => e.message).join(" "));
      const panel = result.effects
        .filter((e) => e.openWindow)
        .at(-1)?.openWindow;
      if (panel) setDialog({ type: "window", id: panel });
      const effect = result.effects.find((e) => e.sound);
      if (effect?.sound) playSound(effect.sound);
    }
  }
  function doMove(dx: number, dy: number) {
    if (!world || !stateRef.current || dialog) return;
    walkToken.current++;
    apply(move(world, stateRef.current, dx, dy));
  }
  function openEntity(e: Entity) {
    if (!world || !stateRef.current) return;
    const result = interact(world, stateRef.current, e);
    apply(result);
    if (
      !result.effects.some((effect) => effect.openWindow) &&
      (["npc", "enemy", "decoration"].includes(e.kind) ||
        (e.kind === "gate" && !result.state.opened.includes(e.id)))
    )
      setDialog({ type: "entity", id: e.id });
  }
  function walkTo(tx: number, ty: number, entity?: Entity) {
    if (!world || !state || mode !== "play") return;
    const token = ++walkToken.current;
    let paths: [number, number][] = [];
    if (entity) {
      const options = [
        [1, 0],
        [-1, 0],
        [0, 1],
        [0, -1],
      ]
        .map(([dx, dy]) => findPath(world, state, entity.x + dx, entity.y + dy))
        .filter((p) => p.length);
      if (Math.abs(entity.x - state.x) + Math.abs(entity.y - state.y) <= 1) {
        openEntity(entity);
        return;
      }
      options.sort((a, b) => a.length - b.length);
      paths = options[0] || [];
      if (!paths.length) {
        notify(
          "К объекту пока нет прохода. Попробуй открыть ворота или обойти препятствие.",
        );
        return;
      }
    } else {
      paths = findPath(world, state, tx, ty);
      if (!paths.length) {
        notify("Туда пока нельзя пройти. Выбери свободную клетку.");
        return;
      }
    }
    const run = async () => {
      for (const [dx, dy] of paths) {
        await new Promise((resolve) => setTimeout(resolve, 105));
        if (token !== walkToken.current || !stateRef.current) return;
        const result = move(world, stateRef.current, dx, dy);
        if (!result.changed) break;
        apply(result);
      }
      if (entity && token === walkToken.current) openEntity(entity);
    };
    void run();
  }
  function handleEntity(id: string) {
    const e = world?.entities.find((e) => e.id === id);
    if (e) walkTo(e.x, e.y, e);
  }
  function doInteract() {
    if (!world || !state) return;
    walkToken.current++;
    const e = nearestInteraction(world, state);
    if (e) openEntity(e);
    else notify("Подойди к персонажу или предмету и нажми E.");
  }
  useEffect(() => {
    const keydown = (e: KeyboardEvent) => {
      if (
        mode !== "play" ||
        dialog ||
        !world ||
        !state ||
        e.ctrlKey ||
        e.metaKey ||
        e.altKey ||
        (e.target instanceof HTMLElement &&
          (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName) ||
            e.target.isContentEditable))
      )
        return;
      const dirs: Record<string, [number, number]> = {
        ArrowUp: [0, -1],
        KeyW: [0, -1],
        ArrowDown: [0, 1],
        KeyS: [0, 1],
        ArrowLeft: [-1, 0],
        KeyA: [-1, 0],
        ArrowRight: [1, 0],
        KeyD: [1, 0],
      };
      if (dirs[e.code]) {
        e.preventDefault();
        if (Date.now() - lastMove.current < 90) return;
        lastMove.current = Date.now();
        doMove(...dirs[e.code]);
      }
      if (e.code === "KeyE") {
        e.preventDefault();
        doInteract();
      }
      if (e.code === "KeyI") {
        e.preventDefault();
        setDialog({ type: "inventory" });
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  });
  function execute(actions: Action[], id: string) {
    if (!world || !state) return;
    const a = applyActions(world, state, actions);
    const b = runRules(world, a.state, "button", id);
    apply({
      state: b.state,
      effects: [...a.effects, ...b.effects],
      changed: a.changed || b.changed,
    });
    if (!a.effects.length && !b.effects.length)
      notify(
        "Кнопка нажата. Добавь действие или связанное правило в мастерской.",
      );
  }
  function enterStudio() {
    if (!save) return;
    setDialog(null);
    setTesting(false);
    setTestState(null);
    setMode("studio");
    if (!save.draft) setSave((s) => (s ? { ...s, draft: clone(s.world) } : s));
  }
  function updateDraft(next: World) {
    if (!save?.draft) return;
    setUndoStack((s) => [...s.slice(-39), clone(save.draft!)]);
    setRedoStack([]);
    setSave((s) => (s ? { ...s, draft: next } : s));
  }
  function undo() {
    if (!save?.draft || !undoStack.length) return;
    const prev = undoStack.at(-1)!;
    setRedoStack((s) => [...s, clone(save.draft!)]);
    setUndoStack((s) => s.slice(0, -1));
    setSave((s) => (s ? { ...s, draft: clone(prev) } : s));
  }
  function redo() {
    if (!save?.draft || !redoStack.length) return;
    const next = redoStack.at(-1)!;
    setUndoStack((s) => [...s, clone(save.draft!)]);
    setRedoStack((s) => s.slice(0, -1));
    setSave((s) => (s ? { ...s, draft: clone(next) } : s));
  }
  function snapshot(label: string, base = save): Snapshot | null {
    if (!base) return null;
    return {
      id: uid("ver"),
      date: new Date().toISOString(),
      label,
      world: clone(base.world),
      state: clone(base.state),
    };
  }
  function saveSnapshot(label: string) {
    const s = snapshot(label);
    if (!s || !save) return;
    setSave({ ...save, snapshots: [s, ...save.snapshots].slice(0, 8) });
    notify("Резервная копия создана в этом браузере.");
  }
  function publish() {
    if (!save?.draft) return;
    const errors = validateWorld(save.draft);
    if (errors.length) {
      notify(errors[0]);
      return;
    }
    const snapshotBefore = snapshot(
      `До публикации версии ${save.world.revision + 1}`,
    )!;
    const published = {
      ...clone(save.draft),
      revision: save.world.revision + 1,
    };
    setSave({
      ...save,
      world: published,
      state: reconcileState(published, save.state),
      draft: null,
      snapshots: [snapshotBefore, ...save.snapshots].slice(0, 8),
    });
    setUndoStack([]);
    setRedoStack([]);
    setTesting(false);
    setTestState(null);
    setMode("play");
    notify(
      `Версия ${published.revision} опубликована. Твои идеи теперь часть мира!`,
    );
    playSound("success");
  }
  function restore(s: Snapshot) {
    if (!save) return;
    const before = snapshot("Перед восстановлением")!;
    setSave({
      ...save,
      world: clone(s.world),
      state: clone(s.state),
      draft: null,
      snapshots: [before, ...save.snapshots].slice(0, 8),
    });
    setTesting(false);
    setTestState(null);
    setMode("play");
    setUndoStack([]);
    setRedoStack([]);
    notify("Версия мира и прогресс восстановлены.");
  }
  function exportCurrent() {
    if (!save) return;
    downloadWorld(
      testing && save.draft ? save.draft : save.world,
      state || save.state,
    );
    notify(
      "Файл мира подготовлен к скачиванию. Храни его как резервную копию.",
    );
  }
  async function importFile(file?: File) {
    if (!file || !save) return;
    setImporting(true);
    try {
      const imported = readImportGuard(await readImport(file));
      if (
        !confirm(
          `Импортировать «${imported.world.name}»? Текущий мир и прогресс будут заменены. Перед заменой создастся резервная копия.`,
        )
      )
        return;
      const before = snapshot("Перед импорта мира")!;
      setSave({
        world: imported.world,
        state: imported.state,
        draft: null,
        snapshots: [before, ...save.snapshots].slice(0, 8),
      });
      setMode("play");
      setTesting(false);
      setTestState(null);
      setDialog(null);
      setUndoStack([]);
      setRedoStack([]);
      notify("Мир импортирован. Можно продолжать приключение!");
    } catch (e) {
      notify(e instanceof Error ? e.message : "Не удалось импортировать мир.");
    } finally {
      setImporting(false);
      if (importRef.current) importRef.current.value = "";
    }
  }
  function readImportGuard(s: SaveData) {
    if (validateWorld(s.world).length)
      throw new Error("Мир не прошёл проверку.");
    return s;
  }
  function freshStart() {
    const w = createWorld();
    setSave({ world: w, state: createState(w), draft: null, snapshots: [] });
    setLoadError("");
    setSaveStatus("saving");
  }

  if (!save || !world || !state)
    return (
      <div className="loading-screen">
        <div className="loading-mark">
          <Sparkles size={38} />
        </div>
        <h1>Мастерская приключений</h1>
        {loadError ? (
          <>
            <p>Не удалось открыть локальное сохранение.</p>
            <div className="load-error">{loadError}</div>
            <p className="muted">
              Можно начать заново. Существующие данные не будут перезаписаны,
              пока ты не подтвердишь действие.
            </p>
            <button
              className="button primary"
              onClick={() => {
                if (
                  confirm(
                    "Создать новый мир и заменить нечитаемое сохранение? Если есть файл мира, сначала отмени и попробуй импортировать его после запуска.",
                  )
                )
                  freshStart();
              }}
            >
              Создать новый мир
            </button>
          </>
        ) : (
          <>
            <p>Открываем твой маленький мир…</p>
            <span className="loading-line" />
          </>
        )}
      </div>
    );

  const activeQuest =
    world.quests.find((q) => state.quests[q.id] === "active") ||
    world.quests.find((q) => state.quests[q.id] !== "completed");
  const questProgress = activeQuest
    ? Math.min(activeQuest.count, state.inventory[activeQuest.itemId] || 0)
    : 0;
  const visibleStats = world.stats.filter(
    (s) => s.visible && !["hp", "energy"].includes(s.id),
  );
  const hp = world.stats.find((s) => s.id === "hp"),
    energy = world.stats.find((s) => s.id === "energy");
  const level = Math.floor((state.stats.xp || 0) / 100) + 1;
  const entity =
    dialog?.type === "entity"
      ? world.entities.find((e) => e.id === dialog.id)
      : undefined;
  const customWindow =
    dialog?.type === "window"
      ? world.windows.find((w) => w.id === dialog.id)
      : undefined;
  const inventory = world.items.filter((i) => (state.inventory[i.id] || 0) > 0);
  const asset = (id?: string) => world.assets.find((a) => a.id === id)?.data;
  const dialogTitles: Record<string, string> = {
    inventory: "Твой рюкзак",
    character: "Карточка хранителя",
    quests: "Книга заданий",
    journal: "Дневник приключения",
    help: "Как устроен этот мир",
    settings: "Твой мир под защитой",
  };

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setMode("play");
            setDialog(null);
          }}
        >
          <span className="brand-mark">
            <Sparkles size={27} strokeWidth={1.6} />
          </span>
          <span>
            Мастерская<small>ПРИКЛЮЧЕНИЙ</small>
          </span>
        </a>
        <div className="world-switch">
          <span className="world-avatar">
            <Leaf size={20} />
          </span>
          <div>
            <strong>{world.name}</strong>
            <small>Твой личный мир</small>
          </div>
          <span className="world-version">v{world.revision}</span>
        </div>
        <span className="nav-caption">ПРИКЛЮЧЕНИЕ</span>
        <nav className="main-nav" aria-label="Основная навигация">
          <button
            className={mode === "play" && !dialog ? "active" : ""}
            onClick={() => {
              setMode("play");
              setDialog(null);
            }}
          >
            <Compass size={19} />
            <span>Исследовать мир</span>
            <span className="nav-active-dot" />
          </button>
          <button
            className={dialog?.type === "character" ? "active" : ""}
            onClick={() => setDialog({ type: "character" })}
          >
            <ShieldCheck size={19} />
            <span>Мой персонаж</span>
          </button>
          <button
            className={dialog?.type === "quests" ? "active" : ""}
            onClick={() => setDialog({ type: "quests" })}
          >
            <ScrollText size={19} />
            <span>Задания</span>
            <small>
              {
                world.quests.filter((q) => state.quests[q.id] !== "completed")
                  .length
              }
            </small>
          </button>
          <button
            className={dialog?.type === "inventory" ? "active" : ""}
            onClick={() => setDialog({ type: "inventory" })}
          >
            <Backpack size={19} />
            <span>Рюкзак</span>
          </button>
          <button
            className={dialog?.type === "journal" ? "active" : ""}
            onClick={() => setDialog({ type: "journal" })}
          >
            <BookOpen size={19} />
            <span>Дневник</span>
          </button>
        </nav>
        <div className="sidebar-divider" />
        <span className="nav-caption">СОЗДАВАЙ</span>
        <nav className="main-nav">
          <button
            className={mode === "studio" ? "active" : ""}
            onClick={enterStudio}
          >
            <Hammer size={19} />
            <span>Мастерская мира</span>
            <span className="new-badge">ТВОРЁМ</span>
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="grow-card">
            <div className="grow-art">
              <Sprite name="flower" />
              <Sparkles size={17} />
            </div>
            <strong>
              Маленький мир.
              <br />
              Большие возможности.
            </strong>
            <p>
              Сегодня — яблоко.
              <br />
              Завтра — целая история.
            </p>
            <button
              onClick={() => {
                setSection("entities");
                enterStudio();
              }}
            >
              Придумать что-нибудь <ArrowUpRight size={15} />
            </button>
          </div>
          <button
            className="sidebar-help"
            onClick={() => setDialog({ type: "help" })}
          >
            <CircleHelp size={18} /> Как это работает <ArrowUpRight size={14} />
          </button>
          <div className="sidebar-profile">
            <span className="profile-avatar">
              <Sprite name={world.heroSprite} src={asset(world.heroAssetId)} />
            </span>
            <div>
              <strong>Хранитель мира</strong>
              <small>Игрок и создатель</small>
            </div>
            <button
              className="icon-button"
              aria-label="Настройки"
              onClick={() => setDialog({ type: "settings" })}
            >
              <Settings2 size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Твои миры</span>
            <ChevronRight size={13} />
            <strong>{world.name}</strong>
            <span className="local-badge">Локально</span>
          </div>
          <div className="topbar-actions">
            <span className={`save-status status-${saveStatus}`}>
              <span className="status-dot" />
              {saveStatus === "saved"
                ? "Сохранено в браузере"
                : saveStatus === "saving"
                  ? "Сохраняем…"
                  : "Нужна резервная копия"}
            </span>
            <span className="toolbar-divider" />
            <button
              className="icon-button"
              title="Экспортировать мир"
              aria-label="Скачать резервную копию"
              onClick={exportCurrent}
            >
              <Download size={18} />
            </button>
            <button
              className="icon-button"
              title="Настройки и импорт"
              aria-label="Настройки и импорт"
              onClick={() => setDialog({ type: "settings" })}
            >
              <Settings2 size={18} />
            </button>
          </div>
        </header>
        <input
          ref={importRef}
          type="file"
          accept=".json,application/json"
          hidden
          onChange={(e) => importFile(e.target.files?.[0])}
        />
        {testing && (
          <div className="test-banner">
            <FlaskConical size={18} />
            <strong>Тестовая копия мира</strong>
            <span>Экспериментируй: основной прогресс не меняется.</span>
            <button
              onClick={() => {
                setTesting(false);
                setTestState(null);
                setMode("studio");
                setDialog(null);
              }}
            >
              <ArrowLeft size={15} /> Вернуться в мастерскую
            </button>
          </div>
        )}
        {mode === "studio" && save.draft ? (
          <Studio
            world={save.draft}
            onChange={updateDraft}
            onBack={() => setMode("play")}
            onTest={() => {
              const errors = validateWorld(save.draft!);
              if (errors.length) {
                notify(errors[0]);
                return;
              }
              setTestState(reconcileState(save.draft!, clone(save.state)));
              setTesting(true);
              setMode("play");
              setDialog(null);
              notify(
                "Тест запущен на копии прогресса. Результаты не затронут основное приключение.",
              );
            }}
            onPublish={publish}
            onDiscard={() => {
              if (
                confirm("Удалить черновик и вернуться к опубликованному миру?")
              ) {
                setSave((s) => (s ? { ...s, draft: null } : s));
                setUndoStack([]);
                setRedoStack([]);
                notify("Черновик сброшен. Опубликованный мир не изменён.");
              }
            }}
            dirty={JSON.stringify(save.draft) !== JSON.stringify(save.world)}
            canUndo={!!undoStack.length}
            canRedo={!!redoStack.length}
            onUndo={undo}
            onRedo={redo}
            snapshots={save.snapshots}
            onSnapshot={saveSnapshot}
            onRestore={restore}
            onExport={exportCurrent}
            notify={notify}
            section={section}
            setSection={setSection}
          />
        ) : (
          <main className="play-page animate-in">
            <div className="page-heading">
              <div>
                <div className="eyebrow">
                  <span className="tiny-spark">✦</span> ГЛАВА I · НАЧАЛО БОЛЬШОЙ
                  ИСТОРИИ
                </div>
                <h1>
                  {world.name}
                  <span className="heading-leaf">
                    <Leaf size={24} />
                  </span>
                </h1>
                <p>Здесь каждое открытие — начало чего-то большего.</p>
              </div>
              <button
                className="button primary workshop-cta"
                onClick={enterStudio}
              >
                <Hammer size={17} /> Открыть мастерскую{" "}
                <ArrowUpRight size={16} />
              </button>
            </div>
            <div className="play-layout">
              <div className="play-center">
                <GameMap
                  world={world}
                  state={state}
                  onTile={(x, y) => walkTo(x, y)}
                  onEntity={handleEntity}
                />
                <div className="quick-actions">
                  <div className="quick-actions-label">
                    <Sparkles size={15} />
                    <span>ТВОИ ДЕЙСТВИЯ</span>
                  </div>
                  <div className="quick-buttons">
                    <button
                      className="quick-button"
                      onClick={() => setDialog({ type: "inventory" })}
                    >
                      <Backpack size={19} />
                      <span>Рюкзак</span>
                      <kbd>I</kbd>
                    </button>
                    {world.buttons.map((b) => {
                      const Icon = buttonIcons[b.icon] || Sparkles;
                      return (
                        <button
                          className="quick-button"
                          key={b.id}
                          onClick={() => execute(b.actions, b.id)}
                        >
                          <Icon size={18} />
                          <span>{b.label}</span>
                        </button>
                      );
                    })}
                    <button
                      className="quick-button add-action"
                      onClick={() => {
                        setSection("interface");
                        enterStudio();
                      }}
                      title="Создать свою кнопку"
                    >
                      <Plus size={18} />
                      <span>Своё действие</span>
                    </button>
                  </div>
                </div>
                <div className="journey-note">
                  <span className="note-icon">
                    <WandSparkles size={22} />
                  </span>
                  <div>
                    <strong>Этот мир умеет расти вместе с тобой</strong>
                    <p>
                      Новый персонаж, предмет или целая механика — всё
                      начинается с твоей идеи.
                    </p>
                  </div>
                  <button
                    onClick={() => {
                      setSection("rules");
                      enterStudio();
                    }}
                  >
                    Попробовать <ArrowRight size={16} />
                  </button>
                </div>
                <div className="mobile-controls">
                  <div className="d-pad">
                    <button
                      aria-label="Идти вверх"
                      onClick={() => doMove(0, -1)}
                    >
                      <ArrowUp size={21} />
                    </button>
                    <button
                      aria-label="Идти влево"
                      onClick={() => doMove(-1, 0)}
                    >
                      <ArrowLeft size={21} />
                    </button>
                    <button aria-label="Идти вниз" onClick={() => doMove(0, 1)}>
                      <ArrowDown size={21} />
                    </button>
                    <button
                      aria-label="Идти вправо"
                      onClick={() => doMove(1, 0)}
                    >
                      <ArrowRight size={21} />
                    </button>
                  </div>
                  <button className="button secondary" onClick={doInteract}>
                    <MessageCircle size={18} /> Действие <kbd>E</kbd>
                  </button>
                </div>
              </div>
              <aside className="game-right">
                <section className="hero-card">
                  <div className="card-eyebrow">
                    <span>ТВОЙ ПЕРСОНАЖ</span>
                    <button
                      className="icon-button"
                      aria-label="Открыть персонажа"
                      onClick={() => setDialog({ type: "character" })}
                    >
                      <ArrowUpRight size={16} />
                    </button>
                  </div>
                  <div className="hero-identity">
                    <div className="hero-portrait">
                      <Sprite
                        name={world.heroSprite}
                        src={asset(world.heroAssetId)}
                      />
                      <span>{level}</span>
                    </div>
                    <div>
                      <h2>Хранитель</h2>
                      <p>Искатель приключений</p>
                      <span className="level-label">
                        <Sparkles size={12} /> Уровень {level}
                      </span>
                    </div>
                  </div>
                  <div className="vitals">
                    {[hp, energy].filter(Boolean).map(
                      (s) =>
                        s && (
                          <div className="vital" key={s.id}>
                            <div>
                              <span>
                                <StatIcon stat={s} size={13} />
                                {s.name}
                              </span>
                              <strong>
                                {state.stats[s.id]} <small>/ {s.max}</small>
                              </strong>
                            </div>
                            <div className="progress-track">
                              <span
                                style={{
                                  width: `${Math.max(0, Math.min(100, ((state.stats[s.id] - s.min) / (s.max - s.min || 1)) * 100))}%`,
                                  background: s.color,
                                }}
                              />
                            </div>
                          </div>
                        ),
                    )}
                  </div>
                  <div className="hero-stat-grid">
                    {visibleStats.map((s) => (
                      <div key={s.id}>
                        <span style={{ color: s.color }}>
                          <StatIcon stat={s} size={16} />
                        </span>
                        <strong>{state.stats[s.id]}</strong>
                        <small>{s.name}</small>
                      </div>
                    ))}
                  </div>
                  <div className="xp-line">
                    <span>До следующего уровня</span>
                    <strong>{(state.stats.xp || 0) % 100} / 100</strong>
                  </div>
                  <div className="progress-track xp-track">
                    <span
                      style={{ width: `${(state.stats.xp || 0) % 100}%` }}
                    />
                  </div>
                </section>
                <section className="quest-card">
                  <div className="card-eyebrow">
                    <span>
                      <ScrollText size={14} /> ТВОЁ ПРИКЛЮЧЕНИЕ
                    </span>
                    <span className="quest-status-dot" />
                  </div>
                  {activeQuest ? (
                    <>
                      <div className="quest-title">
                        <span className="quest-icon">
                          <Leaf size={21} />
                        </span>
                        <div>
                          <span className="quest-category">
                            {state.quests[activeQuest.id] === "active"
                              ? "В процессе"
                              : "Первое задание"}
                          </span>
                          <h3>{activeQuest.name}</h3>
                        </div>
                      </div>
                      <p>{activeQuest.description}</p>
                      <div className="quest-objective">
                        <span
                          className={`objective-check ${questProgress >= activeQuest.count ? "complete" : ""}`}
                        >
                          {questProgress >= activeQuest.count ? (
                            <Check size={12} />
                          ) : null}
                        </span>
                        <span>
                          Собрать {spriteLabelsName(world, activeQuest.itemId)}
                        </span>
                        <strong>
                          {questProgress}/{activeQuest.count}
                        </strong>
                      </div>
                      <div className="quest-reward">
                        <span>Награда</span>
                        <strong>
                          <Coins size={14} /> {activeQuest.coins}
                        </strong>
                        <strong>
                          <Star size={14} /> {activeQuest.xp}
                        </strong>
                        {activeQuest.rewardItemId && (
                          <Sprite
                            name={
                              world.items.find(
                                (i) => i.id === activeQuest.rewardItemId,
                              )?.sprite || "key"
                            }
                          />
                        )}
                      </div>
                      <button
                        className="quest-link"
                        onClick={() => setDialog({ type: "quests" })}
                      >
                        Открыть задания <ArrowRight size={15} />
                      </button>
                    </>
                  ) : (
                    <div className="all-quests-done">
                      <CheckCircle2 size={27} />
                      <h3>Все задания выполнены!</h3>
                      <p>Самое время придумать новое.</p>
                      <button
                        className="text-button"
                        onClick={() => {
                          setSection("quests");
                          enterStudio();
                        }}
                      >
                        Создать задание <Plus size={14} />
                      </button>
                    </div>
                  )}
                </section>
                <section className="backpack-card">
                  <div className="card-eyebrow">
                    <span>
                      <Backpack size={14} /> ПОД РУКОЙ
                    </span>
                    <button
                      className="text-button"
                      onClick={() => setDialog({ type: "inventory" })}
                    >
                      Всё <ArrowUpRight size={13} />
                    </button>
                  </div>
                  <div className="inventory-preview">
                    {inventory.slice(0, 4).map((i) => (
                      <button
                        key={i.id}
                        title={i.name}
                        aria-label={`${i.name}, ${state.inventory[i.id]} шт.`}
                        onClick={() => {
                          setDialog({ type: "inventory" });
                        }}
                      >
                        <Sprite name={i.sprite} src={asset(i.assetId)} />
                        <span>{state.inventory[i.id]}</span>
                      </button>
                    ))}
                    {Array.from(
                      { length: Math.max(0, 4 - inventory.length) },
                      (_, i) => (
                        <button
                          key={`empty-${i}`}
                          className="empty-slot"
                          aria-label="Открыть рюкзак"
                          onClick={() => setDialog({ type: "inventory" })}
                        >
                          <Plus size={15} />
                        </button>
                      ),
                    )}
                  </div>
                </section>
              </aside>
            </div>
            <footer className="page-footer">
              <span>
                <Leaf size={13} /> Создано для твоих идей. Сохраняется на твоём
                устройстве.
              </span>
              <button onClick={() => setDialog({ type: "help" })}>
                Маленькая подсказка <CircleHelp size={14} />
              </button>
            </footer>
          </main>
        )}
      </div>
      {toast && (
        <div className="toast" role="status">
          <span className="toast-icon">
            <Sparkles size={19} />
          </span>
          <span>{toast}</span>
          <button
            className="icon-button"
            onClick={() => setToast("")}
            aria-label="Закрыть уведомление"
          >
            <X size={16} />
          </button>
        </div>
      )}
      {dialog && (
        <Modal
          title={
            dialog.type === "entity"
              ? entity?.name || "Взаимодействие"
              : dialog.type === "window"
                ? customWindow?.title || "Окно"
                : dialogTitles[dialog.type]
          }
          onClose={() => setDialog(null)}
          wide={["inventory", "quests", "help"].includes(dialog.type)}
        >
          {dialog.type === "inventory" && (
            <>
              <p className="modal-intro">
                Всё, что ты нашёл в приключении. Нажми на предмет, чтобы узнать
                больше или использовать его.
              </p>
              <div className="inventory-grid">
                {inventory.map((i) => (
                  <article className="inventory-item" key={i.id}>
                    <div className="inventory-item-art">
                      <Sprite name={i.sprite} src={asset(i.assetId)} />
                      <span>× {state.inventory[i.id]}</span>
                    </div>
                    <h3>{i.name}</h3>
                    <p>{i.description}</p>
                    <button
                      className={`button small ${i.kind === "consumable" || i.kind === "equipment" ? "primary" : "secondary"}`}
                      onClick={() => apply(useItem(world, state, i.id))}
                    >
                      {i.kind === "consumable"
                        ? "Использовать"
                        : i.kind === "equipment"
                          ? "Применить"
                          : "Подробнее"}
                    </button>
                  </article>
                ))}
              </div>
              {!inventory.length && (
                <Empty
                  icon={<Backpack size={28} />}
                  title="Пока легко и свободно"
                  text="Исследуй карту: предметы появятся здесь после подбора."
                />
              )}
            </>
          )}
          {dialog.type === "character" && (
            <>
              <div className="character-modal-hero">
                <Sprite
                  name={world.heroSprite}
                  src={asset(world.heroAssetId)}
                />
                <div>
                  <span className="eyebrow">ИГРОК И СОЗДАТЕЛЬ</span>
                  <h2>Хранитель · уровень {level}</h2>
                  <p>{state.steps} шагов навстречу открытиям</p>
                </div>
              </div>
              <div className="character-stats">
                {world.stats.map((s) => (
                  <div key={s.id}>
                    <span style={{ color: s.color }}>
                      <StatIcon stat={s} size={21} />
                    </span>
                    <span>{s.name}</span>
                    <strong>
                      {state.stats[s.id]}
                      {["hp", "energy"].includes(s.id) ? ` / ${s.max}` : ""}
                    </strong>
                  </div>
                ))}
              </div>
              <button
                className="button secondary"
                onClick={() => {
                  setDialog(null);
                  setSection("stats");
                  enterStudio();
                }}
              >
                <Plus size={16} /> Добавить свою характеристику
              </button>
            </>
          )}
          {dialog.type === "quests" && (
            <div className="quest-list">
              {world.quests.map((q) => {
                const status = state.quests[q.id],
                  count = Math.min(q.count, state.inventory[q.itemId] || 0),
                  giver = world.entities.find((e) => e.questId === q.id);
                return (
                  <article
                    className={`quest-detail ${status === "completed" ? "quest-completed" : ""}`}
                    key={q.id}
                  >
                    <div className="quest-detail-top">
                      <span className="quest-icon">
                        {status === "completed" ? (
                          <CheckCircle2 size={22} />
                        ) : (
                          <ScrollText size={22} />
                        )}
                      </span>
                      <div>
                        <span className="eyebrow">
                          {status === "completed"
                            ? "ВЫПОЛНЕНО"
                            : status === "active"
                              ? "В ПРОЦЕССЕ"
                              : "НОВОЕ ЗАДАНИЕ"}
                        </span>
                        <h3>{q.name}</h3>
                      </div>
                    </div>
                    <p>{q.description}</p>
                    <div className="quest-detail-progress">
                      <span>
                        {world.items.find((i) => i.id === q.itemId)?.name}
                      </span>
                      <strong>
                        {status === "completed" ? q.count : count} / {q.count}
                      </strong>
                    </div>
                    <div className="progress-track">
                      <span
                        style={{
                          width: `${status === "completed" ? 100 : (count / q.count) * 100}%`,
                        }}
                      />
                    </div>
                    <div className="quest-detail-bottom">
                      <span>
                        <Coins size={15} /> {q.coins} <Star size={15} /> {q.xp}
                      </span>
                      {giver && status !== "completed" && (
                        <button
                          className="button small secondary"
                          onClick={() => {
                            setDialog(null);
                            walkTo(giver.x, giver.y, giver);
                          }}
                        >
                          <MapPin size={14} /> К персонажу
                        </button>
                      )}
                      {status === "completed" && (
                        <span className="completed-label">
                          <Check size={14} /> Награда получена
                        </span>
                      )}
                    </div>
                  </article>
                );
              })}
              {!world.quests.length && (
                <Empty
                  title="Придумай первое задание"
                  text="Открой мастерскую, создай цель и назначь персонажа."
                />
              )}
            </div>
          )}
          {dialog.type === "entity" && entity && (
            <div className="entity-dialog">
              <div
                className={`dialog-portrait ${entity.kind === "enemy" ? "enemy-portrait" : ""}`}
              >
                <Sprite name={entity.sprite} src={asset(entity.assetId)} />
              </div>
              <p className="dialog-speech">
                {entity.dialogue || "Этот объект хранит свою историю."}
              </p>
              {entity.kind === "enemy" &&
                !state.removed.includes(entity.id) && (
                  <>
                    <div className="enemy-health">
                      <Heart size={16} />
                      <span>Здоровье противника</span>
                      <strong>
                        {state.entityStats[entity.id]?.hp ?? entity.stats.hp} /{" "}
                        {entity.stats.hp}
                      </strong>
                    </div>
                    <button
                      className="button primary full-width"
                      onClick={() => apply(attack(world, state, entity))}
                    >
                      <Swords size={17} /> Атаковать · сила {state.stats.attack}
                    </button>
                    <p className="muted small">
                      Противник ответит ударом. Защита уменьшает урон. За победу
                      — опыт и монеты.
                    </p>
                  </>
                )}
              {entity.kind === "npc" &&
                entity.questId &&
                (() => {
                  const q = world.quests.find((q) => q.id === entity.questId);
                  if (!q) return null;
                  const status = state.quests[q.id];
                  return (
                    <div className="dialog-quest">
                      <span className="eyebrow">ЗАДАНИЕ</span>
                      <h3>{q.name}</h3>
                      <p>{q.description}</p>
                      {status === "available" ? (
                        <button
                          className="button primary full-width"
                          onClick={() => {
                            setGame({
                              ...state,
                              quests: { ...state.quests, [q.id]: "active" },
                            });
                            notify(`Задание «${q.name}» принято!`);
                            setDialog(null);
                          }}
                        >
                          <ScrollText size={17} /> Взяться за дело
                        </button>
                      ) : status === "active" ? (
                        <button
                          className="button primary full-width"
                          disabled={(state.inventory[q.itemId] || 0) < q.count}
                          onClick={() => apply(interact(world, state, entity))}
                        >
                          <Gift size={17} />
                          {(state.inventory[q.itemId] || 0) < q.count
                            ? `Нужно ещё ${q.count - (state.inventory[q.itemId] || 0)} предметов`
                            : "Передать предметы и получить награду"}
                        </button>
                      ) : (
                        <div className="quest-thanks">
                          <CheckCircle2 size={19} /> Спасибо, хранитель! Ты
                          отлично справился.
                        </div>
                      )}
                    </div>
                  );
                })()}
              {entity.kind === "gate" && (
                <button
                  className="button primary full-width"
                  onClick={() => {
                    const result = interact(world, state, entity);
                    apply(result);
                    if (result.state.opened.includes(entity.id))
                      setDialog(null);
                  }}
                >
                  Попробовать открыть
                </button>
              )}
              {entity.kind === "decoration" && (
                <button
                  className="button secondary full-width"
                  onClick={() => setDialog(null)}
                >
                  Продолжить путь <ArrowRight size={16} />
                </button>
              )}
            </div>
          )}
          {dialog.type === "window" && customWindow && (
            <div className="custom-window-content">
              {customWindow.imageId && (
                <img
                  className="custom-window-image"
                  src={asset(customWindow.imageId)}
                  alt={customWindow.title}
                />
              )}
              <p className="custom-window-text">{customWindow.text}</p>
              {!!customWindow.stats.length && (
                <div className="custom-window-stats">
                  {customWindow.stats.map((id) => {
                    const s = world.stats.find((s) => s.id === id);
                    return (
                      s && (
                        <div key={id}>
                          <span style={{ color: s.color }}>
                            <StatIcon stat={s} size={20} />
                          </span>
                          <small>{s.name}</small>
                          <strong>{state.stats[id]}</strong>
                        </div>
                      )
                    );
                  })}
                </div>
              )}
              {customWindow.buttons.map((b) => {
                const Icon = buttonIcons[b.icon] || Sparkles;
                return (
                  <button
                    className="button secondary full-width"
                    key={b.id}
                    onClick={() => execute(b.actions, b.id)}
                  >
                    <Icon size={17} />
                    {b.label}
                  </button>
                );
              })}
            </div>
          )}
          {dialog.type === "journal" && (
            <>
              <p className="modal-intro">
                Последние 40 событий твоего приключения. Новое — сверху.
              </p>
              <div className="journal-list">
                {state.log.map((text, i) => (
                  <div key={`${i}-${text}`}>
                    <span>
                      <Clock3 size={15} />
                    </span>
                    <p>{text}</p>
                    {i === 0 && <small>Сейчас</small>}
                  </div>
                ))}
              </div>
            </>
          )}
          {dialog.type === "settings" && (
            <>
              <div className="settings-status">
                <ShieldCheck size={30} />
                <div>
                  <h3>Твой мир — на твоём устройстве</h3>
                  <p>
                    Мир, графика и прогресс хранятся в этом браузере. Аккаунт не
                    нужен. Очистка данных сайта удалит сохранение.
                  </p>
                </div>
              </div>
              <div className="settings-actions">
                <button onClick={exportCurrent}>
                  <Download size={21} />
                  <span>
                    <strong>Скачать резервную копию</strong>
                    <small>
                      Мир, изображения и текущий прогресс в JSON-файле
                    </small>
                  </span>
                  <ArrowUpRight size={17} />
                </button>
                <button
                  disabled={importing}
                  onClick={() => importRef.current?.click()}
                >
                  <Upload size={21} />
                  <span>
                    <strong>
                      {importing ? "Читаем мир…" : "Импортировать мир"}
                    </strong>
                    <small>Перенести сохранение из другого браузера</small>
                  </span>
                  <ArrowUpRight size={17} />
                </button>
                <button
                  onClick={() => {
                    setDialog(null);
                    setSection("history");
                    enterStudio();
                  }}
                >
                  <RotateCcw size={21} />
                  <span>
                    <strong>История и восстановление</strong>
                    <small>{save.snapshots.length} из 8 резервных версий</small>
                  </span>
                  <ArrowUpRight size={17} />
                </button>
                <button onClick={() => setSound(!sound)}>
                  {sound ? <Volume2 size={21} /> : <VolumeX size={21} />}
                  <span>
                    <strong>Звуки приключения</strong>
                    <small>
                      {sound ? "Включены" : "Выключены"} · настройка на этот
                      сеанс
                    </small>
                  </span>
                  <span className={`settings-toggle ${sound ? "on" : ""}`} />
                </button>
              </div>
              <div className="info-strip">
                <CloudDownload size={18} />
                <span>
                  Публичная ссылка открывает приложение, но не передаёт другим
                  твоё локальное сохранение.
                </span>
              </div>
            </>
          )}
          {dialog.type === "help" && (
            <>
              <div className="help-banner">
                <Sparkles size={28} />
                <div>
                  <h3>Не просто игра. Твоя игровая мастерская.</h3>
                  <p>
                    Исследуй готовый остров, а потом меняй его и добавляй своё.
                  </p>
                </div>
              </div>
              <div className="help-grid">
                <article>
                  <Keyboard size={23} />
                  <h3>Исследуй</h3>
                  <p>
                    Стрелки или WASD — движение. E — действие рядом. I — рюкзак.
                    Можно просто нажимать на карту и объекты.
                  </p>
                </article>
                <article>
                  <Leaf size={23} />
                  <h3>Начни с садовника</h3>
                  <p>
                    Прими задание, собери три яблока и вернись. Получишь ключ от
                    рощи и сможешь открыть сундук за рекой.
                  </p>
                </article>
                <article>
                  <Hammer size={23} />
                  <h3>Создавай</h3>
                  <p>
                    В мастерской есть персонажи, предметы, характеристики,
                    задания, правила, кнопки, окна и загрузка графики.
                  </p>
                </article>
                <article>
                  <WorkflowIcon />
                  <h3>Оживляй идеями</h3>
                  <p>
                    Правила работают так: «Когда событие → если условия →
                    сделать действия». Никакого программного кода.
                  </p>
                </article>
                <article>
                  <FlaskConical size={23} />
                  <h3>Проверяй безопасно</h3>
                  <p>
                    Черновик не меняет опубликованный мир. «Проверить» запускает
                    копию прогресса. «Опубликовать» применяет изменения.
                  </p>
                </article>
                <article>
                  <Download size={23} />
                  <h3>Сохрани историю</h3>
                  <p>
                    Скачивай мир в настройках. История хранит 8 версий. Если
                    эксперимент не удался, восстанови рабочую копию.
                  </p>
                </article>
              </div>
              <div className="info-strip">
                <AlertCircle size={17} />
                <span>
                  Базовые действия готовы заранее. Из них собираются новые
                  механики. Для принципиально нового типа поведения может
                  понадобиться расширить сам движок.
                </span>
              </div>
              <button
                className="button primary full-width"
                onClick={() => {
                  setDialog(null);
                  enterStudio();
                }}
              >
                Сотворить что-нибудь своё <Sparkles size={17} />
              </button>
            </>
          )}
        </Modal>
      )}
    </div>
  );
}
function spriteLabelsName(world: World, id: string) {
  const name = world.items.find((i) => i.id === id)?.name || "предметы";
  return name.toLowerCase();
}
function WorkflowIcon() {
  return <Flag size={23} />;
}
