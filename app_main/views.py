from __future__ import annotations
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import logout
from .forms import AccountForm
from django.utils.translation import gettext_lazy as _
import re
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.contrib.sites.models import Site
from django.conf import settings
from django.views.decorators.http import require_POST
from django.core.cache import cache
from django.urls import NoReverseMatch
from allauth.account.models import EmailAddress
from urllib.parse import urlencode
from allauth.account.views import SignupView
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.urls import reverse
from .models import SiteSetup
from .models_monitoring import Monitoring
from django.db.models import Case, When, Value, IntegerField
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.views.decorators.vary import vary_on_headers
from django.utils.translation import get_language

from .models_documents import Document

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

    monitorings = (
        Monitoring.objects
        .filter(is_active=True)
        .annotate(
            is_best=Case(
                When(name__icontains="bestchange", then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by("-is_best", "number", "id")  # Bestchange всегда первый, затем по порядку
    )
    ctx = {
        "main_h1": setup.safe_translation_getter("main_h1", any_language=True) or "",
        "main_subtitle": setup.safe_translation_getter("main_subtitle", any_language=True) or "",
        "monitorings": monitorings,
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
    return True @ require_GET


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


class SignupOrLoginRedirectView(SignupView):
    """
    Если при регистрации указан e-mail существующего пользователя,
    перенаправляем на страницу логина и подставляем этот e-mail.
    Во всех остальных случаях оставляем стандартное поведение allauth.
    """

    def post(self, request, *args, **kwargs):
        email = (request.POST.get("email") or "").strip()

        # Если поле email присутствует и такой пользователь уже есть — уводим на логин.
        if email:
            User = get_user_model()
            if User._default_manager.filter(email__iexact=email).exists():
                messages.info(
                    request,
                    _("Этот e-mail уже зарегистрирован. Войдите в аккаунт, используя его.")
                )
                login_url = reverse("account_login")
                query = urlencode({"email": email})
                return redirect(f"{login_url}?{query}")

        # Иначе обычный флоу регистрации allauth
        return super().post(request, *args, **kwargs)


# Примитивная сигнатура бота по User-Agent
_BOT_UA_RE = re.compile(
    r"(?:bot|crawler|spider|scrapy|httpclient|libwww|curl|wget|"
    r"python-requests|httpx|java|okhttp|go-http|feed|uptime|monitor|"
    r"checker|analy|validator|scan|pingdom|datadog|newrelic)",
    re.I,
)


def _client_ip(request) -> str:
    xff = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return xff or request.META.get("REMOTE_ADDR", "") or ""


def _looks_like_bot(request) -> bool:
    # В разработке и для тест-клиента не блокируем
    if settings.DEBUG:
        return False
    ua = (request.META.get("HTTP_USER_AGENT") or "").strip()
    if not ua:
        return True  # пустой UA — почти всегда бот
    if ua.lower() == "testclient":
        return False
    return bool(_BOT_UA_RE.search(ua))


def _rate_limited(mon_id: int, ip: str) -> bool:
    """
    Рейт-лимит по одному мониторингу с одного IP:
    не более N кликов за окно W секунд.
    Можно переопределить через settings.MONITORING_GO_GUARD.
    """
    conf = getattr(settings, "MONITORING_GO_GUARD", {})
    per_min = int(conf.get("RATE_LIMIT_PER_MIN", 10))  # по умолчанию 10/мин
    window = int(conf.get("RATE_LIMIT_WINDOW", 60))  # окно 60 сек
    if per_min <= 0:
        return False

    key = f"mon_go:{mon_id}:{ip}"
    try:
        fresh = cache.add(key, 1, timeout=window)  # True если ключ новый
        if fresh:
            return False
        cnt = cache.incr(key)
        return cnt > per_min
    except Exception:
        # если кэш недоступен — не лочим клики
        return False


def _passes_guard(request, mon_id: int) -> bool:
    conf = getattr(settings, "MONITORING_GO_GUARD", {})
    if not conf.get("ENABLED", True):
        return True
    if settings.DEBUG:
        return True

    ip = _client_ip(request)
    if _looks_like_bot(request):
        return False
    if _rate_limited(mon_id, ip):
        return False
    return True


@require_GET
def monitoring_go(request, pk: int):
    """
    Редирект на партнёра с учётом включённости, защитой от ботов и логированием клика.
    """
    mon = get_object_or_404(Monitoring, pk=pk, is_active=True)
    target = (mon.link or "").strip()

    # Пустая ссылка — тихо 204 (как у тебя было)
    if not target:
        return HttpResponse(status=204)

    # Гарантируем https://, если схема не указана
    if not re.match(r"^https?://", target, re.IGNORECASE):
        target = "https://" + target

    # Защита: боты/дудос → молча игнорируем (204)
    if not _passes_guard(request, mon.id):
        return HttpResponse(status=204)

    # Логирование клика (твоя логика register_click)
    try:
        mon.register_click()
        # Если нужно — можно дополнительно логировать IP/UA/Referer/язык:
        # ip = _client_ip(request)
        # ua = request.META.get("HTTP_USER_AGENT", "")
        # ref = request.META.get("HTTP_REFERER", "")
        # lang = getattr(request, "LANGUAGE_CODE", "")
        # ts = timezone.now()
    except Exception:
        # не мешаем пользователю даже если счётчик не сохранился
        pass

    # Временный редирект на партнёрскую ссылку
    return redirect(target)


@require_GET
@vary_on_headers("Accept-Language")
def documents_list(request):
    # Показываем только опубликованные; без «дыр» по переводам:
    docs = []
    for d in Document.objects.filter(is_published=True).order_by("order", "id"):
        title = d.safe_translation_getter("title", default=None, any_language=False)
        if title:
            docs.append(d)

    ctx = {"docs": docs}
    return render(request, "docs/list.html", ctx)


@require_GET
@vary_on_headers("Accept-Language")
def document_detail(request, pk: int):
    doc = get_object_or_404(Document, pk=pk, is_published=True)
    # если нет перевода для текущего языка — 404 (поведение как у других частей сайта)
    title = doc.safe_translation_getter("title", default=None, any_language=False)
    if not title:
        # можно сделать редирект на /docs/ или 404; выберем 404
        raise Http404("Document has no translation for current language")
    ctx = {"doc": doc}
    return render(request, "docs/detail.html", ctx)
