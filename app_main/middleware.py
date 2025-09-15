from __future__ import annotations

import json
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from django.utils.translation import gettext_lazy as _

from django_otp import devices_for_user

from .services.site_setup import get_site_setup

# --- Referral cookie constants ---
REF_COOKIE_NAME = "ref_sig"
REF_COOKIE_SALT = "partners.referral"


class Admin2FARedirectMiddleware(MiddlewareMixin):
    """
    Требуем настроить 2FA для сотрудников, заходящих в админку.
    Если у пользователя-стофа НЕТ ни одного подтверждённого OTP-устройства —
    мягко уводим на мастер подключения 2FA.
    """
    TWOFA_PREFIX = "/security/2fa/"

    def process_request(self, request):
        path = request.path
        setup = get_site_setup()
        admin_prefix = f"/{setup.admin_path.strip('/')}/"

        # игнорируем не-админку и сам мастер 2FA
        if not path.startswith(admin_prefix) or path.startswith(self.TWOFA_PREFIX):
            return None

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_staff:
            return None

        # если есть хотя бы одно подтверждённое устройство — пускаем
        try:
            if any(devices_for_user(user, confirmed=True)):
                return None
        except Exception:
            # в сомнительных случаях не блокируем
            return None

        return HttpResponseRedirect(f"{self.TWOFA_PREFIX}setup/")


class AdminSessionTimeoutMiddleware:
    """
    Автовыход из админки по бездействию.
    Работает только под путём админки (динамически из SiteSetup.admin_path).

    - Если admin_session_timeout_min > 0: выходим при простое > N минут.
      Также обновляем срок жизни сессии на N минут при каждом запросе в админке.
    - Если admin_session_timeout_min == 0: не выходим по простою (ставим cookie-сессию до закрытия браузера).
    """
    SESSION_KEY_LAST = "admin_last_activity"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        setup = get_site_setup()
        admin_prefix = f"/{setup.admin_path.strip('/')}/"

        # Применяемся только в зоне админки и только для аутентифицированных.
        if request.path.startswith(admin_prefix) and getattr(request, "user", None) and request.user.is_authenticated:
            minutes = int(getattr(setup, "admin_session_timeout_min", 10) or 0)

            if minutes <= 0:
                # Нет авто-логаута по простою — cookie-сессия (до закрытия браузера)
                request.session.set_expiry(0)
            else:
                now = timezone.now()
                last_ts = request.session.get(self.SESSION_KEY_LAST)
                last = None
                if last_ts:
                    try:
                        last = timezone.datetime.fromisoformat(last_ts)
                        if timezone.is_naive(last):
                            last = timezone.make_aware(last, timezone.utc)
                    except Exception:
                        last = None

                if last is not None:
                    delta = (now - last).total_seconds()
                    if delta > minutes * 60:
                        logout(request)
                        messages.warning(request, _("Сессия админки завершена из-за отсутствия активности."))
                        login_url = f"{admin_prefix}login/?next={quote(request.get_full_path())}"
                        from django.shortcuts import redirect
                        return redirect(login_url)

                # Обновляем «последнюю активность» и продлеваем срок жизни сессии
                request.session[self.SESSION_KEY_LAST] = now.isoformat()
                request.session.set_expiry(minutes * 60)

        return self.get_response(request)


class ReferralAttributionMiddleware:
    """
    Ставит подписанную referral-cookie при наличии ?ref=XXXX в URL.

    Политика: Last click wins (переписывает предыдущую метку до регистрации).
    Срок: из SiteSetup.ref_attribution_window_days (0 => не ставим persistent cookie).
    Всегда записывает данные и в сессию на текущий заход (на случай моментальной регистрации).

    Удаление: после успешной привязки в сигнале ставим флаг session['ref_cookie_delete']=True,
              и middleware удаляет ТОЛЬКО нашу ref-cookie.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        setup = get_site_setup()
        ref_code = request.GET.get("ref", "").strip()

        # читаем окно атрибуции гарантированно «свежее», обходя кэш настроек
        try:
            window_days = int(
                type(setup).objects.only("ref_attribution_window_days").get(pk=setup.pk).ref_attribution_window_days or 0
            )
        except Exception:
            window_days = int(getattr(setup, "ref_attribution_window_days", 90) or 0)

        to_set_cookie = None
        now = timezone.now()

        # если в URL есть реф-код — пишем в сессию и (опционально) в persistent cookie
        if ref_code:
            payload = {
                "code": ref_code,
                "first_seen": now.isoformat(),
                "landing": request.build_absolute_uri()[:500],
            }
            request.session["referral_pending"] = payload
            # Last click wins: просто перезапишем cookie, если окно > 0
            if window_days > 0:
                to_set_cookie = payload

        response = self.get_response(request)

        # установить подписанную cookie (после ответа), если нужно
        if to_set_cookie is not None:
            max_age = window_days * 86400
            response.set_signed_cookie(
                REF_COOKIE_NAME,
                json.dumps(to_set_cookie, ensure_ascii=False),
                salt=REF_COOKIE_SALT,
                max_age=max_age,
                samesite="Lax",
                secure=bool(getattr(settings, "SESSION_COOKIE_SECURE", False)),
                httponly=True,
            )

        # удалить ref-cookie по флагу из сессии (после успешной регистрации)
        if request.session.pop("ref_cookie_delete", False):
            # Django 5.x: delete_cookie не принимает secure=
            response.delete_cookie(
                REF_COOKIE_NAME,
                samesite="Lax",
            )
            request.session.pop("referral_pending", None)

        return response

    @staticmethod
    def read_cookie(request) -> dict | None:
        try:
            raw = request.get_signed_cookie(REF_COOKIE_NAME, default=None, salt=REF_COOKIE_SALT)
            if not raw:
                return None
            return json.loads(raw)
        except Exception:
            return None
