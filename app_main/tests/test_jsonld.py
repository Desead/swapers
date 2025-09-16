# app_main/tests/test_jsonld.py
import json
import re
from urllib.parse import urlparse

import pytest
from django.utils.encoding import force_str

from app_main.models import SiteSetup


JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _extract_jsonld(response_content: bytes):
    """Вернёт список dict'ов из всех <script type="application/ld+json">."""
    html = force_str(response_content, encoding="utf-8", strings_only=False, errors="strict")
    blocks = []
    for m in JSONLD_RE.finditer(html):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            # иногда страницы могут отдавать массив блоков в одном скрипте или один объект
            continue
        if isinstance(data, list):
            blocks.extend([d for d in data if isinstance(d, dict)])
        elif isinstance(data, dict):
            blocks.append(data)
    return blocks


def _find_by_type(blocks, typ: str):
    """Найти первый JSON-LD блок с @type == typ."""
    for b in blocks:
        if isinstance(b, dict) and b.get("@type") == typ:
            return b
    return None


def _is_abs_https(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme == "https" and bool(p.netloc)
    except Exception:
        return False


def _is_abs_http_or_https(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except Exception:
        return False


@pytest.mark.django_db
def test_jsonld_org_and_website_present_on_home(client):
    setup = SiteSetup.get_solo()
    setup.jsonld_enabled = True
    setup.save()

    resp = client.get("/", follow=True)
    assert resp.status_code == 200

    blocks = _extract_jsonld(resp.content)
    assert blocks, "Ожидались JSON-LD блоки на главной"

    org = _find_by_type(blocks, "Organization")
    site = _find_by_type(blocks, "WebSite")

    assert org is not None, "Должен быть JSON-LD блок Organization"
    assert site is not None, "Должен быть JSON-LD блок WebSite"

    # Базовая валидность
    assert org.get("@context") == "https://schema.org"
    assert site.get("@context") == "https://schema.org"

    assert isinstance(org.get("name", ""), str) and org["name"].strip()
    assert isinstance(site.get("name", ""), str) and site["name"].strip()

    assert isinstance(org.get("url", ""), str) and _is_abs_http_or_https(org["url"])
    assert isinstance(site.get("url", ""), str) and _is_abs_http_or_https(site["url"])


@pytest.mark.django_db
def test_jsonld_disabled_removes_blocks(client):
    setup = SiteSetup.get_solo()
    setup.jsonld_enabled = False
    setup.save()

    resp = client.get("/", follow=True)
    assert resp.status_code == 200

    blocks = _extract_jsonld(resp.content)
    # При выключенном флаге сайт-wide JSON-LD не должен отдаваться
    assert blocks == [] or all(b.get("@type") not in {"Organization", "WebSite"} for b in blocks)


@pytest.mark.django_db
def test_jsonld_urls_and_logo_are_https_if_present(client):
    """
    Рекомендуем: абсолютные HTTPS-URL в ключевых полях.
    Если логотип есть, проверяем, что он https; sameAs — хотя бы абсолютные http(s).
    """
    setup = SiteSetup.get_solo()
    setup.jsonld_enabled = True
    # Дефолты у нас уже на https, но на всякий случай убедимся
    org = setup.jsonld_organization or {}
    site = setup.jsonld_website or {}
    if "url" in org:
        org["url"] = org["url"].replace("http://", "https://")
    if "url" in site:
        site["url"] = site["url"].replace("http://", "https://")
    if "logo" in org:
        org["logo"] = org["logo"].replace("http://", "https://")
    setup.jsonld_organization = org
    setup.jsonld_website = site
    setup.save()

    resp = client.get("/", follow=True)
    assert resp.status_code == 200

    blocks = _extract_jsonld(resp.content)
    org_b = _find_by_type(blocks, "Organization")
    site_b = _find_by_type(blocks, "WebSite")
    assert org_b and site_b

    # url должны быть абсолютными https
    assert _is_abs_https(org_b.get("url", "")), "Organization.url должен быть абсолютным https"
    assert _is_abs_https(site_b.get("url", "")), "WebSite.url должен быть абсолютным https"

    # logo (если указан) — абсолютный https
    logo = org_b.get("logo")
    if isinstance(logo, str) and logo:
        assert _is_abs_https(logo), "Organization.logo должен быть абсолютным https"

    # sameAs — список абсолютных http(s) ссылок
    same_as = org_b.get("sameAs", [])
    if isinstance(same_as, list):
        for link in same_as:
            assert isinstance(link, str) and _is_abs_http_or_https(link), "sameAs должен содержать абсолютные URL"
