from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _t
from parler.models import TranslatableModel, TranslatedFields

# CKEditor 5 (django-ckeditor-5)
from django_ckeditor_5.fields import CKEditor5Field

import bleach

from app_main.models import SiteSetup

# --- Разрешённый HTML для документов (CKEditor5 + CSP-friendly без inline-стилей/скриптов) ---
BLEACH_ALLOWED_TAGS = {
    # базовые
    "p", "br", "a", "strong", "em", "u", "s", "blockquote", "code", "pre", "hr",
    # списки
    "ul", "ol", "li",
    # заголовки
    "h1", "h2", "h3", "h4", "h5", "h6",
    # таблицы
    "table", "thead", "tbody", "tr", "th", "td",
    # картинки и обёртки, которые часто даёт CKEditor 5
    "img", "figure", "figcaption", "span",
}
BLEACH_ALLOWED_ATTRS = {
    "a": ["href", "rel", "target", "name"],
    "img": ["src", "alt", "title", "width", "height", "class"],
    "figure": ["class"],
    "span": ["class"],
    "p": ["class"],
    "h1": ["class"], "h2": ["class"], "h3": ["class"], "h4": ["class"], "h5": ["class"], "h6": ["class"],
    "table": ["class"],
    "th": ["scope"],
}
BLEACH_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def _substitute_placeholders(raw_html: str) -> str:
    """
    Подстановка маркеров вида [[DOMAIN]] / [[DOMAIN_VIEW]] из SiteSetup.
    Если чего-то нет — оставляем как есть.
    """
    if not raw_html:
        return raw_html
    try:
        setup = SiteSetup.get_solo()
        mapping = {
            "[[DOMAIN]]": (setup.domain or "").strip(),
            "[[DOMAIN_VIEW]]": (setup.domain_view or "").strip(),
        }
        for k, v in mapping.items():
            raw_html = raw_html.replace(k, v)
        return raw_html
    except Exception:
        return raw_html


def sanitize_html(raw_html: str) -> str:
    """
    Чистим HTML от небезопасного, оставляя минимально необходимый набор тегов/атрибутов.
    Без inline-стилей, без скриптов — дружим с CSP.
    """
    if not raw_html:
        return raw_html

    cleaned = bleach.clean(
        raw_html,
        tags=BLEACH_ALLOWED_TAGS,
        attributes=BLEACH_ALLOWED_ATTRS,
        protocols=BLEACH_ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
    # linkify: аккуратно проставит href’ы там, где это уместно; rel/target можно оставлять на совести редактора,
    # а при необходимости дополнить в шаблоне.
    return bleach.linkify(
        cleaned,
        callbacks=[],
        skip_tags=None,
        parse_email=True,
    )


class Document(TranslatableModel):
    """Публикуемые документы сайта (Правила, Политики и т.д.)."""

    # НЕпереводимые
    show_in_site = models.BooleanField(_t("Показывать на сайте"), default=True)
    updated_at = models.DateTimeField(_t("Обновлён"), auto_now=True)

    # Переводимые (тут тело переводим через CKEditor5Field)
    translations = TranslatedFields(
        title=models.CharField(_t("Заголовок"), max_length=200),
        slug=models.SlugField(_t("Ссылка"), max_length=200, blank=True),
        # CKEditor 5: хранится как текст, в админке/формах — виджет редактора
        body=CKEditor5Field(_t("Содержимое"), blank=True, config_name="default"),
    )

    class Meta:
        verbose_name = _t("Документ")
        verbose_name_plural = _t("Документы")

    def __str__(self):
        return self.safe_translation_getter("title", any_language=True) or f"Document #{self.pk}"

    def render_body(self) -> str:
        """
        Готовое к выводу тело:
        1) подставляем плейсхолдеры типа [[DOMAIN]];
        2) пропускаем через санитайзер.
        """
        raw = self.safe_translation_getter("body", default="", any_language=False) or ""
        with_vars = _substitute_placeholders(raw)
        return sanitize_html(with_vars)

    def render_title(self) -> str:
        title = self.safe_translation_getter("title", default="", any_language=False) or ""
        return title.strip()
