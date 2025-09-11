# app_main/middleware_csp_fallback.py
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings

# Соответствие директив -> имя настройки в Django settings
_DIRECTIVES = {
    "default-src": "CSP_DEFAULT_SRC",
    "script-src": "CSP_SCRIPT_SRC",
    "style-src": "CSP_STYLE_SRC",
    "img-src": "CSP_IMG_SRC",
    "font-src": "CSP_FONT_SRC",
    "connect-src": "CSP_CONNECT_SRC",
    "frame-ancestors": "CSP_FRAME_ANCESTORS",
    "form-action": "CSP_FORM_ACTION",
    "base-uri": "CSP_BASE_URI",
    "object-src": "CSP_OBJECT_SRC",
}

class CSPHeaderEnsureMiddleware(MiddlewareMixin):
    """
    Если заголовок CSP по какой-то причине не установлен django-csp,
    выставляем его из настроек CSP_* (Report-Only или Enforce).
    Не трогаем ответ, если заголовок уже есть.
    """
    def process_response(self, request, response):
        # Если уже есть любой вариант заголовка — не вмешиваемся
        if ("Content-Security-Policy" in response.headers
                or "Content-Security-Policy-Report-Only" in response.headers):
            return response

        # Собираем политику из настроек
        parts = []
        for directive, setting_name in _DIRECTIVES.items():
            sources = getattr(settings, setting_name, ())
            if sources:
                parts.append(f"{directive} {' '.join(sources)}")

        if parts:
            header_name = (
                "Content-Security-Policy-Report-Only"
                if getattr(settings, "CSP_REPORT_ONLY", False)
                else "Content-Security-Policy"
            )
            response.headers[header_name] = "; ".join(parts)

        return response
