"""Конфигурация приложения: dataclass-дерево + JSON.

Все пороги живут здесь, чтобы их можно было менять без правки кода —
через ``config/airmouse.json`` (создаётся при первом запуске) или через
команды ``python -m airmouse config set ...``.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    get_args,
    get_origin,
    get_type_hints,
)


def app_root() -> Path:
    """Папка, рядом с которой живут данные приложения.

    В исходниках это корень репозитория, в собранном PyInstaller-EXE —
    папка с самим EXE (иначе конфиг писался бы во временный каталог распаковки).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_path(value: "str | Path") -> Path:
    """Относительные пути считаем от ``app_root()``, а не от текущего каталога."""
    p = Path(value)
    return p if p.is_absolute() else (app_root() / p)


PROJECT_ROOT = app_root()
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "airmouse.json"


# --------------------------------------------------------------------------- #
#  Сериализация вложенных dataclass-ов
# --------------------------------------------------------------------------- #
def _is_dataclass_type(tp: Any) -> bool:
    return isinstance(tp, type) and dataclasses.is_dataclass(tp)


def _coerce(value: Any, tp: Any) -> Any:
    """Приводит значение из JSON к нужному типу поля."""
    if _is_dataclass_type(tp):
        if isinstance(value, dict):
            return from_dict(tp, value)
        return tp()
    origin = get_origin(tp)
    if origin is None:
        if tp is float and isinstance(value, int):
            return float(value)
        if tp is int and isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    args = get_args(tp)
    if origin in (tuple, Tuple) and isinstance(value, (list, tuple)):
        if len(args) == 2 and args[1] == Ellipsis:  # Tuple[float, ...]
            return tuple(_coerce(v, args[0]) for v in value)
        return tuple(_coerce(v, a) for v, a in zip(value, args))
    if origin in (list, List) and isinstance(value, (list, tuple)):
        item_tp = args[0] if args else Any
        return [_coerce(v, item_tp) for v in value]
    if origin in (dict, Dict) and isinstance(value, dict):
        val_tp = args[1] if len(args) > 1 else Any
        return {k: _coerce(v, val_tp) for k, v in value.items()}
    return value


def from_dict(cls: type, data: Dict[str, Any]) -> Any:
    """Строит dataclass из словаря, не падая на незнакомых ключах."""
    if not isinstance(data, dict):
        return cls()
    try:  # при `from __future__ import annotations` типы полей — строки
        hints = get_type_hints(cls)
    except Exception:  # pragma: no cover - защита от экзотических аннотаций
        hints = {}
    kwargs: Dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue
        kwargs[f.name] = _coerce(data[f.name], hints.get(f.name, Any))
    return cls(**kwargs)


# --------------------------------------------------------------------------- #
#  Секции конфигурации
# --------------------------------------------------------------------------- #
@dataclass
class CameraConfig:
    index: int = 0                 # номер камеры (0 — встроенная)
    width: int = 960
    height: int = 540
    fps: int = 30
    mirror: bool = True            # зеркалить кадр, как в зеркале
    backend: str = "auto"          # auto | dshow | msmf | v4l2 | any
    video_file: str = ""           # если задан — вместо камеры читаем файл


@dataclass
class HandConfig:
    enabled: bool = True
    max_hands: int = 1
    min_detection_confidence: float = 0.6
    min_tracking_confidence: float = 0.6
    pose_stable_frames: int = 3        # сколько кадров жест должен держаться
    pinch_ratio: float = 0.32          # «щипок» начинается
    pinch_release_ratio: float = 0.42  # и отпускается (гистерезис)
    drag_delay_s: float = 0.30         # удержание щипка -> перетаскивание
    click_cooldown_s: float = 0.35
    open_palm_hold_s: float = 1.00     # пауза по раскрытой ладони
    pause_max_motion: float = 0.010    # ладонь должна почти стоять (доли кадра/кадр)
    fist_scroll_gain: float = 22.0     # «тиков» прокрутки на единицу смещения
    fist_scroll_deadzone: float = 0.006
    pointer_source: str = "auto"       # auto | index_tip | palm


@dataclass
class FaceConfig:
    enabled: bool = True
    every_n_frames: int = 2            # экономия CPU: лицо раз в N кадров
    ear_blink: float = 0.19            # порог «глаз закрыт»
    ear_open: float = 0.25             # порог «глаз открыт» (гистерезис)
    blink_min_s: float = 0.06
    blink_max_s: float = 0.45
    double_blink_window_s: float = 0.90
    smile_delta: float = 0.055         # прирост ширины улыбки к нейтрали
    smile_hold_s: float = 0.45
    smile_cooldown_s: float = 2.0
    brow_delta: float = 0.045          # подъём бровей к нейтрали
    brow_hold_s: float = 0.50
    brow_cooldown_s: float = 2.0
    mouth_open_ratio: float = 0.55
    head_pointer_gain_x: float = 9.0   # скорость мыши от поворота головы
    head_pointer_gain_y: float = 7.0
    head_deadzone_deg: float = 3.0
    calm_s: float = 0.35               # сколько нейтрали нужно для baseline


@dataclass
class PointerConfig:
    active_box: Tuple[float, float, float, float] = (0.16, 0.14, 0.84, 0.86)
    edge_margin_px: int = 6
    min_cutoff: float = 1.05           # One Euro: меньше — плавнее
    beta: float = 0.03                 # больше — отзывчивее на рывки
    d_cutoff: float = 1.0
    deadzone_norm: float = 0.0018      # микро-дрожание руки игнорируем
    max_step_px: int = 260             # защита от «телепорта» мыши
    relative_mode: bool = False        # True — джойстик, False — абсолют
    relative_gain: float = 2200.0


@dataclass
class LipConfig:
    enabled: bool = False
    template_dir: str = "profiles/lip"
    window_frames: int = 36
    stride_s: float = 0.15
    max_distance: float = 0.055        # порог «это слово»
    band: float = 0.25                 # полоса Сакоэ-Чибы для DTW
    judge_reps: int = 8                # сколько повторов при записи
    words: Dict[str, str] = field(default_factory=dict)  # слово -> действие


@dataclass
class ActionConfig:
    mapping: Dict[str, str] = field(default_factory=lambda: {
        "pinch_release": "left_click",
        "middle_pinch_release": "right_click",
        "thumb_up": "double_click",
        "open_palm_hold": "toggle_pause",
        "smile_hold": "toggle_pause",
        "brow_hold": "toggle_head_pointer",
        "double_blink": "left_click",
        "wink_left": "right_click",
        "wink_right": "right_click",
    })
    scroll_mode: str = "fist"          # прокрутка кулаком (см. gestures)
    double_click_interval_s: float = 0.12


@dataclass
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    hand: HandConfig = field(default_factory=HandConfig)
    face: FaceConfig = field(default_factory=FaceConfig)
    pointer: PointerConfig = field(default_factory=PointerConfig)
    lip: LipConfig = field(default_factory=LipConfig)
    actions: ActionConfig = field(default_factory=ActionConfig)

    show_window: bool = True
    show_skeleton: bool = True
    tracker: str = "auto"              # auto | mediapipe | classical | none
    model_dir: str = "models"
    profile_dir: str = "profiles"
    log_file: str = "logs/airmouse.log"
    head_pointer: bool = False
    start_paused: bool = False
    warmup_s: float = 2.0              # первые секунды не нажимаем: дайте встать в кадр


# --------------------------------------------------------------------------- #
#  Загрузка / сохранение
# --------------------------------------------------------------------------- #
def load_config(path: Optional[Path] = None) -> AppConfig:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not path.exists():
        cfg = AppConfig()
        save_config(cfg, path)
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppConfig()
    cfg = from_dict(AppConfig, data)
    return cfg


def save_config(cfg: AppConfig, path: Optional[Path] = None) -> Path:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dataclasses.asdict(cfg), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def set_value(cfg: AppConfig, dotted: str, raw: str) -> Any:
    """``hand.pinch_ratio=0.34`` -> меняет поле и возвращает новое значение."""
    parts = dotted.split(".")
    node: Any = cfg
    for part in parts[:-1]:
        if not hasattr(node, part):
            raise KeyError(f"нет секции '{part}' в '{dotted}'")
        node = getattr(node, part)
    name = parts[-1]
    if not hasattr(node, name):
        raise KeyError(f"нет поля '{dotted}'")
    current = getattr(node, name)
    if isinstance(current, bool):
        value: Any = raw.strip().lower() in ("1", "true", "yes", "on", "да")
    elif isinstance(current, int):
        value = int(float(raw))
    elif isinstance(current, float):
        value = float(raw)
    elif isinstance(current, tuple):
        value = tuple(float(x) for x in raw.replace(" ", "").split(","))
    else:
        value = raw
    setattr(node, name, value)
    return value
