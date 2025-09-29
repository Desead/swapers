import pytest
from django.db import IntegrityError, transaction
from app_market.models import Exchange, ExchangeApiKey
from app_market.models.exchange import LiquidityProvider

pytestmark = pytest.mark.django_db


def _create_exchange(provider=LiquidityProvider.KUCOIN):
    return Exchange.objects.create(provider=provider)


@pytest.mark.parametrize(
    "val,expected",
    [
        (None, ""),                 # пусто
        ("", ""),                   # пустая строка
        ("a", "**********"),        # < 3 символов — не раскрываем вообще
        ("ab", "**********"),
        ("abc", "abc**********"),   # 3..5 символов — первые 3 + **********
        ("abcd", "abc**********"),
        ("abcde", "abc**********"),
        ("abcdef", "abc**********def"),   # >=6 — первые 3 + ********** + последние 3
        ("abcdefghijklmnop", "abc**********nop"),
    ],
)
def test_mask_logic_view_fields(val, expected):
    ex = _create_exchange()
    obj = ExchangeApiKey.objects.create(
        exchange=ex,
        label="main",
        api_key=val,
        api_secret=val,
        api_passphrase=val,
    )
    obj.refresh_from_db()
    assert obj.api_key_view == expected
    assert obj.api_secret_view == expected
    assert obj.api_passphrase_view == expected


def test_mask_updates_on_change_only():
    ex = _create_exchange()
    obj = ExchangeApiKey.objects.create(exchange=ex, label="main", api_key="abcdef")
    mask1 = obj.api_key_view
    assert mask1 == "abc**********def"

    obj.api_key = "xyz123456"
    obj.save()
    obj.refresh_from_db()
    assert obj.api_key_view != mask1
    assert obj.api_key_view == "xyz**********456"


def test_unique_label_per_exchange():
    ex = _create_exchange()
    ExchangeApiKey.objects.create(exchange=ex, label="prod")

    with transaction.atomic():
        with pytest.raises(IntegrityError):
            ExchangeApiKey.objects.create(exchange=ex, label="prod")  # тот же exchange+label

    ex2 = _create_exchange(LiquidityProvider.WHITEBIT)
    ExchangeApiKey.objects.create(exchange=ex2, label="prod")  # ок
