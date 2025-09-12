from django import template
from django.conf import settings

register = template.Library()

@register.simple_tag(takes_context=True)
def switch_lang_url(context, lang_code: str) -> str:
    """
    Возвращает текущий путь, но с другим языковым префиксом.
    Пример: /ru/dashboard/ -> /en/dashboard/
    Если префикса нет — просто добавляет /<lang>/ в начало.
    """
    request = context.get("request")
    if not request:
        return f"/{lang_code}/"

    path = request.path or "/"
    parts = path.split("/", 2)  # ["", "ru", "rest"] или ["", ""]

    langs = {code for code, _ in getattr(settings, "LANGUAGES", [])}
    rest = ""
    if len(parts) > 2 and parts[1] in langs:
        rest = parts[2]  # было /<lang>/<rest>
    else:
        rest = parts[1] if len(parts) > 1 else ""

    if rest:
        return f"/{lang_code}/{rest}"
    return f"/{lang_code}/"
