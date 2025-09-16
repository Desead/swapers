# app_main/sitemaps.py
from __future__ import annotations

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from django.utils.translation import override

from app_main.models import SiteSetup  # читаем флажки прямо из БД


class I18nStaticSitemap(Sitemap):
    """
    Статический sitemap с hreflang-альтернативами.
    Протокол берётся из атрибута self.protocol (выставляет наша обёртка sitemap_xml).
    """
    changefreq = "daily"
    priority = 1.0

    def items(self):
        # сюда добавляйте именованные маршруты, которые должны быть в карте
        return ["home"]

    def location(self, item: str) -> str:
        # i18n_patterns: reverse под языком вернёт /ru/... /en/...
        return reverse(item)

    def alternates(self, item, site, protocol):
        """
        Django ожидает список словарей {'lang': 'ru', 'location': 'https://...'}.
        Штатный шаблон сам выведет <xhtml:link .../>.
        """
        setup = SiteSetup.get_solo()
        if not bool(getattr(setup, "hreflang_enabled", True)):
            return []

        langs = [code for code, _ in settings.LANGUAGES]
        xdefault = (getattr(setup, "hreflang_xdefault", "ru") or "ru")
        if xdefault not in langs and langs:
            xdefault = langs[0]

        # посчитаем URL для каждого языка
        per_lang = {}
        for lang in langs:
            with override(lang):
                per_lang[lang] = f"{protocol}://{site.domain}{self.location(item)}"

        alts = [{"lang": lang, "location": per_lang[lang]} for lang in langs]
        # x-default укажем на выбранный язык
        alts.append({"lang": "x-default", "location": per_lang[xdefault]})
        return alts
