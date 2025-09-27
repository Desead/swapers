import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from app_market.models import Exchange, ExchangeKind, PaymentProviderProfile

pytestmark = pytest.mark.django_db

def test_psp_profile_only_for_psp_kind():
    ex_cex = Exchange.objects.create(name="Binance", exchange_kind=ExchangeKind.CEX)
    with pytest.raises(ValidationError):
        PaymentProviderProfile(exchange=ex_cex).save()

    ex_psp = Exchange.objects.create(name="PayPal", exchange_kind=ExchangeKind.PSP)
    p = PaymentProviderProfile.objects.create(exchange=ex_psp)
    assert p.environment == "LIVE"
    assert p.settlement_currency == "USD"

def test_psp_profile_normalizes_currency_and_unique():
    ex_psp = Exchange.objects.create(name="Skrill", exchange_kind=ExchangeKind.PSP)
    p = PaymentProviderProfile.objects.create(exchange=ex_psp, settlement_currency="usd ")
    assert p.settlement_currency == "USD"

    # OneToOne: второй профиль на тот же exchange не допускается
    with pytest.raises(ValidationError):
        PaymentProviderProfile.objects.create(exchange=ex_psp)
