import re
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from app_library.models import BannerAsset
from app_main.models_monitoring import Monitoring


def _svg_file(name: str = "tiny.svg") -> SimpleUploadedFile:
    # Минимальный SVG (валидируется только расширение и размер <= 1 МБ)
    data = b'<svg xmlns="http://www.w3.org/2000/svg" width="88" height="31"></svg>'
    return SimpleUploadedFile(name, data, content_type="image/svg+xml")


def _make_asset(name: str, theme: str) -> BannerAsset:
    return BannerAsset.objects.create(name=name, theme=theme, file=_svg_file(f"{name}.svg"))


def _page(client) -> bytes:
    # Главная у тебя редиректит на /<lang>/ — follow=True
    resp = client.get("/", follow=True)
    assert resp.status_code == 200
    return resp.content


def _partners_html(html: bytes) -> str:
    # Пытаемся вырезать только блок партнёров (если есть класс/идентификатор),
    # иначе парсим всю страницу — тесты всё равно ищут точные alt/title.
    text = html.decode("utf-8", errors="ignore")
    m = re.search(r'<section[^>]*class="[^"]*partner-badges[^"]*"[^>]*>(.*?)</section>', text, re.S | re.I)
    return m.group(1) if m else text


def _find_imgs(block: str):
    # Возвращаем список словарей по <img ...> внутри блока партнёров
    imgs = []
    for m in re.finditer(r'<img\b([^>]*)>', block, re.I):
        attrs = m.group(1)
        def get(attr):
            mm = re.search(fr'{attr}\s*=\s*"([^"]*)"', attrs)
            return mm.group(1) if mm else None
        imgs.append({
            "alt": get("alt"),
            "title": get("title"),
            "src": get("src"),
            "data_theme": get("data-theme"),
        })
    return imgs


@pytest.mark.django_db
def test_bestchange_always_first(client):
    # Активные мониторинги с разными number; BestChange должен быть первым в разметке
    # даже если у него number больше.
    light = _make_asset("light", "light")
    dark = _make_asset("dark", "dark")

    Monitoring.objects.create(name="Gamma", number=0, is_active=True,
                              banner_light_asset=light)
    Monitoring.objects.create(name="bestCHANGE", number=999, is_active=True,
                              banner_dark_asset=dark, banner_light_asset=light)
    Monitoring.objects.create(name="Alpha", number=1, is_active=True,
                              banner_dark_asset=dark)

    html = _partners_html(_page(client))
    imgs = _find_imgs(html)

    # Собираем alt по порядку появления
    alts_in_order = [i["alt"] for i in imgs if i["alt"]]
    assert alts_in_order, "На странице не найдены <img> из блока мониторингов"

    # Первый alt должен относиться к BestChange (регистр не важен)
    assert "bestchange" in alts_in_order[0].lower()


@pytest.mark.django_db
def test_only_active_are_shown(client):
    light = _make_asset("light2", "light")

    Monitoring.objects.create(name="ShownOne", is_active=True,
                              banner_light_asset=light, number=10)
    Monitoring.objects.create(name="HiddenOne", is_active=False,
                              banner_light_asset=light, number=0)

    html = _partners_html(_page(client))
    txt = html.lower()
    assert "shownone".lower() in txt
    assert "hiddenone".lower() not in txt


@pytest.mark.django_db
def test_both_theme_images_present_when_available(client):
    # Если заданы оба ассета — в разметке должны быть две картинки
    light = _make_asset("light3", "light")
    dark = _make_asset("dark3", "dark")

    m = Monitoring.objects.create(
        name="DualTheme",
        is_active=True,
        banner_light_asset=light,
        banner_dark_asset=dark,
        number=5,
    )

    html = _partners_html(_page(client))
    imgs = [i for i in _find_imgs(html) if i["alt"] == m.name]

    # Должны быть две <img>: одна с data-theme="light", другая — "dark"
    themes = sorted([i["data_theme"] for i in imgs if i["data_theme"] in ("light", "dark")])
    assert themes == ["dark", "light"]


@pytest.mark.django_db
def test_single_theme_fallback(client):
    # Если есть только один ассет — в разметке должна быть ровно одна <img> с этим alt
    light = _make_asset("light4", "light")
    m = Monitoring.objects.create(
        name="OnlyLight",
        is_active=True,
        banner_light_asset=light,
        number=7,
    )
    html = _partners_html(_page(client))
    imgs = [i for i in _find_imgs(html) if i["alt"] == m.name]
    assert len(imgs) == 1
    assert imgs[0]["data_theme"] in (None, "light")  # в твоём шаблоне может быть пусто или явно light


@pytest.mark.django_db
def test_alt_and_title_attributes(client):
    light = _make_asset("light5", "light")

    with_title = Monitoring.objects.create(
        name="WithTitle",
        title="Подсказка про мониторинг",
        is_active=True,
        banner_light_asset=light,
        number=1,
    )
    no_title = Monitoring.objects.create(
        name="NoTitle",
        title="",
        is_active=True,
        banner_light_asset=light,
        number=2,
    )

    html = _partners_html(_page(client))
    imgs = _find_imgs(html)

    # ALT = name
    alt_map = {i["alt"]: i for i in imgs if i["alt"]}
    assert with_title.name in alt_map
    assert no_title.name in alt_map

    # TITLE есть, если в модели заполнено; если пусто — атрибут отсутствует или пуст
    assert alt_map[with_title.name]["title"] == with_title.title
    assert not (alt_map[no_title.name].get("title") or "").strip()
