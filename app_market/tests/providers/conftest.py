# app_market/tests/providers/conftest.py
import pytest
from app_market.models.exchange import Exchange, LiquidityProvider

pytestmark = pytest.mark.django_db

@pytest.fixture(autouse=True)
def _disable_sync_debounce(settings):
    settings.PROVIDER_SYNC_DEBOUNCE_SECONDS = 0

@pytest.fixture
def ex_bybit(db):
    return Exchange.objects.create(provider=LiquidityProvider.BYBIT)

@pytest.fixture
def ex_kucoin(db):
    return Exchange.objects.create(provider=LiquidityProvider.KUCOIN)

@pytest.fixture
def ex_htx(db):
    return Exchange.objects.create(provider=LiquidityProvider.HTX)

@pytest.fixture
def ex_whitebit(db):
    return Exchange.objects.create(provider=LiquidityProvider.WHITEBIT)

@pytest.fixture
def ex_mexc(db):
    return Exchange.objects.create(provider=LiquidityProvider.MEXC)
