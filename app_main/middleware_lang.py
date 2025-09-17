from django.conf import settings
from django.utils import translation

class LanguageVariantNormalizeMiddleware:
    """
    Нормализует язык до поддерживаемого варианта (напр. ru-RU -> ru)
    до работы LocaleMiddleware и фиксирует это в ответе (cookie).
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1) нормализуем куку языка
        raw = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME) or request.COOKIES.get("django_language")
        canonical = None
        if raw:
            try:
                canonical = translation.get_supported_language_variant(raw, strict=False)
            except LookupError:
                canonical = "ru"
            # подменяем значение в текущем запросе
            request.COOKIES[settings.LANGUAGE_COOKIE_NAME] = canonical
            request.COOKIES.pop("django_language", None)

        # 2) подчистим заголовок Accept-Language для типичных кейсов
        al = request.META.get("HTTP_ACCEPT_LANGUAGE")
        if al:
            request.META["HTTP_ACCEPT_LANGUAGE"] = al.replace("ru-RU", "ru").replace("ru_RU", "ru")

        response = self.get_response(request)

        # если кука была «не каноничная» — выставим правильную
        if canonical:
            response.set_cookie(
                settings.LANGUAGE_COOKIE_NAME,
                canonical,
                max_age=getattr(settings, "LANGUAGE_COOKIE_AGE", None),
                samesite=getattr(settings, "LANGUAGE_COOKIE_SAMESITE", "Lax"),
                secure=getattr(settings, "LANGUAGE_COOKIE_SECURE", False),
                httponly=False,
                path="/",
            )
        return response
