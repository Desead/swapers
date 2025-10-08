import os
from pathlib import Path
from django.utils.translation import gettext_lazy as _t
from csp.constants import SELF  # опционально, если используешь константы
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# --- режим ---
DEBUG = True  # <<< В проде поставите False

SECRET_KEY = "CHANGE_ME_IN_PROD"
ALLOWED_HOSTS: list[str] = []

SITE_ID = 1
LANGUAGE_CODE = "ru"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Языки интерфейса (только 'ru' и 'en')
LANGUAGES = [
    ("ru", _t("Russian")),
    ("en", _t("English")),
    ("de", _t("German")),
    ("fr", _t("French")),
    ("es", _t("Spanish")),
    ("it", _t("Italian")),
    ("uk", _t("Ukrainian")),
]

PARLER_DEFAULT_LANGUAGE_CODE = LANGUAGE_CODE
PARLER_LANGUAGES = {
    None: [
        {"code": "ru"},
        {"code": "en"},
        {"code": "de"},
        {"code": "fr"},
        {"code": "es"},
        {"code": "it"},
        {"code": "uk"},
    ],
    "default": {
        "fallbacks": [LANGUAGE_CODE, "en"],  # сначала основной (ru), затем en
        "hide_untranslated": True,  # не показывать пустые переводы
    },
}

LOCALE_PATHS = [BASE_DIR / "locale"]

INSTALLED_APPS = [
    "swapers.admin.OTPAdminConfig",  # админка под OTP
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "app_library.apps.AppLibraryConfig",
    "app_main.apps.AxesRusConfig",  # rate-limit/lockout
    "app_market.apps.AppMarketConfig",
    "app_main.apps.AppMainConfig",  # <= чтобы сработал ready()

    "django.contrib.sites",
    "allauth",
    "allauth.account",

    "django_otp",
    "django_otp.plugins.otp_totp",
    "parler",
    "django_ckeditor_5",
]

AUTH_USER_MODEL = "app_main.User"

MIDDLEWARE = [
    # 0) базовые
    "django.middleware.security.SecurityMiddleware",
    "csp.middleware.CSPMiddleware",

    # 1) сессии → рефералка → нормализация языка → локализация
    "django.contrib.sessions.middleware.SessionMiddleware",
    "app_main.middleware.ReferralAttributionMiddleware",
    "app_main.middleware_lang.LanguageVariantNormalizeMiddleware",
    "django.middleware.locale.LocaleMiddleware",

    # 1.5) Axes — после Session, до Auth
    "app_main.middleware_blacklist.BlacklistBlockMiddleware",
    "axes.middleware.AxesMiddleware",

    # 2) общие
    "django.middleware.common.CommonMiddleware",
    "app_main.middleware_noindex.GlobalNoIndexMiddleware",

    # 3) безопасность форм → аутентификация → OTP → allauth
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "allauth.account.middleware.AccountMiddleware",

    # 4) сообщения/кликджекинг
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",

    # 5) админ-специфика
    "app_main.middleware.Admin2FARedirectMiddleware",
    "app_main.middleware.AdminSessionTimeoutMiddleware",

    "app_main.middleware_csp_fallback.CSPHeaderEnsureMiddleware",
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
            "django.template.context_processors.i18n",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
            "django.template.context_processors.static",
            "django.template.context_processors.media",
            "django.template.context_processors.tz",
            "app_main.context_processors.site_settings",
            "app_main.context_processors.seo_meta",
        ],
    },
}]

# SQLite по умолчанию (prod перекроет)
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# backends — Axes ДО allauth
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# почта дефолтная (dev), prod перекроет
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "no-reply@localhost"

# cookies базово
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# --- allauth (без rate limits) ---
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"  # dev перекроет на http

# Полностью выключаем встроенный троттлинг allauth:
ACCOUNT_RATE_LIMITS = {}  # пусто = нет лимитов; всё делаем через django-axes

# редиректы
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"
ACCOUNT_LOGOUT_REDIRECT_URL = "/"
ACCOUNT_SIGNUP_REDIRECT_URL = "/dashboard/"
ACCOUNT_EMAIL_CONFIRMATION_AUTHENTICATED_REDIRECT_URL = "/dashboard/"
ACCOUNT_EMAIL_CONFIRMATION_ANONYMOUS_REDIRECT_URL = "/accounts/login/"
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

# --- CSP ---
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://fonts.googleapis.com")
CSP_IMG_SRC = ("'self'", "data:")
CSP_FONT_SRC = ("'self'", "data:", "https://fonts.gstatic.com")
CSP_CONNECT_SRC = ("'self'", "https://fonts.gstatic.com", "https://fonts.googleapis.com")
CSP_FRAME_ANCESTORS = ("'self'",)
CSP_FORM_ACTION = ("'self'",)
CSP_BASE_URI = ("'self'",)
CSP_OBJECT_SRC = ("'none'",)
CSP_EXCLUDE_URL_PREFIXES = (
    "/admin/", "/ru/admin/", "/en/admin/",
    "/accounts/", "/ru/accounts/", "/en/accounts/",
)
CSP_INCLUDE_NONCE_IN = ("script-src", "style-src")
CSP_REPORT_ONLY = True
CSP_REPORT_URI = "/csp-report/"

TELEGRAM_ECHO_TO_CONSOLE = True

# --- Axes ---
# вместо устаревших AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP / AXES_USE_USER_AGENT:
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"], "ip_address"]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_PERMANENT_LOCK_OUT = False
AXES_RESET_ON_SUCCESS = True
AXES_USERNAME_FORM_FIELD = "login"  # allauth логин-поле
AXES_HTTP_RESPONSE_CODE = 403  # чтобы совпадало с нашими тестами/ожиданиями
AXES_LOCKOUT_TEMPLATE = "security/locked_out.html"

# наш handler с чёрным списком
AXES_HANDLER = "app_main.security.axes_handler.BlacklistAwareAxesHandler"
AXES_USERNAME_CALLABLE = "app_main.axes_handler.axes_get_username"
# язык-кука
LANGUAGE_COOKIE_NAME = "sw_lang"
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365  # 1 год
LANGUAGE_COOKIE_SAMESITE = "Lax"

FORMS_URLFIELD_ASSUME_HTTPS = True

CKEDITOR_5_CONFIGS = {
    'default': {
        'toolbar': [
            'heading', '|', 'bold', 'italic', 'link', 'bulletedList', 'numberedList',
            '|', 'outdent', 'indent', '|', 'blockQuote', 'insertTable', '|', 'undo', 'redo'
        ],
        'language': 'ru',
    },
}

SECRETS_DIR = BASE_DIR / ".secrets"
SECRETS_DIR.mkdir(exist_ok=True)
FIELD_KEY_FILE = SECRETS_DIR / "field_encryption.key"


def _read_or_create_field_key(path: Path) -> str:
    """
    Храним один Fernet-ключ в файле. Если файла нет — создаём.
    Формат: urlsafe base64, длина строки ~44 символа.
    """
    if path.exists():
        return path.read_text(encoding="utf-8").strip()

    # Генерируем новый ключ
    try:
        from cryptography.fernet import Fernet
    except Exception as e:
        raise RuntimeError(
            "Пакет 'cryptography' не установлен. Установи: pip install cryptography"
        ) from e

    key = Fernet.generate_key().decode("utf-8")
    path.write_text(key, encoding="utf-8")
    return key


FIELD_ENCRYPTION_KEY = _read_or_create_field_key(FIELD_KEY_FILE)

# ===== Decimal geometry for amounts =====
DECIMAL_AMOUNT_INT_DIGITS = 18  # целых разрядов в БД
DECIMAL_AMOUNT_DEC_PLACES = 10  # знаков после точки в БД

# «Зазор» для вычислений: на сколько целых разрядов меньше, чем в БД (обычно 1)
DECIMAL_CALC_INT_OFFSET = 1  # 1 => вычисления ведём на 17 целых

# ===== Percents =====
DECIMAL_PERCENT_PLACES_DB = 5  # хранение (БД)
DECIMAL_PERCENT_PLACES_CALC = 6  # расчёты (можно держать чуть тоньше)
DECIMAL_PERCENT_MAX_DIGITS = 12  # max_digits для процентных полей БД

# ===== Decimal context precision =====
DECIMAL_CONTEXT_PREC = 50  # глобальная точность контекста Decimal

# ===== Business limits for crypto withdraw (centralized) =====
CRYPTO_WD_MIN_MIN = 0
CRYPTO_WD_MIN_MAX = 100_000
CRYPTO_WD_FEE_FIX_MAX = 100_000
