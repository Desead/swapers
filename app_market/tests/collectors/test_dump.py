from __future__ import annotations
from decimal import Decimal
from pathlib import Path
import json
import pytest

from app_market.collectors.dump import write_daily_dump

@pytest.mark.django_db
def test_write_dump_once(settings, tmp_path):
    settings.COLLECTORS_DUMP_ROOT = tmp_path
    payload = {"a": Decimal("1.23"), "b": "x"}
    p1 = write_daily_dump("prices", "BYBIT", payload)
    assert p1 is not None and p1.exists()
    # повторная запись — не трогаем файл
    p2 = write_daily_dump("prices", "BYBIT", {"a": "changed"})
    assert p2 is None
    # проверяем, что остался исходный json и Decimal сериализован
    data = json.loads(p1.read_text())
    assert data["a"] == "1.23"
    assert data["b"] == "x"
    # имя и путь
    assert p1.name == "prices-bybit.json"
    assert Path(settings.COLLECTORS_DUMP_ROOT) in p1.parents
