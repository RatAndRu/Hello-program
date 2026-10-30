"""0.58: регрессии сочетаний, найденных аудитом всех choice-полей карточек."""

from __future__ import annotations

import unittest

import manifold3d as mf

from forma.geometry import solid_parts
from forma.run import build


def ok(script: str):
    result = build(script, analyze_model=False)
    if not result.ok:
        raise AssertionError(f"{result.error}\n{script}")
    for obj in result.scene.objects.values():
        assert obj.manifold.status() == mf.Error.NoError
        assert obj.manifold.volume() > 0
        assert obj.manifold.num_tri() > 0
    return result


class CardChoiceRegression058Test(unittest.TestCase):
    def test_spikes_default_base_accepts_every_surface(self):
        for surface in ("верх", "низ", "право", "лево", "перёд", "зад", "вся"):
            with self.subTest(surface=surface):
                result = ok(
                    "заготовка = box size=[140,140,40]\n"
                    f"заготовка = spikes заготовка surface={surface} count=12 "
                    "height=28 base_d=12 tip_d=0.8 sides=24 lean=0 direction=0 seed=1"
                )
                obj = result.scene.objects["заготовка"]
                self.assertEqual(obj.meta.get("spikes"), 12)
                self.assertEqual(solid_parts(obj.manifold), 1)

    def test_hair_only_exposes_implemented_growth_choices(self):
        for growth in ("авто", "нормаль", "вниз", "свисание"):
            with self.subTest(growth=growth):
                result = ok(
                    "заготовка = box size=[80,70,18] round=5\n"
                    f"hair заготовка style=волоски surface=верх length=24 thick=1.4 "
                    f"count=48 growth={growth} drape=да bend=1.8 spread=0.25 seed=7"
                )
                self.assertEqual(result.scene.objects["заготовка"].meta.get("roots"), 48)

    def test_shrinkwrap_card_gap_supports_every_join(self):
        for join in ("нет", "слить", "сгладить"):
            with self.subTest(join=join):
                result = ok(
                    "цель = sphere radius=35\n"
                    "плёнка = box size=[65,65,2] at=[0,0,34]\n"
                    f"плёнка = shrinkwrap [цель, плёнка] gap=-1 direction=ближняя "
                    f"amount=1 transition=0 detail=2 join={join} weld=2"
                )
                visible = [obj for obj in result.scene.objects.values() if obj.visible]
                # Цель остаётся в дереве построения как скрытый исходник;
                # на сцене и в GLB после join должен быть только результат.
                self.assertEqual(len(visible), 2 if join == "нет" else 1)
                self.assertEqual(solid_parts(result.scene.objects["плёнка"].manifold), 1)
                self.assertEqual(result.scene.objects["плёнка"].meta.get("join"), join)


if __name__ == "__main__":
    unittest.main()
