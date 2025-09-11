"""
URL configuration for NewUser project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponsePermanentRedirect
from app_main.views_security import csp_report

# берём префикс через сервис (с кэшем); если таблицы ещё нет — падаем в "admin"
try:
    from app_main.services.site_setup import get_admin_prefix

    ADMIN_PREFIX = get_admin_prefix()
except Exception:
    ADMIN_PREFIX = "admin"

from app_main.views import dashboard, account_settings, account_delete


def _admin_redirect_view(request):
    """Редирект со стандартного /admin/ на актуальный путь из настроек (301)."""
    target = f"/{ADMIN_PREFIX}/"
    return HttpResponsePermanentRedirect(target)


urlpatterns = [
    # Админка по динамическому пути
    path(f"{ADMIN_PREFIX}/", admin.site.urls),

    # allauth (вход/регистрация/сброс)
    path("accounts/", include("allauth.urls")),

    # ЛК
    path("dashboard/", dashboard, name="dashboard"),
    path("account/settings/", account_settings, name="account_settings"),
    path("account/delete/", account_delete, name="account_delete"),

    path("csp-report/", csp_report, name="csp_report"),

    # Остальной сайт
    path("", include("app_main.urls")),
]
