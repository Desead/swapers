# app_main/tests/test_site_setup.py
from django.test import TestCase, override_settings
from django.contrib.sites.models import Site
from django.urls import reverse

from app_main.models import SiteSetup


class SiteSetupSyncTests(TestCase):
    def setUp(self):
        # выставим домен/имя и сохраним — это триггерит синхронизацию django_site
        setup = SiteSetup.get_solo()
        setup.domain = "example.com"
        setup.domain_view = "Swap Title"
        setup.admin_path = "admin"
        setup.save()
        self.setup = setup

    def test_sites_table_synced(self):
        site = Site.objects.get(pk=1)
        assert site.domain == "example.com"
        assert site.name == "Swap Title"

    @override_settings(DEBUG=False)
    def test_robots_txt_uses_site_and_hides_paths(self):
        resp = self.client.get("/robots.txt")
        assert resp.status_code == 200
        text = resp.content.decode()

        # Продакшен-вариант: https + канонический домен из django_site
        assert "Sitemap: https://example.com/sitemap.xml" in text

        # Запреты стандартных путей
        assert f"Disallow: /{self.setup.admin_path}/" in text
        assert "Disallow: /accounts/" in text

    def test_sitemap_xml_has_hreflang(self):
        # Проверяем, что карта сайта отдаётся и содержит alternate с ru/en
        resp = self.client.get("/sitemap.xml")
        assert resp.status_code == 200
        xml = resp.content.decode()

        # Hreflang для языков
        assert 'hreflang="ru"' in xml
        assert 'hreflang="en"' in xml

        # Обычно ссылки в sitemap полные, на домене из django_site
        assert "example.com" in xml
