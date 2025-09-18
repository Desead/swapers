import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


def _field_names(model_cls):
    # множество атрибутов модели (по именам полей)
    return {f.name for f in model_cls._meta.get_fields() if hasattr(f, "attname")}


def _create_user(password="Pass123456!"):
    """
    Создаёт обычного пользователя, учитывая разный USERNAME_FIELD.
    Не дублируем email, чтобы не ловить 'multiple values for keyword "email"'.
    """
    User = get_user_model()
    username_field = getattr(User, "USERNAME_FIELD", "username")
    fields = _field_names(User)

    params = {}
    if username_field == "email":
        params["email"] = "user@example.com"
    else:
        params[username_field] = "user"
        if "email" in fields:
            params["email"] = "user@example.com"

    # сначала пробуем create_user (корректно проставит is_active и т.п.)
    try:
        user = User.objects.create_user(password=password, **params)
    except Exception:
        # fallback: прямое создание + set_password
        user = User.objects.create(**params)
        if hasattr(user, "set_password"):
            user.set_password(password)
            user.save(update_fields=["password"])

    return user, password


def _create_superuser(password="Admin123456!"):
    """
    Создаёт суперпользователя, учитывая USERNAME_FIELD и наличие email.
    """
    User = get_user_model()
    username_field = getattr(User, "USERNAME_FIELD", "username")
    fields = _field_names(User)

    params = {}
    if username_field == "email":
        params["email"] = "admin@example.com"
    else:
        params[username_field] = "admin"
        if "email" in fields:
            params["email"] = "admin@example.com"

    try:
        user = User.objects.create_superuser(password=password, **params)
    except Exception:
        user = User.objects.create(is_staff=True, is_superuser=True, **params)
        if hasattr(user, "set_password"):
            user.set_password(password)
            user.save(update_fields=["password"])

    return user, password


@pytest.mark.django_db
def test_account_delete_requires_confirm_word(client):
    user, password = _create_user()
    client.force_login(user)

    url = reverse("account_delete")

    # неверное подтверждение — пользователь остаётся
    resp = client.post(url, {"password": password, "confirm_text": "WRONG"}, follow=True)
    assert resp.status_code == 200
    User = get_user_model()
    assert User.objects.filter(pk=user.pk).exists()

    # пустое подтверждение — пользователь остаётся
    resp = client.post(url, {"password": password, "confirm_text": ""}, follow=True)
    assert resp.status_code == 200
    assert User.objects.filter(pk=user.pk).exists()


@pytest.mark.django_db
def test_account_delete_success_case_insensitive(client):
    user, password = _create_user()
    client.force_login(user)

    url = reverse("account_delete")

    # допускаем различный регистр подтверждения
    resp = client.post(url, {"password": password, "confirm_text": "delete"}, follow=True)
    assert resp.status_code == 200

    User = get_user_model()
    assert not User.objects.filter(pk=user.pk).exists()


@pytest.mark.django_db
def test_superuser_protected_from_self_delete(client):
    admin, admin_password = _create_superuser()
    client.force_login(admin)

    url = reverse("account_delete")
    resp = client.post(url, {"password": admin_password, "confirm_text": "DELETE"}, follow=True)
    assert resp.status_code == 200

    User = get_user_model()
    # суперпользователь не должен удаляться через UI
    assert User.objects.filter(pk=admin.pk).exists()
