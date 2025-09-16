# app_main/tests/test_admin_telegram_alerts.py
import pytest
from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.contrib.auth import get_user_model

from app_main.models import SiteSetup
from app_main.admin import SiteSetupAdmin
from app_main.utils import audit as audit_utils


@pytest.fixture
def admin_rf_user(db):
    User = get_user_model()
    u = User.objects.create_superuser(email="admin@test.local", password="x")
    rf = RequestFactory()
    req = rf.post("/admin/app_main/sitesetup/1/change/", HTTP_USER_AGENT="pytest-UA/1.0")
    req.user = u
    req.META["REMOTE_ADDR"] = "127.0.0.1"
    return req


@pytest.fixture
def admin_class():
    return SiteSetupAdmin(SiteSetup, AdminSite())


@pytest.mark.django_db
def test_alert_sent_on_change_and_masking_happens(monkeypatch, admin_class, admin_rf_user):
    setup = SiteSetup.get_solo()
    setup.telegram_bot_token = "TEST:TOKEN"
    setup.telegram_chat_id = "-1001234567890"
    setup.email_host_password = "oldsecret"
    setup.robots_txt = "User-agent: *\nDisallow:\n"
    setup.fee_percent = Decimal("0.50")
    setup.save()

    calls = []

    def fake_send(token, chat_id, text, parse_mode="HTML"):
        calls.append({"token": token, "chat_id": chat_id, "text": text})
        return True

    monkeypatch.setattr("app_main.admin.send_telegram_message", fake_send)

    setup.email_host_password = "newsecret"                 # должен замаскироваться ***cret
    setup.robots_txt = "User-agent: *\nDisallow: /\n"       # должен уйти как hash:xxxx
    setup.fee_percent = Decimal("0.75")                     # критично
    admin_class.save_model(admin_rf_user, setup, form=None, change=True)

    assert len(calls) == 1
    payload = calls[0]
    assert payload["token"] == "TEST:TOKEN"
    assert payload["chat_id"] == "-1001234567890"

    text = payload["text"]
    assert "SiteSetup изменён" in text
    assert "***cret" in text           # маскирование секрета
    assert "hash:" in text             # хеш длинного текста
    assert ("Комиссия" in text) or ("процент" in text) or ("fee" in text.lower())


@pytest.mark.django_db
def test_no_alert_when_no_changes(monkeypatch, admin_class, admin_rf_user):
    setup = SiteSetup.get_solo()
    setup.telegram_bot_token = "TEST:TOKEN"
    setup.telegram_chat_id = "-1001234567890"
    setup.save()

    calls = []
    monkeypatch.setattr("app_main.admin.send_telegram_message", lambda *a, **kw: calls.append(1) or True)

    admin_class.save_model(admin_rf_user, setup, form=None, change=True)
    assert calls == []


@pytest.mark.django_db
def test_no_alert_if_token_or_chat_missing(monkeypatch, admin_class, admin_rf_user):
    setup = SiteSetup.get_solo()
    setup.telegram_bot_token = ""
    setup.telegram_chat_id = ""
    setup.save()

    calls = []
    monkeypatch.setattr("app_main.admin.send_telegram_message", lambda *a, **kw: calls.append(1) or True)

    setup.fee_percent = Decimal("0.60")
    admin_class.save_model(admin_rf_user, setup, form=None, change=True)
    assert calls == []


@pytest.mark.django_db
def test_token_masking_and_description_truncation(monkeypatch, admin_class, admin_rf_user):
    """
    Проверяем:
    - токен маскируется ***xxxx (последние 4 символа);
    - длинные строки (не входящие в HASH_FIELDS) обрезаются и содержат '…'.
    """
    setup = SiteSetup.get_solo()
    setup.telegram_bot_token = "token-aaaaaaaaaaaaaaaaaaaaabcd"  # хвост abcd
    setup.telegram_chat_id = "-1001234567890"
    setup.seo_default_description = "X" * 150  # длинная строка (не hashed)
    setup.save()

    calls = []

    def fake_send(token, chat_id, text, parse_mode="HTML"):
        calls.append({"token": token, "chat_id": chat_id, "text": text})
        return True

    monkeypatch.setattr("app_main.admin.send_telegram_message", fake_send)

    # меняем токен и описание на другие длинные значения
    setup.telegram_bot_token = "token-bbbbbbbbbbbbbbbbbbbbbbwxyz"  # хвост wxyz
    setup.seo_default_description = "Y" * 150
    admin_class.save_model(admin_rf_user, setup, form=None, change=True)

    assert len(calls) == 1
    text = calls[0]["text"]

    # маскирование токена: ***abcd → ***wxyz
    assert "***abcd" in text
    assert "***wxyz" in text

    # обрезка длинной строки: не должно быть длинных 140+ символов подряд; должен быть символ '…'
    assert "Y" * 140 not in text
    assert "…" in text


def test_severity_levels_unit():
    assert audit_utils.severity_for_fields(["fee_percent"]) == "critical"
    assert audit_utils.severity_for_fields(["email_host"]) == "important"
    assert audit_utils.severity_for_fields(["seo_default_title"]) == "info"
