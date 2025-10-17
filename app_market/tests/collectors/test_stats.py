from __future__ import annotations
import pytest

from app_market.collectors import tasks as collectors_tasks
from app_market.models.exchange import Exchange, LiquidityProvider

@pytest.mark.django_db
def test_run_stats_ok(monkeypatch):
    ex = Exchange.objects.create(provider=LiquidityProvider.BYBIT)

    def fake_collect_exchange_stats(exchange, timeout=20):
        assert exchange.id == ex.id
        return {"run_at": "now", "markets": {"pairs_total": 5}}

    monkeypatch.setenv("DUMMY", "1")
    monkeypatch.setattr("app_market.services.stats.collect_exchange_stats", fake_collect_exchange_stats, raising=False)

    res = collectors_tasks.run_stats(provider="BYBIT", dump_raw=True)
    assert res["provider"] == "BYBIT"
    assert res["exchange_id"] == ex.id
    assert "snapshot_at" in res

@pytest.mark.django_db
def test_run_stats_skipped_on_stats_error(monkeypatch):
    ex = Exchange.objects.create(provider=LiquidityProvider.RAPIRA)

    class StatsError(Exception):
        pass

    def raise_stats_error(exchange, timeout=20):
        raise StatsError("RAPIRA: сбор статистики ещё не реализован")

    # подменяем и сам эксепшн, и функцию
    monkeypatch.setitem(collectors_tasks.__dict__, "StatsError", StatsError)
    monkeypatch.setattr("app_market.services.stats.collect_exchange_stats", raise_stats_error, raising=False)

    res = collectors_tasks.run_stats(provider="RAPIRA", dump_raw=False)
    assert res["provider"] == "RAPIRA"
    assert res["exchange_id"] == ex.id
    assert res["skipped"] is True
