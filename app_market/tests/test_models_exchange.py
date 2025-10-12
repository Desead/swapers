import pytest
from decimal import Decimal
from app_market.models.exchange import ExchangeKind, Exchange, LiquidityProvider

pytestmark = pytest.mark.django_db


def test_exchange_defaults_and_stablecoin_normalization():
    ex = Exchange.objects.create(provider=LiquidityProvider.KUCOIN, stablecoin="usdt")
    ex.refresh_from_db()

    assert ex.exchange_kind == ExchangeKind.CEX  # дефолт
    assert ex.stablecoin == "USDT"
    assert ex.is_available is True
    assert ex.can_receive is True
    assert ex.can_send is True
    assert ex.spot_taker_fee == Decimal("0.1")
    assert ex.spot_maker_fee == Decimal("0.1")
    assert ex.futures_taker_fee == Decimal("0.1")
    assert ex.futures_maker_fee == Decimal("0.1")
    assert ex.show_prices_on_home is False


def test_exchange_unique_provider():
    Exchange.objects.create(provider=LiquidityProvider.MEXC)
    with pytest.raises(Exception):
        Exchange.objects.create(provider=LiquidityProvider.MEXC)


def test_exchange_can_be_manual_kind():
    ex = Exchange.objects.create(provider=LiquidityProvider.CASH, exchange_kind=ExchangeKind.CASH)
    assert ex.exchange_kind == ExchangeKind.CASH

