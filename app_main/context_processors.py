from __future__ import annotations
import json
from typing import Dict
from urllib.parse import urlsplit, urlunsplit
from django.conf import settings
from django.urls import reverse
from django.utils import translation, timezone
from django.utils.translation import get_language

from app_main.models_documents import Document
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
        if hasattr(setup, "safe_translation_getter"):
            val = setup.safe_translation_getter(
                field, default=None, language_code=cur_lang, any_language=True
            )
            return val if val not in (None, "") else default
        return getattr(setup, field, default)

    # --- включённые на сайте языки (выбор в админке) ---
    def _enabled_lang_codes() -> list[str]:
        """
        Читаем SiteSetup.site_enabled_languages.
        Допускаем форматы: list/tuple, JSON-строка, строка "ru,en,...".
        Если поле пустое/невалидное — берём все языки из settings.LANGUAGES.
        """
        raw = getattr(setup, "site_enabled_languages", None)

        def _norm_list(x) -> list[str]:
            if x is None:
                return []
            if isinstance(x, (list, tuple)):
                return [str(i).split("-")[0].lower() for i in x]
            if isinstance(x, str):
                s = x.strip()
                # возможно, это JSON
                if s and s[0] in "[{" and s[-1] in "]}":
                    try:
                        data = json.loads(s)
                        if isinstance(data, (list, tuple)):
                            return [str(i).split("-")[0].lower() for i in data]
                    except Exception:
                        pass
                # обычная comma-separated
                return [part.strip().split("-")[0].lower() for part in s.split(",") if part.strip()]
            return []

        enabled_raw = _norm_list(raw)
        all_codes_in_settings = [code.split("-")[0].lower() for code, _ in settings.LANGUAGES]

        if enabled_raw:
            want = set(enabled_raw)
            result = [c for c in all_codes_in_settings if c in want]
            return result or all_codes_in_settings  # если не совпало — показываем все
        return all_codes_in_settings

    LANGS_ENABLED = _enabled_lang_codes()

    # схема для мета (уважаем настройку в SiteSetup)
    scheme = "https" if getattr(setup, "use_https_in_meta", False) else request.scheme
    host = request.get_host()

    # hreflang: абсолютные URL только для включённых языков
    hreflangs: Dict[str, str] = {}
    for code, _name in settings.LANGUAGES:
        short = code.split("-")[0].lower()
        if short not in LANGS_ENABLED:
            continue
        alt_path = f"/{short}{'' if tail == '/' else tail}/".replace("//", "/")
        if tail.endswith("/"):
            alt_path = alt_path[:-1]  # не удваиваем слэш в конце
        hreflangs[short] = f"{scheme}://{host}{alt_path}"

    # меню языков для UI (только включённые)
    lang_name_by_code = {code.split("-")[0].lower(): name for code, name in settings.LANGUAGES}
    LANG_MENU = []
    for short in LANGS_ENABLED:
        alt_path = f"/{short}{'' if tail == '/' else tail}/".replace("//", "/")
        if tail.endswith("/"):
            alt_path = alt_path[:-1]
        LANG_MENU.append(
            {
                "code": short,
                "name": lang_name_by_code.get(short, short.upper()),
                "url": f"{scheme}://{host}{alt_path}",
                "active": short == cur_lang,
            }
        )

    # canonical
    CANONICAL_URL = f"{scheme}://{host}{request.path}"

    # favicon/logo absolute
    FAVICON_URL = _media_abs(request, getattr(setup, "favicon", None), force_scheme=scheme)
    LOGO_URL = _media_abs(request, getattr(setup, "logo", None), force_scheme=scheme)

    # Twitter image absolute
    TW_IMAGE_URL = _media_abs(request, getattr(setup, "twitter_image", None), force_scheme=scheme)

    # JSON-LD (берём как есть)
    JSONLD_ORG = getattr(setup, "jsonld_organization", None)
    JSONLD_WEBSITE = getattr(setup, "jsonld_website", None)

    # SEO тайтлы/описания
    SEO_TITLE = _tr("seo_default_title", getattr(setup, "domain_view", ""))
    SEO_DESCRIPTION = _tr("seo_default_description", "")
    SEO_KEYWORDS = _tr("seo_default_keywords", "")
    COPYRIGHT_FIELD = _tr("copyright_field", "")

    # Open Graph
    OG_IMAGE_URL = _media_abs(request, getattr(setup, "og_image", None), force_scheme=scheme)
    OG_LOCALE_ALTS = [x.strip() for x in (getattr(setup, "og_locale_alternates", "") or "").split(",") if x.strip()]

    # -------- статус работы (UTC) --------
    def _is_open_now() -> bool:
        if getattr(setup, "maintenance_mode", False):
            return False
        now_utc = timezone.now()
        now_t = now_utc.time()
        wd = now_utc.weekday()  # 0=Mon . 6=Sun
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

    # --- Документы для меню и футера (фолбэк на RU) ---
    try:
        cur = (get_language() or settings.LANGUAGE_CODE).split("-")[0]
    except Exception:
        cur = (translation.get_language() or settings.LANGUAGE_CODE).split("-")[0]

    # ищем, какой код считать «русским»
    ru_like = "ru"
    for code, _name in getattr(settings, "LANGUAGES", (("ru", "Russian"),)):
        c = code.lower().split("-")[0]
        if c == "ru":
            ru_like = code
            break

    docs = []
    for d in Document.objects.filter(show_in_site=True):
        # title/slug для текущего языка, затем фолбэк на RU, иначе пропускаем
        title = d.safe_translation_getter("title", default=None, language_code=cur, any_language=False) \
                or d.safe_translation_getter("title", default=None, language_code=ru_like, any_language=False)
        slug = d.safe_translation_getter("slug", default=None, language_code=cur, any_language=False) \
               or d.safe_translation_getter("slug", default=None, language_code=ru_like, any_language=False)
        if not title or not slug:
            continue
        docs.append({"title": title, "href": reverse("document_view", kwargs={"slug": slug})})

    # по названию, чтобы везде одинаково
    try:
        docs.sort(key=lambda x: x["title"].lower())
    except Exception:
        pass

    # --- /документы ---

    return {
        "DOCS_MENU": docs,

        # Базовое
        "CUR_LANG": cur_lang,
        "SITE_NAME": getattr(setup, "domain_view", ""),
        "CANONICAL_URL": CANONICAL_URL,
        "HREFLANGS": hreflangs,
        "BLOCK_INDEXING": bool(getattr(setup, "block_indexing", False)),

        # Языки
        "LANGS_ENABLED": LANGS_ENABLED,  # список кодов включённых языков
        "LANGS_ALL": [code.split("-")[0].lower() for code, _ in settings.LANGUAGES],
        "LANG_MENU": LANG_MENU,  # элементы для переключателя в UI

        # SEO
        "SEO_TITLE": SEO_TITLE,
        "SEO_DESCRIPTION": SEO_DESCRIPTION,
        "SEO_KEYWORDS": SEO_KEYWORDS,
        "COPYRIGHT_FIELD": COPYRIGHT_FIELD,

        # Брендинг
        "FAVICON_URL": FAVICON_URL,
        "LOGO_URL": LOGO_URL,

        # Open Graph
        "OG_ENABLED": bool(getattr(setup, "og_enabled", True)),
        "OG_TYPE": getattr(setup, "og_type_default", "website"),
        "OG_TITLE": _tr("og_title", SEO_TITLE),
        "OG_DESCRIPTION": _tr("og_description", SEO_DESCRIPTION),
        "OG_IMAGE_URL": OG_IMAGE_URL,
        "OG_IMAGE_ALT": _tr("og_image_alt", getattr(setup, "domain_view", "")),
        "OG_IMAGE_WIDTH": getattr(setup, "og_image_width", 0),
        "OG_IMAGE_HEIGHT": getattr(setup, "og_image_height", 0),
        "OG_SITE_NAME": getattr(setup, "domain_view", ""),
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
