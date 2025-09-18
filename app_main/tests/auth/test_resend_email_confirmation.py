import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core import mail
from allauth.account.models import EmailAddress


def _field_names(model_cls):
    return {f.name for f in model_cls._meta.get_fields() if hasattr(f, "attname")}


def _create_user(email="user@example.com"):
    """
    Для этого теста пароль не нужен (используем client.force_login),
    поэтому создаём пользователя без установки пароля — это сильно быстрее.
    """
    User = get_user_model()
    username_field = getattr(User, "USERNAME_FIELD", "username")
    fields = _field_names(User)

    params = {}
    if username_field == "email":
        params["email"] = email
    else:
        params[username_field] = "user"
        if "email" in fields:
            params["email"] = email

    user = User.objects.create(**params)
    return user



# @pytest.mark.django_db
# def test_resend_email_first_time_sends_and_throttles(client, settings):
#     settings.ACCOUNT_EMAIL_VERIFICATION = "mandatory"
#     user = _create_user()
#     client.force_login(user)
#
#     url = reverse("account_email_resend")
#
#     # первая отправка — письмо должно уйти
#     resp1 = client.post(url, follow=True)
#     assert resp1.status_code == 200
#     assert len(mail.outbox) == 1
#
#     # повторная отправка сразу — троттлинг (письмо не уходит)
#     resp2 = client.post(url, follow=True)
#     assert resp2.status_code == 200
#     assert len(mail.outbox) == 1  # без изменений
#
#
# @pytest.mark.django_db
# def test_resend_email_if_already_verified_does_not_send(client, settings):
#     settings.ACCOUNT_EMAIL_VERIFICATION = "mandatory"
#     user = _create_user()
#     client.force_login(user)
#
#     # пометим e-mail как уже подтверждённый
#     EmailAddress.objects.update_or_create(
#         user=user, email=user.email, defaults={"verified": True, "primary": True}
#     )
#
#     url = reverse("account_email_resend")
#     resp = client.post(url, follow=True)
#     assert resp.status_code == 200
#
#     # писем не ушло
#     assert len(mail.outbox) == 0
