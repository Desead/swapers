# app_market/tests/test_liquidity_provider_no_i18n.py
import pytest
from django.utils.translation import override
from django.utils.functional import Promise
from app_market.models.exchange import LiquidityProvider, Exchange

pytestmark = pytest.mark.django_db

def test_liquidity_provider_choices_are_not_lazy_translations():
    # labels в choices не должны быть lazy (Promise)
    for value, label in LiquidityProvider.choices:
        assert not isinstance(label, Promise), f"Label for {value} must not be lazy-translated"


def test_provider_display_does_not_change_with_locale():
    ex = Exchange.objects.create(provider=LiquidityProvider.KUCOIN)
    label_default = ex.get_provider_display()

    # Меняем локаль — метка должна остаться той же
    with override("ru"):
        assert ex.get_provider_display() == label_default
    with override("en"):
        assert ex.get_provider_display() == label_default
