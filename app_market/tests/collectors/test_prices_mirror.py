from __future__ import annotations
import pytest

from app_market.collectors import tasks as collectors_tasks
from app_market.models.exchange import Exchange, LiquidityProvider
from app_market.models.price import PriceL1

@pytest.mark.django_db
def test_run_prices_with_admin_mirror(monkeypatch):
    ex = Exchange.objects.create(provider=LiquidityProvider.BYBIT)

    # подменяем коллектор на фиктивный
    from app_market.tests.collectors._dummies import dummy_collect_spot
    monkeypatch.setitem(collectors_tasks.PRICE_COLLECTORS, "BYBIT", dummy_collect_spot)

    res = collectors_tasks.run_prices(provider="BYBIT", dump_raw=True, mirror_to_admin=True)
    assert res["pushed"] == 1
    assert res["skipped"] == 0
    assert res["mirrored_to_admin"] is True

    # проверяем, что запись попала в БД для админки
    rows = PriceL1.objects.filter(provider=ex)
    assert rows.count() == 1
    r = rows.first()
    assert r.src_base_code == "BTC"
    assert r.src_quote_code == "USDT"
