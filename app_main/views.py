from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import logout
from .forms import AccountForm
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotModified
from django.urls import reverse
from django.utils import timezone
from django.utils.http import http_date, parse_http_date_safe
import hashlib

from .models import SiteSetup


def home(request):
    return render(request, "home.html")


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

    return render(request, "account_settings.html", {"form": form})


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
def robots_txt(request):
    """
    Единый robots.txt:
    - если settings.ALLOW_INDEXING=False → закрываем весь сайт;
    - иначе берём текст из SiteSetup.robots_txt, нормализуем переносы,
      автодобавляем строку Sitemap (если её нет), без дублей;
    - кешируем на 1 час с «версией» по updated_at;
    - выставляем ETag и Last-Modified, поддерживаем 304.
    """
    allow_indexing = bool(getattr(settings, "ALLOW_INDEXING", True))

    # схема/хост
    scheme = request.META.get("HTTP_X_FORWARDED_PROTO") or ("https" if not settings.DEBUG else request.scheme)
    try:
        domain = Site.objects.get_current(request).domain
    except Exception:
        domain = request.get_host()
    sitemap_url = f"{scheme}://{domain}{reverse('sitemap')}"

    # данные настроек
    setup = SiteSetup.get_solo()
    ver = int(setup.updated_at.timestamp()) if setup.updated_at else 0

    cache_key = f"robots_txt::{domain}::{int(allow_indexing)}::{ver}"
    cached = cache.get(cache_key)
    if cached is not None:
        content = cached
    else:
        if not allow_indexing:
            content = "User-agent: *\nDisallow: /\n"
        else:
            base = (setup.robots_txt or "").replace("\r\n", "\n").replace("\r", "\n")
            if not base.endswith("\n"):
                base += "\n"
            # не дублируем Sitemap
            if "sitemap:" not in base.lower():
                base += f"Sitemap: {sitemap_url}\n"
            content = base

        cache.set(cache_key, content, timeout=3600)

    # заголовки кэширования
    last_modified_dt = setup.updated_at or timezone.now()
    last_modified_http = http_date(last_modified_dt.timestamp())
    etag = hashlib.md5(content.encode("utf-8")).hexdigest()

    # условные заголовки → 304
    inm = request.META.get("HTTP_IF_NONE_MATCH")
    ims = request.META.get("HTTP_IF_MODIFIED_SINCE")
    if inm and inm == etag:
        return HttpResponseNotModified()
    if ims:
        try:
            ims_ts = parse_http_date_safe(ims)
            if ims_ts and int(last_modified_dt.timestamp()) <= int(ims_ts):
                return HttpResponseNotModified()
        except Exception:
            pass

    resp = HttpResponse(content, content_type="text/plain; charset=utf-8")
    resp["ETag"] = etag
    resp["Last-Modified"] = last_modified_http
    resp["Cache-Control"] = "public, max-age=3600"
    return resp
