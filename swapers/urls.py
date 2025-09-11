from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponsePermanentRedirect
from django.shortcuts import redirect
from django.utils import translation

from app_main.views_security import csp_report

# берём префикс через сервис (с кэшем); если таблицы ещё нет — падаем в "admin"
try:
    from app_main.services.site_setup import get_admin_prefix
    ADMIN_PREFIX = get_admin_prefix()
except Exception:
    ADMIN_PREFIX = "admin"

from app_main.views import dashboard, account_settings, account_delete

# --- i18n ---
from django.conf.urls.i18n import i18n_patterns
from django.views.i18n import set_language, JavaScriptCatalog


def _admin_redirect_view(request):
    """Редирект со стандартного /admin/ на актуальный путь из настроек (301/302)."""
    try:
        from app_main.services.site_setup import get_admin_prefix
        admin_prefix = get_admin_prefix()  # читаем актуальный префикс «на лету»
    except Exception:
        admin_prefix = "admin"
    # 302, чтобы браузер не кэшировал жёстко, если меняешь префикс
    return HttpResponsePermanentRedirect(f"/{admin_prefix}/")


def _root_redirect_to_language(request):
    """
    Редиректит с '/' на '/<lang>/' согласно приоритету:
    cookie -> сессия -> заголовки браузера -> LANGUAGE_CODE.
    """
    lang = translation.get_language_from_request(request) or translation.get_language()
    lang = (lang or "ru").split("-")[0]  # нормализация кода вроде 'en-us' -> 'en'
    return redirect(f"/{lang}/", permanent=False)


urlpatterns = [
    # Админка по динамическому пути (без языкового префикса)
    path(f"{ADMIN_PREFIX}/", admin.site.urls),
    path("admin/", _admin_redirect_view),  # редирект со стандартного '/admin/'

    # Отчёты CSP (сервисный endpoint — без префикса)
    path("csp-report/", csp_report, name="csp_report"),

    # i18n служебные маршруты (без префикса)
    path("i18n/setlang/", set_language, name="set_language"),
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),

    # Корень сайта редиректит на актуальный язык
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

    # Остальной сайт
    path("", include("app_main.urls")),
)
