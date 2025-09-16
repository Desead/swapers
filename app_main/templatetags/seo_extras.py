# app_main/templatetags/seo_extras.py
from __future__ import annotations
import re
from django import template

register = template.Library()

# Находим открывающие теги <script ...> и <style ...> (без учёта регистра)
_TAG_RE = re.compile(r"<(script|style)(\s[^>]*)?>", re.IGNORECASE)

@register.filter
def csp_nonce(html: str, nonce: str | None) -> str:
    """
    Вставляет nonce="..." в теги <script> и <style>, если его там нет.
    Ничего не меняет, если html пустой или nonce отсутствует.
    """
    if not html or not nonce:
        return html or ""

    def _repl(m: re.Match) -> str:
        tag = m.group(1)
        attrs = m.group(2) or ""
        # если nonce уже есть — не дублируем
        if "nonce=" in attrs.lower():
            return f"<{tag}{attrs}>"
        return f'<{tag}{attrs} nonce="{nonce}">'

    return _TAG_RE.sub(_repl, html)
