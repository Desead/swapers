import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from urllib.parse import urlparse, parse_qs

@pytest.mark.django_db
def test_signup_with_existing_email_redirects_to_login(client):
    User = get_user_model()
    email = "user@example.com"
    User.objects.create(email=email, is_active=True)

    resp = client.post(
        reverse("account_signup"),
        data={
            "email": email,
            "password1": "Pass123456!",
            "password2": "Pass123456!",
        },
        follow=False,
    )

    # Должен быть редирект на логин с ?email=...
    assert resp.status_code in (301, 302)
    assert reverse("account_login") in resp["Location"]
    # Должен быть редирект на логин с ?email=...
    assert resp.status_code in (301, 302)
    assert reverse("account_login") in resp["Location"]

    # Разбираем URL и проверяем, что email передан как query-параметр (без оглядки на URL-encoding)
    loc = resp["Location"]
    qs = parse_qs(urlparse(loc).query)
    assert qs.get("email") == [email]

