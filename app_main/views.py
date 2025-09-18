from __future__ import annotations
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import logout
from .forms import AccountForm
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from django.core.cache import cache
import re
from django.http import HttpResponse
from django.urls import reverse
from django.contrib.sites.models import Site
from django.utils.translation import override
from django.conf import settings
import xml.etree.ElementTree as ET

from django.views.decorators.http import require_POST
from django.core.cache import cache
from django.urls import NoReverseMatch
from allauth.account.models import EmailAddress

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
        required_word = "DELETE"
        confirm = (request.POST.get("confirm_text", "") or "").strip()

        if confirm.upper() != required_word:
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
def robots_txt(request):
    setup = SiteSetup.get_solo()

    # Если включён глобальный запрет – отдаём жесткий Disallow: /
    if setup.block_indexing:
        ver = int(setup.updated_at.timestamp()) if setup.updated_at else 0
        cache_key = f"robots:block:v1:{ver}"
        cached = cache.get(cache_key)
        if cached is not None:
            return HttpResponse(cached, content_type="text/plain; charset=utf-8")
        body = "User-agent: *\nDisallow: /\n"
        cache.set(cache_key, body, 60 * 60)  # 1 час
        return HttpResponse(body, content_type="text/plain; charset=utf-8")

    # --- дальше остаётся твоя текущая логика формирования robots ---
    # (ниже только правим ключ кэша, чтобы он менялся при изменении настроек)
    scheme = "https" if not settings.DEBUG else "http"
    try:
        site_domain = (Site.objects.get_current(request).domain or "").strip().strip("/")
    except Exception:
        site_domain = ""
    raw_host = (request.get_host() or "").strip().strip("/").split(":", 1)[0]
    host = site_domain or (setup.domain or "").strip().strip("/") or raw_host or "localhost"

    # В ключ добавим updated_at, чтобы кэш точно сбрасывался после сохранения настроек
    ver = int(setup.updated_at.timestamp()) if setup.updated_at else 0
    cache_key = f"robots:prod:v2:{host}:{ver}"

    cached = cache.get(cache_key)
    if cached is not None:
        return HttpResponse(cached, content_type="text/plain; charset=utf-8")

    base = (setup.robots_txt or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln for ln in base.split("\n") if ln.strip()]
    lines = [ln for ln in lines if not re.match(r"(?i)^\s*sitemap\s*:", ln)]

    admin_path = (setup.admin_path or "admin").strip("/")
    must_have = {
        f"disallow: /{admin_path}/": f"Disallow: /{admin_path}/",
        "disallow: /accounts/": "Disallow: /accounts/",
    }
    existing_lower = {ln.strip().lower() for ln in lines}
    for key_lower, canonical in must_have.items():
        if key_lower not in existing_lower:
            lines.append(canonical)

    body = "\n".join(lines) + "\n"
    cache.set(cache_key, body, 60 * 60)
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


# === ДОБАВИТЬ (рядом с вашими вьюхами, до использования)
def _send_confirmation_email(request, user) -> bool:
    """
    Возвращает True, если попытались отправить письмо.
    Email берём из user.email; письмо отправится только если адрес ещё не подтверждён.
    """
    email = (user.email or "").strip()
    if not email:
        return False
    # add_email создаст/обновит EmailAddress и при confirm=True отправит письмо.
    EmailAddress.objects.add_email(request, user, email, confirm=True)
    return True


@login_required
@require_POST
def account_email_resend(request):
    """
    Повторная отправка письма подтверждения для текущего пользователя.
    Ограничение: не чаще 1 раза в минуту (серверный кэш).
    """
    user = request.user

    # Если уже подтверждён — не отправляем
    try:
        if user.email:
            try:
                eaddr = EmailAddress.objects.get(user=user, email=user.email)
            except EmailAddress.DoesNotExist:
                eaddr = None
            if eaddr and eaddr.verified:
                messages.info(request, _("Ваш e-mail уже подтверждён."))
                try:
                    return redirect("account_settings")
                except NoReverseMatch:
                    return redirect("account_email_verification_sent")
    except Exception:
        pass  # не мешаем флоу из-за вспомогательных ошибок

    # Троттлинг: 1 запрос в минуту
    cache_key = f"email_confirm_resend:{user.pk}"
    # cache.add вернёт False, если ключ уже есть (то есть недавно жали кнопку)
    if not cache.add(cache_key, "1", timeout=60):
        messages.warning(request, _("Слишком часто. Попробуйте ещё раз через минуту."))
        return redirect("account_email_verification_sent")

    # Отправляем письмо
    _send_confirmation_email(request, request.user)

    if getattr(user, "email", None):
        messages.success(
            request,
            _("Ссылка для подтверждения отправлена на %(email)s.") % {"email": user.email},
        )
    else:
        messages.success(request, _("Ссылка для подтверждения отправлена."))

    return redirect("account_email_verification_sent")
