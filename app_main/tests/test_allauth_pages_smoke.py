# app_main/tests/test_allauth_pages_smoke.py
import pytest
from django.urls import reverse

@pytest.mark.django_db
@pytest.mark.parametrize("name", [
    "account_login",
    "account_signup",
    "account_reset_password",
])
def test_allauth_pages_render(name, client, switch_lang):
    switch_lang("ru", next_url="/")          # гарантируем префикс /ru/
    path = reverse(name)
    r = client.get(path)
    assert r.status_code in (200, 302)
