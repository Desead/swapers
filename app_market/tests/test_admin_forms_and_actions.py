import pytest
from django.contrib import admin
from django.test import RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.auth import get_user_model

from app_market.models import Exchange, ExchangeApiKey
from app_market.models.exchange import LiquidityProvider
from app_market.admin.exchanges_admin import (
    ExchangeAdmin,
    ExchangeApiKeyAdminForm,
)

pytestmark = pytest.mark.django_db

def _make_exchange(provider=LiquidityProvider.KUCOIN) -> Exchange:
    return Exchange.objects.create(provider=provider)
# ---------- helpers ----------

def _admin_request(rf: RequestFactory, user=None):
    """
    Делает валидный admin request с сессией и message storage.
    Не зависит от сигнатуры create_superuser().
    """
    req = rf.post("/")
    # Лёгкий стаб-пользователь для admin actions:
    class _DummyUser:
        is_staff = True
        is_superuser = True
        def has_perm(self, perm):  # на всякий случай
            return True
        def __str__(self):
            return "dummy-admin"

    req.user = user or _DummyUser()
    req._dont_enforce_csrf_checks = True

    # messages требуют session
    from django.contrib.sessions.middleware import SessionMiddleware
    SessionMiddleware(lambda r: None).process_request(req)
    req.session.save()

    # backend сообщений
    req._messages = FallbackStorage(req)
    return req


# ---------- tests: API key admin form ----------

def test_apikey_form_preserves_values_when_blank():
    ex = _make_exchange()
    inst = ExchangeApiKey.objects.create(
        exchange=ex,
        label="prod",
        api_key="AAA",
        api_secret="BBB",
        api_passphrase="CCC",
        is_enabled=True,
    )

    form = ExchangeApiKeyAdminForm(
        data={
            "exchange": ex.pk,
            "label": "prod",
            "is_enabled": "on",
            # поля пустые → должны сохраниться старые значения
            "api_key": "",
            "api_secret": "",
            "api_passphrase": "",
            # чекбоксы очистки не отмечены
            # clear_api_key / clear_api_secret / clear_api_passphrase — отсутствуют
        },
        instance=inst,
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    obj.refresh_from_db()

    assert obj.api_key == "AAA"
    assert obj.api_secret == "BBB"
    assert obj.api_passphrase == "CCC"


def test_apikey_form_clears_values_when_clear_flags_set():
    ex = _make_exchange()
    inst = ExchangeApiKey.objects.create(
        exchange=ex,
        label="prod",
        api_key="AAA",
        api_secret="BBB",
        api_passphrase="CCC",
        is_enabled=True,
    )

    form = ExchangeApiKeyAdminForm(
        data={
            "exchange": ex.pk,
            "label": "prod",
            "is_enabled": "on",
            # значения можно оставить пустыми — очистка произойдёт по флажкам
            "api_key": "",
            "api_secret": "",
            "api_passphrase": "",
            "clear_api_key": "on",
            "clear_api_secret": "on",
            "clear_api_passphrase": "on",
        },
        instance=inst,
    )
    assert form.is_valid(), form.errors
    obj = form.save()
    obj.refresh_from_db()

    assert obj.api_key == ""
    assert obj.api_secret == ""
    assert obj.api_passphrase == ""


# ---------- tests: admin action "healthcheck now" ----------

def test_admin_action_healthcheck_now_updates_is_available(monkeypatch):
    ex_ok = _make_exchange(LiquidityProvider.KUCOIN)
    ex_down = _make_exchange(LiquidityProvider.BYBIT)

    # Подменим check_exchange прямо в модуле админки
    from app_market.admin import exchanges_admin as admin_mod
    from app_market.services.health import HealthResult

    def fake_check_exchange(exchange, persist=True):
        available = exchange.provider != LiquidityProvider.BYBIT
        code = "OK" if available else "NETWORK_DOWN"
        res = HealthResult(
            provider=exchange.provider,
            exchange_id=exchange.id or 0,
            available=available,
            code=code,
            detail="stub",
            latency_ms=0,
        )
        if persist:
            # имитируем поведение сервиса: сохраняем is_available
            Exchange.objects.filter(pk=exchange.pk).update(is_available=available)
        return res

    monkeypatch.setattr(admin_mod, "check_exchange", fake_check_exchange)

    # Готовим admin action
    exchange_admin = ExchangeAdmin(Exchange, admin.site)
    req = _admin_request(RequestFactory())

    qs = Exchange.objects.filter(pk__in=[ex_ok.pk, ex_down.pk])
    exchange_admin.action_healthcheck_now(req, qs)

    ex_ok.refresh_from_db()
    ex_down.refresh_from_db()

    assert ex_ok.is_available is True
    assert ex_down.is_available is False
