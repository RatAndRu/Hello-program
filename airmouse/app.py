"""Главный цикл приложения: камера -> распознавание -> действия -> оверлей."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from . import __version__
from .actions import ActionRouter, DryRunBackend, PyAutoGuiBackend
from .camera import ThreadedCamera
from .config import AppConfig, resolve_path
from .face import FaceFSM, FaceMetrics, measure_face
from .gestures import Event, HandFSM, POSE_TITLES_RU, analyze_hand, classify_pose
from .lipreading import LipReader, TemplateStore, mouth_features
from .overlay import OverlayState, render
from .pointer import PointerMapper
from .tracker import FrameResult, create_tracker

log = logging.getLogger("airmouse")

# Как называть движки в окне и в журнале.
BACKEND_TITLES = {
    "mediapipe": "ИИ MediaPipe (нейросеть)",
    "classical": "классический CV (без ИИ)",
    "none": "без распознавания",
}

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
        self._shape = None
        self._lit = 0.0
        self._last_scroll_log = 0.0
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
        warmup = now < self._armed_at

        if hasattr(self.tracker, "process_events"):
            events, shape = self.tracker.process_events(frame, ts_ms, now)
            self._shape = shape
            res = FrameResult(backend=self.tracker.name)
            self._hands, self._face = [], None
            events = self._translate(events, now)
        else:
            res = self.tracker.process(frame, ts_ms)
            self._hands = res.hands
            self._face = res.face
            self._shape = None
            hand = res.primary_hand
            events = self._translate(self.hand_fsm.update(hand, now), now)
            events += self._handle_face(res.face, now)
            events += self._handle_lip(res.face, now)
            if self.router.head_pointer and self._metrics is not None:
                dt = max(now - self._last_now, 1e-3) if self._last_now else 0.016
                vel = self.face_fsm.head_velocity(dt)
                pt = self.pointer.delta(vel, now)
                if pt is not None:
                    events.append(Event("pointer", pt))

        self.stats.frames += 1
        self.stats.hand_frames += 1 if self._hands or self._shape is not None else 0
        self.stats.face_frames += 1 if self._face is not None else 0
        self._last_now = now

        if warmup:
            # Разминка: распознавание уже работает, но ничего не нажимаем —
            # человек успевает встать перед камерой.
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
            elif ev.kind == "scroll":
                if now - self._last_scroll_log >= 1.0:
                    log.info("прокрутка: %s тиков", ev.value)
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
        s.paused = self.router.paused
        s.head_pointer = self.router.head_pointer
        s.hand_seen = bool(self._hands) or self._shape is not None
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
                    )
                else:
                    canvas = None

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
                    if key in (27, ord("q"), ord("й")):
                        self.running = False
                    elif key in (ord("p"), ord("з")):
                        self.router.paused = not self.router.paused
                    elif key in (ord("h"), ord("р")):
                        self.router.head_pointer = not self.router.head_pointer
                    elif key in (ord("m"), ord("M"), ord("ь")):
                        self.switch_backend()
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
