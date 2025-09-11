import time
from django.utils.deprecation import MiddlewareMixin
from django.http import HttpResponseRedirect
from django.conf import settings
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp import devices_for_user


class ReferralMiddleware:
    """
    Если пришли с ?ref=CODE — кладём код в сессию.
    allauth заберёт его в сигнале user_signed_up.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        code = request.GET.get("ref")
        if code:
            try:
                request.session["ref_code"] = code
            except Exception:
                pass
        return self.get_response(request)


def _admin_prefix() -> str:
    try:
        from app_main.services.site_setup import get_admin_prefix
        return f"/{get_admin_prefix().strip('/')}/"
    except Exception:
        return "/admin/"

class Admin2FARedirectMiddleware(MiddlewareMixin):
    """
    Политика:
    - Если staff идёт в админку и У НЕГО НЕТ подтверждённого OTP-устройства → уводим на мастер /security/2fa/setup/.
    - Если устройство есть, но текущая сессия не верифицирована → НЕ редиректим, пускаем в админку,
      и там OTPAdminSite сам покажет форму логина с запросом 2FA.
    - Idle-таймаут: при превышении порога просто снимаем отметку verified и
      ДЕЛАЕМ мягкий redirect на тот же URL, чтобы этот же запрос уже пошёл как «неверифицированный»
      и админка показала ввод кода. На /security/2fa/... не вмешиваемся.
    """
    _TWOFA_PREFIX = "/security/2fa/"
    _SESSION_LAST_SEEN_KEY = "admin_last_seen"
    _SESSION_THROTTLE_SEC = 10  # чтобы не писать в сессию на каждый запрос

    def _user_has_confirmed_device(self, user) -> bool:
        try:
            return any(devices_for_user(user, confirmed=True))
        except Exception:
            return False

    def process_request(self, request):
        path = request.path

        # Не трогаем путь мастера 2FA
        if path.startswith(self._TWOFA_PREFIX):
            return None

        # Работаем только для путей админки
        if not path.startswith(_admin_prefix()):
            return None

        user = getattr(request, "user", None)
        if not (user and user.is_authenticated and user.is_staff):
            return None

        # --- Idle-таймаут: сначала проверяем и, если надо, снимаем верификацию и перезагружаем страницу ---
        timeout = int(getattr(settings, "ADMIN_OTP_IDLE_TIMEOUT_SECONDS", 0) or 0)
        if timeout > 0 and hasattr(request, "session"):
            now = int(time.time())
            sess = request.session
            last_seen = int(sess.get(self._SESSION_LAST_SEEN_KEY, 0) or 0)

            if last_seen and (now - last_seen > timeout):
                # истёк простой — очищаем отметку verified и обновим last_seen после прохождения 2FA
                try:
                    sess.pop(DEVICE_ID_SESSION_KEY, None)
                    sess.pop(self._SESSION_LAST_SEEN_KEY, None)
                    sess.modified = True
                except Exception:
                    pass
                # мягко перезагружаем ту же страницу, чтобы текущий запрос уже шёл как "неверифицированный"
                return HttpResponseRedirect(request.get_full_path())

            # обновим last_seen с троттлингом
            if now - last_seen >= self._SESSION_THROTTLE_SEC:
                sess[self._SESSION_LAST_SEEN_KEY] = now
                sess.modified = True

        # --- Требование подключить устройство ТОЛЬКО если его нет ---
        is_verified = getattr(user, "is_verified", None)
        if not callable(is_verified) or not is_verified():
            # если устройства нет — уводим на мастер подключения
            if not self._user_has_confirmed_device(user):
                return HttpResponseRedirect(f"{self._TWOFA_PREFIX}setup/")
            # если устройство есть — не мешаем: админка сама запросит OTP
            return None

        return None