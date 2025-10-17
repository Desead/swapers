from __future__ import annotations
import importlib
import types
import pytest

from app_market.collectors import tasks as collectors_tasks
from app_market.models.exchange import Exchange, LiquidityProvider

@pytest.mark.django_db
def test_run_wallet_assets_with_dummy_adapter(settings, monkeypatch):
    # регистрируем фиктивный модуль и класс, чтобы runner загрузил его по dotted path
    dummy_mod = types.ModuleType("tests_dummy_mod")
    from app_market.tests.collectors._dummies import DummyAdapter
    dummy_mod.DummyAdapter = DummyAdapter
    monkeypatch.setitem(importlib.sys.modules, "tests_dummy_mod", dummy_mod)

    # провайдер и Exchange
    settings.COLLECTORS_PROVIDER_REGISTRY = {
        "BYBIT": {"path": "tests_dummy_mod:DummyAdapter", "enabled": True, "needs_api": False}
    }
    ex = Exchange.objects.create(provider=LiquidityProvider.BYBIT)

    # сам вызов
    res = collectors_tasks.run_wallet_assets(provider="BYBIT", adapter=DummyAdapter(), dump_raw=False)
    assert res["provider"] == "BYBIT"
    assert res["exchange_id"] == ex.id
    assert res["processed"] == 3
    assert res["created"] == 2
    assert res["updated"] == 1
