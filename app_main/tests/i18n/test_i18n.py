# app_main/tests/i18n/test_i18n.py
import pytest
from django.conf import settings
from django.urls import reverse

# --- Нормализация языка (middleware + redirect) ---
@pytest.mark.django_db
@pytest.mark.parametrize("accept_language", ["ru-RU,ru;q=0.9", "ru_RU,ru;q=0.9"])
def test_root_redirect_normalizes_to_ru(client, accept_language):
    client.defaults["HTTP_ACCEPT_LANGUAGE"] = accept_language
    resp = client.get("/", follow=False)
    assert resp.status_code in (301, 302)
    assert resp.headers["Location"].endswith("/ru/")

@pytest.mark.django_db
@pytest.mark.parametrize("bad_cookie", ["ru-RU", "ru_RU"])
def test_middleware_normalizes_language_cookie_to_ru(client, settings, bad_cookie):
    client.cookies[settings.LANGUAGE_COOKIE_NAME] = bad_cookie
    resp = client.get(reverse("home"), follow=True)
    assert resp.status_code == 200
    lang_cookie = resp.cookies.get(settings.LANGUAGE_COOKIE_NAME)
    assert lang_cookie is not None and lang_cookie.value == "ru"

@pytest.mark.django_db
def test_root_redirect_defaults_to_ru_without_hints(client):
    client.defaults.pop("HTTP_ACCEPT_LANGUAGE", None)
    client.cookies.pop(getattr(settings, "LANGUAGE_COOKIE_NAME", "django_language"), None)
    resp = client.get("/", follow=False)
    assert resp.status_code in (301, 302)
    assert resp.headers["Location"].endswith("/ru/")

# --- Функциональные проверки i18n ---
@pytest.mark.django_db
def test_set_language_changes_i18n_reverse(client, switch_lang):
    switch_lang("en", next_url="/")
    assert reverse("home").startswith("/en/")

@pytest.mark.django_db
def test_home_page_title_ru(client, switch_lang):
    switch_lang("ru", next_url="/")
    r = client.get(reverse("home"))
    assert r.status_code == 200
    assert "Главная" in r.content.decode("utf-8")

@pytest.mark.django_db
def test_set_language_cookie_not_overridden_by_normalizer(client, settings):
    # сначала ставим ru (нормализатор не должен вмешиваться)
    resp1 = client.post(reverse("set_language"), {"language": "ru", "next": "/"}, follow=False)
    assert resp1.status_code in (302, 303)
    # потом ставим en и убеждаемся, что ответ содержит en (а не ru)
    resp2 = client.post(reverse("set_language"), {"language": "en", "next": "/"}, follow=False)
    assert resp2.status_code in (302, 303)
    assert resp2.cookies.get(settings.LANGUAGE_COOKIE_NAME).value == "en"
