import pytest
from django.contrib.auth import get_user_model
from django.conf import settings

from allauth.account.models import EmailAddress


def _create_superuser_flexible():
    """
    Создаёт суперпользователя для любых конфигураций кастомной модели:
    - если USERNAME_FIELD == 'email', то достаточно email+password;
    - иначе добавляем username (или иной USERNAME_FIELD).
    Если create_superuser недоступен/ругается на сигнатуру — падаем на create().
    """
    User = get_user_model()
    username_field = getattr(User, "USERNAME_FIELD", "username")
    base_email = "admin@example.com"
    base_password = "AdminPass123!"

    # Набор полей для create_superuser
    params = {}
    if username_field == "email":
        params["email"] = base_email
    else:
        params[username_field] = "admin"
        # почти всегда хотим иметь email для allauth
        if "email" in {f.name for f in User._meta.get_fields()}:
            params["email"] = base_email

    try:
        # пробуем штатный путь
        user = User.objects.create_superuser(password=base_password, **params)
    except Exception:
        # fallback: прямая запись + пароль
        create_params = dict(params)
        create_params.update({"is_superuser": True, "is_staff": True})
        user = User.objects.create(**create_params)
        if hasattr(user, "set_password"):
            user.set_password(base_password)
            user.save(update_fields=["password"])
    return user


@pytest.mark.django_db
def test_superuser_email_verified_on_create(settings):
    """
    При создании суперпользователя его email должен автоматически стать
    верифицированным и основным (allauth EmailAddress: verified=True, primary=True).
    """
    # на всякий случай фиксируем «строгость» верификации в тесте
    settings.ACCOUNT_EMAIL_VERIFICATION = "mandatory"

    user = _create_superuser_flexible()
    assert user.is_superuser is True

    # у суперпользователя должен быть email; иначе тесту нечего проверять
    assert getattr(user, "email", None), "Superuser must have email for allauth verification."

    # сигнал должен был создать/обновить EmailAddress
    ea = EmailAddress.objects.get(user=user, email=user.email)
    assert ea.verified is True
    assert ea.primary is True


@pytest.mark.django_db
def test_regular_user_is_not_auto_verified(settings):
    """
    Для обычного пользователя авто-верификации быть не должно (проверяем, что сигнал
    не срабатывает на не-суперпользователей).
    """
    settings.ACCOUNT_EMAIL_VERIFICATION = "mandatory"

    User = get_user_model()
    username_field = getattr(User, "USERNAME_FIELD", "username")
    params = {}
    if username_field == "email":
        params["email"] = "user@example.com"
    else:
        params[username_field] = "user"
        if "email" in {f.name for f in User._meta.get_fields()}:
            params["email"] = "user@example.com"

    user = User.objects.create(**params)

    qs = EmailAddress.objects.filter(user=user)
    # либо совсем нет записи, либо она есть, но не верифицирована
    assert not qs.exists() or qs.filter(verified=False).exists()
