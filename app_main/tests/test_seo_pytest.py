# app_main/tests/test_seo_pytest.py
import pytest

@pytest.mark.django_db
def test_robots_txt_prod_uses_site_and_hides_paths(settings, client, site_setup):
    settings.DEBUG = False
    r = client.get("/robots.txt")
    assert r.status_code == 200
    txt = r.content.decode()
    assert f"Sitemap: https://{site_setup.domain}/sitemap.xml" in txt
    assert f"Disallow: /{site_setup.admin_path}/" in txt
    assert "Disallow: /accounts/" in txt

@pytest.mark.django_db
def test_sitemap_has_hreflang(client, site_setup):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    xml = r.content.decode()
    # Для каждого URL Django отдаёт вариант для RU и EN плюс alternates
    assert 'hreflang="ru"' in xml
    assert 'hreflang="en"' in xml
