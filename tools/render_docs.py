"""Рисует картинки для README: docs/overlay-*.png.

Запуск:  python tools/render_docs.py
Скрины делаются из настоящего оверлея (``airmouse.overlay.render``) на
синтетической кисти и лице — без камеры, поэтому результат детерминирован.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from airmouse import overlay  # noqa: E402
from airmouse.config import AppConfig  # noqa: E402
from airmouse.gestures import synthetic_hand  # noqa: E402
from airmouse.synthetic import synthetic_face  # noqa: E402

W, H = 960, 540
OUT = ROOT / "docs"


def background() -> np.ndarray:
    """Тёмный градиент вместо кадра камеры — так подписи читаются лучше."""
    img = np.zeros((H, W, 3), dtype=np.uint8)
    for y in range(H):
        v = int(52 + 26 * (y / H))
        img[y, :] = (v, v, v + 2)
    cv2.ellipse(img, (W // 2, H // 2 + 40), (W // 2, H // 2), 0, 0, 360, (66, 66, 68), -1)
    return img


def state(**kw) -> overlay.OverlayState:
    base = dict(
        fps=29.6,
        backend="ИИ MediaPipe (нейросеть)",
        actions_on=True,
        hand_seen=True,
        face_seen=True,
        active_box=AppConfig().pointer.active_box,
        version="0.6.0",
        events=["12:31:02  щипок → левый клик", "12:31:05  жест: ОК → двойной клик"],
        last_event="щипок → левый клик",
    )
    base.update(kw)
    return overlay.OverlayState(**base)


def save(img: np.ndarray, name: str) -> None:
    OUT.mkdir(exist_ok=True)
    path = OUT / name
    cv2.imwrite(str(path), img)
    print(f"  {path.relative_to(ROOT)}  {img.shape[1]}x{img.shape[0]}")


def main() -> int:
    print("рендерю картинки для README:")
    face = synthetic_face(center=(0.30, 0.30), scale=0.6, smile=0.5, mouth_open=0.12)
    palm = synthetic_hand(center=(0.66, 0.66), scale=0.26)

    # 1. Общий вид: рука + лицо + сводка
    st = state(pose="ладонь", expression="улыбка 62%", ear=0.29, smile=0.62, hand_count=1)
    save(overlay.render(background(), st, hands=[palm], face=face), "overlay-main.png")

    # 2. Крупный план кисти: 21 точка, подписи пальцев
    point_hand = synthetic_hand(center=(0.46, 0.66), scale=0.30,
                               curl={"middle": 1.0, "ring": 1.0, "pinky": 1.0})
    st = state(pose="указательный", expression="нейтрально", hand_count=1)
    save(overlay.render(background(), st, hands=[point_hand], face=None), "overlay-hand.png")

    # 3. «Прицел»: пальцы сходятся, курсор заморожен на крестике
    pinching = synthetic_hand(center=(0.52, 0.60), scale=0.28, pinch_index=True,
                              curl={"middle": 1.0, "ring": 1.0, "pinky": 1.0})
    st = state(pose="щипок", expression="нейтрально", aiming=True,
               aim=(0.60, 0.42), hand_count=1)
    save(overlay.render(background(), st, hands=[pinching], face=None), "overlay-aim.png")

    # 4. Две руки: масштаб / прокрутка + роли рук
    left = synthetic_hand(center=(0.34, 0.74), scale=0.21)
    right = synthetic_hand(center=(0.70, 0.72), scale=0.19)
    st = state(pose="ладонь", expression="нейтрально", hand_count=2,
               two_hand_hint="две ладони: разведите руки → масштаб",
               split_roles=True, roles_text="роли: 1 — курсор, 2 — клики")
    save(overlay.render(background(), st, hands=[left, right], face=None, primary=0),
         "overlay-two-hands.png")

    # 5. Настройки с ползунками (клавиша C)
    from airmouse.settings_ui import SettingsPanel

    panel = SettingsPanel(AppConfig())
    panel.open()
    panel.goto_page(0)
    rows = panel.layout()
    panel._apply(rows[4], rows[4].track[0] + int(rows[4].track[2] * 0.42))
    shot = panel.draw(np.zeros((H, W, 3), dtype=np.uint8),
                      live="сейчас: щипок 0.42   жест: указательный   29 кадр/с")
    save(shot, "overlay-settings.png")

    # 6. Справка по жестам
    st = state(pose="ладонь", expression="улыбка 62%", show_help=True, hand_count=1)
    save(overlay.render(background(), st, hands=[palm], face=face), "overlay-help.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
