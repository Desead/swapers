import pytest
from decimal import Decimal
from app_market.models import Exchange

pytestmark = pytest.mark.django_db


def test_exchange_defaults_and_stablecoin_normalization():
    ex = Exchange.objects.create(name="Binance", stablecoin="usdt")
    ex.refresh_from_db()

    # stablecoin → upper + trimmed
    assert ex.stablecoin == "USDT"

    # доступность по умолчанию True (редактируется автоматически)
    assert ex.is_available is True

    # режимы работы по умолчанию включены
    assert ex.can_receive is True
    assert ex.can_send is True

    # комиссии по умолчанию 0.1
    assert ex.spot_taker_fee == Decimal("0.1")
    assert ex.spot_maker_fee == Decimal("0.1")
    assert ex.futures_taker_fee == Decimal("0.1")
    assert ex.futures_maker_fee == Decimal("0.1")

    # флажок "цены на главную" по умолчанию выключен
    assert ex.show_prices_on_home is False


def test_exchange_unique_name():
    Exchange.objects.create(name="OKX")
    with pytest.raises(Exception):
        Exchange.objects.create(name="OKX")
