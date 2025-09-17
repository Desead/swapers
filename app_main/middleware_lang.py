from django.conf import settings
from django.utils import translation

class LanguageVariantNormalizeMiddleware:
    """
    Нормализует язык до поддерживаемого варианта (напр. ru-RU -> ru)
    до работы LocaleMiddleware и правит cookie ТОЛЬКО если было
    реальное изменение (чтобы не перебивать set_language).
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang_cookie_name = getattr(settings, "LANGUAGE_COOKIE_NAME", "django_language")
        original_cookies = dict(request.COOKIES)

        raw = original_cookies.get(lang_cookie_name) or original_cookies.get("django_language")
        canonical = None
        should_write_cookie = False

        if raw:
            try:
                canonical = translation.get_supported_language_variant(raw, strict=False)
            except LookupError:
                canonical = "ru"
            # Нормализуем только если реально отличается (ru-RU -> ru)
            if canonical != raw or (lang_cookie_name not in original_cookies and "django_language" in original_cookies):
                request.COOKIES[lang_cookie_name] = canonical
                request.COOKIES.pop("django_language", None)
                should_write_cookie = True

        # Подчистим заголовок Accept-Language от ru-RU, но не навязываем ru
        al = request.META.get("HTTP_ACCEPT_LANGUAGE")
        if al:
            request.META["HTTP_ACCEPT_LANGUAGE"] = al.replace("ru-RU", "ru").replace("ru_RU", "ru")

        response = self.get_response(request)

        # Если вьюха уже поставила куку языка — не трогаем (важно для set_language)
        if lang_cookie_name in getattr(response, "cookies", {}):
            return response

        # Пишем куку только если действительно нормализовали/мигрировали
        if should_write_cookie and canonical:
            response.set_cookie(
                lang_cookie_name,
                canonical,
                max_age=getattr(settings, "LANGUAGE_COOKIE_AGE", None),
                samesite=getattr(settings, "LANGUAGE_COOKIE_SAMESITE", "Lax"),
                secure=getattr(settings, "LANGUAGE_COOKIE_SECURE", False),
                httponly=False,
                path="/",
            )
        return response
