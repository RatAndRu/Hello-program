"""Главный цикл приложения: камера -> распознавание -> действия -> оверлей."""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from . import __version__
from .actions import ActionRouter, DryRunBackend, PyAutoGuiBackend
from .camera import ThreadedCamera
from . import keys
from .config import AppConfig, resolve_path, save_config
from .face import FaceFSM, FaceMetrics, measure_face
from .handphysics import HandPhysics
from .handtrack import HandTracker, is_edge_on
from .profile import MotionProfile, MotionWizard
from .gaze import (
    screen_point,
    CALIBRATION_TARGETS,
    TARGET_TITLES,
    PURSUIT_DURATION_S,
    PURSUIT_MARGIN,
    PURSUIT_ROWS,
    GazeCalibration,
    GazeCursor,
    GazeDwell,
    average_gaze,
    pursuit_metrics,
    pursuit_point,
)
from .body import BodyFSM, BodySmoother, arm_points, measure_body
from .headpose import HeadPoseEstimator
from .gestures import (
    SIDE_TITLES_RU,
    Event,
    HandFSM,
    HandGate,
    HandSide,
    POSE_TITLES_RU,
    TwoHandFSM,
    analyze_hand,
    classify_pose,
)
from .lipreading import LipReader, TemplateStore, mouth_features
from .overlay import OverlayState, render, render_gaze_calibration
from .landmarks import WRIST
from .pointer import PointerMapper
from .settings_ui import SettingsPanel, cycle_preset, modes_summary
from .tracker import FrameResult, create_tracker

log = logging.getLogger("airmouse")

# Как называть движки в окне и в журнале.
BACKEND_TITLES = {
    "mediapipe": "ИИ MediaPipe (нейросеть)",
    "classical": "классический CV (без ИИ)",
    "none": "без распознавания",
}

# События мимики, которые нельзя выпускать во время перетаскивания/щипка.
# что вторая рука имеет право делать в режиме hand.roles=split
SPLIT_CLICK_EVENTS = {
    "pinch_release", "middle_pinch_release", "drag_start", "drag_end",
    "scroll", "ok_sign", "rock_sign", "three_fingers",
}

FACE_SUPPRESSED = {"open_palm_hold", "smile_hold", "brow_hold", "eyes_closed_hold",
                   "head_nod", "head_shake"}

HAND_EVENTS_RU = {
    "pinch_release": "клик",
    "middle_pinch_release": "правый клик",
    "thumb_up": "большой палец",
    "open_palm_hold": "ладонь: пауза",
    "drag_start": "перетаскивание",
    "drag_end": "отпустил",
    "scroll": "прокрутка",
    "double_blink": "двойное моргание",
    "wink_left": "подмигнул",
    "wink_right": "подмигнул",
    "smile_hold": "улыбка",
    "brow_hold": "брови",
    "eyes_closed_hold": "глаза закрыты",
    "lip_word": "по губам",
    "head_nod": "кивок",
    "head_shake": "поворот головой",
    "zoom": "масштаб",
}


@dataclass
class Stats:
    frames: int = 0
    hand_frames: int = 0
    face_frames: int = 0
    clicks: int = 0
    scrolls: int = 0


class AirMouseApp:
    # Сколько раз подряд пробовать растянуть окно на весь экран, прежде чем
    # сделать паузу (потом серия начинается заново — см. _fit_window_to_screen).
    FIT_TRIES_MAX = 4

    def __init__(
        self,
        cfg: AppConfig,
        dry_run: bool = False,
        show_window: Optional[bool] = None,
        output: Optional[Path] = None,
        on_event=None,
    ) -> None:
        self.cfg = cfg
        self.dry_run = dry_run
        self.show_window = cfg.show_window if show_window is None else show_window
        self.output = output
        self.on_event = on_event

        self.backend = DryRunBackend() if dry_run else PyAutoGuiBackend()
        self.router = ActionRouter(self.backend, cfg)
        self.pointer = PointerMapper(cfg.pointer, self.backend.screen_size())
        self.hand_fsm = HandFSM(cfg.hand)
        # фильтр «это точно рука?»: фантомные детекции не должны управлять
        self.hand_gate = HandGate(cfg.hand)
        # «мышь глазами»: абсолютный режим по калибровке взгляда
        self.gaze_calib = GazeCalibration.from_dict(getattr(cfg.face, "gaze_calibration", {}))
        self._gaze_error_cache = (self.gaze_calib.error()
                                  if self.gaze_calib.ready else (0.0, 0.0))
        self.gaze_cursor = GazeCursor(getattr(cfg.face, "gaze_deadzone_px", 12),
                                      getattr(cfg.face, "gaze_cursor_alpha", 0.55))
        self.gaze_dwell = GazeDwell(
            float(getattr(cfg.face, "gaze_dwell_s", 0.6)),
            float(getattr(cfg.face, "gaze_dwell_px", 60)),
            float(getattr(cfg.face, "gaze_dwell_cooldown_s", 1.0)),
        )
        self._calib: Optional[dict] = None      # идёт мастер калибровки взгляда
        self._palm_hint_at = -1e9               # когда последний раз подсказывали про ладонь
        self._gaze_drift_at = -1e9              # когда говорили «лицо уехало, калибруй»
        self._gaze_track: deque = deque(maxlen=30)   # куда смотрели (для дрожания)
        self._body_points = None                # последние 33 точки тела (для скелета)
        # Трекер кисти и физика пальцев: рука не пропадает на пару кадров, а
        # пальцы не выгибаются так, как анатомически невозможно.
        self.hand_tracker = HandTracker(
            predict_frames=int(getattr(cfg.hand, "predict_frames", 6)),
            use_body=bool(getattr(cfg.hand, "predict_use_body", True)),
        )
        self._physics: Dict[int, HandPhysics] = {}
        self._predicted_hands: List[bool] = []
        self._hands_draw: List = []         # кисти для окна (с предсказаниями)
        self._hand_notes: List[str] = []
        self.body_smoother = BodySmoother(
            min_visibility=float(getattr(cfg.body, "min_visibility", 0.5)),
        )
        self._body_want: Optional[bool] = None  # с каким «хочу тело» создан движок
        self.motion_wizard: Optional[MotionWizard] = None
        self._motion_at = 0.0                   # время прошлого кадра профиля
        self._body_counter = 0                  # прореживание позы тела
        # поворот головы: чтобы курсор не прыгал, когда человек вертит головой,
        # но продолжает смотреть в ту же точку экрана
        self.head_pose = HeadPoseEstimator()
        self.two_hand_fsm = TwoHandFSM(cfg.hand, self._two_hand_relax())
        self.face_fsm = FaceFSM(cfg.face)
        # тело целиком: приседания, наклон, руки вверх (по желанию)
        self.body_fsm = BodyFSM(cfg.body)
        self.camera: Optional[ThreadedCamera] = None
        self.tracker = None
        self.lip_reader: Optional[LipReader] = None
        self.stats = Stats()
        self.state = OverlayState(
            active_box=cfg.pointer.active_box,
            paused=self.router.paused,
            head_pointer=self.router.head_pointer,
            gaze_pointer=self.router.gaze_pointer,
            dry_run=dry_run,
            actions_on=not dry_run,
            pinch_threshold=cfg.hand.pinch_ratio,
            version=__version__,
        )
        # что произошло за последние секунды — показываем прямо в окне
        self._events_log: deque = deque(maxlen=3)
        self.running = False
        self._prepared = False
        self._last_seq = -1
        self._last_now = 0.0
        self._first_now: Optional[float] = None
        self._armed_at = 0.0
        self._face_counter = 0
        self._metrics: Optional[FaceMetrics] = None
        self._face = None
        self._hands: List = []
        self._primary_index = 0
        self._primary_wrist: Optional[np.ndarray] = None
        self._shape = None
        self._lit = 0.0
        self._last_scroll_log = 0.0
        # вторая рука в режиме «две руки» только нажимает — там щипок проще
        self.click_fsm = HandFSM(cfg.hand, self._click_relax())
        self.settings: Optional[SettingsPanel] = None
        self._mouse_bound = False
        self._frame_size: Tuple[int, int] = (960, 540)
        self._paused_for_settings = False
        self._window_name = "AirMouse"
        self._fullscreen = bool(getattr(cfg, "fullscreen", False))  # окно на весь экран
        # что уже применено к окну; False — обычное окно при старте
        self._fullscreen_applied: Optional[bool] = False
        self._screen_size_cache: Optional[Tuple[int, int]] = None
        self._fit_last_try = 0.0
        self._fit_tries = 0
        self._fit_series = 0                    # сколько серий попыток уже было
        self._window_sized = False              # окно уже получило стартовый размер
        self._preview_cache: Optional[Tuple[int, int]] = None
        self._preview_at = 0.0
        # Куда сохранять настройки. None — путь по умолчанию (~/.airmouse/config.json);
        # autosave включается в командной строке, чтобы тесты и demo ничего не писали.
        self.config_path: Optional[Path] = None
        self.autosave: bool = False
        self._saved_snapshot: str = ""
        self._autosave_at = 0.0

    # ------------------------------------------------------------------ #
    def setup(self) -> None:
        log.info("Запуск: backend=%s, окно=%s, dry-run=%s",
                 self.cfg.tracker, self.show_window, self.dry_run)
        self.camera = ThreadedCamera(self.cfg.camera).start()
        w, h = self.camera.camera.resolution
        log.info("Камера: %s, %dx%d", self.camera.camera.source_name, w, h)
        # Тело включаем сами, если модель позы уже лежит рядом (в собранном EXE
        # она есть всегда) — иначе человек запускает, не видит скелета и решает,
        # что детект тела не работает.
        if not bool(getattr(self.cfg.body, "enabled", False)) and \
                bool(getattr(self.cfg.body, "auto", True)):
            from .models import find_model
            pose_model = find_model(resolve_path(self.cfg.model_dir), "pose_landmarker")
            if pose_model is not None:
                self.cfg.body.enabled = True
                log.info("Тело: модель позы найдена (%s) — включаю автоматически",
                         pose_model.name)
        self.tracker = create_tracker(
            self.cfg.tracker,
            self.cfg.hand,
            self.cfg.face,
            resolve_path(self.cfg.model_dir),
            progress=log.info,
            want_body=bool(getattr(self.cfg.body, "enabled", False)),
        )
        log.info("Распознавание: %s", getattr(self.tracker, "name", "?"))
        self._body_want = bool(getattr(self.cfg.body, "enabled", False))
        if self._body_want and not getattr(self.tracker, "want_body", False):
            self.cfg.body.enabled = False
            self._body_want = False
            log.warning("Тело: движок не умеет позу — режим тела выключен")
        if self.cfg.lip.enabled:
            store = TemplateStore(resolve_path(self.cfg.lip.template_dir))
            self.lip_reader = LipReader(
                store,
                window_frames=self.cfg.lip.window_frames,
                stride_s=self.cfg.lip.stride_s,
                max_distance=self.cfg.lip.max_distance,
                band=self.cfg.lip.band,
            )
            log.info("Слова по губам: %s", self.lip_reader.vocabulary or "словарь пуст")
        self._prepared = True

    # ------------------------------------------------------------------ #
    def stop(self) -> None:
        self.running = False

    def _translate(self, events: List[Event], now: float) -> List[Event]:
        """Нормализованные координаты руки -> пиксели экрана."""
        out: List[Event] = []
        for ev in events:
            if ev.kind == "pointer":
                if self.router.head_pointer:
                    continue  # пока включена «мышь головой», рука курсор не двигает
                x, y = ev.value  # type: ignore[misc]
                pt = self.pointer.absolute((x, y), now)
                if pt is not None:
                    out.append(Event("pointer", pt))
            else:
                out.append(ev)
        return out

    def _handle_face(self, face, now: float) -> List[Event]:
        # Мимика может быть выключена, но метрики и зрачок нужны всё равно:
        # без них не работают «мышь глазами» и калибровка взгляда.
        if face is None:
            self._metrics = None
            return []
        self._face_counter += 1
        if self._face_counter % max(self.cfg.face.every_n_frames, 1) != 0 and self._metrics is not None:
            return []
        self._metrics = measure_face(face, self.head_pose)
        if not self.face_fsm.baseline.ready:
            # первые ~1.5 секунды — калибровка нейтрального выражения
            for _ in range(4):
                self.face_fsm.baseline.update(self._metrics, alpha=0.4)
            return []
        events = self.face_fsm.update(self._metrics, now)
        if not self.cfg.face.enabled:
            # «Лицо» выключено: жесты мимики не нажимают, но взгляд считается
            return []
        return events

    def _track_hands(self, hands, now: float, body) -> List:
        """Трекер кисти + физика пальцев: непрерывность и правдоподобность.

        Зачем: кисть, повёрнутая ребром, и кисть, прикрытая другой рукой, читаются
        плохо — нейросеть то теряет её на пару кадров, то выгибает пальцы так,
        как человек их выгнуть не может. Трекер продолжает движение по скорости
        предыдущих кадров (и подтягивает кисть к запястью из тела, если оно
        видно), а физика поправляет невозможные позы.

        Возвращает кисти **для жестов** — только реально измеренные. Отдельно
        готовится список для отрисовки: там есть и предсказанные кисти, и
        поправленные физикой пальцы. Жесты сознательно не строятся на
        предсказаниях: выдуманная рука не должна нажимать кнопки.
        """
        self._predicted_hands = []
        self._hand_notes = []
        if not hands and not bool(getattr(self.cfg.body, "enabled", False)):
            self.hand_tracker.reset()
            return []
        # Кисть «ребром» (плоская линия) — это не измерение позы пальцев, а шум.
        # Такую руку не отдаём детектором: трекер продолжит её движение по
        # предыдущим кадрам, и на экране не будет дёргающейся ладони-полоски.
        measured = []
        edge_on = 0
        for hand in hands:
            if is_edge_on(hand):
                edge_on += 1
                continue
            measured.append(hand)
        tracked = self.hand_tracker.update(measured, now, body=body)
        if edge_on and not self.hand_tracker.count:
            self._hand_notes.append("кисть ребром: поза не измеряется")
        result = []            # для жестов: только измеренные руки
        draw = []              # для окна: с предсказаниями и поправками физики
        alive = set()
        for item in tracked:
            key = int(getattr(item, "track_id", 0))
            alive.add(key)
            physics = self._physics.get(key)
            if physics is None:
                physics = HandPhysics(bool(getattr(self.cfg.hand, "physics", True)))
                self._physics[key] = physics
            hand = item.hand
            if bool(getattr(self.cfg.hand, "physics", True)):
                out = physics.update(hand, now)
                draw.append(out.hand)
                if item.predicted:
                    # предсказанную кисть тоже проверяем: физика не даст ей
                    # выгнуться, пока она «едет» по инерции
                    pass
                if out.suspect:
                    self._hand_notes.append(out.note())
            else:
                draw.append(hand)
            self._predicted_hands.append(bool(item.predicted))
            if item.predicted:
                self._hand_notes.append(item.note)
            else:
                result.append(hand)
        self._hands_draw = draw
        # состояние физики для забытых треков больше не нужно
        for key in [k for k in self._physics if k not in alive]:
            del self._physics[key]
        return result

    def _handle_body(self, points, now: float) -> List[Event]:
        """Тело целиком: считаем позу (и упражнения), если режим включён."""
        if not getattr(self.cfg.body, "enabled", False):
            return []
        self._body_counter += 1
        every = max(1, int(getattr(self.cfg.body, "every_n_frames", 1)))
        # прореживаем: поза тела не меняется за 30 мс, а CPU экономит заметно
        if self._body_counter % every != 0 and self.body_fsm.metrics.visible:
            return []
        if points is None:
            return self.body_fsm.update(None, now)
        metrics = measure_body(points, float(getattr(self.cfg.body, "min_visibility", 0.5)))
        events = self.body_fsm.update(metrics, now)
        if events:
            self.state.body_text = self.body_fsm.text
        # В очередь действий отдаём только то, что человек сам привязал к
        # команде (по умолчанию тело только считает и показывает).
        mapped = []
        for ev in events:
            if ev.kind == "squat_rep":
                self._events_log.appendleft(f"приседание №{ev.value}")
            if self.cfg.actions.mapping.get(ev.kind):
                mapped.append(ev)
        return mapped

    def _handle_lip(self, face, now: float) -> List[Event]:
        if self.lip_reader is None or face is None:
            return []
        feat = mouth_features(face)
        result = self.lip_reader.push(feat, now)
        if result is None:
            return []
        action = self.cfg.lip.words.get(result.word)
        log.info("Губы: «%s» (d=%.3f) -> %s", result.word, result.distance, action)
        return [Event("lip_word", value=result)]

    # ------------------------------------------------------------------ #
    def screen_size(self) -> Tuple[int, int]:
        """Разрешение монитора в пикселях — в нём и рисуется калибровка."""
        if self._screen_size_cache is not None:
            return self._screen_size_cache
        size = (960, 540)
        try:
            w, h = self.backend.screen_size()
            if w and h:
                size = (int(w), int(h))
        except Exception as exc:      # без GUI размер экрана может быть неизвестен
            log.debug("Размер экрана неизвестен: %s", exc)
        self._screen_size_cache = size
        return size

    @property
    def fullscreen(self) -> bool:
        return self._fullscreen

    def toggle_fullscreen(self) -> bool:
        """Окно предпросмотра на весь экран (клавиша F)."""
        self._fullscreen = not self._fullscreen
        self._fullscreen_applied = None
        self._fit_tries = 0
        self._fit_series = 0
        log.info("Окно: %s", "на весь экран" if self._fullscreen else "в окне")
        return self._fullscreen

    def _apply_window_mode(self) -> None:
        """Переключает окно между обычным и полноэкранным — только при смене.

        Калибровка взгляда всегда идёт на весь экран: иначе крестик оказывается
        в углу окошка, а не в углу монитора, и калибровка получается сжатой.
        """
        want = bool(self._fullscreen or self.calibrating)
        if want == self._fullscreen_applied:
            if want:
                self._fit_window_to_screen()
            return
        self._fullscreen_applied = want
        self._preview_cache = None
        self._preview_at = 0.0
        # Каждое новое включение полного экрана — с чистым листом: раньше счётчик
        # попыток «растянуть окно» выбирался один раз за запуск, и после первой
        # же калибровки окно больше не разворачивалось — помогала только
        # перезагрузка приложения.
        self._fit_tries = 0
        self._fit_last_try = 0.0
        self._fit_series = 0
        try:
            if want:
                cv2.setWindowProperty(self._window_name, cv2.WND_PROP_FULLSCREEN,
                                      cv2.WINDOW_FULLSCREEN)
                cv2.moveWindow(self._window_name, 0, 0)
            else:
                cv2.setWindowProperty(self._window_name, cv2.WND_PROP_FULLSCREEN,
                                      cv2.WINDOW_NORMAL)
                cv2.resizeWindow(self._window_name, 960, 540)
        except Exception as exc:      # бэкенд без полноэкранного режима
            log.debug("Полноэкранный режим недоступен: %s", exc)
            if want:
                # запасной путь: окно размером с экран в левом верхнем углу
                try:
                    w, h = self.screen_size()
                    cv2.resizeWindow(self._window_name, w, h)
                    cv2.moveWindow(self._window_name, 0, 0)
                except Exception:
                    pass

    def window_target_size(self) -> Tuple[int, int]:
        """Какого размера должно быть окно: доля экрана при сохранении пропорций.

        Пользователь просил «нормально масштабировать экран приложения, а не
        только на калибровке»: картинка с веб-камеры 960×540 на мониторе
        выглядит маленьким окошком. Здесь считаем стартовый размер от экрана
        (``window_scale``, по умолчанию 85%), сохраняя пропорции кадра, и не
        выходим за сам экран.
        """
        sw, sh = self.screen_size()
        scale = float(getattr(self.cfg, "window_scale", 0.85) or 0.85)
        scale = max(0.3, min(1.0, scale))
        fw, fh = self._frame_size
        aspect = fw / float(fh) if fw and fh else 16.0 / 9.0
        w = int(sw * scale)
        h = int(round(w / aspect))
        if h > sh * scale:                       # высокий кадр — ограничиваем по высоте
            h = int(sh * scale)
            w = int(round(h * aspect))
        return max(w, 320), max(h, 240)

    def _preview_size(self) -> Optional[Tuple[int, int]]:
        """Размер холста для показа — ровно как окно (кешируем 4 раза в секунду)."""
        if not self.show_window:
            return None
        now = time.monotonic()
        if now - self._preview_at < 0.25:
            return self._preview_cache
        self._preview_at = now
        rect = self.window_rect()
        if rect is None:
            self._preview_cache = None
            return None
        _x, _y, w, h = rect
        self._preview_cache = (w, h) if (w >= 320 and h >= 240) else None
        return self._preview_cache

    def _preview_frame(self, frame: np.ndarray) -> np.ndarray:
        """Растянуть кадр до окна: оверлей тогда рисуется в настоящих пикселях.

        Иначе окно всего лишь растягивает уже готовую картинку 960×540, и текст
        с panels «мылится». Здесь кадр увеличивается до размера окна, и весь
        интерфейс рисуется в этом же размере — крупно и резко.
        """
        size = self._preview_size()
        if size is None:
            return frame
        if (frame.shape[1], frame.shape[0]) == size:
            return frame
        return cv2.resize(frame, size, interpolation=cv2.INTER_LINEAR)

    def window_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """Где на экране реально лежит картинка окна: (x, y, ширина, высота)."""
        try:
            x, y, w, h = cv2.getWindowImageRect(self._window_name)
        except Exception:
            return None
        if int(w) <= 0 or int(h) <= 0:
            return None
        return int(x), int(y), int(w), int(h)

    def _fit_window_to_screen(self) -> None:
        """Догоняет окно до всего экрана: система не всегда даёт полный экран.

        Проверяем реальный прямоугольник картинки. Если окно меньше монитора
        (панель задач, другой бэкенд, DPI), повторяем попытку — но не чаще
        раза в секунду, чтобы не мигать. После серии из нескольких попыток
        даём окну паузу и через несколько секунд пробуем снова: если человек
        вышел из полного экрана и снова начал калибровку, окно обязано
        развернуться, сколько бы раз это ни повторялось.
        """
        rect = self.window_rect()
        if rect is None:
            return
        sw, sh = self.screen_size()
        x, y, w, h = rect
        if x == 0 and y == 0 and w >= sw and h >= sh:
            return
        now = time.monotonic()
        if now - self._fit_last_try < 1.0:
            return
        if self._fit_tries >= self.FIT_TRIES_MAX:
            # серия попыток исчерпана — но не навсегда: ждём паузу и начинаем
            # новую серию (например, окно «съежилось» после выхода из полного
            # экрана, и его снова надо растянуть). Пауза растёт, чтобы на
            # «неподатливом» бэкенде окно не мигало каждые три секунды.
            pause = min(3.0 * (2 ** min(self._fit_series, 3)), 30.0)
            if now - self._fit_last_try < pause:
                return
            self._fit_tries = 0
            self._fit_series += 1
        self._fit_last_try = now
        self._fit_tries += 1
        try:
            cv2.setWindowProperty(self._window_name, cv2.WND_PROP_FULLSCREEN,
                                  cv2.WINDOW_FULLSCREEN)
            cv2.resizeWindow(self._window_name, sw, sh)
            cv2.moveWindow(self._window_name, 0, 0)
        except Exception as exc:
            log.debug("Окно не удалось растянуть на весь экран: %s", exc)

    def calibration_canvas(self) -> np.ndarray:
        """Холст ровно по размеру окна; прицел — в настоящем пикселе экрана.

        Важно: холст рисуется в размере **окна**, а не в размере, который
        сообщает система мыши. Иначе картинка масштабируется окном (на экране с
        масштабом 125% всё «раздувается» на четверть), и прицел уезжает с угла.
        """
        sw, sh = self.screen_size()
        rect = self.window_rect()
        if rect is None:
            # размер окна не спросить — рисуем «как есть», без масштабирования
            self.state.calib_debug = f"холст {sw}×{sh} (размер окна неизвестен)"
            return render_gaze_calibration((sw, sh), self.state)
        wx, wy, ww, wh = rect
        note = ""
        if ww != sw or wh != sh or wx or wy:
            # окно не покрыло монитор: прицел будет чуть внутри края
            note = " · окно меньше экрана (нажмите F)"
        elif ww < 1000:
            note = ""
        self.state.calib_debug = (
            f"экран {sw}×{sh} · окно {ww}×{wh} · холст {ww}×{wh}{note}"
        )
        return render_gaze_calibration((ww, wh), self.state)

    # ------------------------------------------------------------------ #
    def _two_hand_relax(self) -> float:
        """Насколько простить жесты в текущем двуручном режиме (0 — строго).

        В «две руки» рука занята одной задачей, поэтому ложных срабатываний там
        меньше: щипок ловится чуть раньше и отпускается чуть позже. Если
        ``hand.simple_two_hand`` выключен, требования остаются строгими.
        """
        if not bool(getattr(self.cfg.hand, "simple_two_hand", True)):
            return 0.0
        roles = (getattr(self.cfg.hand, "roles", "single") or "single").lower()
        mode = (getattr(self.cfg.hand, "two_hand", "off") or "off").lower()
        if roles == "split":
            return 1.0
        if mode in ("zoom", "scroll"):
            return 0.5
        return 0.0

    def _click_relax(self) -> float:
        """Вторая рука нажимает — для неё послабление полное."""
        roles = (getattr(self.cfg.hand, "roles", "single") or "single").lower()
        return self._two_hand_relax() if roles == "split" else 0.0

    def _sync_relax(self) -> None:
        """Режим рук могли переключить на ходу — обновляем пороги автоматов."""
        self.click_fsm.set_relax(self._click_relax())
        self.hand_fsm.set_relax(self._two_hand_relax())
        self.two_hand_fsm.relax = self._two_hand_relax()

    def process_frame(self, frame: np.ndarray, now: float, ts_ms: int) -> List[Event]:
        events: List[Event] = []
        # пока открыта панель настроек, мышь держим на паузе принудительно:
        # случайный жест не должен «разбудить» курсор под рукой пользователя
        if self.settings_open():
            self.router.paused = True
        warmup = now < self._armed_at
        self._sync_relax()

        if hasattr(self.tracker, "process_events"):
            events, shape = self.tracker.process_events(frame, ts_ms, now)
            self._shape = shape
            res = FrameResult(backend=self.tracker.name)
            self._hands, self._face = [], None
            events = self._translate(events, now)
        else:
            res = self.tracker.process(frame, ts_ms)
            raw_body = (getattr(res, "body", None)
                        if bool(getattr(self.cfg.body, "enabled", False)) else None)
            # Тело сглаживаем и показываем только когда оно реально видно:
            # иначе скелет мигал по нескольку раз в секунду (в кадре только рука).
            self._body_points = self.body_smoother.update(raw_body, now)
            self._reconcile_body()
            hands = self.hand_gate.update(res.hands)
            if self.cfg.hand.second_hand == "ignore" and len(hands) > 1:
                hands = hands[:1]
            hands = self._track_hands(hands, now, getattr(res, "body", None))
            self._hands = hands
            self._face = res.face
            self._shape = None
            if not self.cfg.hand.enabled:
                # режим «только лицо»: руки рисуются, но ничего не нажимают
                self.hand_fsm.update(None, now)
                self.click_fsm.update(None, now)
                hands = []
            index = self._pick_primary(hands)
            self._primary_index = index or 0
            hand = hands[index] if index is not None else None
            if getattr(self.cfg.hand, "roles", "single") == "split" and len(hands) >= 2:
                # Режим «две руки»: одна ведёт курсор, вторая только нажимает.
                # Курсор при щипке второй рукой вообще не сдвигается.
                click_hand = hands[1 - self._primary_index]
                moved = [e for e in self.hand_fsm.update(hand, now)
                         if e.kind in ("pointer", "pointer_freeze")]
                # вторая рука нажимает: курсор она не двигает и паузу не включает
                clicking = [e for e in self.click_fsm.update(click_hand, now)
                            if e.kind in SPLIT_CLICK_EVENTS]
                events = self._translate(moved, now) + clicking
            else:
                self.click_fsm.update(None, now)
                events = self._translate(self.hand_fsm.update(hand, now), now)
            face_events = self._handle_face(res.face, now)
            # Пока рука тащит объект или держит щипок, мимика не должна
            # вмешиваться: иначе улыбка/ладонь «отпускают» кнопку мыши.
            if self.hand_fsm.dragging or self.hand_fsm.pinching:
                face_events = [e for e in face_events if e.kind not in FACE_SUPPRESSED]
            events += face_events
            events += self._handle_lip(res.face, now)
            events += self._handle_body(getattr(res, "body", None), now)
            # жесты двумя руками (масштаб/прокрутка) — только когда видно обе руки
            # и вторая рука не занята нажатиями
            if len(hands) >= 2 and getattr(self.cfg.hand, "roles", "single") != "split":
                events += self.two_hand_fsm.update(hands, now)
            if self.router.head_pointer and self._metrics is not None:
                events.extend(self._head_pointer_events(now))
            if self.motion_wizard is not None:
                self._tick_motion_profile(now)
            if self.calibrating:
                # мастер калибровки: копим зрачок, ничего не нажимаем
                self._tick_gaze_calibration(now)
            elif self.router.gaze_pointer and self._metrics is not None:
                events.extend(self._gaze_pointer_events(now))
                self._note_gaze_drift(now)

        self.stats.frames += 1
        self.stats.hand_frames += 1 if self._hands or self._shape is not None else 0
        self.stats.face_frames += 1 if self._face is not None else 0
        self._last_now = now

        if warmup:
            # Разминка: распознавание уже работает, но ничего не нажимаем —
            # человек успевает встать перед камерой.
            return events

        if self.settings_open():
            # Панель настроек: распознавание идёт (видно живые цифры), но ни один
            # жест ничего не нажимает — иначе ладонь «снимала» бы паузу прямо
            # в момент перетаскивания ползунка.
            return events

        if self.calibrating or self.motion_wizard is not None:
            # Пока идёт калибровка взгляда или профиль движений, жесты не
            # нажимают: человек в это время выполняет упражнения, а не рулит.
            return events

        self._note_palm_hint(now)
        for ev in events:
            before = len(self.router.log)
            try:
                self.router.handle(ev, now)
            except Exception as exc:  # FailSafe pyautogui и прочее
                log.error("Ошибка выполнения действия (%s): %s", ev.kind, exc)
                self.router.paused = True
                self.router.release_all()
            applied = self.router.log[before:]
            if ev.kind in ("pointer", "pointer_freeze"):
                pass
            elif ev.kind in ("scroll", "zoom"):
                if now - self._last_scroll_log >= 1.0:
                    log.info("%s: %s", HAND_EVENTS_RU.get(ev.kind, ev.kind), ev.value)
                    self._last_scroll_log = now
            else:
                name = HAND_EVENTS_RU.get(ev.kind, ev.kind)
                done = ", ".join(a for a in applied if not a.startswith("unmapped")) or "—"
                log.info("жест %s -> %s", name, done)
                self._events_log.append(
                    f"{time.strftime('%H:%M:%S')}  {name} → {done}"
                )
            if ev.kind == "pinch_release":
                self.stats.clicks += 1
            elif ev.kind == "scroll":
                self.stats.scrolls += 1
            if self.on_event is not None and ev.kind in HAND_EVENTS_RU:
                self.on_event(ev)

        return events

    # ------------------------------------------------------------------ #
    def _bind_mouse(self) -> None:
        """Навесить обработчик мыши на окно предпросмотра (один раз)."""
        if self._mouse_bound:
            return
        try:
            cv2.setMouseCallback(self._window_name,
                                 lambda event, x, y, flags, param: self._on_mouse(event, x, y))
            self._mouse_bound = True
        except Exception as exc:
            log.warning("Не удалось включить мышь для настроек: %s", exc)

    def _window_scale(self) -> Tuple[float, float]:
        """Во сколько раз окно больше холста: клики мыши приходят в пикселях окна.

        В полноэкранном режиме (клавиша F и калибровка взгляда) окно растянуто
        на весь монитор, поэтому координаты мыши нужно пересчитать обратно.
        """
        fw, fh = self._frame_size
        try:
            _x, _y, ww, wh = cv2.getWindowImageRect(self._window_name)
        except Exception:
            return 1.0, 1.0
        if ww > 0 and wh > 0 and (ww != fw or wh != fh):
            return fw / float(ww), fh / float(wh)
        return 1.0, 1.0

    def _on_mouse(self, event: int, x: int, y: int) -> None:
        if not self.settings_open():
            return
        size = self._frame_size
        sx, sy = self._window_scale()
        x, y = int(x * sx), int(y * sy)
        action = self.settings.on_mouse(event, x, y, size)
        if action in ("save", "close"):
            self._close_settings()
        elif action in ("change", "reset"):
            self._apply_settings_live()

    def _apply_settings_live(self) -> None:
        """Применить изменённые настройки к уже работающим узлам.

        Все автоматы держат ссылку на тот же объект конфигурации, поэтому правки
        видны сразу; здесь досинхронизируем то, что копируется в состояние окна.
        """
        self.pointer.cfg = self.cfg.pointer
        self.state.pinch_threshold = self.cfg.hand.pinch_ratio

    def _side_text_short(self) -> str:
        return SIDE_TITLES_RU.get(self.hand_fsm.side, "—")

    def calibrate_side(self) -> bool:
        """Клавиша K: запомнить текущую ориентацию кисти как «ладонь».

        Без этой калибровки сторона кисти не определяется: по 21 точке нельзя
        отличить «моя правая рука ладонью» от «моя левая рука тылом» — это
        зеркальные позы. Одно нажатие, пока ладонь смотрит в камеру, снимает
        неоднозначность.
        """
        ok = self.hand_fsm.side_est.calibrate()
        if ok:
            self._events_log.append(
                f"{time.strftime('%H:%M:%S')}  калибровка: ладонь запомнена"
            )
            log.info("Сторона кисти откалибрована: sign=%.0f",
                     self.cfg.hand.side_reference)
        else:
            self._events_log.append(
                f"{time.strftime('%H:%M:%S')}  калибровка: покажите ладонь в камеру"
            )
            log.info("Калибровка стороны не удалась: рука не в кадре или повёрнута ребром")
        return ok

    def flip_side(self) -> None:
        """Инверсия «ладонь ↔ тыл», если калибровка была наоборот."""
        self.hand_fsm.side_est.flip()
        self._events_log.append(f"{time.strftime('%H:%M:%S')}  сторона кисти: инверсия")

    def cycle_modes(self) -> str:
        """Клавиша V: рука → рука + лицо → две руки → только лицо."""
        name = cycle_preset(self.cfg, self.router)
        self._events_log.append(f"{time.strftime('%H:%M:%S')}  режим: {name}")
        log.info("Режим управления: %s (%s)", name, modes_summary(self.cfg, self.router))
        return name

    def settings_open(self) -> bool:
        return self.settings is not None and self.settings.is_open

    def toggle_settings(self) -> bool:
        """Открыть/закрыть окно настроек с ползунками (клавиша C).

        Пока окно открыто, управление мышью на паузе: иначе курсор убегал бы
        из-под руки прямо во время перетаскивания ползунка.
        """
        if self.settings_open():
            self._close_settings()
            return False
        if not self.show_window:
            log.info("Настройки открываются только с окном: уберите --no-window")
            return False
        if self.settings is None:
            self.settings = SettingsPanel(self.cfg, path=self.config_path,
                                          runtime=self.router, hooks={
                "calibrate": self.calibrate_side,
                "flip": self.flip_side,
                "side": self._side_text_short,
                "gaze_calibrate": self.start_gaze_calibration,
                "gaze_reset": self.reset_gaze_calibration,
            })
        if not self.settings.open():
            return False
        self._bind_mouse()
        self._paused_for_settings = self.router.paused
        self.router.paused = True
        self._events_log.append(
            f"{time.strftime('%H:%M:%S')}  настройки: управление мышью на паузе"
        )
        return True

    def save_settings(self, reason: str = "") -> Optional[Path]:
        """Сохранить всё, что настроено, чтобы после перезапуска было так же.

        Пишем **весь** конфиг, а не отдельные ключи: режимы, пороги, ползунки,
        калибровку взгляда и профиль движений, раскладку ролей рук. Раньше
        сохраняла только кнопка в панели настроек, поэтому всё, что включалось
        клавишами (мышь глазами, тело, полный экран), после выхода пропадало.
        """
        if not self.autosave:
            return None
        # то, что переключается на ходу, лежит не только в cfg — переносим
        self.cfg.fullscreen = bool(self._fullscreen)
        self.cfg.gaze_pointer = bool(self.router.gaze_pointer)
        self.cfg.head_pointer = bool(self.router.head_pointer)
        # пустую калибровку не записываем как «есть»: иначе в файле остаётся
        # восемь пустых полей и по нему не понять, калиброван человек или нет
        self.cfg.face.gaze_calibration = (self.gaze_calib.to_dict()
                                          if self.gaze_calib.ready else {})
        try:
            snapshot = json.dumps(asdict(self.cfg), ensure_ascii=False,
                                  sort_keys=True, default=str)
        except Exception as exc:        # страховка: не сохранить, но и не упасть
            log.debug("Настройки не сериализуются: %s", exc)
            return None
        if snapshot == self._saved_snapshot:
            return None                 # ничего не менялось — не трогаем диск
        try:
            path = save_config(self.cfg, self.config_path)
        except Exception as exc:
            log.warning("Не удалось сохранить настройки: %s", exc)
            return None
        self._saved_snapshot = snapshot
        log.info("Настройки сохранены: %s%s", path,
                 f" ({reason})" if reason else "")
        return path

    def _remember_snapshot(self) -> None:
        """Запомнить текущее состояние конфига как уже сохранённое."""
        try:
            self._saved_snapshot = json.dumps(asdict(self.cfg), ensure_ascii=False,
                                              sort_keys=True, default=str)
        except Exception:
            self._saved_snapshot = ""

    def _maybe_autosave(self, now: float) -> None:
        """Раз в несколько секунд проверяем, не изменились ли настройки."""
        if not self.autosave or now - self._autosave_at < 5.0:
            return
        self._autosave_at = now
        self.save_settings()

    def _close_settings(self) -> None:
        if self.settings is None:
            return
        was_dirty = self.settings.dirty
        self.settings.close(save=was_dirty)
        saved = was_dirty or self.settings.saved
        self._events_log.append(
            f"{time.strftime('%H:%M:%S')}  "
            + ("настройки сохранены" if saved else "настройки закрыты без сохранения")
        )
        if saved:
            # панель уже записала файл — запоминаем снимок, чтобы автосохранение
            # не писало его второй раз
            self._remember_snapshot()
        self.router.paused = self._paused_for_settings
        self._paused_for_settings = False

    def _settings_live(self) -> str:
        """Строка «сейчас: …» — чтобы видеть эффект ползунков на живых цифрах."""
        parts: List[str] = []
        feats = getattr(self.hand_fsm, "last_features", None)
        if feats is not None and getattr(feats, "valid", False):
            parts.append(f"щипок {feats.pinch:.2f}")
        if self.state.pose and self.state.pose != "—":
            parts.append(f"жест: {self.state.pose}")
        pos = self.pointer.position
        if pos is not None:
            parts.append(f"курсор {int(pos[0])},{int(pos[1])}")
        if self.router.head_pointer:
            parts.append(f"голова {self.face_fsm.rel_yaw:+.0f}°/ {self.face_fsm.rel_pitch:+.0f}°")
        if self.router.gaze_pointer:
            parts.append(f"взгляд {self.face_fsm.gaze_x:+.2f}/{self.face_fsm.gaze_y:+.2f}")
        parts.append(f"{self.state.fps:.0f} кадр/с")
        return "сейчас: " + "   ".join(parts)

    def _head_pointer_events(self, now: float) -> List[Event]:
        """«Мышь головой»: курсор двигается наклоном головы.

        В нейтрали курсор стоит; возврат головы в нормальное положение не тянет
        его обратно — движение начинается только со следующего наклона за
        мёртвой зоной. Чувствительность — ``face.head_gain_x/y`` (пикселей в
        секунду на градус).
        """
        dt = max(now - self._last_now, 1e-3) if self._last_now else 1.0 / 30.0
        dx, dy = self.face_fsm.head_step(dt)
        limit = float(self.cfg.pointer.max_step_px)
        dx = max(-limit, min(limit, dx))
        dy = max(-limit, min(limit, dy))
        if abs(dx) < 1.0 and abs(dy) < 1.0:
            return []
        return [Event("pointer_rel", value=(dx, dy))]

    def _gaze_pointer_events(self, now: float) -> List[Event]:
        """«Мышь глазами».

        Если взгляд откалиброван (клавиша ``B``) — курсор **телепортируется**
        туда, куда человек смотрит: положение зрачка переводится в точку экрана
        через калибровочное преобразование, сглаживается и не дёргается на
        дрожании (``face.gaze_deadzone_px``). Косить глазами не нужно.

        Без калибровки — резервный «скоростной» режим: чем дальше зрачок от
        нейтрали, тем быстрее едет курсор.
        """
        if (self.cfg.face.gaze_absolute and self.gaze_calib.ready
                and self.face_fsm.gaze_valid and self._metrics is not None):
            # Поправка на поворот головы: человек вертит головой, но смотрит
            # в ту же точку — зрачок «уезжает», калибровка это вычитает.
            u, v = self.gaze_calib.head_correct(
                self.face_fsm.gaze_u, self.face_fsm.gaze_v,
                self.face_fsm.head_yaw, self.face_fsm.head_pitch,
            )
            sx, sy = self.gaze_calib.apply(u, v)
            width, height = self.backend.screen_size()
            # 0 -> первый пиксель, 1 -> последний: край экрана достижим ровно
            px, py = screen_point(sx, sy, (width, height))
            self._gaze_track.append((float(sx), float(sy)))
            point = self.gaze_cursor.update(px, py)
            events: List[Event] = []
            if point is not None:
                x, y = point
                events.append(Event("pointer", value=(int(round(x)), int(round(y)))))
            if self.cfg.face.gaze_dwell_click:
                # «взгляд + удержание»: клик не мгновенный, а через 600 мс,
                # с видимым прогрессом — иначе это классическая проблема
                # Midas touch (любое движение глаз что-то нажимает)
                progress, fired = self.gaze_dwell.update(px, py, now)
                self.state.gaze_dwell = progress
                if fired:
                    events.append(Event("gaze_click", label="удержание взгляда"))
            return events
        dt = max(now - self._last_now, 1e-3) if self._last_now else 1.0 / 30.0
        dx, dy = self.face_fsm.gaze_step(dt)
        limit = float(getattr(self.cfg.face, "gaze_max_step_px",
                              self.cfg.pointer.max_step_px))
        dx = max(-limit, min(limit, dx))
        dy = max(-limit, min(limit, dy))
        if abs(dx) < 1.0 and abs(dy) < 1.0:
            return []
        return [Event("pointer_rel", value=(dx, dy))]

    def _note_palm_hint(self, now: float) -> None:
        """Один раз в несколько секунд объяснить, почему ладонь не сработала.

        Человек поднимает руку, ждёт паузу, и ничего не происходит: обычно кисть
        стоит под углом или развёрнута тылом. Молчать в этот момент — худшее,
        что можно сделать, поэтому причина пишется в журнал окна.
        """
        hint = getattr(self.hand_fsm, "palm_reject", "")
        if not hint:
            return
        every = float(getattr(self.cfg.hand, "palm_hint_cooldown_s", 8.0))
        if now - self._palm_hint_at < every:
            return
        self._palm_hint_at = now
        self._events_log.appendleft(f"ладонь: {hint}")
        log.info("Ладонь не распознана: %s", hint)

    # ------------------------------------------------------------------ #
    #  Профиль движений: личный диапазон рук, мимики и тела (клавиша N)
    # ------------------------------------------------------------------ #
    def start_motion_profile(self) -> str:
        """Мастер «профиля движений»: замерить свой диапазон вместо среднего.

        Взгляду калибровка нужна, потому что «палец зрачка» сам по себе не
        говорит, куда человек смотрит. Рукам, лицу и телу она в этом смысле не
        нужна — но их **размах** у всех разный, и общий порог кому-то мал, а
        кому-то велик. Здесь измеряем размах и ставим пороги по нему.
        """
        if self.calibrating:
            return "сначала закончите калибровку взгляда"
        self.motion_wizard = MotionWizard()
        self._motion_at = 0.0
        text = ("профиль движений: сейчас по очереди разожмите пальцы, улыбнитесь, "
                "поднимите брови, откройте рот и присядьте — всё по подсказке сверху")
        self._events_log.appendleft(text)
        log.info("Старт профиля движений (N)")
        return text

    def skip_motion_step(self) -> str:
        """ПРОБЕЛ: пропустить текущий шаг профиля."""
        if self.motion_wizard is None:
            return ""
        done = self.motion_wizard.skip()
        if done:
            return self._finish_motion_profile()
        self._events_log.appendleft(self.motion_wizard.text())
        return self.motion_wizard.text()

    def cancel_motion_profile(self) -> str:
        self.motion_wizard = None
        self._events_log.appendleft("профиль движений отменён")
        return "профиль движений отменён"

    def _motion_features(self) -> Dict[str, Optional[float]]:
        """Текущие признаки для мастера профиля (нет данных — ``None``)."""
        pinch: Optional[float] = None
        if self._hands:
            try:
                pinch = float(analyze_hand(self._hands[0], self.cfg.hand.pointer_source).pinch)
            except Exception:               # кривые landmarks — просто пропускаем кадр
                pinch = None
        fsm = self.face_fsm
        smile = float(getattr(fsm, "smile_score", 0.0))
        brow = float(getattr(fsm, "brow_score", 0.0))
        mouth: Optional[float] = None
        if self._metrics is not None and getattr(self._metrics, "valid", False):
            mouth = float(self._metrics.mouth_open)
        body = getattr(self.body_fsm, "metrics", None)
        squat = float(getattr(body, "squat", 0.0)) if body is not None else None
        return {"pinch": pinch, "smile": smile, "brow": brow,
                "mouth": mouth, "squat": squat}

    def _tick_motion_profile(self, now: float) -> None:
        """Один кадр мастера: отдать ему текущие признаки и проверить время."""
        wizard = self.motion_wizard
        if wizard is None:
            return
        dt = 0.0 if self._motion_at <= 0.0 else max(0.0, now - self._motion_at)
        self._motion_at = now or 1e-6
        if wizard.update(dt, **self._motion_features()):
            self._finish_motion_profile()

    def _finish_motion_profile(self) -> str:
        """Свести замеры в профиль, применить пороги и сохранить в настройках."""
        wizard = self.motion_wizard
        self.motion_wizard = None
        if wizard is None:
            return ""
        prof = wizard.finish()
        suggested = prof.suggest()
        applied = []
        for key, value in suggested.items():
            if hasattr(self.cfg.hand, key):
                setattr(self.cfg.hand, key, value)
            elif hasattr(self.cfg.face, key):
                setattr(self.cfg.face, key, value)
            elif hasattr(self.cfg.body, key):
                setattr(self.cfg.body, key, value)
            else:
                continue
            applied.append(f"{key}={value:g}")
        self.cfg.motion_profile = prof.to_dict()
        text = prof.text()
        if applied:
            text += ". пороги: " + ", ".join(applied)
        else:
            text += ". пороги не менялись: мало данных, повторите (N)"
        self._events_log.appendleft(text)
        log.info("%s", text)
        return text

    # ------------------------------------------------------------------ #
    #  Калибровка взгляда: «ведите взгляд за красной точкой»
    # ------------------------------------------------------------------ #
    def start_gaze_calibration(self, mode: str = "") -> str:
        """Мастер калибровки взгляда.

        Фазы: ``pursuit`` — вести взгляд за медленно ползущей точкой;
        ``head_intro`` — прочитать, что делать дальше (никуда смотреть не надо);
        ``head_count`` — «3…2…1»; ``head`` — 6 секунд смотреть в центр и
        медленно вертеть головой.

        Старый режим ``points`` (девять прицелов по пробелу) остаётся запасным:
        ``config set face.gaze_calib_mode=points``.
        """
        chosen = (mode or str(getattr(self.cfg.face, "gaze_calib_mode", "pursuit"))).lower()
        points_mode = chosen == "points"
        self._calib = {
            "mode": "points" if points_mode else "pursuit",
            "phase": "points" if points_mode else "pursuit",
            "phase_since": None,
            "elapsed": 0.0,
            "index": 0,
            "samples": [],                  # «посмотрите и нажмите» или глаза в моменте
            "points": [],                   # (gx, gy, sx, sy) для подгонки
            "pursuit": [],                  # (t, gx, gy, sx, sy) — «вёл за точкой»
            "dot": (PURSUIT_MARGIN, PURSUIT_ROWS[0]),
            "trail": [],                    # след точки: видно, куда она уползла
            "head": [],                     # (gx, gy, yaw, pitch) для компенсации
            "head_since": None,
        }
        self.gaze_cursor.reset()
        # Полный экран ставим заново при каждой калибровке: окно могло «съежиться»
        # после прошлого раза, а прицел обязан попадать в настоящие углы монитора.
        self._fullscreen_applied = None
        self._fit_tries = 0
        self._fit_last_try = 0.0
        self._fit_series = 0
        if not self.show_window:
            log.warning("Калибровка взгляда без окна: прицел на весь экран не "
                        "показать — запустите с окном (или нажмите F)")
        if points_mode:
            text = f"калибровка взгляда: {TARGET_TITLES[0]} — смотрите и нажмите пробел"
        else:
            text = ("калибровка взгляда: ведите взгляд за красной точкой — "
                    f"{self._pursuit_s():.0f} с (ПРОБЕЛ — хватит, Esc — отмена)")
        self._events_log.appendleft(text)
        return text

    @property
    def calibrating(self) -> bool:
        return self._calib is not None

    # ------------------------------------------------------------------ #
    def _pursuit_s(self) -> float:
        return float(getattr(self.cfg.face, "gaze_pursuit_s", PURSUIT_DURATION_S))

    def _head_phase_s(self) -> float:
        return float(getattr(self.cfg.face, "gaze_head_check_s", 6.0))

    def _phase_elapsed(self) -> float:
        if self._calib is None:
            return 0.0
        return float(self._calib.get("elapsed") or 0.0)

    def calibration_target(self) -> Optional[Tuple[float, float]]:
        """Куда сейчас смотреть (нормированные координаты экрана)."""
        if self._calib is None:
            return None
        phase = self._calib.get("phase")
        if phase == "pursuit":
            return self._calib.get("dot") or (0.5, 0.5)
        if phase in ("head_intro", "head_count", "head"):
            return (0.5, 0.5)
        index = int(self._calib["index"])
        if 0 <= index < len(CALIBRATION_TARGETS):
            return CALIBRATION_TARGETS[index]
        return None

    def calibration_text(self) -> str:
        if self._calib is None:
            return ""
        phase = self._calib.get("phase")
        elapsed = self._phase_elapsed()
        if phase == "pursuit":
            left = max(0.0, self._pursuit_s() - elapsed)
            return (f"ВЗГЛЯД: ведите взгляд за красной точкой  ({left:.0f} с)   "
                    "не отвлекайтесь на текст    ПРОБЕЛ — хватит    Esc — отмена")
        if phase == "head_intro":
            return ("ДАЛЬШЕ: 6 секунд смотреть в центр и медленно вертеть головой. "
                    "Прочитали — жмите ПРОБЕЛ (или подождите, начнётся само)")
        if phase == "head_count":
            left = max(0.0, float(getattr(self.cfg.face, "gaze_head_count_s", 3.0)) - elapsed)
            return f"ПРИГОТОВЬТЕСЬ: {int(left) + 1}…   смотрите в центр экрана"
        if phase == "head":
            left = max(0.0, self._head_phase_s() - elapsed)
            return ("ВЗГЛЯД: не отводя взгляда от центра, поверните голову "
                    f"влево-вправо и вверх-вниз  ({left:.0f} с)    ПРОБЕЛ — готово")
        index = int(self._calib["index"])
        if index < len(CALIBRATION_TARGETS):
            title = TARGET_TITLES[index]
            return (f"ВЗГЛЯД: {title}  ({index + 1}/{len(CALIBRATION_TARGETS)})"
                    f"   смотрите туда и нажмите ПРОБЕЛ    Esc — отмена")
        return "калибровка взгляда: сохраняю…"

    def cancel_gaze_calibration(self) -> str:
        self._calib = None
        self.gaze_cursor.reset()
        self._fullscreen_applied = None      # вернуть окно в обычный вид
        self._fit_tries = 0
        self._fit_last_try = 0.0
        self._fit_series = 0
        self._events_log.appendleft("калибровка взгляда отменена")
        return "калибровка взгляда отменена"

    def _enter_phase(self, phase: str, now: float, note: str = "") -> None:
        self._calib["phase"] = phase
        self._calib["phase_since"] = now
        self._calib["elapsed"] = 0.0
        self._calib["samples"] = []
        if note:
            self._events_log.appendleft(note)

    def _after_pursuit(self, now: float) -> str:
        """Точка прошла экран — дальше проверка поворота головы (если включена)."""
        if self._head_phase_s() > 0:
            self._enter_phase("head_intro", now,
                              "калибровка: прочитайте подсказку и жмите ПРОБЕЛ")
            return self.calibration_text()
        return self._finish_gaze_calibration()

    def confirm_gaze_point(self) -> str:
        """ПРОБЕЛ: досрочно закончить текущую фазу или запомнить точку."""
        if self._calib is None:
            return ""
        phase = self._calib.get("phase")
        now = self._calib.get("now") or 0.0
        if phase == "pursuit":
            frames = len(self._calib["pursuit"])
            if frames < 30:
                return "ещё рано: проведите взглядом за точкой хотя бы секунду"
            return self._after_pursuit(now)
        if phase == "head_intro":
            self._enter_phase("head_count", now)
            return self.calibration_text()
        if phase in ("head_count", "head"):
            return self._finish_gaze_calibration()
        # --- запасной режим: девять прицелов --- #
        if not self.face_fsm.gaze_valid:
            return "зрачков не видно — калибровка невозможна"
        target = self.calibration_target()
        if target is None:
            return ""
        samples = self._calib["samples"]
        if len(samples) < 3:
            return "подержите взгляд на точке ещё мгновение"
        gx, gy = average_gaze(samples)
        self._calib["points"].append((gx, gy, target[0], target[1]))
        self._calib["samples"] = []
        self._calib["index"] = int(self._calib["index"]) + 1
        if int(self._calib["index"]) < len(CALIBRATION_TARGETS):
            return self.calibration_text()
        return self._after_pursuit(now)

    # ------------------------------------------------------------------ #
    def _finish_gaze_calibration(self) -> str:
        """Собрать калибровку: гомография + поправка на голову + динамика взгляда."""
        data = self._calib or {}
        if data.get("mode") == "pursuit":
            points = [(u, v, sx, sy) for (_t, u, v, sx, sy) in data.get("pursuit") or []]
        else:
            points = list(data.get("points") or [])
        head_samples = list(data.get("head") or [])
        calib = GazeCalibration(points=points, feature="head2")
        fitted = calib.fit()
        self._calib = None
        self.gaze_cursor.reset()
        self._fullscreen_applied = None      # калибровка кончилась — обычное окно
        self._fit_tries = 0
        self._fit_last_try = 0.0
        self._fit_series = 0
        if not fitted:
            text = "калибровка взгляда не удалась: мало кадров — нажмите B ещё раз"
            self._events_log.appendleft(text)
            log.warning("%s", text)
            return text
        metrics = pursuit_metrics(data.get("pursuit") or [])
        calib.latency_ms = metrics["latency_ms"]
        calib.responsiveness = metrics["responsiveness"]
        calib.pursuit_frames = int(metrics["frames"])
        calib.face_scale = float(getattr(self._metrics, "interocular", 0.0) or 0.0)
        head_ok = calib.fit_head(head_samples)
        self.gaze_calib = calib
        self.cfg.face.gaze_calibration = calib.to_dict()
        self.cfg.face.gaze_absolute = True
        worst, mean = calib.error()
        self._gaze_error_cache = (worst, mean)
        self._gaze_track.clear()
        tune = self._autotune_gaze(calib)
        self.save_settings("калибровка взгляда")
        text = (f"калибровка взгляда готова: {len(calib.points)} проб, "
                f"{calib.quality_text()}, "
                f"задержка взгляда {calib.latency_ms:.0f} мс, "
                f"{calib.head_gain_text() if head_ok else 'поворот головы: без компенсации'}")
        if tune:
            text += f", {tune}"
        self._events_log.appendleft(text)
        log.info("Калибровка взгляда: %d проб, %s, задержка %.0f мс",
                 len(calib.points), calib.quality_text(), calib.latency_ms)
        if worst > 0.08:
            warn = ("калибровка неточная (промах до "
                    f"{worst * 100:.0f}% экрана) — повторите, ведя точку глазами")
            self._events_log.appendleft(warn)
            self.state.backend_note = warn[:64]
            log.warning("%s", warn)
        return text

    def _autotune_gaze(self, calib: GazeCalibration) -> str:
        """Подобрать сглаживание и мёртвую зону по данным самой калибровки.

        Идея из настроек Eye Tracking у Apple: «smoothing» — больше плавности
        или больше отзывчивости. Величину выбираем не на глаз, а по двум
        измерениям: насколько зрачок отстаёт от цели (задержка) и насколько он
        шумит (средний промах).
        """
        if not bool(getattr(self.cfg.face, "gaze_autotune", True)):
            return ""
        _worst, mean = calib.error()
        latency_s = max(0.0, calib.latency_ms) / 1000.0
        alpha = min(0.90, max(0.35, 0.90 - latency_s * 1.5))
        deadzone = int(round(min(30.0, max(6.0, 6.0 + mean * 300.0))))
        self.cfg.face.gaze_cursor_alpha = round(alpha, 2)
        self.cfg.face.gaze_deadzone_px = deadzone
        self.gaze_cursor = GazeCursor(deadzone, self.cfg.face.gaze_cursor_alpha)
        return f"сглаживание {alpha:.2f}, мёртвая зона {deadzone} px"

    def _note_gaze_drift(self, now: float) -> None:
        """Лицо уехало от камеры — как у Apple, напомнить про перекалибровку."""
        calib = self.gaze_calib
        if not calib.ready or calib.face_scale <= 1e-6 or self._metrics is None:
            return
        scale = float(getattr(self._metrics, "interocular", 0.0) or 0.0)
        if scale <= 1e-6:
            return
        limit = float(getattr(self.cfg.face, "gaze_recalib_scale", 0.25))
        if abs(scale / calib.face_scale - 1.0) <= limit:
            return
        every = float(getattr(self.cfg.face, "gaze_recalib_cooldown_s", 60.0))
        if now - self._gaze_drift_at < every:
            return
        self._gaze_drift_at = now
        text = "лицо/камера сместились после калибровки — нажмите B, иначе взгляд врёт на краях"
        self._events_log.appendleft(text)
        log.info("%s", text)

    # ------------------------------------------------------------------ #
    def _tick_gaze_calibration(self, now: float) -> None:
        """Один кадр мастера калибровки: время, точка, сэмплы."""
        calib = self._calib
        if calib is None:
            return
        calib["now"] = now
        if calib.get("phase_since") is None:
            calib["phase_since"] = now
        elapsed = max(0.0, now - float(calib["phase_since"]))
        calib["elapsed"] = elapsed
        phase = calib.get("phase")
        if phase == "pursuit":
            dot = pursuit_point(elapsed, self._pursuit_s())
            calib["dot"] = dot
            trail = calib["trail"]
            trail.append(dot)
            if len(trail) > 60:
                del trail[:-60]
            if elapsed >= self._pursuit_s():
                self._after_pursuit(now)
                return
        elif phase == "head_intro":
            if elapsed >= float(getattr(self.cfg.face, "gaze_head_intro_s", 8.0)):
                self._enter_phase("head_count", now)
                return
        elif phase == "head_count":
            if elapsed >= float(getattr(self.cfg.face, "gaze_head_count_s", 3.0)):
                self._enter_phase("head", now, "калибровка: смотрите в центр и вертите головой")
                return
        elif phase == "head":
            if elapsed >= self._head_phase_s():
                self._finish_gaze_calibration()
                self._update_state([], 0.0)
                return
        self._collect_gaze_sample()

    def _collect_gaze_sample(self) -> None:
        """Копим положение зрачка: за точкой, на прицеле или при повороте головы."""
        if self._calib is None or not self.face_fsm.gaze_valid:
            return
        phase = self._calib.get("phase")
        if phase == "pursuit":
            dot = self._calib.get("dot") or (0.5, 0.5)
            self._calib["pursuit"].append(
                (self._phase_elapsed(), self.face_fsm.gaze_u, self.face_fsm.gaze_v,
                 dot[0], dot[1])
            )
            return
        if phase == "head":
            head = self._calib["head"]
            head.append((self.face_fsm.gaze_u, self.face_fsm.gaze_v,
                         self.face_fsm.head_yaw, self.face_fsm.head_pitch))
            if len(head) > 600:
                del head[:-600]
            return
        if phase != "points":
            return                    # intro/count — ничего не снимаем
        samples = self._calib["samples"]
        samples.append((self.face_fsm.gaze_u, self.face_fsm.gaze_v))
        if len(samples) > 60:
            del samples[:-60]
    def reset_gaze_calibration(self) -> str:
        self.gaze_calib = GazeCalibration()
        self.gaze_cursor.reset()
        self._gaze_error_cache = (0.0, 0.0)
        self._gaze_track.clear()
        self.cfg.face.gaze_calibration = {}
        self.save_settings("калибровка сброшена")
        self._events_log.appendleft("калибровка взгляда сброшена")
        return "калибровка взгляда сброшена"

    def reset_gaze_calibration(self) -> str:
        self.gaze_calib = GazeCalibration()
        self.gaze_cursor.reset()
        self._gaze_error_cache = (0.0, 0.0)
        self._gaze_track.clear()
        self.cfg.face.gaze_calibration = {}
        self.save_settings("калибровка сброшена")
        self._events_log.appendleft("калибровка взгляда сброшена")
        return "калибровка взгляда сброшена"

    def toggle_gaze_pointer(self) -> str:
        """Включить/выключить управление курсором глазами (клавиша G)."""
        on = not self.router.gaze_pointer
        self.router.gaze_pointer = on
        self.cfg.gaze_pointer = on
        self.state.gaze_pointer = on
        hint = ""
        if on and not (self.cfg.face.gaze_absolute and self.gaze_calib.ready):
            hint = " (B — калибровка: без неё курсор телепортируется)"
        self._events_log.appendleft(
            "мышь глазами " + ("вкл" if on else "выкл")
            + ("" if self.face_fsm.gaze_valid else " (зрачков пока не видно)")
            + hint
        )
        return "gaze_pointer=" + ("on" if on else "off")

    def gaze_direction(self) -> Tuple[str, Optional[Tuple[float, float]]]:
        """Куда смотрит человек: слово и (если есть калибровка) точка экрана.

        Важно, что направление считается **тем же путём**, что и курсор: когда
        есть калибровка, берётся точка экрана из гомографии, а не «сырое»
        положение зрачка. Раньше подпись «взгляд: влево» строилась по сырым
        числам, а курсор ехал по калиброванной карте — и они расходились,
        особенно вверх-вниз.
        """
        fsm = self.face_fsm
        cfg = self.cfg.face
        calibrated = bool(cfg.gaze_absolute and self.gaze_calib.ready
                          and not self.gaze_calib.stale)
        if calibrated:
            u, v = self.gaze_calib.head_correct(
                fsm.gaze_u, fsm.gaze_v, fsm.head_yaw, fsm.head_pitch)
            sx, sy = self.gaze_calib.apply(u, v)
            # «прямо» — центральная восьмая часть экрана: иначе шум зрачка
            # переключал бы слово по десять раз в секунду
            nx, ny = (sx - 0.5) * 2.0, (sy - 0.5) * 2.0
            if abs(nx) < 0.16 and abs(ny) < 0.16:
                where = "прямо"
            elif abs(nx) >= abs(ny):
                where = "вправо" if nx > 0 else "влево"
            else:
                where = "вниз" if ny > 0 else "вверх"
            return where, (sx, sy)

        gx, gy = fsm.gaze_x - fsm.baseline.gaze_x, fsm.gaze_y - fsm.baseline.gaze_y
        # сравниваем «насколько вышли за свою мёртвую зону», а не сырые числа:
        # по вертикали ход зрачка меньше, и сырое сравнение всегда давало «прямо»
        nx = gx / max(cfg.gaze_full_scale_x, 1e-3)
        ny = gy / max(cfg.gaze_full_scale_y, 1e-3)
        inside = (abs(gx) <= cfg.gaze_deadzone) and (abs(gy) <= cfg.gaze_deadzone_y)
        if inside:
            where = "прямо"
        elif abs(nx) >= abs(ny):
            where = "вправо" if gx > 0 else "влево"
        else:
            where = "вниз" if gy > 0 else "вверх"
        return where, None

    def gaze_quality(self) -> str:
        """Точность и дрожание взгляда словами: «ошибка 1.4%, дрожание 0.6%».

        Ошибка — по промахам калибровки (насколько гомография не попала в точки,
        по которым её строили). Дрожание — разброс уже калиброванной позиции за
        последнюю секунду: видно, насколько «звенит» курсор, даже когда взгляд
        стоит на месте.
        """
        parts = []
        calib = self.gaze_calib
        if calib.ready and not calib.stale:
            worst, mean = self._gaze_error_cache
            parts.append(f"ошибка {mean * 100:.1f}%")
            if worst > 0.08:
                parts.append("калибровка неточная")
        track = list(self._gaze_track)[-30:]
        if len(track) >= 8:
            xs = [p[0] for p in track]
            ys = [p[1] for p in track]
            jitter = max(max(xs) - min(xs), max(ys) - min(ys))
            parts.append(f"дрожание {jitter * 100:.1f}%")
        return " · ".join(parts)

    def gaze_text(self) -> str:
        """Короткая строка про взгляд: куда смотрит и включено ли управление."""
        fsm = self.face_fsm
        if not fsm.gaze_valid:
            return "взгляд: зрачков не видно (нужна нейросеть MediaPipe)"
        where, point = self.gaze_direction()
        quality = self.gaze_quality()
        quality = f" · {quality}" if quality else ""
        head = ""
        if self.face_fsm.head_ok:
            yaw = self.face_fsm.head_yaw
            pitch = self.face_fsm.head_pitch
            # про голову пишем только когда она реально повёрнута: при ровной
            # голове строка и без того длинная
            if abs(yaw) > 5 or abs(pitch) > 5:
                head = f" · голова {yaw:+.0f}°/{pitch:+.0f}°"
        if self.router.gaze_pointer:
            mode = ("телепорт" if (self.cfg.face.gaze_absolute
                                   and self.gaze_calib.ready
                                   and not self.gaze_calib.stale) else "скоростной")
            return f"взгляд: {where} · мышь глазами ВКЛ ({mode}){quality}{head}"
        if self.gaze_calib.stale:
            return f"взгляд: {where} · калибровка старого образца — нажмите B{head}"
        if self.gaze_calib.ready:
            mark = "⚠ " if self._gaze_error_cache[0] > 0.08 else ""
            return (f"взгляд: {where} · {mark}калибровка есть{quality} "
                    f"(G — включить){head}")
        return f"взгляд: {where} · B — калибровка взгляда{head}"

    def _expression_text(self) -> str:
        """Текущее выражение лица словами — чтобы мимика была понятна без графиков."""
        m = self._metrics
        if m is None or not m.valid:
            return ""
        fsm = self.face_fsm
        ear = min(m.ear_left, m.ear_right)
        if ear < self.cfg.face.ear_blink:
            return "глаза закрыты"
        # грусть проверяем раньше улыбки: опущенные уголки растягивают рот,
        # и по одной ширине рта это выглядело бы как «улыбка N%»
        sad = getattr(fsm, "sad_score", 0.0)
        if sad > self.cfg.face.sad_delta:
            level = min(1.0, sad / max(self.cfg.face.sad_delta * 2.5, 1e-6))
            return f"грусть {level:.0%}"
        if fsm.smile_score > self.cfg.face.smile_delta:
            level = min(1.0, fsm.smile_score / max(self.cfg.face.smile_delta * 2.5, 1e-6))
            return f"улыбка {level:.0%}"
        if (fsm.brow_score > self.cfg.face.brow_delta * 1.2
                and m.mouth_open > self.cfg.face.surprise_mouth):
            return "удивление"
        if fsm.brow_score > self.cfg.face.brow_delta:
            return "брови подняты"
        if m.mouth_open > self.cfg.face.mouth_open_ratio:
            return "рот открыт"
        return "нейтрально"

    def _update_state(self, events: List[Event], loop_fps: float) -> None:
        s = self.state
        s.fps = loop_fps
        s.warmup = self._last_now < self._armed_at
        raw_name = getattr(self.tracker, "name", "?")
        s.backend = BACKEND_TITLES.get(raw_name, raw_name)
        s.backend_note = getattr(self.tracker, "fallback_reason", "") or ""
        s.events = list(self._events_log)
        s.expression = self._expression_text()
        s.actions_on = not self.dry_run
        s.dry_run = self.dry_run
        # «прицел»: курсор заморожен на точке, куда целятся щипком
        s.aiming = bool(self.hand_fsm.approaching) and self.hand_fsm.aim_point is not None
        s.aim = self.hand_fsm.aim_point
        s.two_hand_hint = self.two_hand_fsm.hint if self.two_hand_fsm.active else ""
        split = getattr(self.cfg.hand, "roles", "single") == "split"
        s.split_roles = split and len(self._hands) >= 2
        s.roles_text = ("роли: 1 — курсор, 2 — клики" if s.split_roles else "")
        s.settings_open = self.settings_open()
        s.modes_text = "режимы: " + modes_summary(self.cfg, self.router)
        side = self.hand_fsm.side
        if side is HandSide.UNKNOWN:
            s.side_text = "сторона кисти: не определена (K — показать ладонь)"
        else:
            s.side_text = f"сторона кисти: {SIDE_TITLES_RU.get(side, '—')}"
        s.paused = self.router.paused
        s.head_pointer = self.router.head_pointer
        s.gaze_pointer = self.router.gaze_pointer
        s.gaze_text = self.gaze_text() if self._metrics is not None else ""
        # одна короткая строка про кисть: предсказание или «физика» пальцев
        notes = list(dict.fromkeys(n for n in self._hand_notes if n))
        s.hand_note = " · ".join(notes[:2])
        s.hand_predicted = bool(self._predicted_hands and any(self._predicted_hands))
        s.body_enabled = bool(getattr(self.cfg.body, "enabled", False))
        metrics_body = self.body_fsm.metrics
        s.body_where = metrics_body.where if metrics_body.visible else ""
        if not s.body_enabled:
            s.body_text = "тело: выключено — клавиша T (или флаг --body)"
        elif metrics_body.visible:
            s.body_text = self.body_fsm.text
        elif getattr(self.tracker, "want_body", False):
            s.body_text = "тело: не вижу — встаньте в кадр (или отойдите на шаг)"
        else:
            s.body_text = "тело: модель позы не загрузилась (нужен MediaPipe)"
        s.gaze_absolute = bool(self.cfg.face.gaze_absolute and self.gaze_calib.ready)
        s.calib_active = self.calibrating
        s.calib_target = self.calibration_target()
        s.calib_text = self.calibration_text()
        s.calib_pursuit = bool(self._calib and self._calib.get("mode") == "pursuit")
        s.calib_trail = tuple(self._calib.get("trail") or ()) if self._calib else ()
        if self.motion_wizard is not None:
            s.profile_text = self.motion_wizard.title
            s.profile_hint = self.motion_wizard.hint
            s.profile_progress = self.motion_wizard.progress
        else:
            s.profile_text = ""
            s.profile_hint = ""
            s.profile_progress = 0.0
        if s.calib_pursuit:
            total = max(self._pursuit_s(), 1e-3)
            s.calib_progress = min(1.0, self._phase_elapsed() / total)
        else:
            s.calib_progress = 0.0
        if self._calib is None:
            s.calib_done = 0
        elif self._calib.get("phase") in ("head", "head_intro", "head_count"):
            s.calib_done = len(CALIBRATION_TARGETS)
        else:
            s.calib_done = int(self._calib["index"])
        s.hand_seen = bool(self._hands) or self._shape is not None
        s.hand_count = len(self._hands)
        s.face_seen = self._face is not None
        if self._hands:
            feats = analyze_hand(self._hands[0], self.cfg.hand.pointer_source)
            s.pose = POSE_TITLES_RU.get(classify_pose(feats, self.cfg.hand), "—")
        elif self._shape is not None:
            s.pose = f"силуэт ({self._shape.rays} лучей)"
        else:
            s.pose = "—"
        m = self._metrics
        if m is not None and m.valid:
            s.ear = min(m.ear_left, m.ear_right)
            s.smile = self.face_fsm.smile_score
            s.brow = self.face_fsm.brow_score
            s.mouth_open = m.mouth_open
            s.sad = getattr(self.face_fsm, "sad_score", 0.0)
        for ev in events:
            if ev.kind in HAND_EVENTS_RU:
                extra = ""
                if ev.kind == "lip_word" and ev.value is not None:
                    extra = f": {ev.value.word}"
                s.last_event = HAND_EVENTS_RU[ev.kind] + extra

    # ------------------------------------------------------------------ #
    def run(self) -> int:
        if not self._prepared:
            self.setup()
        self.pointer.reset()
        self.running = True
        started = time.monotonic()
        fps = 0.0
        last_loop = started
        exit_code = 0
        try:
            while self.running:
                frame, stamp, seq = self.camera.read()
                if frame is None or seq == self._last_seq:
                    if self.camera.ended:
                        log.info("Видео закончилось")
                        break
                    if not self.camera.alive and self.camera.errors > 20:
                        log.error("Камера перестала отдавать кадры")
                        exit_code = 2
                        break
                    time.sleep(0.003)
                    continue
                self._last_seq = seq

                # В видеофайле время берём из самого видео, иначе — системное.
                now = stamp if (self.cfg.camera.video_file and stamp is not None) else time.monotonic()
                if self._first_now is None:
                    self._first_now = now
                    last_loop = now - 1.0 / max(self.cfg.camera.fps, 1)
                    self._armed_at = now + max(self.cfg.warmup_s, 0.0)
                    if self.cfg.warmup_s > 0:
                        log.info("Разминка %.1f с: распознавание идёт, действия отключены",
                                 self.cfg.warmup_s)
                dt = max(now - last_loop, 1e-3)
                last_loop = now
                fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt
                ts_ms = int((now - self._first_now) * 1000)

                try:
                    events = self.process_frame(frame, now, ts_ms)
                except Exception as exc:  # приложение в фоне не должно падать молча
                    log.exception("Сбой обработки кадра: %s", exc)
                    self.router.paused = True
                    self.router.release_all()
                    events = []
                self._update_state(events, fps)
                self._maybe_autosave(now)

                if self.show_window or self.output is not None:
                    if self.calibrating:
                        # калибровка — на весь монитор, а не в окошке: прицел
                        # должен стоять в настоящем углу экрана
                        canvas = self.calibration_canvas()
                    else:
                        # кадр растягиваем до окна и рисуем поверх него же —
                        # интерфейс получается крупным и резким, а не «мыльным»
                        canvas = render(
                            self._preview_frame(frame), self.state,
                            self._hands_draw or self._hands, self._face,
                            shape=self._shape, metrics=self._metrics,
                            primary=self._primary_index,
                            body=self._body_points if self.cfg.body.show_skeleton else None,
                            body_min_visibility=float(self.cfg.body.min_visibility),
                            predicted=self._predicted_hands,
                        )
                else:
                    canvas = None

                if canvas is not None and not self.calibrating:
                    self._frame_size = (canvas.shape[1], canvas.shape[0])
                if canvas is not None and self.settings_open():
                    canvas = self.settings.draw(canvas, live=self._settings_live())

                if self.output is not None:
                    cv2.imwrite(str(self.output), canvas)

                if self.show_window and canvas is not None:
                    try:
                        cv2.imshow(self._window_name, canvas)
                        if not self._window_sized and not self._fullscreen:
                            # первый показ: сразу нормальный размер, а не 960×540
                            try:
                                w, h = self.window_target_size()
                                cv2.resizeWindow(self._window_name, w, h)
                                log.info("Окно предпросмотра: %dx%d", w, h)
                            except Exception as exc:
                                log.debug("Окно не удалось растянуть при старте: %s", exc)
                            self._window_sized = True
                        self._apply_window_mode()
                        # без & 0xFF: на русской раскладке нужен полный код
                        key = cv2.waitKey(1)
                    except cv2.error as exc:
                        log.warning("Окно предпросмотра недоступно (%s) — работаю в фоне", exc)
                        self.show_window = False
                        continue
                    if self._window_closed():
                        log.info("Окно закрыто крестиком — выходим")
                        self.running = False
                        break
                    handled = False
                    if self.settings_open():
                        action = self.settings.on_key(key)
                        handled = action is not None
                        if action in ("save", "close"):
                            self._close_settings()
                            self._update_state([], fps)
                        elif action in ("reset", "change"):
                            self._apply_settings_live()
                    if not handled:
                        self.handle_hotkey(key)
        except KeyboardInterrupt:
            log.info("Прервано пользователем")
        finally:
            self.shutdown()
        return exit_code

    # ------------------------------------------------------------------ #
    def handle_hotkey(self, key: int) -> bool:
        """Горячие клавиши окна. Работают в любой раскладке (см. ``keys``).

        Возвращает ``True``, если клавиша что-то сделала.
        """
        if keys.matches(key, "esc") or keys.matches(key, "q"):
            if self.motion_wizard is not None:
                self.cancel_motion_profile()
                return True
            if self.calibrating:
                self.cancel_gaze_calibration()
                return True
            self.running = False
            return True
        if keys.matches(key, "p"):
            self.router.paused = not self.router.paused
            return True
        if keys.matches(key, "h"):
            self.router.head_pointer = not self.router.head_pointer
            self.cfg.head_pointer = self.router.head_pointer
            return True
        if keys.matches(key, "g"):
            self.toggle_gaze_pointer()
            return True
        if keys.matches(key, "b"):
            if self.calibrating:
                self.cancel_gaze_calibration()
            else:
                self.start_gaze_calibration()
            return True
        if self.calibrating and keys.matches(key, "space"):
            self.confirm_gaze_point()
            return True
        if keys.matches(key, "t"):
            self.toggle_body()
            return True
        if keys.matches(key, "n"):
            if self.motion_wizard is not None:
                self.cancel_motion_profile()
            elif not self.calibrating:
                self.start_motion_profile()
            return True
        if self.motion_wizard is not None and keys.matches(key, "space"):
            self.skip_motion_step()
            return True
        if keys.matches(key, "f"):
            self.toggle_fullscreen()
            return True
        if keys.matches(key, "m"):
            self.switch_backend()
            return True
        if keys.matches(key, "c"):
            self.toggle_settings()
            return True
        if keys.matches(key, "v"):
            self.cycle_modes()
            return True
        if keys.matches(key, "k"):
            self.calibrate_side()
            return True
        if keys.matches(key, "i") or keys.matches(key, "tab"):
            self.state.show_help = not self.state.show_help
            return True
        if keys.matches(key, "space"):
            log.info("Статистика: кадров=%d, рука=%d, лицо=%d, кликов=%d, прокруток=%d",
                     self.stats.frames, self.stats.hand_frames,
                     self.stats.face_frames, self.stats.clicks, self.stats.scrolls)
            return True
        return False

    def _pick_primary(self, hands: List) -> Optional[int]:
        """Какая рука «главная»: та же, что и в прошлом кадре.

        Без этого при двух руках в кадре они перехватывали управление друг у
        друга (курсор прыгал, жесты путались). Главная рука выбирается по
        близости запястья к предыдущему положению, а вторая только рисуется.
        """
        if not hands:
            self._primary_wrist = None
            return None
        index = 0
        if self._primary_wrist is not None:
            dists = [
                float(np.linalg.norm(h.points[WRIST, :2] - self._primary_wrist))
                for h in hands
            ]
            best = int(np.argmin(dists))
            if dists[best] < 0.35:  # рука всё ещё там же
                index = best
        else:
            # впервые: главной считаем самую крупную (ближайшую к камере) руку
            index = int(np.argmax([float(h.palm_size) for h in hands]))
        self._primary_wrist = np.array(hands[index].points[WRIST, :2], dtype=np.float64)
        return index

    # ------------------------------------------------------------------ #
    def _window_closed(self) -> bool:
        """Нажали крестик? OpenCV не сообщает об этом сам — спрашиваем свойство."""
        try:
            return cv2.getWindowProperty(self._window_name, cv2.WND_PROP_VISIBLE) < 1
        except cv2.error:
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    #  Тело целиком: включение на ходу (клавиша T)
    # ------------------------------------------------------------------ #
    def set_body(self, on: bool, note: bool = True) -> str:
        """Включить/выключить распознавание тела и, если нужно, пересоздать движок.

        Модель позы — отдельная модель MediaPipe, поэтому её нельзя «включить
        на ходу» в уже созданном движке: его приходится создать заново (доли
        секунды, камера не останавливается).
        """
        on = bool(on)
        was = bool(getattr(self.cfg.body, "enabled", False))
        self.cfg.body.enabled = on
        if not on:
            self._body_points = None
            self.body_fsm = BodyFSM(self.cfg.body)
            text = "тело: выключено"
            if note:
                self._events_log.appendleft(text)
            return text

        if getattr(self.tracker, "want_body", False):
            text = "тело: уже включено"
            if note:
                self._events_log.appendleft(text)
            return text

        backend = getattr(self.tracker, "name", self.cfg.tracker)
        target = "mediapipe" if backend in ("mediapipe", "auto") else backend
        try:
            new = create_tracker(
                target,
                self.cfg.hand,
                self.cfg.face,
                resolve_path(self.cfg.model_dir),
                progress=log.info,
                want_body=True,
            )
        except Exception as exc:
            self.cfg.body.enabled = was
            text = f"тело не включилось: {type(exc).__name__}: {exc}"
            log.error("%s", text)
            self.state.backend_note = text[:64]
            if note:
                self._events_log.appendleft(text)
            return text

        if not getattr(new, "want_body", False):
            try:
                new.close()
            except Exception:
                pass
            self.cfg.body.enabled = was
            text = "тело: нужен MediaPipe (классическое CV позу не видит)"
            if note:
                self._events_log.appendleft(text)
            return text

        self._install_tracker(new)
        self.body_fsm = BodyFSM(self.cfg.body)
        text = "тело: включено — встаньте целиком в кадр"
        if note:
            self._events_log.appendleft(text)
        log.info("Режим тела включён (клавиша T)")
        return text

    def toggle_body(self) -> str:
        return self.set_body(not bool(getattr(self.cfg.body, "enabled", False)))

    def _reconcile_body(self) -> None:
        """Следить, не переключили ли тело ползунком в окне настроек."""
        want = bool(getattr(self.cfg.body, "enabled", False))
        if self._body_want is None or want == self._body_want:
            self._body_want = want
            return
        self._body_want = want
        self.set_body(want, note=True)

    def _install_tracker(self, new: Any) -> None:
        """Поставить новый движок и сбросить автоматы (общая часть с M)."""
        old, self.tracker = self.tracker, new
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self.hand_fsm = HandFSM(self.cfg.hand, self._two_hand_relax())
        self.head_pose.reset()
        self.two_hand_fsm = TwoHandFSM(self.cfg.hand, self._two_hand_relax())
        self.face_fsm = FaceFSM(self.cfg.face)
        self.body_fsm = BodyFSM(self.cfg.body)
        self._metrics = None
        self._face_counter = 0
        self._body_points = None
        self._armed_at = time.monotonic() + max(self.cfg.warmup_s, 0.0) * 0.5
        self._body_want = bool(getattr(self.cfg.body, "enabled", False))

    def switch_backend(self) -> str:
        """Переключить движок на лету (клавиша M) и вернуть новый."""
        current = getattr(self.tracker, "name", "none")
        target = "classical" if current == "mediapipe" else "mediapipe"
        # тело — отдельная модель позы: раньше при переключении движка про неё
        # забывали, и вместе с движком молча выключался скелет
        want_body = bool(getattr(self.cfg.body, "enabled", False))
        try:
            new = create_tracker(
                target,
                self.cfg.hand,
                self.cfg.face,
                resolve_path(self.cfg.model_dir),
                progress=log.info,
                want_body=want_body,
            )
        except Exception as exc:
            note = f"не удалось включить {target}: {type(exc).__name__}: {exc}"
            log.error("%s", note)
            self.state.backend_note = note[:64]
            return current

        old, self.tracker = self.tracker, new
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        # сбрасываем автоматы: старые жесты не должны «дожиматься» на новом движке
        self.hand_fsm = HandFSM(self.cfg.hand, self._two_hand_relax())
        self.head_pose.reset()
        self.two_hand_fsm = TwoHandFSM(self.cfg.hand, self._two_hand_relax())
        self.face_fsm = FaceFSM(self.cfg.face)
        self.body_fsm = BodyFSM(self.cfg.body)
        self._metrics = None
        self._face_counter = 0
        self._armed_at = time.monotonic() + max(self.cfg.warmup_s, 0.0) * 0.5
        name = getattr(self.tracker, "name", "?")
        log.info("Движок переключён: %s", BACKEND_TITLES.get(name, name))
        self._body_want = want_body
        self._body_points = None
        note = ""
        if want_body and not getattr(self.tracker, "want_body", False):
            note = " · тело недоступно на этом движке"
        self._events_log.append(
            f"{time.strftime('%H:%M:%S')}  движок → {BACKEND_TITLES.get(name, name)}{note}"
        )
        return name

    def shutdown(self) -> None:
        self.running = False
        # Сначала настройки, потом всё остальное: даже если камера не закроется
        # красиво, человек не потеряет калибровку и включённые режимы.
        try:
            self.save_settings("выход")
        except Exception as exc:
            log.debug("Настройки при выходе не сохранены: %s", exc)
        self.router.release_all()
        if self.camera is not None:
            self.camera.stop()
        if self.tracker is not None:
            self.tracker.close()
        if self.show_window:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass
        log.info("Остановлено. Кадров: %d, кликов: %d", self.stats.frames, self.stats.clicks)
