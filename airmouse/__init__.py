"""AirMouse — управление компьютером жестами рук, мимикой и «чтением по губам».

Пакет сознательно разделён на слои:

* ``filters`` / ``landmarks`` / ``gestures`` / ``face`` / ``lipreading`` —
  чистая логика распознавания (только numpy, без камеры и без ОС);
* ``tracker`` / ``camera`` — источники данных (MediaPipe, классическое CV);
* ``pointer`` / ``actions`` — преобразование событий в движения мыши и нажатия;
* ``app`` / ``cli`` / ``overlay`` / ``tray`` — рабочее приложение.

Логика распознавания не зависит ни от MediaPipe, ни от операционной системы,
поэтому её можно тестировать на синтетических данных без веб-камеры.
"""

import sys
import types

__version__ = "0.18.0"
APP_NAME = "AirMouse"


def _stub_matplotlib_if_absent() -> None:
    """MediaPipe импортирует ``matplotlib.pyplot`` ради своих функций рисования.

    Нам они не нужны (оверлей рисуем сами через OpenCV), а matplotlib — это
    примерно 25 МБ в сборке EXE. Если настоящего matplotlib нет, подставляем
    максимально скромную заглушку: она нужна только для того, чтобы импорт
    ``mediapipe.tasks.python.vision`` прошёл. К её функциям мы не обращаемся.
    """
    if "matplotlib" in sys.modules:
        return
    try:  # настоящий matplotlib — используем его
        import matplotlib  # noqa: F401
    except Exception:
        pass
    else:
        return
    matplotlib = types.ModuleType("matplotlib")
    pyplot = types.ModuleType("matplotlib.pyplot")

    def _unsupported(*_args, **_kwargs):
        raise RuntimeError("matplotlib не включён в сборку AirMouse (заглушка)")

    pyplot.__getattr__ = _unsupported  # type: ignore[attr-defined]
    matplotlib.pyplot = pyplot
    sys.modules["matplotlib"] = matplotlib
    sys.modules["matplotlib.pyplot"] = pyplot


_stub_matplotlib_if_absent()
