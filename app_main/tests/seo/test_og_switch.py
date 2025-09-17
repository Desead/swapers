import pytest
from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

# минимальный валидный 1x1 PNG
_PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx\x9cc``\x00\x00\x00\x02\x00\x01"
    b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
)

@override_settings(DEBUG=False)
@pytest.mark.django_db
def test_og_disabled_hides_tags(site_setup, get_home_html):
    site_setup.og_enabled = False
    site_setup.save(update_fields=["og_enabled"])
    html = get_home_html()
    assert 'property="og:title"' not in html.lower()
    assert 'property="og:description"' not in html.lower()
    assert 'property="og:type"' not in html.lower()
    assert 'property="og:url"' not in html.lower()
    assert 'property="og:image"' not in html.lower()



@override_settings(DEBUG=False)
@pytest.mark.django_db
def test_og_enabled_shows_tags(site_setup, get_home_html):
    site_setup.og_enabled = True
    site_setup.og_title = "Swapers — обмен криптовалют"
    site_setup.og_description = "Быстрый и безопасный обмен."
    site_setup.og_type_default = "website"
    site_setup.og_image.save("og.png", SimpleUploadedFile("og.png", _PNG_1x1, content_type="image/png"))
    site_setup.save()

    html = get_home_html()
    low = html.lower()
    assert 'property="og:title"' in low
    assert 'property="og:description"' in low
    assert 'property="og:type"' in low
    assert 'property="og:url"' in low
    assert 'property="og:image"' in low

