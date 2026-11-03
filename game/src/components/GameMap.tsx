import { useState, type CSSProperties } from "react";
import {
  Sun,
  MousePointer2,
  Move,
  Maximize2,
  Minimize2,
  Sparkles,
  MessageCircle,
  LockKeyhole,
} from "lucide-react";
import { COLS, ROWS, tileAt, type World, type GameState } from "../model";
import { Sprite } from "./Sprite";

interface Props {
  world: World;
  state: GameState;
  onTile: (x: number, y: number) => void;
  onEntity?: (id: string) => void;
  editor?: boolean;
  selectedId?: string;
  placing?: boolean;
}
export function GameMap({
  world,
  state,
  onTile,
  onEntity,
  editor = false,
  selectedId,
  placing = false,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const asset = (id?: string) => world.assets.find((a) => a.id === id)?.data;
  const style = {
    "--cols": COLS,
    "--rows": ROWS,
    backgroundImage: world.backgroundId
      ? `url("${asset(world.backgroundId)}")`
      : undefined,
  } as CSSProperties;
  return (
    <section
      className={`map-card ${expanded ? "map-expanded" : ""} ${editor ? "map-editor" : ""}`}
      aria-label="Карта мира"
    >
      <div className="map-heading">
        <div className="map-location">
          <span className="live-dot" />
          <span>{editor ? "Редактор карты" : "Тихая роща"}</span>
          <span className="map-chapter">
            {editor ? "Выбери объект и клетку" : "Остров искр · Глава I"}
          </span>
        </div>
        <div className="map-weather">
          <Sun size={15} />
          <span>Дневное время</span>
          <button
            className="icon-button"
            onClick={() => setExpanded(!expanded)}
            aria-label={expanded ? "Уменьшить карту" : "Развернуть карту"}
          >
            {expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
        </div>
      </div>
      <div
        className={`map-viewport theme-${world.theme} ${world.backgroundId ? "has-background" : ""} ${placing ? "placing" : ""}`}
        style={style}
      >
        <div
          className="tile-layer"
          style={{
            gridTemplateColumns: `repeat(${COLS},1fr)`,
            gridTemplateRows: `repeat(${ROWS},1fr)`,
          }}
        >
          {Array.from({ length: COLS * ROWS }, (_, i) => {
            const x = i % COLS,
              y = Math.floor(i / COLS),
              tile = tileAt(x, y);
            return (
              <button
                key={i}
                className={`tile tile-${tile} ${(x + y) % 3 === 0 ? "tile-variant" : ""}`}
                tabIndex={editor && !placing ? -1 : 0}
                aria-label={`Клетка ${x}, ${y}${tile === "tree" ? ": дерево" : tile === "water" ? ": река" : ""}`}
                onClick={() => onTile(x, y)}
              >
                {tile === "tree" && (
                  <Sprite name="tree" className="terrain-tree" />
                )}
                {tile === "grass" && (x * 3 + y) % 4 === 0 && (
                  <span className="grass-tuft" />
                )}
                {tile === "flowers" && (
                  <span className="tiny-flowers">
                    <i />
                    <i />
                    <i />
                  </span>
                )}
                {tile === "water" && <span className="water-ripple" />}
                {tile === "bridge" && <span className="bridge-planks" />}
              </button>
            );
          })}
        </div>
        <div className="scenery-layer" aria-hidden="true">
          <div className="pond-stones stones-one" />
          <div className="pond-stones stones-two" />
          <div className="map-butterfly butterfly-one">✦</div>
          <div className="map-butterfly butterfly-two">✦</div>
        </div>
        {world.entities
          .filter((e) => !state.removed.includes(e.id))
          .map((e) => (
            <button
              key={e.id}
              className={`map-entity entity-${e.kind} ${selectedId === e.id ? "entity-selected" : ""} ${state.opened.includes(e.id) ? "entity-opened" : ""}`}
              style={{
                left: `${(e.x / COLS) * 100}%`,
                top: `${(e.y / ROWS) * 100}%`,
                width: `${100 / COLS}%`,
                height: `${100 / ROWS}%`,
              }}
              tabIndex={-1}
              aria-label={e.name}
              title={e.name}
              onClick={(event) => {
                event.stopPropagation();
                if (editor) onTile(e.x, e.y);
                else onEntity?.(e.id);
              }}
            >
              <Sprite name={e.sprite} src={asset(e.assetId)} />
              {e.kind === "npc" && !editor && (
                <span
                  className={`entity-marker ${e.questId && state.quests[e.questId] === "active" ? "marker-active" : ""}`}
                >
                  {e.questId && state.quests[e.questId] === "completed"
                    ? "✓"
                    : "!"}
                </span>
              )}
              {e.kind === "gate" && !state.opened.includes(e.id) && (
                <span className="entity-lock">
                  <LockKeyhole size={11} />
                </span>
              )}
              {e.kind === "chest" && state.opened.includes(e.id) && (
                <span className="entity-marker marker-active">✓</span>
              )}
              {selectedId === e.id && editor && (
                <span className="entity-name-tag">{e.name}</span>
              )}
            </button>
          ))}
        <div
          className={`map-hero ${state.steps % 2 ? "hero-step" : ""}`}
          style={{
            left: `${(state.x / COLS) * 100}%`,
            top: `${(state.y / ROWS) * 100}%`,
            width: `${100 / COLS}%`,
            height: `${100 / ROWS}%`,
          }}
          aria-label={`Герой: клетка ${state.x}, ${state.y}`}
        >
          <span className="hero-ring" />
          <Sprite name={world.heroSprite} src={asset(world.heroAssetId)} />
          <span className="hero-label">Ты</span>
        </div>
        <div className="map-corner-label">
          <Sparkles size={13} />
          <span>{editor ? "Мир возможностей" : "Твоё приключение"}</span>
        </div>
        {placing && (
          <div className="placement-banner">
            <MousePointer2 size={16} /> Нажми на клетку, чтобы разместить объект
          </div>
        )}
      </div>
      <footer className="map-footer">
        <div className="control-hints">
          <span>
            <kbd>W</kbd>
            <kbd>A</kbd>
            <kbd>S</kbd>
            <kbd>D</kbd> <span>движение</span>
          </span>
          <span>
            <kbd>E</kbd> <span>действие</span>
          </span>
          <span className="mouse-hint">
            <MousePointer2 size={14} /> или нажми на карту
          </span>
        </div>
        <span className="coordinates">
          <Move size={13} /> {state.x}, {state.y}
        </span>
      </footer>
    </section>
  );
}
