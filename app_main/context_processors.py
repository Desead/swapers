from .services.site_setup import get_site_setup
from typing import Dict
from django.conf import settings
from django.utils import translation

def site_settings(request):
    """
    Возвращает объект SiteSetup (через кэш) в шаблоны.
    Пример использования: {{ site_setup.admin_path }}
    """
    return {"site_setup": get_site_setup()}



def _split_lang_from_path(path: str) -> tuple[str | None, str]:
    """
    Возвращает (lang, tail) где lang — префикс языка из settings.LANGUAGES
    (например 'ru' или 'en'), а tail — оставшаяся часть пути С '/' в начале
    или просто '/' если «хвоста» нет.
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

def seo_meta(request) -> Dict[str, str | Dict[str, str]]:
    """
    В шаблоны кладём:
      - CANONICAL_URL — абсолютный URL текущей страницы с языковым префиксом
      - HREFLANGS — { 'ru': url, 'en': url, ... } для всех языков
      - CUR_LANG — текущий язык (двухбуквенный)
    """
    cur_lang, tail = _split_lang_from_path(request.path_info)
    # если префикса нет — возьмём активный язык (en, ru, …)
    if not cur_lang:
        cur_lang = (translation.get_language() or settings.LANGUAGE_CODE).split("-")[0]

    # абсолютные URL для каждого языка
    hreflangs: Dict[str, str] = {}
    for code, _name in settings.LANGUAGES:
        short = code.split("-")[0]
        alt_path = f"/{short}{'' if tail == '/' else tail}/".replace("//", "/")
        # если хвост уже заканчивается '/', не удваиваем:
        if tail.endswith("/"):
            alt_path = f"/{short}{tail}"
        hreflangs[short] = request.build_absolute_uri(alt_path)

    # каноникал — текущий язык + текущий «хвост»
    canonical_path = f"/{cur_lang}{tail}"
    canonical_url = request.build_absolute_uri(canonical_path)

    return {
        "CANONICAL_URL": canonical_url,
        "HREFLANGS": hreflangs,
        "CUR_LANG": cur_lang,
    }
