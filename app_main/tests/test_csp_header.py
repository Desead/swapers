# app_main/tests/test_csp_header.py
from django.test import Client
from app_main.tests.base import FastTestCase

class CSPHeaderTests(FastTestCase):
    def test_csp_header_present_on_dashboard(self):
        c = Client()
        r = c.get("/dashboard/", follow=True)  # ← идём до конечной страницы (логин)
        self.assertTrue(
            ("Content-Security-Policy-Report-Only" in r.headers)
            or ("Content-Security-Policy" in r.headers)
        )

    def test_csp_header_present_on_admin_login(self):
        c = Client()
        # Получим реальный префикс админки и проверим финальную страницу логина
        from app_main.services.site_setup import get_admin_prefix
        admin_prefix = get_admin_prefix().strip("/")
        r = c.get(f"/{admin_prefix}/login/", follow=True)
        self.assertTrue(
            ("Content-Security-Policy-Report-Only" in r.headers)
            or ("Content-Security-Policy" in r.headers)
        )
