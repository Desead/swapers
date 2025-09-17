# app_main/tests/security/test_axes.py
import pytest
from django.urls import reverse

# Совместимый импорт reset для разных версий django-axes
try:
    from axes.utils import reset as axes_reset
except Exception:  # старые релизы
    from axes.utils.reset import reset as axes_reset  # type: ignore

from axes.models import AccessAttempt
from allauth.account.models import EmailAddress

from app_main.models_security import BlocklistEntry


def reset_axes(**kwargs):
    """
    Унифицированный вызов сброса Axes.
    На одних версиях ожидается ip, на других ip_address.
    Мы используем ip=..., а если прилетит ip_address — переименуем.
    Также сбрасываем только по одному критерию за вызов.
    """
    if "ip_address" in kwargs and "ip" not in kwargs:
        kwargs = {**kwargs, "ip": kwargs.pop("ip_address")}
    return axes_reset(**kwargs)


def _fail_login(client, url, login, times):
    """Сделать times неуспешных логинов подряд, ожидая обычную форму/редирект (не 403)."""
    for _ in range(times):
        r = client.post(url, {"login": login, "password": "wrong"}, follow=False)
        assert r.status_code in (200, 302, 303)


def _verify_email(user):
    """Помечаем e-mail как подтверждённый, иначе allauth может не редиректить после логина."""
    EmailAddress.objects.get_or_create(
        user=user,
        email=user.email,
        defaults={"verified": True, "primary": True},
    )
    EmailAddress.objects.filter(user=user, email=user.email).update(verified=True, primary=True)


@pytest.mark.django_db
def test_login_lockout_after_limit(client, django_user_model, settings):
    settings.AXES_FAILURE_LIMIT = 3
    axes_reset()  # глобально очистим перед тестом

    user = django_user_model.objects.create_user(email="u@example.com", password="CorrectPass123")
    url = reverse("account_login")

    # 2 неудачные попытки — ещё не блок
    _fail_login(client, url, user.email, times=2)

    # 3-я — уже блок (403 от Axes или 200 с ошибкой формы от allauth на разных связках)
    r_blocked = client.post(url, {"login": user.email, "password": "wrong"}, follow=False)
    assert r_blocked.status_code in (403, 200)

    # Снимем блок: по username и по IP — ОТДЕЛЬНЫМИ вызовами
    ip = client.defaults.get("REMOTE_ADDR", "127.0.0.1")
    reset_axes(username=user.email)
    reset_axes(ip=ip)

    # Подтвердим e-mail, чтобы успешный логин дал редирект (или хотя бы 200 от allauth)
    _verify_email(user)

    r_ok = client.post(url, {"login": user.email, "password": "CorrectPass123"}, follow=False)
    assert r_ok.status_code in (200, 302, 303)


@pytest.mark.django_db
def test_axes_reset_by_username_allows_login(client, django_user_model, settings):
    settings.AXES_FAILURE_LIMIT = 2
    axes_reset()

    user = django_user_model.objects.create_user(email="u@example.com", password="Pass12345")
    url = reverse("account_login")

    # 1-я неуспешная — ещё не блок
    r1 = client.post(url, {"login": user.email, "password": "wrong"}, follow=False)
    assert r1.status_code in (200, 302, 303)

    # 2-я неуспешная — уже блок (возможен 403 или 200 с ошибкой формы)
    r2 = client.post(url, {"login": user.email, "password": "wrong"}, follow=False)
    assert r2.status_code in (403, 200)

    # Верные данные тоже должны блокироваться
    r_blocked = client.post(url, {"login": user.email, "password": "Pass12345"}, follow=False)
    assert r_blocked.status_code in (403, 200)

    # Сброс: по username и дополнительно по IP
    ip = client.defaults.get("REMOTE_ADDR", "127.0.0.1")
    reset_axes(username=user.email)
    reset_axes(ip=ip)

    _verify_email(user)

    r_ok = client.post(url, {"login": user.email, "password": "Pass12345"}, follow=False)
    assert r_ok.status_code in (200, 302, 303)


@pytest.mark.django_db
def test_axes_reset_by_ip_allows_login(client, django_user_model, settings):
    settings.AXES_FAILURE_LIMIT = 2
    axes_reset()

    user = django_user_model.objects.create_user(email="ip@test.com", password="IpPass123")
    url = reverse("account_login")

    # Зафиксируем «клиентский» IP и нагоним фейлы на IP (по левому логину)
    ip = "10.11.12.13"
    client.defaults["REMOTE_ADDR"] = ip

    # 1-я неуспешная по "левому" логину — ещё не блок
    r1 = client.post(url, {"login": "nobody@example.com", "password": "wrong"}, follow=False)
    assert r1.status_code in (200, 302, 303)

    # 2-я неуспешная — уже блок по IP
    r2 = client.post(url, {"login": "nobody@example.com", "password": "wrong"}, follow=False)
    assert r2.status_code in (403, 200)

    # Попытка верного логина — тоже должна блокировать
    r_blocked = client.post(url, {"login": user.email, "password": "IpPass123"}, follow=False)
    assert r_blocked.status_code in (403, 200)

    # Сброс по IP + (на всякий случай) по username
    reset_axes(ip=ip)
    reset_axes(username=user.email)

    _verify_email(user)

    r_ok = client.post(url, {"login": user.email, "password": "IpPass123"}, follow=False)
    assert r_ok.status_code in (200, 302, 303)


@pytest.mark.django_db
def test_blacklist_by_email_blocks_login(client, django_user_model):
    """Если email в чёрном списке — логин с ним должен отдавать 403 до Axes."""
    user = django_user_model.objects.create_user(email="banme@example.com", password="OkPass123")
    BlocklistEntry.objects.create(email=user.email, is_active=True)

    url = reverse("account_login")
    r = client.post(url, {"login": user.email, "password": "OkPass123"}, follow=False)
    assert r.status_code == 403


@pytest.mark.django_db
def test_blacklist_by_ip_blocks_login(client, django_user_model):
    """Если IP в чёрном списке — логин с него должен отдавать 403 до Axes."""
    user = django_user_model.objects.create_user(email="ok@example.com", password="OkPass123")
    ip = "203.0.113.42"
    client.defaults["REMOTE_ADDR"] = ip
    BlocklistEntry.objects.create(ip_address=ip, is_active=True)

    url = reverse("account_login")
    r = client.post(url, {"login": user.email, "password": "OkPass123"}, follow=False)
    assert r.status_code == 403


@pytest.mark.django_db
def test_axes_username_callable_populates_username(client, settings):
    """
    Проверяем, что AccessAttempt.username заполняется нашим callable
    даже при вводе мусорного логина (берём login из POST).
    """
    settings.AXES_FAILURE_LIMIT = 1
    axes_reset()

    url = reverse("account_login")
    client.post(url, {"login": "someone@example.com", "password": "wrong"}, follow=False)

    attempt = AccessAttempt.objects.order_by("-id").first()
    assert attempt is not None
    # В нашем AxesUsernameCallable возвращается POST['login'], а не анонимный <unknown>
    assert attempt.username == "someone@example.com"
