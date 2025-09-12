from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import logout
from .forms import AccountForm
from django.utils.translation import gettext_lazy as _
import re
from django.http import HttpResponse
from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers

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
@vary_on_headers("Host")
@cache_page(60 * 60)  # 1 hour
def robots_txt(request):
    setup = SiteSetup.get_solo()
    base = (getattr(setup, "robots_txt", "") or "")

    # Нормализуем переносы строк
    text = base.replace("\r\n", "\n").replace("\r", "\n")

    # Убираем уже вписанные (вручную) строки Sitemap:, чтобы не дублировать
    lines = [ln for ln in text.split("\n") if not re.match(r"(?i)^\s*sitemap\s*:", ln)]

    # Текущая схема/хост
    scheme = "https" if request.is_secure() else "http"
    host = request.get_host() or setup.domain
    sitemap_url = f"{scheme}://{host}/sitemap.xml"

    lines.append(f"Sitemap: {sitemap_url}")

    body = "\n".join(ln for ln in lines if ln.strip()).strip() + "\n"
    return HttpResponse(body, content_type="text/plain; charset=utf-8")
