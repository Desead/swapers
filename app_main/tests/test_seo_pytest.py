import re
import pytest

@pytest.mark.django_db
def test_sitemap_has_ru_and_en_urls(client, site_setup):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    xml = r.content.decode()

    # допускаем http/https; корневая у тебя отдаётся как /ru/, а не /
    assert re.search(r"<loc>https?://example\.com/ru/</loc>", xml)
    assert re.search(r"<loc>https?://example\.com/en/</loc>", xml)
