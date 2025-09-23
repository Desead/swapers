import re
import urllib.parse as ul
from django.core.files.uploadedfile import SimpleUploadedFile
from app_library.models import BannerAsset
import pytest
from django.urls import reverse

from app_main.models_monitoring import Monitoring


def _get(url, client, follow=False):
    return client.get(url, follow=follow)


@pytest.mark.django_db
def test_go_redirects_to_partner_url(client):
    mon = Monitoring.objects.create(
        name="SomePartner",
        is_active=True,
        link="https://example.com/path?utm=x",
        number=10,
    )
    url = reverse("monitoring_go", args=[mon.id])

    resp = _get(url, client)
    # ожидаем временный редирект
    assert resp.status_code == 302
    # целевой URL должен совпадать
    # (django тест-клиент в resp.url кладёт конечный Location)
    assert resp.url == mon.link


@pytest.mark.django_db
def test_go_404_when_inactive(client):
    mon = Monitoring.objects.create(
        name="Inactive",
        is_active=False,
        link="https://example.com/",
        number=1,
    )
    url = reverse("monitoring_go", args=[mon.id])

    resp = _get(url, client)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_go_204_when_link_empty(client):
    mon = Monitoring.objects.create(
        name="NoLink",
        is_active=True,
        link="",
        number=2,
    )
    url = reverse("monitoring_go", args=[mon.id])

    resp = _get(url, client)
    assert resp.status_code == 204


@pytest.mark.django_db
def test_home_links_use_go_endpoint(client):
    # создаём минимальный светлый баннер (svg подойдёт и проходит валидацию)
    svg = b"<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'></svg>"
    asset = BannerAsset.objects.create(
        name="for-home",
        theme="light",
        file=SimpleUploadedFile("for-home.svg", svg, content_type="image/svg+xml"),
    )

    mon = Monitoring.objects.create(
        name="VisibleOnHome",
        is_active=True,
        link="https://example.com/",
        number=3,
        banner_light_asset=asset,  # <- важно: есть картинка => блок рендерится
    )

    resp = client.get("/", follow=True)
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")

    go_href = reverse("monitoring_go", args=[mon.id])
    pattern = rf'<a[^>]+class="[^"]*\bpartner-badge\b[^"]*"[^>]+href="{re.escape(go_href)}"[^>]*aria-label="{re.escape(mon.name)}"'
    assert re.search(pattern, html), "Ожидалась ссылка на monitoring_go вокруг баннера на главной"
