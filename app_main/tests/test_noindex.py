# tests/test_noindex.py
import re
from django.test import TestCase, override_settings
from django.urls import reverse
from app_main.models import SiteSetup

@override_settings(DEBUG=False)
class TestNoIndex(TestCase):
    @classmethod
    def setUpTestData(cls):
        # гарантируем наличие singleton
        SiteSetup.get_solo()

    def set_block(self, value: bool):
        setup = SiteSetup.get_solo()
        setup.block_indexing = value
        setup.save(update_fields=["block_indexing", "updated_at"])
        return setup

    def test_middleware_sets_header_when_blocking(self):
        self.set_block(True)
        resp = self.client.get(reverse("home"))
        assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"

    def test_middleware_no_header_when_not_blocking(self):
        self.set_block(False)
        resp = self.client.get(reverse("home"))
        assert resp.headers.get("X-Robots-Tag") is None

    def test_robots_txt_disallow_all_when_blocking(self):
        self.set_block(True)
        resp = self.client.get(reverse("robots_txt"))
        body = resp.content.decode("utf-8").strip()
        assert body == "User-agent: *\nDisallow: /"

    def test_robots_txt_normal_when_not_blocking(self):
        setup = self.set_block(False)
        resp = self.client.get(reverse("robots_txt"))
        body = resp.content.decode("utf-8")
        # нет глобального Disallow: /
        assert not re.search(r"(?mi)^\s*Disallow:\s*/\s*$", body)
        # есть служебные запреты
        assert f"Disallow: /{setup.admin_path.strip('/')}/" in body
        assert "Disallow: /accounts/" in body

    def test_robots_switches_without_manual_cache_clear(self):
        # 1) сначала нормальный режим
        setup = self.set_block(False)
        url = reverse("robots_txt")
        r1 = self.client.get(url).content.decode()

        # 2) включаем запрет индексации и проверяем, что ответ изменился
        self.set_block(True)
        r2 = self.client.get(url).content.decode()

        assert r1 != r2
        assert r2.strip() == "User-agent: *\nDisallow: /"
