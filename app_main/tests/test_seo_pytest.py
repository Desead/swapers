# app_main/tests/test_seo_pytest.py
import pytest

@pytest.mark.django_db
def test_sitemap_has_hreflang(client, site_setup):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    xml = r.content.decode()
    # Для каждого URL Django отдаёт вариант для RU и EN плюс alternates
    assert 'hreflang="ru"' in xml
    assert 'hreflang="en"' in xml
