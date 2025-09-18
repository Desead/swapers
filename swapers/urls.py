from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.utils import translation
from django.conf import settings
from django.conf.urls.static import static
from app_main.views_security import csp_report
from app_main.views import dashboard, account_settings, account_delete, robots_txt, account_email_resend
from django.utils.translation import get_supported_language_variant

# --- i18n ---
from django.conf.urls.i18n import i18n_patterns
from django.views.i18n import set_language

# берём префикс через сервис (с кэшем); если таблицы ещё нет — падаем в "admin"
try:
    from app_main.services.site_setup import get_admin_prefix

    ADMIN_PREFIX = get_admin_prefix()
except Exception:
    ADMIN_PREFIX = "admin"


def _admin_redirect_view(request):
    """Редирект со стандартного /admin/ на актуальный путь из настроек (302)."""
    try:
        from app_main.services.site_setup import get_admin_prefix
        admin_prefix = get_admin_prefix()
    except Exception:
        admin_prefix = "admin"
    return redirect(f"/{admin_prefix}/", permanent=False)  # 302


def _root_redirect_to_language(request):
    lang = translation.get_language_from_request(request) or translation.get_language() or "ru"
    try:
        lang = get_supported_language_variant(lang, strict=False)  # 'ru-RU' -> 'ru'
    except LookupError:
        lang = "ru"
    return redirect(f"/{lang}/", permanent=False)


urlpatterns = [
    # Админка без языкового префикса
    path(f"{ADMIN_PREFIX}/", admin.site.urls),
    path("admin/", _admin_redirect_view),

    # Сервисные эндпоинты без i18n
    path("csp-report/", csp_report, name="csp_report"),
    path("i18n/setlang/", set_language, name="set_language"),
    # path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),

    path("robots.txt", robots_txt, name="robots_txt"),
]

# Rosetta — удобнее прятать за DEBUG
if settings.DEBUG:
    urlpatterns += [path("rosetta/", include("rosetta.urls"))]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Корень сайта — редирект на активный язык. Должен идти ПОСЛЕ всех сервисных путей.
urlpatterns += [
    path("", _root_redirect_to_language, name="root_redirect"),
]

# Пользовательские маршруты — под префиксом языка
urlpatterns += i18n_patterns(
    # allauth (вход/регистрация/сброс)
    path("accounts/", include("allauth.urls")),

    # ЛК
    path("dashboard/", dashboard, name="dashboard"),
    path("account/settings/", account_settings, name="account_settings"),
    path("account/delete/", account_delete, name="account_delete"),
    path("account/email/resend/", account_email_resend, name="account_email_resend"),

    # Остальной сайт
    path("", include("app_main.urls")),
)
