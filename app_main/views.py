from __future__ import annotations
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import logout
from .forms import AccountForm
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from django.http import HttpResponse
from django.contrib.sites.models import Site
from django.core.cache import cache
import re
from django.contrib.sitemaps.views import sitemap as django_sitemap
from app_main.sitemaps import I18nStaticSitemap

from .models import SiteSetup

_OUTLINK_SALT = "outlinks.v1"
_ALLOWED_SCHEMES = {"http", "https", "mailto", "tg", "tel"}


@require_GET
@vary_on_headers("Accept-Language")
def home(request):
    setup = SiteSetup.get_solo()

    if setup.maintenance_mode:
        # Отдаём 503, чтобы поисковики не считали сайт «упавшим» навсегда
        resp = render(request, "maintenance.html", status=503)
        resp["Retry-After"] = "3600"  # можно подстроить (в секундах)
        return resp

    ctx = {
        "main_h1": setup.main_h1,
        "main_subtitle": setup.main_subtitle,
    }
    return render(request, "home.html", ctx)


@login_required
def dashboard(request):
    # ссылка вида https://site.tld/?ref=CODE
    ref_link = None
    if getattr(request.user, "referral_code", ""):
        base = request.build_absolute_uri("/")
        ref_link = f"{base}?ref={request.user.referral_code}"
    return render(request, "dashboard.html", {
        "user_obj": request.user,
        "ref_link": ref_link,
    })


@login_required
def account_settings(request):
    user = request.user
    if request.method == "POST":
        form = AccountForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, _("Настройки сохранены."))
            return redirect("account_settings")
        messages.error(request, _("Проверьте форму — есть ошибки."))
    else:
        form = AccountForm(instance=user)

    return render(request, "account/account_settings.html", {"form": form})


@login_required
def account_delete(request):
    """
    Самоудаление аккаунта с подтверждением пароля.
    Удаление суперпользователя запрещено из интерфейса.
    """
    user = request.user

    if user.is_superuser:
        messages.error(request, _("Удаление суперпользователя запрещено из интерфейса. Используйте админку."))
        return redirect("account_settings")

    if request.method == "POST":
        password = request.POST.get("password", "")
        confirm = request.POST.get("confirm_text", "").strip()

        if confirm != "DELETE":
            messages.error(request, _("Подтверждение не совпало. Введите слово DELETE."))
            return redirect("account_delete")

        if not user.check_password(password):
            messages.error(request, _("Неверный пароль."))
            return redirect("account_delete")

        email = user.email
        logout(request)
        user.delete()
        messages.success(request, _("Аккаунт удалён."))
        return redirect("home")

    return render(request, "account/account_delete.html")


@require_GET
@vary_on_headers("Host")
@cache_page(60 * 60)  # 1 hour
def robots_txt(request):
    setup = SiteSetup.get_solo()

    # Схема зафиксирована как прод: всегда HTTPS
    scheme = "https" if not settings.DEBUG else "http"

    # Хост: сперва django.contrib.sites, потом SiteSetup.domain, потом Host, потом localhost
    try:
        site_domain = (Site.objects.get_current(request).domain or "").strip().strip("/")
    except Exception:
        site_domain = ""
    raw_host = (request.get_host() or "").strip().strip("/").split(":", 1)[0]
    host = site_domain or (setup.domain or "").strip().strip("/") or raw_host or "localhost"

    # Кэш-ключ (версионированный)
    cache_key = f"robots:prod:v1:{host}"
    cached = cache.get(cache_key)
    if cached is not None:
        return HttpResponse(cached, content_type="text/plain; charset=utf-8")

    # База из админки, но без любых строк 'Sitemap:'
    base = (setup.robots_txt or "")
    base = base.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln for ln in base.split("\n") if ln.strip()]
    lines = [ln for ln in lines if not re.match(r"(?i)^\s*sitemap\s*:", ln)]

    # Гарантированные запреты служебных путей
    admin_path = (setup.admin_path or "admin").strip("/")
    must_have = {
        f"disallow: /{admin_path}/": f"Disallow: /{admin_path}/",
        "disallow: /accounts/": "Disallow: /accounts/",
    }
    existing_lower = {ln.strip().lower() for ln in lines}
    for key_lower, canonical in must_have.items():
        if key_lower not in existing_lower:
            lines.append(canonical)

    # Ровно одна строка Sitemap (в конце)
    lines.append(f"Sitemap: {scheme}://{host}/sitemap.xml")

    body = "\n".join(lines) + "\n"
    cache.set(cache_key, body, 60 * 60)
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


def sitemap_xml(request):
    """
    Обёртка над стандартной вьюхой карт: форсируем протокол через атрибут Sitemap.
    """
    setup = SiteSetup.get_solo()
    protocol = "https" if bool(getattr(setup, "use_https_in_meta", False)) else "http"

    sm = I18nStaticSitemap()
    sm.protocol = protocol  # <-- ВАЖНО: выставляем протокол здесь

    return django_sitemap(request, sitemaps={"static": sm})
