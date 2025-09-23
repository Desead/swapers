# app_main/templatetags/placeholders.py
from __future__ import annotations

import re
from django import template
from django.conf import settings
from django.utils.safestring import mark_safe

from app_main.models import SiteSetup  # путь как у тебя в проекте

register = template.Library()

_PLACEHOLDER_RE = re.compile(r"\[\[(?P<name>[A-Z0-9_]+)\]\]")


def _mapping():
    setup = SiteSetup.get_solo()
    # схема для ссылок
    scheme = "https" if getattr(setup, "use_https_in_meta", False) or not settings.DEBUG else "http"
    domain = (setup.domain or "").strip()
    domain_view = (setup.domain_view or domain).strip()
    origin = f"{scheme}://{domain}" if domain else ""

    return {
        "DOMAIN": domain,
        "DOMAIN_VIEW": domain_view,
        "SCHEME": scheme,
        "ORIGIN": origin,
        # при желании легко расширить:
        # "CONTACT_EMAIL_CLIENTS": setup.contact_email_clients or "",
        # "CONTACT_EMAIL_PARTNERS": setup.contact_email_partners or "",
    }


@register.simple_tag(takes_context=True)
def render_placeholders(context, html: str | None):
    """
    Заменяет в html плейсхолдеры вида [[NAME]] значениями из SiteSetup.
    Не трогает неизвестные плейсхолдеры — оставляет как есть.
    """
    if not html:
        return ""
    table = _mapping()

    def repl(m: re.Match):
        name = m.group("name")
        return table.get(name, m.group(0))  # неизвестные — не трогаем

    return mark_safe(_PLACEHOLDER_RE.sub(repl, html))
