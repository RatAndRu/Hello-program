"""Тесты чистой логики: каждый «чек» из airmouse.selftest — отдельный тест.

Так одна и та же проверка доступна и как ``python -m airmouse selftest``
(без pytest), и как обычный pytest-тест в CI.
"""

from __future__ import annotations

import pytest

from airmouse.selftest import CHECKS


@pytest.mark.parametrize("check", CHECKS, ids=[c.__name__ for c in CHECKS])
def test_check(check):
    result = check()
    assert result.ok, f"{result.name}: {result.detail}"
