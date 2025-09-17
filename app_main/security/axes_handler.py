# app_main/security/axes_handler.py
from axes.handlers.database import AxesDatabaseHandler
from django.conf import settings
from ipware import get_client_ip
from axes.helpers import get_client_username

from app_main.models_security import BlocklistEntry


def _extract_login_from_request(request, credentials):
    field = getattr(settings, "AXES_USERNAME_FORM_FIELD", "username")
    if credentials:
        for key in ("email", "username", field, "login"):
            if credentials.get(key):
                return credentials[key]
    if request is not None:
        return (
            request.POST.get("email")
            or request.POST.get(field)
            or request.POST.get("login")
            or get_client_username(request)
        )
    return None


def _is_in_blocklist(request, credentials) -> bool:
    # 1) IP
    ip, _ = get_client_ip(request)
    if ip and BlocklistEntry.objects.filter(is_active=True, ip_address=ip).exists():
        return True
    # 2) Email (логин)
    email = _extract_login_from_request(request, credentials)
    if email and BlocklistEntry.objects.filter(is_active=True, email=email).exists():
        return True
    # 3) Уже аутентифицированный пользователь
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        if BlocklistEntry.objects.filter(is_active=True, user=user).exists():
            return True
    return False


class BlacklistAwareAxesHandler(AxesDatabaseHandler):
    """
    Мгновенно блокируем попытку, если email/IP/пользователь в BlocklistEntry.
    Делаем это РАНО (в is_allowed), затем отдаём управление стандартной логике Axes.
    """

    def is_allowed(self, request, credentials: dict | None = None) -> bool:
        # Ранняя проверка чёрного списка — сразу запрещаем
        if _is_in_blocklist(request, credentials):
            return False
        # Иначе — обычная логика Axes (whitelist, locked, и т.д.)
        return super().is_allowed(request, credentials)

    # (Опционально можно оставить, чтобы Axes считал и наш ЧС как «blacklisted»)
    def is_blacklisted(self, request, credentials: dict | None = None) -> bool:
        if _is_in_blocklist(request, credentials):
            return True
        return super().is_blacklisted(request, credentials)
