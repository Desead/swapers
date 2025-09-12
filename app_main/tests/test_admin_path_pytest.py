# app_main/tests/test_admin_path_pytest.py
from django.urls import reverse

def test_admin_index_uses_dynamic_path(site_setup, client):
    # текущий путь в моделях = "admin"
    url = reverse("admin:index")
    assert url == f"/{site_setup.admin_path}/"
    # страница открывается (302 на логин — норм без авторизации)
    r = client.get(url, follow=False)
    assert r.status_code in (200, 302, 401)
