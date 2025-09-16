import re
import pytest
from django.urls import reverse

from app_main.models import SiteSetup


def _final_response(client, url):
    # follow=True, чтобы дойти до реальной страницы (учитывая i18n-редиректы)
    resp = client.get(url, follow=True)
    # Если было несколько редиректов — берём последний ответ
    if hasattr(resp, "redirect_chain") and resp.redirect_chain:
        return resp
    return resp


@pytest.mark.django_db
def test_csp_absent_on_admin_login(client):
    """На админке CSP-заголовки отсутствуют (мы их убираем специально)."""
    setup = SiteSetup.get_solo()
    admin_login_url = f"/{setup.admin_path}/login/"
    r = _final_response(client, admin_login_url)
    assert r.status_code in (200, 302)
    hdrs = r.headers
    assert "Content-Security-Policy" not in hdrs
    assert "Content-Security-Policy-Report-Only" not in hdrs


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/accounts/login/", "/ru/accounts/login/"])
def test_csp_relaxed_on_accounts_pages(client, path):
    """
    На allauth-страницах используем relaxed-профиль:
    - НЕТ 'strict-dynamic'
    - ЕСТЬ 'script-src' с 'self'
    - ЕСТЬ 'style-src-attr' 'unsafe-inline'
    """
    r = _final_response(client, path)
    # Бывает 200 сразу, бывает 200 после редиректа на локализованную версию — это ок.
    assert r.status_code in (200, 302)

    csp = r.headers.get("Content-Security-Policy", "") or r.headers.get("Content-Security-Policy-Report-Only", "")
    assert csp, "CSP header must be present on accounts pages"

    assert "script-src" in csp
    assert "'self'" in csp  # разрешаем свои скрипты
    assert "strict-dynamic" not in csp  # relaxed-профиль

    # style-src-attr для инлайн-атрибутов стилей (allauth иногда их использует)
    assert "style-src-attr" in csp and "'unsafe-inline'" in csp


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/", "/ru/"])
def test_csp_strict_on_front_pages(client, path):
    """
    На обычных страницах используем strict-профиль:
    - ЕСТЬ 'strict-dynamic'
    - ЕСТЬ nonce в script-src (вида 'nonce-...')
    - ЕСТЬ style-src-attr 'unsafe-inline' (чтобы не падали style="")
    """
    r = _final_response(client, path)
    assert r.status_code in (200, 302)

    csp = r.headers.get("Content-Security-Policy", "") or r.headers.get("Content-Security-Policy-Report-Only", "")
    assert csp, "CSP header must be present on front pages"

    # strict-dynamic включён
    assert "script-src" in csp and "strict-dynamic" in csp

    # В script-src должен быть nonce (любое значение)
    assert re.search(r"script-src[^;]*'nonce-[A-Za-z0-9_\-]+'", csp), f"Expected nonce in script-src, got: {csp}"

    # Для совместимости с существующей вёрсткой
    assert "style-src-attr" in csp and "'unsafe-inline'" in csp
