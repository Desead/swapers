import re
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
def test_og_values_come_from_sitesetup(site_setup, get_home_html):
    site_setup.og_enabled = True
    site_setup.og_title = "Custom Title"
    site_setup.og_description = "Custom Description"
    site_setup.og_type_default = "article"
    site_setup.og_image.save("og.png", SimpleUploadedFile("og.png", _PNG_1x1, content_type="image/png"))
    site_setup.save()

    html = get_home_html()

    def has_meta(prop, substr):
        pat = rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\'][^"\']*{re.escape(substr)}'
        return re.search(pat, html, flags=re.IGNORECASE) is not None

    assert has_meta("og:title", "Custom Title")
    assert has_meta("og:description", "Custom Description")
    assert has_meta("og:type", "article")
    assert has_meta("og:image", ".png")
