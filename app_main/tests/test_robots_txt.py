# app_main/tests/test_robots_txt.py
import pytest
from django.test import Client
from django.urls import reverse
from django.test.utils import override_settings
from app_main.models import SiteSetup

def get_text(resp):
    return resp.content.decode("utf-8", errors="replace")

@pytest.mark.django_db
def test_robots_txt_basic_ok_and_plaintext(client: Client, site_setup):
    """Всегда отдаем прод-вариант: https + домен из django.contrib.sites."""
    url = reverse("robots_txt")
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp["Content-Type"].split(";")[0].strip() == "text/plain"
    body = get_text(resp)
    assert "Sitemap: https://example.com/sitemap.xml" in body
    assert f"Disallow: /{site_setup.admin_path}/" in body
    assert "Disallow: /accounts/" in body

@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}})
@pytest.mark.django_db
def test_robots_txt_includes_custom_body_and_updates_immediately(client: Client, site_setup):
    """Проверяем, что кастомные строки из админки сохраняются, а Sitemap добавляется один раз."""
    site = SiteSetup.get_solo()
    site.robots_txt = "User-agent: *\nDisallow: /secret/\n"
    site.save()

    url = reverse("robots_txt")
    resp = client.get(url)
    text = get_text(resp)
    assert "User-agent: *" in text
    assert "Disallow: /secret/" in text
    # Прод-вариант всё равно добавит служебные запреты:
    assert f"Disallow: /{site_setup.admin_path}/" in text
    assert "Disallow: /accounts/" in text
    # И добавит ровно один Sitemap с https+example.com
    assert text.count("Sitemap: ") == 1
    assert "Sitemap: https://example.com/sitemap.xml" in text

@pytest.mark.django_db
def test_robots_txt_always_https(client: Client, site_setup):
    """Независимо от заголовков, схема всегда https (прод-поведение)."""
    url = reverse("robots_txt")
    resp = client.get(url, HTTP_X_FORWARDED_PROTO="http")
    text = get_text(resp)
    assert "Sitemap: https://example.com/sitemap.xml" in text

@pytest.mark.django_db
def test_robots_txt_no_duplicate_sitemap_line(client: Client, site_setup):
    """Даже если в поле вставили Sitemap, выдаём ровно одну итоговую строку Sitemap (https + текущий домен)."""
    site = SiteSetup.get_solo()
    site.robots_txt = (
        "User-agent: *\n"
        "Disallow:\n"
        "Sitemap: http://bad.invalid/sitemap.xml\n"
    )
    site.save()

    resp = client.get(reverse("robots_txt"))
    text = get_text(resp)
    assert text.count("Sitemap: ") == 1
    assert "Sitemap: https://example.com/sitemap.xml" in text
