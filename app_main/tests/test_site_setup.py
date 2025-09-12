# app_main/tests/test_site_setup.py
import re
import pytest
from django.urls import reverse
from app_main.models import SiteSetup


def _get_text(resp) -> str:
    return resp.content.decode("utf-8", errors="ignore")


@pytest.mark.django_db
def test_robots_txt_single_sitemap_and_plaintext(client):
    """Отдаём text/plain и ровно одну строку Sitemap с абсолютным URL."""
    resp = client.get(reverse("robots_txt"))
    assert resp.status_code == 200
    assert resp["Content-Type"].split(";")[0].strip() == "text/plain"

    text = _get_text(resp)
    lines = text.splitlines()
    sitemap_lines = [ln for ln in lines if ln.lower().startswith("sitemap:")]
    assert len(sitemap_lines) == 1, text

    # Абсолютный URL на /sitemap.xml (http/https — любой)
    url = sitemap_lines[0].split(":", 1)[1].strip()
    assert url.endswith("/sitemap.xml")
    assert re.match(r"^https?://[^/]+/sitemap\.xml$", url), url


@pytest.mark.django_db
def test_robots_txt_deduplicates_user_sitemap_line(client):
    """
    Если в админке в robots_txt случайно добавили свою строку 'Sitemap: ...',
    во вьюхе всё равно должна остаться ровно одна (та, что формируется сервером).
    """
    site = SiteSetup.get_solo()
    site.robots_txt = (
        "User-agent: *\n"
        "Disallow:\n"
        "Sitemap: http://example.com/sitemap.xml\n"  # лишняя пользовательская строка
    )
    site.save()

    resp = client.get(reverse("robots_txt"))
    text = _get_text(resp)
    assert resp.status_code == 200

    sitemap_lines = [ln for ln in text.splitlines() if ln.lower().startswith("sitemap:")]
    assert len(sitemap_lines) == 1, text

    # Проверим формат конечного URL, но без привязки к конкретному хосту.
    url = sitemap_lines[0].split(":", 1)[1].strip()
    assert re.match(r"^https?://[^/]+/sitemap\.xml$", url), url


@pytest.mark.django_db
def test_robots_txt_has_at_least_one_disallow_line(client):
    """
    В robots.txt должна быть хотя бы одна строка Disallow (пустая или с путём) —
    фиксируем базовый инвариант, не привязываясь к DEBUG/домену.
    """
    resp = client.get(reverse("robots_txt"))
    text = _get_text(resp)
    assert any(ln.lower().startswith("disallow") for ln in text.splitlines()), text
