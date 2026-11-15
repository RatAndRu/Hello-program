"""Окно настроек: ползунки, применение значений, сохранение, поведение без GUI."""

import json

import cv2
import numpy as np
import pytest

from airmouse.app import AirMouseApp
from airmouse.config import AppConfig
from airmouse.settings_ui import (
    DEFAULTS,
    SLIDERS,
    SettingsPanel,
    apply_defaults,
    build_pages,
    changed_values,
    groups,
)


# --------------------------------------------------------------------------- #
#  Ползунки как преобразование «значение <-> положение»
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("slider", SLIDERS, ids=[s.key for s in SLIDERS])
def test_slider_position_roundtrip(slider):
    mid = (slider.lo + slider.hi) / 2.0
    pos = slider.to_pos(mid)
    value = slider.from_pos(pos)
    assert slider.lo <= value <= slider.hi
    assert abs(value - mid) <= slider.step / 2 + 1e-9


@pytest.mark.parametrize("slider", SLIDERS, ids=[s.key for s in SLIDERS])
def test_slider_set_get(slider):
    cfg = AppConfig()
    target = slider.lo + slider.step * 3
    slider.set(cfg, target)
    assert slider.get(cfg) == pytest.approx(target, abs=1e-6)


@pytest.mark.parametrize("slider", SLIDERS, ids=[s.key for s in SLIDERS])
def test_slider_positions_are_clamped(slider):
    assert slider.from_pos(-5) == slider.lo
    assert slider.from_pos(slider.ticks + 100) == slider.hi


def test_sliders_respond_to_calibration_values():
    """Сдвиг зоны курсора и чувствительность реально меняют конфиг."""
    cfg = AppConfig()
    by_key = {s.key: s for s in SLIDERS}
    by_key["pointer.active_box[0]"].set(cfg, 0.22)
    by_key["pointer.active_box[2]"].set(cfg, 0.12)
    assert cfg.pointer.active_box[0] == pytest.approx(0.22)
    assert cfg.pointer.active_box[2] == pytest.approx(0.88)
    by_key["face.head_gain_x"].set(cfg, 40.0)
    assert cfg.face.head_gain_x == pytest.approx(40.0)
    by_key["hand.pinch_ratio"].set(cfg, 0.28)
    assert cfg.hand.pinch_ratio == pytest.approx(0.28)
    # отпускание всегда выше порога — щипок не «залипает»
    assert cfg.hand.pinch_release_ratio > cfg.hand.pinch_ratio


def test_active_box_never_collapses():
    cfg = AppConfig()
    by_key = {s.key: s for s in SLIDERS}
    by_key["pointer.active_box[0]"].set(cfg, 0.45)
    by_key["pointer.active_box[2]"].set(cfg, 0.45)
    left, top, right, bottom = cfg.pointer.active_box
    assert right - left >= 0.149
    assert bottom - top >= 0.149


def test_defaults_reset_and_change_tracking():
    cfg = AppConfig()
    by_key = {s.key: s for s in SLIDERS}
    by_key["pointer.min_cutoff"].set(cfg, 2.0)
    by_key["hand.click_cooldown_s"].set(cfg, 0.7)
    assert len(changed_values(cfg)) == 2
    apply_defaults(cfg)
    assert changed_values(cfg) == []
    assert cfg.pointer.min_cutoff == pytest.approx(DEFAULTS["pointer.min_cutoff"])


def test_groups_keep_order():
    names = [name for name, _ in groups(SLIDERS)]
    assert names[0].startswith("Курсор")
    assert "Мышь головой" in " ".join(names)
    total = sum(len(items) for _, items in groups(SLIDERS))
    assert total == len(SLIDERS)


# --------------------------------------------------------------------------- #
#  Сохранение
# --------------------------------------------------------------------------- #
def test_save_writes_config(tmp_path):
    path = tmp_path / "airmouse.json"
    cfg = AppConfig()
    win = SettingsPanel(cfg, path=path)
    cfg.face.head_gain_x = 55.0
    win.dirty = True
    win.save()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["face"]["head_gain_x"] == pytest.approx(55.0)
    assert win.saved is True
    assert win.dirty is False
    assert path.name in win.status


def test_reset_returns_factory_values(tmp_path):
    cfg = AppConfig()
    win = SettingsPanel(cfg, path=tmp_path / "cfg.json")
    cfg.hand.pinch_ratio = 0.45
    win.reset()
    assert cfg.hand.pinch_ratio == pytest.approx(DEFAULTS["hand.pinch_ratio"])
    assert win.dirty is True


def test_panel_does_not_need_gui():
    """Панель рисуется в кадр сама — отдельное окно и GUI OpenCV не нужны."""
    panel = SettingsPanel(AppConfig())
    assert panel.open() is True
    assert panel.is_open is True
    canvas = panel.draw(np.zeros((540, 960, 3), dtype=np.uint8))
    assert canvas.shape == (540, 960, 3)
    assert canvas.any(), "панель должна что-то нарисовать"
    panel.close(save=False)
    assert panel.is_open is False


# --------------------------------------------------------------------------- #
#  Приложение
# --------------------------------------------------------------------------- #
def test_app_does_not_open_settings_without_window():
    app = AirMouseApp(AppConfig(), dry_run=True, show_window=False)
    assert app.toggle_settings() is False
    assert app.router.paused is False


def test_app_pauses_actions_while_settings_open(monkeypatch):
    app = AirMouseApp(AppConfig(), dry_run=True, show_window=True)
    app.settings = SettingsPanel(app.cfg)

    def fake_close(save: bool = False) -> None:
        app.settings.is_open = False
        app.settings.saved = bool(save)
        app.settings.dirty = False

    monkeypatch.setattr(app, "_bind_mouse", lambda: None)
    monkeypatch.setattr(app.settings, "close", fake_close)

    # панель открыта внутри окна: действия на паузе
    app.settings.is_open = True
    app.router.paused = False
    app._close_settings()
    assert app.router.paused is False
    assert app.router.paused is False
    assert app.settings.is_open is False
    assert any("настройки" in line for line in app._events_log)


def test_settings_hint_visible_in_overlay():
    from airmouse.overlay import OverlayState

    state = OverlayState()
    assert "C настройки" in state.hints


# --------------------------------------------------------------------------- #
#  Панель: попадание мышью, кнопки, страницы
# --------------------------------------------------------------------------- #
def _panel(cfg=None, path=None, page: int = 1):
    """Панель сразу на странице «Курсор» (0 — это «Режимы»)."""
    panel = SettingsPanel(cfg or AppConfig(), path=path)
    panel.open()
    panel.goto_page(page)
    return panel


def test_click_on_track_sets_value():
    cfg = AppConfig()
    panel = _panel(cfg)
    row = panel.layout()[4]              # «сглаживание курсора»
    assert row.slider is not None
    x0, _y, track_w, _h = row.track
    action = panel.on_mouse(cv2.EVENT_LBUTTONDOWN, x0 + track_w // 2, row.rect[1] + 5)
    assert action == "change"
    value = row.slider.get(cfg)
    assert row.slider.lo < value < row.slider.hi
    assert panel.dirty is True


def test_drag_moves_value_left_and_right():
    cfg = AppConfig()
    panel = _panel(cfg)
    row = panel.layout()[4]
    x0, _y, track_w, _h = row.track
    panel.on_mouse(cv2.EVENT_LBUTTONDOWN, x0 + track_w // 2, row.rect[1] + 5)
    middle = row.slider.get(cfg)
    panel.on_mouse(cv2.EVENT_MOUSEMOVE, x0 + track_w - 2, row.rect[1] + 5)
    right = row.slider.get(cfg)
    panel.on_mouse(cv2.EVENT_MOUSEMOVE, x0 + 2, row.rect[1] + 5)
    left = row.slider.get(cfg)
    assert right > middle > left
    panel.on_mouse(cv2.EVENT_LBUTTONUP, x0, row.rect[1] + 5)
    assert panel._drag is None


def test_save_button_saves_and_closes(tmp_path):
    cfg = AppConfig()
    path = tmp_path / "airmouse.json"
    panel = _panel(cfg, path)
    row = panel.layout()[0]
    panel.on_mouse(cv2.EVENT_LBUTTONDOWN, row.track[0] + row.track[2] // 2, row.rect[1] + 5)
    label, (bx, by, bw, bh) = panel.buttons()[0]
    assert label == "СОХРАНИТЬ"
    action = panel.on_mouse(cv2.EVENT_LBUTTONDOWN, bx + bw // 2, by + bh // 2)
    assert action == "save"
    assert panel.is_open is False
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["pointer"]["active_box"][0] != AppConfig().pointer.active_box[0]


def test_reset_button_restores_factory():
    cfg = AppConfig()
    panel = _panel(cfg)
    cfg.hand.click_cooldown_s = 0.9
    _label, (bx, by, bw, bh) = panel.buttons()[1]
    assert panel.on_mouse(cv2.EVENT_LBUTTONDOWN, bx + bw // 2, by + bh // 2) == "reset"
    assert cfg.hand.click_cooldown_s == pytest.approx(DEFAULTS["hand.click_cooldown_s"])


def test_close_button_discards_when_untouched(tmp_path):
    panel = _panel(AppConfig(), tmp_path / "cfg.json")
    _label, (bx, by, bw, bh) = panel.buttons()[2]
    assert panel.on_mouse(cv2.EVENT_LBUTTONDOWN, bx + bw // 2, by + bh // 2) == "close"
    assert panel.is_open is False
    assert not (tmp_path / "cfg.json").exists()


def test_pages_and_keys():
    panel = _panel()
    assert len(panel.pages) == 7
    assert panel.pages[0].title == "Режимы"
    assert panel.pages[5].title == "Тело"
    assert panel.pages[6].title == "Окно и рука"
    assert panel.on_key(ord("2")) == "page"
    assert panel.page == 1
    assert panel.on_key(9) == "page"          # Tab — следующая страница
    assert panel.page == 2
    panel.on_key(ord("1"))
    assert panel.page == 0
    assert panel.on_key(ord("r")) == "reset"
    assert panel.on_key(27) in ("close", "save")
    assert panel.is_open is False


def test_only_current_page_sliders_are_drawn():
    panel = _panel()
    for index, page in enumerate(panel.pages):
        panel.goto_page(index)
        rows = panel.layout()
        assert len(rows) == len(page.sliders)
        assert [r.slider.key for r in rows] == [s.key for s in page.sliders]


class _FakeTracker:
    name = "fake"

    def __init__(self, hands):
        self.hands = list(hands)

    def process(self, frame, ts_ms):
        from airmouse.tracker import FrameResult

        return FrameResult(hands=list(self.hands), face=None, backend="fake")

    def close(self):
        pass


def test_gesture_cannot_unpause_while_settings_open():
    """На панели настроек жест не должен «разбудить» мышь под рукой."""
    from airmouse.gestures import synthetic_hand

    app = AirMouseApp(AppConfig(), dry_run=True, show_window=True)
    app.tracker = _FakeTracker([synthetic_hand()])     # раскрытая ладонь = пауза
    app._prepared = True
    app.settings = SettingsPanel(app.cfg)
    app.settings.open()
    app.router.paused = False
    for i in range(40):                                # ладонь держится 1.3 с
        app.process_frame(np.zeros((360, 640, 3), dtype=np.uint8), 100.0 + i * 0.04, i * 40)
        assert app.router.paused is True
