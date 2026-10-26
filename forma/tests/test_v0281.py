"""0.28.1: стрелки шага у параметров инструментов.

Стрелки нужны не только числам: у текстовых параметров (вид линзы, сторона
инь-яна, сечения клинка, стиля аниме, узора решётки…) они листают готовые
варианты. Поэтому проверяем две вещи:

* каждое значение, которое стрелка может подставить, действительно строится
  (иначе «удобная кнопка» выдавала бы ошибку сценария);
* у параметров с вариантами в карточках эти варианты описаны (`choices`),
  иначе стрелки там просто не появятся.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from forma.run import build

APP_JS = Path(__file__).resolve().parents[1] / "web" / "js" / "app.js"

# (что проверяем, шаблон сценария, значения — ровно те, что листает стрелка)
CASES = [
    ("корона", "к = crown shape={}", ["треугольные", "скруглённые", "волна"]),
    ("кубическое отверстие", "д = cube_hole size=[40,40,40] hole=12 axis={}", ["z", "x", "y"]),
    ("саморез", "в = screw d=6 length=30 head={}",
     ["потай", "полукруг", "шестигранник", "нет"]),
    ("яйцо", "я = egg sharp={}", ["верх", "низ"]),
    ("инь-ян", "и = yin_yang side={}", ["левый", "правый"]),
    ("линза", "л = lens diameter=50 sag=6 mode={}",
     ["выпуклая", "вогнутая", "плосковыпуклая", "плосковогнутая", "мениск"]),
    ("складки", "к = box size=[60,60,60]\nwrinkle к amp=2 mode={}",
     ["радиус", "высота", "шум", "клетка", "трещины"]),
    ("рельеф", "к = box size=[100,80,10]\nrelief к image=docs/pattern.png depth=2 mode={}",
     ["обёртка", "плоскость"]),
    ("поры", "ш = sphere radius=30\nporous ш size=4 count=20 mode={}",
     ["поры", "ячеи", "пузыри", "глазки"]),
    ("решётка", "ш = sphere radius=40\nlattice ш cell=18 wire=4 mode={}",
     ["прямоуг", "ромб", "соты"]),
    ("клинок", "к = blade kind={}",
     ["катана", "танто", "ятоган", "стилет", "двуручник", "серп", "нож"]),
    ("клинок: силуэт", "к = blade profile={}", ["прямой", "суженный", "листовой"]),
    ("клинок: сечение", "к = blade section={}", ["линза", "клин", "плоский", "алмаз"]),
    ("клинок: остриё", "к = blade tip={}", ["острое", "киссаки", "закруглённое", "тупое"]),
    ("ручка: перекладина", "р = handle bar_shape={}", ["цилиндр", "капсула", "брусок"]),
    ("ручка: стойки", "р = handle post_shape={}", ["цилиндр", "капсула", "брусок"]),
    ("ступени: внутренний угол", "с = stairs inner={}", ["прямой", "скруглённый"]),
    ("причёска", "п = hair style={}", ["аниме", "хвост", "короткий", "мех"]),
    ("экран", "ч = display style={}", ["смартфон", "будильник", "монитор"]),
    ("зеркало", "з = mirror_plate shape={}", ["прямоуг", "круг", "овал"]),
    ("узор", "к = box size=[60,60,20]\npattern к color=#d94f3d size=10 step=20 shape={}",
     ["круги", "кольца", "полосы", "клетка", "треугольники", "ромбы", "волны"]),
    ("аниме", "anime mode={}", ["аниме", "манга", "комикс", "скетч", "линия", "выкл"]),
    ("фаска (приём)", "к = box size=[60,40,20]\nк = bevel [к] radius=3 mode={}",
     ["авто", "скругление", "фаска"]),
    ("полость (приём)", "к = box size=[120,80,50]\nк = shell [к] thickness=3 open={}",
     ["top", "bottom", "both"]),
    ("наполнение (приём)",
     "т = lathe points=[[0,0],[60,0],[60,30],[0,30]] thickness=3 open=top\n"
     "fill т level=0.7 grain={}",
     ["шар", "горох", "зерно", "капля", "куб", "галька"]),
]

# Параметры, у которых в карточке обязаны быть варианты для стрелок.
REQUIRED_CHOICES = [
    ("axis", "z"), ("head", "потай"), ("sharp", "верх"), ("side", "левый"),
    ("mode", "выпуклая"), ("bar_shape", "капсула"), ("post_shape", "брусок"),
    ("inner", "скруглённый"), ("profile", "листовой"), ("section", "алмаз"),
    ("tip", "киссаки"), ("mode", "радиус"),
    ("mode", "плоскость"), ("mode", "поры"), ("mode", "ромб"),
    ("kind", "катана"), ("style", "аниме"), ("style", "будильник"),
    ("shape", "прямоуг"), ("shape", "круги"), ("mode", "аниме"),
    ("shape", "треугольные"),
]


class StepperChoices(unittest.TestCase):
    def test_every_offered_value_builds(self):
        for label, template, values in CASES:
            for value in values:
                result = build(template.format(value), analyze_model=False)
                message = (result.error or {}).get("message", "")
                self.assertTrue(result.ok, f"{label}: «{value}» — {message}")

    def test_choices_are_declared_in_cards(self):
        text = APP_JS.read_text(encoding="utf-8")
        # стрелки листают только объявленные варианты: ищем строку параметра
        # с нужным ключом и проверяем, что в ней есть ожидаемое значение
        lines = [ln for ln in text.splitlines() if "choices: [" in ln]
        for key, sample in REQUIRED_CHOICES:
            hit = [ln for ln in lines if f"k: '{key}'" in ln and f"'{sample}'" in ln]
            self.assertTrue(hit, f"у параметра «{key}» нет варианта «{sample}»")
        self.assertGreaterEqual(text.count("choices: ["), 25)

    def test_stepper_code_is_present(self):
        text = APP_JS.read_text(encoding="utf-8")
        for marker in ("function stepToolValue(", "function attachToolStep(",
                       "function buildToolField(", "tool-step", "choices: ["):
            self.assertIn(marker, text)

    def test_free_text_fields_stay_free(self):
        """Путь к картинке и свободный текст шагать нечем — стрелок там не должно."""
        text = APP_JS.read_text(encoding="utf-8")
        self.assertIn("k: 'image', label: 'карта', v: 'docs/pattern.png', kind: 'raw' }", text)
        self.assertIn("k: 'text', label: 'текст'", text)


if __name__ == "__main__":
    unittest.main()
