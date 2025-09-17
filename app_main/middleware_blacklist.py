from django.http import HttpResponse
from django.conf import settings
from ipware import get_client_ip
from axes.helpers import get_client_username

from app_main.models_security import BlocklistEntry


class BlacklistBlockMiddleware:
    """
    Мгновенно блокирует POST на страницы логина (/accounts/login/, /admin/login/),
    если email/IP/пользователь в BlocklistEntry.
    Срабатывает до Axes / allauth.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and self._is_login_path(request.path):
            if self._is_blocked(request):
                status = getattr(settings, "AXES_HTTP_RESPONSE_CODE", 403) or 403
                return HttpResponse("Forbidden", status=status)
        return self.get_response(request)

    @staticmethod
    def _is_login_path(path: str) -> bool:
        # локализованные пути тоже попадают (…/ru/accounts/login/)
        return path.endswith("/accounts/login/") or path.endswith("/admin/login/")

    @staticmethod
    def _extract_login(request):
        field = getattr(settings, "AXES_USERNAME_FORM_FIELD", "username")
        return (
            request.POST.get("email")
            or request.POST.get(field)
            or request.POST.get("login")
            or get_client_username(request)
        )

    def _is_blocked(self, request) -> bool:
        # 1) IP
        ip, _ = get_client_ip(request)
        if ip and BlocklistEntry.objects.filter(is_active=True, ip_address=ip).exists():
            return True
        # 2) Email (логин)
        email = self._extract_login(request)
        if email and BlocklistEntry.objects.filter(is_active=True, email=email).exists():
            return True
        # 3) Уже аутентифицированный пользователь
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            if BlocklistEntry.objects.filter(is_active=True, user=user).exists():
                return True
        return False
