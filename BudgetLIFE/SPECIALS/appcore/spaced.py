"""Интервальные повторения по алгоритму SM-2 — фишка LanguageYOI.

В LanguageYOI на этом держится вся учёба: слово показывается через
увеличивающиеся промежутки (сегодня → завтра → через 3 дня → через неделю…), а
коэффициент ``ease`` отражает, насколько легко оно даётся. Алгоритм не зависит от
предмета — годится для слов, иероглифов, карточек, техобслуживания, повторения
команд и любых «надо не забыть».

Классические оценки (0–5) и понятные русские кнопки:

===========  ======  ==================================================
Кнопка       Оценка  Что значит
===========  ======  ==================================================
«Забыл»        1     показать снова сегодня/завтра, ease падает
«Трудно»       3     вспомнил с трудом, прогресс чуть назад
«Хорошо»       4     вспомнил — обычный шаг вперёд
«Легко»        5     слишком просто, ease растёт, интервал больше
===========  ======  ==================================================

``review()`` возвращает новое состояние карточки: ``repetitions``, ``ease``,
``interval_days`` и ``due`` (дата следующего показа). Состояние — обычный словарь,
поэтому его удобно держать и в JSON, и в SQLite.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

__all__ = ["GRADES", "GRADE_BUTTONS", "new_card", "review", "is_due", "due_in_days",
           "grade_from_button", "schedule"]

# Понятные названия оценок (интерфейс и голосовые команды).
GRADES = {0: "Не помню", 1: "Забыл", 2: "Почти", 3: "Трудно", 4: "Хорошо", 5: "Легко"}
GRADE_BUTTONS = {"забыл": 1, "забыла": 1, "не помню": 1, "трудно": 3,
                 "почти": 2, "хорошо": 4, "нормально": 4, "легко": 5, "просто": 5}

MIN_EASE = 1.3
DEFAULT_EASE = 2.5
FIRST_INTERVAL = 1
SECOND_INTERVAL = 6


def new_card(*, today: date | None = None, ease: float = DEFAULT_EASE) -> dict:
    """Новая карточка: показывать сразу (интервал 0 дней)."""
    today = today or date.today()
    return {"repetitions": 0, "ease": float(ease), "interval_days": 0,
            "due": today.isoformat(), "last_review": "", "lapses": 0, "reviews": 0}


def grade_from_button(word: str) -> int | None:
    """«забыл»/«трудно»/«хорошо»/«легко» → оценка SM-2 (или None)."""
    return GRADE_BUTTONS.get((word or "").strip().lower().replace("ё", "е"))


def _as_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value[:len(fmt) + 2].strip(), fmt).date()
            except ValueError:
                continue
    return date.today()


def review(card: dict, grade: int, *, today: date | None = None,
           leech_limit: int = 8) -> dict:
    """Одна попытка вспомнить → новое состояние карточки (SM-2).

    ``leech_limit`` — после стольких «Забыл» карточка помечается ``leech: True``
    (её стоит переделать или разбить — как в LanguageYOI）。
    """
    if grade not in range(6):
        raise ValueError("Оценка должна быть от 0 до 5")
    today = today or date.today()
    state = dict(card or new_card(today=today))
    state.setdefault("ease", DEFAULT_EASE)
    state.setdefault("repetitions", 0)
    state.setdefault("lapses", 0)
    state.setdefault("reviews", 0)

    if grade < 3:
        # Провал: счётчик повторений сбрасывается, интервал — снова маленький.
        state["repetitions"] = 0
        state["lapses"] = int(state["lapses"]) + 1
        state["interval_days"] = 0 if grade == 0 else FIRST_INTERVAL
    else:
        state["repetitions"] = int(state["repetitions"]) + 1
        reps = state["repetitions"]
        if reps == 1:
            state["interval_days"] = FIRST_INTERVAL
        elif reps == 2:
            state["interval_days"] = SECOND_INTERVAL
        else:
            state["interval_days"] = max(1, round(int(state["interval_days"]) * float(state["ease"])))

    # Коэффициент лёгкости по формуле SM-2 (для «Трудно» он падает, для «Легко» растёт).
    ease = float(state["ease"]) + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    state["ease"] = round(max(MIN_EASE, ease), 3)
    state["reviews"] = int(state["reviews"]) + 1
    state["last_review"] = today.isoformat()
    state["due"] = (today + timedelta(days=max(1, int(state["interval_days"])))).isoformat()
    state["leech"] = int(state["lapses"]) >= leech_limit
    return state


def is_due(card: dict, *, today: date | None = None) -> bool:
    """Пора ли показывать карточку (в том числе давно пропущенную)."""
    today = today or date.today()
    return _as_date(card.get("due")) <= today


def due_in_days(card: dict, *, today: date | None = None) -> int:
    """Через сколько дней показывать (0 — сегодня, меньше нуля — просрочено)."""
    today = today or date.today()
    return (_as_date(card.get("due")) - today).days


def schedule(card: dict, *, today: date | None = None) -> dict:
    """Что будет с карточкой при каждой оценке — для подсказок в интерфейсе.

    Пример: ``schedule(card)["хорошо"]`` → ``{"due": "2026-10-12", "interval_days": 7}``.
    """
    today = today or date.today()
    out = {}
    for grade, name in GRADES.items():
        variant = review(card, grade, today=today)
        out[name.lower()] = {"due": variant["due"], "interval_days": variant["interval_days"],
                             "ease": variant["ease"]}
    return out