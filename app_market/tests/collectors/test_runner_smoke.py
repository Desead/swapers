from __future__ import annotations
import importlib, types
import pytest

from app_market.collectors.runner import run_once
from app_market.models.exchange import Exchange, LiquidityProvider

@pytest.mark.django_db
def test_runner_smoke_wallet_only(settings, monkeypatch):
    # фиктивный адаптер
    dummy_mod = types.ModuleType("tests_dummy_mod_r")
    from app_market.tests.collectors._dummies import DummyAdapter
    dummy_mod.DummyAdapter = DummyAdapter
    monkeypatch.setitem(importlib.sys.modules, "tests_dummy_mod_r", dummy_mod)

    # конфиг и Exchange
    settings.COLLECTORS_PROVIDER_REGISTRY = {
        "BYBIT": {"path": "tests_dummy_mod_r:DummyAdapter", "enabled": True, "needs_api": False}
    }
    Exchange.objects.create(provider=LiquidityProvider.BYBIT)

    rc = run_once(providers=["BYBIT"], task="wallet-assets", dump_raw=False, admin_mirror=False)
    assert rc >= 1  # хотя бы один шаг прошёл успешно
