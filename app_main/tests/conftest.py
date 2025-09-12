# app_main/tests/conftest.py
import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import translation

from app_main.models import SiteSetup


@pytest.fixture
def site_setup(db):
    s = SiteSetup.get_solo()
    s.domain = "example.com"
    s.domain_view = "Swap"
    s.admin_path = "admin"
    s.save()
    return s


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(email="u@example.com", password="pass123")


@pytest.fixture
def staff_user(db):
    User = get_user_model()
    return User.objects.create_user(
        email="staff@example.com", password="pass123", is_staff=True
    )


@pytest.fixture
def auth_client(client, user):
    assert client.login(email=user.email, password="pass123")
    return client


@pytest.fixture
def staff_client(client, staff_user):
    assert client.login(email=staff_user.email, password="pass123")
    return client


@pytest.fixture
def switch_lang(client, db):
    """Ставит язык в сессии + активирует его в текущем потоке (чтобы reverse() дал правильный префикс)."""
    def _switch(lang_code: str, next_url="/"):
        client.post(
            reverse("set_language"),
            {"language": lang_code, "next": next_url},
            follow=True,
        )
        # Важно: активируем язык для текущего потока — reverse() начнёт отдавать /en/, /ru/, ...
        translation.activate(lang_code.split("-", 1)[0])
        return client
    return _switch
