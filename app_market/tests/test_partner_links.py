import pytest
from django.contrib import admin
from app_market.models import Exchange
from app_market.models.exchange import LiquidityProvider
from app_market.admin.exchanges_admin import ExchangeAdmin

pytestmark = pytest.mark.django_db


def test_partner_url_for_known_providers_not_empty():
    """
    Для нормальных провайдеров partner_url должен быть непустым http(s)-URL.
    Берём несколько разных типов для надёжности (биржа, PSP).
    """
    for provider in (LiquidityProvider.BINANCE, LiquidityProvider.BYBIT, LiquidityProvider.PAYPAL):
        ex = Exchange.objects.create(provider=provider)
        assert ex.partner_url, f"partner_url пуст для {provider}"
        assert ex.partner_url.startswith(("http://", "https://")), f"partner_url не URL: {ex.partner_url}"


def test_partner_url_for_manual_is_empty():
    """
    Для ручного режима ссылка отсутствует.
    """
    ex = Exchange.objects.create(provider=LiquidityProvider.MANUAL)
    assert ex.partner_url == ""


def test_admin_partner_link_renders_anchor_for_known_provider():
    """
    В админке должен рендериться кликабельный <a> с правильным href и названием провайдера.
    """
    ex = Exchange.objects.create(provider=LiquidityProvider.BINANCE)
    admin_site = admin.site
    ex_admin = ExchangeAdmin(Exchange, admin_site)

    html = ex_admin.partner_link(ex)
    assert isinstance(html, str)
    assert "<a " in html and 'target="_blank"' in html and 'rel="noopener' in html
    assert f'href="{ex.partner_url}"' in html
    # Текст переведён, но имя провайдера должно входить в надпись
    assert ex.get_provider_display() in html


def test_admin_partner_link_shows_dash_for_manual():
    """
    В админке для Manual должен выводиться эм-даш '—' вместо ссылки.
    """
    ex = Exchange.objects.create(provider=LiquidityProvider.MANUAL)
    ex_admin = ExchangeAdmin(Exchange, admin.site)

    html = ex_admin.partner_link(ex)
    assert html == "—"


def test_admin_partner_link_is_readonly_field():
    """
    Поле partner_link должно быть только для чтения в админке.
    """
    readonly = set(ExchangeAdmin.readonly_fields)
    assert "partner_link" in readonly
