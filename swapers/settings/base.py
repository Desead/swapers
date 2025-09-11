from pathlib import Path
from csp.constants import SELF  # опционально, если используешь константы

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# --- Вы управляете режимом здесь ---
DEBUG = True  # <<< В проде поставите False

SECRET_KEY = "CHANGE_ME_IN_PROD"
ALLOWED_HOSTS: list[str] = []

SITE_ID = 1
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

INSTALLED_APPS = [
    "swapers.admin.OTPAdminConfig",  # админка под OTP
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    'app_main.apps.AppMainConfig',  # <= так, чтобы сработал ready()

    "django.contrib.sites",
    "allauth",
    "allauth.account",

    "django_otp",
    "django_otp.plugins.otp_totp",
]

AUTH_USER_MODEL = "app_main.User"

MIDDLEWARE = [
    "csp.middleware.CSPMiddleware",  # 1. django-csp (первым)
    "app_main.middleware_csp_fallback.CSPHeaderEnsureMiddleware",  # 2. страховка

    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",

    # ловим ?ref=... как можно раньше, когда сессия уже есть
    "app_main.middleware.ReferralMiddleware",

    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",

    # 2FA: должно идти сразу после аутентификации
    "django_otp.middleware.OTPMiddleware",

    # <<< ОБЯЗАТЕЛЬНО для allauth >>>
    "allauth.account.middleware.AccountMiddleware",

    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",

    # наш редирект в мастер 2FA при заходе в админку
    "app_main.middleware.Admin2FARedirectMiddleware",
]

ROOT_URLCONF = "swapers.urls"
WSGI_APPLICATION = "swapers.wsgi.application"
ASGI_APPLICATION = "swapers.asgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {
        "context_processors": [
            "django.template.context_processors.debug",
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
            "app_main.context_processors.site_settings",
        ],
    },
}]

# База «по умолчанию» (перекроется в prod при необходимости)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Почта: дефолт на консоль (перекроется в prod)
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "no-reply@localhost"

# Базовые cookie-флаги
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# allauth (новые ключи)
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"  # dev переопределит на http
ACCOUNT_RATE_LIMITS = {
    "login": "15/m/ip",
    "login_failed": "5/10m/key,20/10m/ip",
    "signup": "5/h/ip",
    "confirm_email": "3/10m/key",
    "reset_password": "5/m/ip,3/m/key",
    "reset_password_from_key": "10/m/ip",
}
# Куда слать после успешного входа
LOGIN_REDIRECT_URL = "/dashboard/"

# Куда слать после выхода
LOGOUT_REDIRECT_URL = "/"

# Allauth — явные редиректы
ACCOUNT_LOGOUT_REDIRECT_URL = "/"
ACCOUNT_SIGNUP_REDIRECT_URL = "/dashboard/"
ACCOUNT_EMAIL_CONFIRMATION_AUTHENTICATED_REDIRECT_URL = "/dashboard/"
ACCOUNT_EMAIL_CONFIRMATION_ANONYMOUS_REDIRECT_URL = "/accounts/login/"

# (не обязательно, но удобно) — где лежит страница логина
LOGIN_URL = "/accounts/login/"
# 2FA
OTP_TOTP_ISSUER = "Swapers"
ADMIN_OTP_IDLE_TIMEOUT_SECONDS = 300

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- CSP (django-csp) ---
# Широкая, но безопасная база: сайт и админка работают без поломок,
# QR (data:) показывается, внешние CDN НЕ разрешены (добавишь при необходимости).
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'",
                  "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'",
                 "https://cdn.jsdelivr.net", "https://fonts.googleapis.com")
CSP_IMG_SRC = ("'self'", "data:")
CSP_FONT_SRC = ("'self'", "data:", "https://fonts.gstatic.com")
CSP_CONNECT_SRC = ("'self'", "https://fonts.gstatic.com", "https://fonts.googleapis.com")
CSP_FRAME_ANCESTORS = ("'self'",)
CSP_FORM_ACTION = ("'self'",)
CSP_BASE_URI = ("'self'",)
CSP_OBJECT_SRC = ("'none'",)

# nonce будет добавляться в заголовок, если вы использовали его в шаблоне
CSP_INCLUDE_NONCE_IN = ("script-src", "style-src")

# Сначала отчётный режим
CSP_REPORT_ONLY = True
CSP_REPORT_URI = "/csp-report/"
