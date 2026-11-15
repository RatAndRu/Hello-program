"""Главный цикл приложения: камера -> распознавание -> действия -> оверлей."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import __version__
from .actions import ActionRouter, DryRunBackend, PyAutoGuiBackend
from .camera import ThreadedCamera
from .config import AppConfig, resolve_path
from .face import FaceFSM, FaceMetrics, measure_face
from .gestures import (
    Event,
    HandFSM,
    POSE_TITLES_RU,
    TwoHandFSM,
    analyze_hand,
    classify_pose,
)
from .lipreading import LipReader, TemplateStore, mouth_features
from .overlay import OverlayState, render
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
        self.two_hand_fsm = TwoHandFSM(cfg.hand)
        self.face_fsm = FaceFSM(cfg.face)
        self.camera: Optional[ThreadedCamera] = None
        self.tracker = None
        self.lip_reader: Optional[LipReader] = None
        self.stats = Stats()
        self.state = OverlayState(
            active_box=cfg.pointer.active_box,
            paused=self.router.paused,
            head_pointer=self.router.head_pointer,
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
        self.click_fsm = HandFSM(cfg.hand)
        self.settings: Optional[SettingsPanel] = None
        self._mouse_bound = False
        self._frame_size: Tuple[int, int] = (960, 540)
        self._paused_for_settings = False
        self._window_name = "AirMouse"

    # ------------------------------------------------------------------ #
    def setup(self) -> None:
        log.info("Запуск: backend=%s, окно=%s, dry-run=%s",
                 self.cfg.tracker, self.show_window, self.dry_run)
        self.camera = ThreadedCamera(self.cfg.camera).start()
        w, h = self.camera.camera.resolution
        log.info("Камера: %s, %dx%d", self.camera.camera.source_name, w, h)
        self.tracker = create_tracker(
            self.cfg.tracker,
            self.cfg.hand,
            self.cfg.face,
            resolve_path(self.cfg.model_dir),
            progress=log.info,
        )
        log.info("Распознавание: %s", getattr(self.tracker, "name", "?"))
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
        if face is None or not self.cfg.face.enabled:
            self._metrics = None
            return []
        self._face_counter += 1
        if self._face_counter % max(self.cfg.face.every_n_frames, 1) != 0 and self._metrics is not None:
            return []
        self._metrics = measure_face(face)
        if not self.face_fsm.baseline.ready:
            # первые ~1.5 секунды — калибровка нейтрального выражения
            for _ in range(4):
                self.face_fsm.baseline.update(self._metrics, alpha=0.4)
            return []
        return self.face_fsm.update(self._metrics, now)

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
    def process_frame(self, frame: np.ndarray, now: float, ts_ms: int) -> List[Event]:
        events: List[Event] = []
        # пока открыта панель настроек, мышь держим на паузе принудительно:
        # случайный жест не должен «разбудить» курсор под рукой пользователя
        if self.settings_open():
            self.router.paused = True
        warmup = now < self._armed_at

        if hasattr(self.tracker, "process_events"):
            events, shape = self.tracker.process_events(frame, ts_ms, now)
            self._shape = shape
            res = FrameResult(backend=self.tracker.name)
            self._hands, self._face = [], None
            events = self._translate(events, now)
        else:
            res = self.tracker.process(frame, ts_ms)
            hands = list(res.hands)
            if self.cfg.hand.second_hand == "ignore" and len(hands) > 1:
                hands = hands[:1]
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
            # жесты двумя руками (масштаб/прокрутка) — только когда видно обе руки
            # и вторая рука не занята нажатиями
            if len(hands) >= 2 and getattr(self.cfg.hand, "roles", "single") != "split":
                events += self.two_hand_fsm.update(hands, now)
            if self.router.head_pointer and self._metrics is not None:
                events.extend(self._head_pointer_events(now))

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

    def _on_mouse(self, event: int, x: int, y: int) -> None:
        if not self.settings_open():
            return
        size = self._frame_size
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
            self.settings = SettingsPanel(self.cfg, runtime=self.router)
        if not self.settings.open():
            return False
        self._bind_mouse()
        self._paused_for_settings = self.router.paused
        self.router.paused = True
        self._events_log.append(
            f"{time.strftime('%H:%M:%S')}  настройки: управление мышью на паузе"
        )
        return True

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

    def _expression_text(self) -> str:
        """Текущее выражение лица словами — чтобы мимика была понятна без графиков."""
        m = self._metrics
        if m is None or not m.valid:
            return ""
        fsm = self.face_fsm
        ear = min(m.ear_left, m.ear_right)
        if ear < self.cfg.face.ear_blink:
            return "глаза закрыты"
        if fsm.smile_score > self.cfg.face.smile_delta:
            level = min(1.0, fsm.smile_score / max(self.cfg.face.smile_delta * 2.5, 1e-6))
            return f"улыбка {level:.0%}"
        if getattr(fsm, "sad_score", 0.0) > self.cfg.face.sad_delta:
            return "грусть"
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
        s.paused = self.router.paused
        s.head_pointer = self.router.head_pointer
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

                if self.show_window or self.output is not None:
                    canvas = render(
                        frame, self.state, self._hands, self._face,
                        shape=self._shape, metrics=self._metrics,
                        primary=self._primary_index,
                    )
                else:
                    canvas = None

                if canvas is not None:
                    self._frame_size = (canvas.shape[1], canvas.shape[0])
                if canvas is not None and self.settings_open():
                    canvas = self.settings.draw(canvas, live=self._settings_live())

                if self.output is not None:
                    cv2.imwrite(str(self.output), canvas)

                if self.show_window and canvas is not None:
                    try:
                        cv2.imshow(self._window_name, canvas)
                        key = cv2.waitKey(1) & 0xFF
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
                    if handled:
                        pass
                    elif key in (27, ord("q"), ord("й")):
                        self.running = False
                    elif key in (ord("p"), ord("з")):
                        self.router.paused = not self.router.paused
                    elif key in (ord("h"), ord("р")):
                        self.router.head_pointer = not self.router.head_pointer
                        self.cfg.head_pointer = self.router.head_pointer
                    elif key in (ord("m"), ord("M"), ord("ь")):
                        self.switch_backend()
                    elif key in (ord("c"), ord("C"), ord("с"), ord("С")):
                        self.toggle_settings()
                    elif key in (ord("v"), ord("V"), ord("в"), ord("В")):
                        self.cycle_modes()
                    elif key in (ord("i"), ord("I"), ord("ш"), ord("?")):
                        self.state.show_help = not self.state.show_help
                    elif key == 9:  # Tab — тот же переключатель, что и «I»
                        self.state.show_help = not self.state.show_help
                    elif key == ord(" "):
                        log.info("Статистика: кадров=%d, рука=%d, лицо=%d, кликов=%d, прокруток=%d",
                                 self.stats.frames, self.stats.hand_frames,
                                 self.stats.face_frames, self.stats.clicks, self.stats.scrolls)
        except KeyboardInterrupt:
            log.info("Прервано пользователем")
        finally:
            self.shutdown()
        return exit_code

    # ------------------------------------------------------------------ #
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

    def switch_backend(self) -> str:
        """Переключить движок на лету (клавиша M) и вернуть новый."""
        current = getattr(self.tracker, "name", "none")
        target = "classical" if current == "mediapipe" else "mediapipe"
        try:
            new = create_tracker(
                target,
                self.cfg.hand,
                self.cfg.face,
                resolve_path(self.cfg.model_dir),
                progress=log.info,
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
        self.hand_fsm = HandFSM(self.cfg.hand)
        self.two_hand_fsm = TwoHandFSM(self.cfg.hand)
        self.face_fsm = FaceFSM(self.cfg.face)
        self._metrics = None
        self._face_counter = 0
        self._armed_at = time.monotonic() + max(self.cfg.warmup_s, 0.0) * 0.5
        name = getattr(self.tracker, "name", "?")
        log.info("Движок переключён: %s", BACKEND_TITLES.get(name, name))
        self._events_log.append(
            f"{time.strftime('%H:%M:%S')}  движок → {BACKEND_TITLES.get(name, name)}"
        )
        return name

    def shutdown(self) -> None:
        self.running = False
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
