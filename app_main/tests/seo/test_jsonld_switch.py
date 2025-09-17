import pytest
from django.test import override_settings

@override_settings(DEBUG=False)
@pytest.mark.django_db
def test_jsonld_disabled_no_script(site_setup, get_home_html):
    site_setup.jsonld_enabled = False
    site_setup.save(update_fields=["jsonld_enabled"])
    html = get_home_html()
    assert 'type="application/ld+json"' not in html.lower()

@override_settings(DEBUG=False)
@pytest.mark.django_db
def test_jsonld_enabled_has_script(site_setup, get_home_html):
    site_setup.jsonld_enabled = True
    site_setup.save(update_fields=["jsonld_enabled"])
    html = get_home_html()
    assert 'type="application/ld+json"' in html.lower()
