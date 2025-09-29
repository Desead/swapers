import pytest
from django import forms
from django.contrib import admin
from django.test import RequestFactory
from app_market.models import Exchange, ExchangeApiKey
from app_market.models.exchange import LiquidityProvider

from app_market.admin.exchanges_admin import (
    ExchangeAdmin,
    ExchangeApiKeyAdmin,
    ExchangeApiKeyAdminForm,
)

pytestmark = pytest.mark.django_db


def test_exchange_admin_readonly_is_available():
    assert "is_available" in ExchangeAdmin.readonly_fields


def test_apikey_admin_form_uses_password_widgets():
    form = ExchangeApiKeyAdminForm()
    assert isinstance(form.fields["api_key"].widget, forms.PasswordInput)
    assert isinstance(form.fields["api_secret"].widget, forms.PasswordInput)
    assert isinstance(form.fields["api_passphrase"].widget, forms.PasswordInput)


def test_apikey_admin_shows_view_fields_in_list_display():
    assert "api_key_view" in ExchangeApiKeyAdmin.list_display
    assert "api_secret_view" in ExchangeApiKeyAdmin.list_display
    assert "api_passphrase_view" in ExchangeApiKeyAdmin.list_display


def test_apikey_admin_readonly_view_fields(admin_site=None):
    readonly = set(ExchangeApiKeyAdmin.readonly_fields)
    assert {"api_key_view", "api_secret_view", "api_passphrase_view"} <= readonly


def test_apikey_admin_changeform_context_renders_views(rf: RequestFactory):
    admin_site = admin.site
    ap_admin = ExchangeApiKeyAdmin(ExchangeApiKey, admin_site)

    ex = Exchange.objects.create(provider=LiquidityProvider.KUCOIN)
    obj = ExchangeApiKey.objects.create(
        exchange=ex, label="main",
        api_key="abcdef", api_secret="abcdef", api_passphrase="abcdef"
    )

    request = rf.get(f"/admin/app_market/exchangeapikey/{obj.pk}/change/")
    request.user = type("U", (), {"is_staff": True, "is_active": True, "has_perm": lambda *a, **k: True})()

    form = ap_admin.get_form(request, obj)
    assert isinstance(form.base_fields["api_key"].widget, forms.PasswordInput)

    readonly_fields = ap_admin.get_readonly_fields(request, obj)
    assert "api_key_view" in readonly_fields

    obj.refresh_from_db()
    assert obj.api_key_view == "abc**********def"
