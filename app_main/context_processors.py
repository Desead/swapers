from __future__ import annotations

import json
from typing import Dict
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.utils import translation, timezone

from .services.site_setup import get_site_setup


def site_settings(request):
    """
    Возвращает объект SiteSetup (через кэш) в шаблоны.
    Пример: {{ site_setup.admin_path }}
    """
    return {"site_setup": get_site_setup()}


def _split_lang_from_path(path: str) -> tuple[str | None, str]:
    """
    Возвращает (lang, tail) где lang — префикс языка из settings.LANGUAGES,
    а tail — оставшаяся часть пути с ведущим '/' (или '/' если пусто).
    """
    codes = {code.split("-")[0] for code, _ in settings.LANGUAGES}
    s = path or "/"
    s = "/" + s.lstrip("/")
    parts = s.lstrip("/").split("/", 1)
    maybe_lang = parts[0] if parts else ""
    if maybe_lang in codes:
        tail = "/" + (parts[1] if len(parts) == 2 else "")
        tail = tail if tail != "" else "/"
        return maybe_lang, tail
    return None, s


def _abs_url(request, raw: str | None, *, force_scheme: str | None = None) -> str | None:
    """
    Делает абсолютный URL из относительного (MEDIA/STATIC) или возвращает исходный,
    при необходимости подменяя схему (http/https).
    """
    if not raw:
        return None
    parts = urlsplit(raw)
    if parts.scheme and parts.netloc:
        # уже абсолютный
        if force_scheme and parts.scheme != force_scheme:
            parts = parts._replace(scheme=force_scheme)
            return urlunsplit(parts)
        return raw
    scheme = force_scheme or request.scheme
    return f"{scheme}://{request.get_host()}{raw}"


def _media_abs(request, filefield, *, force_scheme: str | None = None) -> str | None:
    """
    Безопасно получить абсолютный URL для Image/FileField:
    - не трогаем .url, если файла нет (нет .name) → None
    - при наличии .url переводим его в абсолютный с нужной схемой
    """
    if not filefield:
        return None
    name = getattr(filefield, "name", "")
    if not name:
        return None
    try:
        raw = filefield.url  # может бросить исключение, если файла нет
    except Exception:
        return None
    return _abs_url(request, raw, force_scheme=force_scheme)


def seo_meta(request) -> Dict[str, object]:
    """
    Единый контекст: SEO/OG/Twitter/JSON-LD + favicon/logo + canonical/hreflang + статус работы.
    Безопасен к отсутствию переводов (django-parler).
    """
    setup = get_site_setup()

    # текущий язык и «хвост» пути
    cur_lang, tail = _split_lang_from_path(request.path_info)
    if not cur_lang:
        cur_lang = (translation.get_language() or settings.LANGUAGE_CODE).split("-")[0]

    # безопасный доступ к переводимым полям SiteSetup
    def _tr(field: str, default: str = "") -> str:
        # Если у модели есть parler-метод — используем его,
        # иначе обычный getattr с дефолтом.
        if hasattr(setup, "safe_translation_getter"):
            val = setup.safe_translation_getter(
                field,
                default=None,
                language_code=cur_lang,
                any_language=True,  # взять любой доступный перевод, если текущего нет
            )
            return val if val not in (None, "") else default
        return getattr(setup, field, default)

    # схема для мета (уважаем настройку в SiteSetup)
    scheme = "https" if getattr(setup, "use_https_in_meta", False) else request.scheme
    host = request.get_host()

    # hreflang: абсолютные URL для каждого языка
    hreflangs: Dict[str, str] = {}
    for code, _name in settings.LANGUAGES:
        short = code.split("-")[0]
        alt_path = f"/{short}{'' if tail == '/' else tail}/".replace("//", "/")
        if tail.endswith("/"):
            alt_path = f"/{short}{tail}"
        hreflangs[short] = f"{scheme}://{host}{alt_path}"

    # canonical — текущий язык + текущий «хвост» без query
    canonical_path = f"/{cur_lang}{tail}"
    CANONICAL_URL = f"{scheme}://{host}{canonical_path}"

    # Медиа (favicon/logo/OG/Twitter)
    OG_IMAGE_URL = _media_abs(request, getattr(setup, "og_image", None), force_scheme=scheme)
    TW_IMAGE_URL = _media_abs(request, getattr(setup, "twitter_image", None), force_scheme=scheme) or OG_IMAGE_URL
    LOGO_URL = _media_abs(request, getattr(setup, "logo", None), force_scheme=scheme)
    FAVICON_URL = _media_abs(request, getattr(setup, "favicon", None), force_scheme=scheme)

    # JSON-LD -> строки (для <script type="application/ld+json">)
    JSONLD_ORG = json.dumps(getattr(setup, "jsonld_organization", {}) or {}, ensure_ascii=False)
    JSONLD_WEBSITE = json.dumps(getattr(setup, "jsonld_website", {}) or {}, ensure_ascii=False)

    # SEO базовые (переводимые)
    SEO_TITLE = _tr("seo_default_title", setup.domain_view)
    SEO_DESCRIPTION = _tr("seo_default_description", "")
    SEO_KEYWORDS = _tr("seo_default_keywords", "")

    # Open Graph
    OG_LOCALE_ALTS = [x.strip() for x in (getattr(setup, "og_locale_alternates", "") or "").split(",") if x.strip()]

    # -------- статус работы (UTC) --------
    def _is_open_now() -> bool:
        if getattr(setup, "maintenance_mode", False):
            return False
        now_utc = timezone.now()
        now_t = now_utc.time()
        wd = now_utc.weekday()  # 0=Mon ... 6=Sun
        suf = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][wd]
        open_t = getattr(setup, f"open_time_{suf}", None)
        close_t = getattr(setup, f"close_time_{suf}", None)
        if not open_t or not close_t or open_t == close_t:
            return False
        if open_t < close_t:
            return open_t <= now_t < close_t
        # ночной интервал через полночь
        return now_t >= open_t or now_t < close_t

    IS_OPEN_NOW = _is_open_now()

    return {
        # Базовое
        "CUR_LANG": cur_lang,
        "SITE_NAME": setup.domain_view,
        "CANONICAL_URL": CANONICAL_URL,
        "HREFLANGS": hreflangs,
        "BLOCK_INDEXING": bool(getattr(setup, "block_indexing", False)),

        # SEO
        "SEO_TITLE": SEO_TITLE,
        "SEO_DESCRIPTION": SEO_DESCRIPTION,
        "SEO_KEYWORDS": SEO_KEYWORDS,

        # Брендинг
        "FAVICON_URL": FAVICON_URL,
        "LOGO_URL": LOGO_URL,

        # Open Graph
        "OG_ENABLED": bool(getattr(setup, "og_enabled", True)),
        "OG_TYPE": getattr(setup, "og_type_default", "website"),
        "OG_TITLE": _tr("og_title", SEO_TITLE),
        "OG_DESCRIPTION": _tr("og_description", SEO_DESCRIPTION),
        "OG_IMAGE_URL": OG_IMAGE_URL,
        "OG_IMAGE_ALT": _tr("og_image_alt", setup.domain_view),
        "OG_IMAGE_WIDTH": getattr(setup, "og_image_width", 0),
        "OG_IMAGE_HEIGHT": getattr(setup, "og_image_height", 0),
        "OG_SITE_NAME": setup.domain_view,
        "OG_LOCALE": getattr(setup, "og_locale_default", "ru_RU"),
        "OG_LOCALE_ALTS": OG_LOCALE_ALTS,

        # Twitter
        "TW_ENABLED": bool(getattr(setup, "twitter_cards_enabled", True)),
        "TW_CARD": getattr(setup, "twitter_card_type", "summary_large_image"),
        "TW_SITE": (getattr(setup, "twitter_site", "") or "").lstrip("@"),
        "TW_CREATOR": (getattr(setup, "twitter_creator", "") or "").lstrip("@"),
        "TW_IMAGE_URL": TW_IMAGE_URL,

        # JSON-LD
        "JSONLD_ENABLED": bool(getattr(setup, "jsonld_enabled", True)),
        "JSONLD_ORG": JSONLD_ORG,
        "JSONLD_WEBSITE": JSONLD_WEBSITE,

        # Вставка в <head> с CSP-нонсом (фильтр добавит nonce в script/style)
        "HEAD_INJECT_HTML": getattr(setup, "head_inject_html", ""),

        # Статус работы
        "MAINTENANCE_MODE": bool(getattr(setup, "maintenance_mode", False)),
        "IS_OPEN_NOW": IS_OPEN_NOW,
    }
