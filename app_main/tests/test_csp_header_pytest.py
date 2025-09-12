# app_main/tests/test_csp_header_pytest.py
def test_csp_header_on_dashboard(staff_client):
    r = staff_client.get("/dashboard/", follow=True)  # следуем на /ru/... или /en/...
    assert r.status_code == 200
    csp = r.headers.get("Content-Security-Policy") or r.headers.get("Content-Security-Policy-Report-Only")
    assert csp and "default-src" in csp and "'self'" in csp
