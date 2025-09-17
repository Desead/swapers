import pytest
from django.test import override_settings

@override_settings(DEBUG=False)
@pytest.mark.django_db
def test_jsonld_contains_valid_json(site_setup, get_home_html, extract_jsonld):
    site_setup.jsonld_enabled = True
    # подменим дефолтные фабрики/значения при необходимости
    org = site_setup.jsonld_organization or {}
    org["name"] = "Swapers Org"
    site_setup.jsonld_organization = org
    site_setup.save()

    html = get_home_html()
    data = extract_jsonld(html)
    assert data is not None, "JSON-LD блок не найден"
    # минимум, что проверяем для валидности schema.org
    assert "@context" in data
    assert data["@context"].startswith("https://schema.org")
    # допускаем, что у вас может рендериться Organization или WebSite
    assert "@type" in data
    assert data["@type"] in {"Organization", "WebSite"}
