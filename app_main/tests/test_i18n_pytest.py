# app_main/tests/test_i18n_pytest.py
import pytest
from django.urls import reverse

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
