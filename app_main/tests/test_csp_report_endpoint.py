import json
from django.test import Client
from django.urls import reverse

from app_main.tests.base import FastTestCase  # быстрые хэшеры/почта


class CSPReportEndpointTests(FastTestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("csp_report")

    def test_accepts_application_csp_report_and_logs(self):
        payload = {"csp-report": {"document-uri": "/", "violated-directive": "img-src"}}
        with self.assertLogs("app_main.views_security", level="WARNING") as cm:
            resp = self.client.post(
                self.url,
                data=json.dumps(payload),
                content_type="application/csp-report",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(any("CSP report:" in line for line in cm.output))

    def test_accepts_application_json(self):
        payload = {"csp-report": {"document-uri": "/", "violated-directive": "script-src"}}
        resp = self.client.post(
            self.url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

    def test_handles_bad_payload_gracefully(self):
        resp = self.client.post(
            self.url,
            data="not a json",
            content_type="application/csp-report",
        )
        self.assertEqual(resp.status_code, 200)
