"""
Django settings — DEV (по умолчанию).
Без .env. Всё общее + удобные дефолты разработки:
- БД: SQLite
- Кэш: LocMem (однопроцессная разработка)
- Email: console
В проде используем swapers.settings.prod (см. соседний файл).
"""

from pathlib import Path
from datetime import timedelta
from django.utils.translation import gettext_lazy as _t

# ───────────────────────────────────────────────────────────────────────────────
# Базовые параметры проекта
# ───────────────────────────────────────────────────────────────────────────────
# ВНИМАНИЕ: файл лежит в swapers/settings/, поэтому BASE_DIR на уровень выше папки swapers
BASE_DIR = Path(__file__).resolve().parent.parent.parent

DEBUG = True  # прод переопределит на False
SECRET_KEY = "CHANGE_ME_IN_PROD"  # прод переопределит реальным ключом
ALLOWED_HOSTS: list[str] = ["*"]  # dev: удобнее *; в проде — список доменов
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:8000", "http://localhost:8000"]
ALLOW_INDEXING = False  # dev: запрет индексации (наш middleware уважает)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ───────────────────────────────────────────────────────────────────────────────
# Локализация и время
# ───────────────────────────────────────────────────────────────────────────────
SITE_ID = 1
LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

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
    None: [{"code": code} for code, _ in LANGUAGES],
    "default": {"fallbacks": [LANGUAGE_CODE, "en"], "hide_untranslated": True},
}
LOCALE_PATHS = [BASE_DIR / "locale"]

# ───────────────────────────────────────────────────────────────────────────────
# Приложения
# ───────────────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    # Админка с OTP (наш форк/конфиг)
    "swapers.admin.OTPAdminConfig",

    # Django core
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Наши приложения
    "app_library.apps.AppLibraryConfig",
    "app_main.apps.AxesRusConfig",  # rate-limit/lockout (обёртка над axes)
    "app_market.apps.AppMarketConfig",
    "app_main.apps.AppMainConfig",  # чтобы сработал ready()

    # Сторонние
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "parler",
    "django_ckeditor_5",
]
# Dev-only тулзы добавляем отдельным списком — prod их потом срежет
DEV_ONLY_APPS = ["rosetta"]
INSTALLED_APPS += DEV_ONLY_APPS

AUTH_USER_MODEL = "app_main.User"

# ───────────────────────────────────────────────────────────────────────────────
# Middleware (важен порядок)
# ───────────────────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    # Безопасность + CSP
    "django.middleware.security.SecurityMiddleware",
    "csp.middleware.CSPMiddleware",

    # Сессии → рефералка → нормализация языка → локализация
    "django.contrib.sessions.middleware.SessionMiddleware",
    "app_main.middleware.ReferralAttributionMiddleware",
    "app_main.middleware_lang.LanguageVariantNormalizeMiddleware",  # нормализуем ru-ru → ru
    "django.middleware.locale.LocaleMiddleware",

    # Блок-лист + Axes (после Session, до Auth)
    "app_main.middleware_blacklist.BlacklistBlockMiddleware",
    "axes.middleware.AxesMiddleware",

    # Общие
    "django.middleware.common.CommonMiddleware",
    "app_main.middleware_noindex.GlobalNoIndexMiddleware",  # уважает ALLOW_INDEXING

    # CSRF → аутентификация → OTP → allauth
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "allauth.account.middleware.AccountMiddleware",

    # Сообщения и X-Frame
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",

    # Админ-специфика
    "app_main.middleware.Admin2FARedirectMiddleware",
    "app_main.middleware.AdminSessionTimeoutMiddleware",

    # Подстраховка по CSP (костыльный хедер, если кто-то потерялся по пути)
    "app_main.middleware_csp_fallback.CSPHeaderEnsureMiddleware",
]

# ───────────────────────────────────────────────────────────────────────────────
# URL/WSGI/ASGI
# ───────────────────────────────────────────────────────────────────────────────
ROOT_URLCONF = "swapers.urls"
WSGI_APPLICATION = "swapers.wsgi.application"
ASGI_APPLICATION = "swapers.asgi.application"

# ───────────────────────────────────────────────────────────────────────────────
# Шаблоны
# ───────────────────────────────────────────────────────────────────────────────
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

# ───────────────────────────────────────────────────────────────────────────────
# База данных (DEV = SQLite)
# ───────────────────────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # Ниже значения совпадают с дефолтами Django; оставлены ради явности:
        "CONN_MAX_AGE": 0,  # 0 = закрывать соединение после каждого запроса (для SQLite ок)
        "ATOMIC_REQUESTS": False,  # транзакции контролируем вручную точечно
    }
}

# ───────────────────────────────────────────────────────────────────────────────
# Кэш (DEV = LocMem; одного процесса достаточно)
# ───────────────────────────────────────────────────────────────────────────────
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "swapers-local",
        "TIMEOUT": 300,
        "KEY_PREFIX": "swapers",
    }
}
# Готовые альтернативы (раскомментируешь при надобности):
# 1) DatabaseCache (кросс-процесс, без Redis). Создать таблицу: `python manage.py createcachetable django_cache`
# CACHES = {
#     "default": {
#         "BACKEND": "django.core.cache.backends.db.DatabaseCache",
#         "LOCATION": "django_cache",
#         "TIMEOUT": 300,
#         "KEY_PREFIX": "swapers",
#     }
# }
# 2) RedisCache (когда поставишь Redis)
# CACHES = {
#     "default": {
#         "BACKEND": "django.core.cache.backends.redis.RedisCache",
#         "LOCATION": "redis://127.0.0.1:6379/0",
#         "TIMEOUT": 300,
#         "KEY_PREFIX": "swapers",
#     }
# }

# ───────────────────────────────────────────────────────────────────────────────
# Статика/медиа
# ───────────────────────────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ───────────────────────────────────────────────────────────────────────────────
# Аутентификация / Allauth
# ───────────────────────────────────────────────────────────────────────────────
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",  # сначала Axes
    "allauth.account.auth_backends.AuthenticationBackend"  # затем allauth
]

# Почта по умолчанию (консоль). Прод переопределит SMTP.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "no-reply@localhost"

# Cookies
SESSION_COOKIE_SAMESITE = "Lax"  # баланс безопасности/совместимости
CSRF_COOKIE_SAMESITE = "Lax"

# Allauth: логин по email, жёсткая верификация
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http"  # dev: удобнее http

# Внутренний троттлинг allauth выключен — используем django-axes как единую политику
ACCOUNT_RATE_LIMITS = {}

# Редиректы
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

# Валидаторы паролей
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ───────────────────────────────────────────────────────────────────────────────
# CSP (Content-Security-Policy)
# ───────────────────────────────────────────────────────────────────────────────
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

# ───────────────────────────────────────────────────────────────────────────────
# Разное
# ───────────────────────────────────────────────────────────────────────────────
TELEGRAM_ECHO_TO_CONSOLE = True

# Axes (защита входа)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"], "ip_address"]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_PERMANENT_LOCK_OUT = False
AXES_RESET_ON_SUCCESS = True
AXES_USERNAME_FORM_FIELD = "login"
AXES_HTTP_RESPONSE_CODE = 403
AXES_LOCKOUT_TEMPLATE = "security/locked_out.html"
AXES_HANDLER = "app_main.security.axes_handler.BlacklistAwareAxesHandler"
AXES_USERNAME_CALLABLE = "app_main.axes_handler.axes_get_username"

# Язык-кука
LANGUAGE_COOKIE_NAME = "sw_lang"
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365  # 1 год
LANGUAGE_COOKIE_SAMESITE = "Lax"

# Удобства
FORMS_URLFIELD_ASSUME_HTTPS = True

# CKEditor 5
CKEDITOR_5_CONFIGS = {
    "default": {
        "toolbar": [
            "heading", "|", "bold", "italic", "link", "bulletedList", "numberedList",
            "|", "outdent", "indent", "|", "blockQuote", "insertTable", "|", "undo", "redo"
        ],
        "language": "ru",
    },
}

# ───────────────────────────────────────────────────────────────────────────────
# Ключ для django-encrypted-fields
# ───────────────────────────────────────────────────────────────────────────────
SECRETS_DIR = BASE_DIR / ".secrets"
SECRETS_DIR.mkdir(exist_ok=True)
FIELD_KEY_FILE = SECRETS_DIR / "field_encryption.key"

def _read_or_create_field_key(path: Path) -> str:
    """Храним один Fernet-ключ в файле. Если файла нет — создаём."""
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    try:
        from cryptography.fernet import Fernet
    except Exception as e:
        raise RuntimeError("Установи пакет 'cryptography' (pip install cryptography)") from e
    key = Fernet.generate_key().decode("utf-8")
    path.write_text(key, encoding="utf-8")
    return key

FIELD_ENCRYPTION_KEY = _read_or_create_field_key(FIELD_KEY_FILE)

# ───────────────────────────────────────────────────────────────────────────────
# Геометрия Decimal (суммы/проценты)
# ───────────────────────────────────────────────────────────────────────────────
DECIMAL_AMOUNT_INT_DIGITS = 18
DECIMAL_AMOUNT_DEC_PLACES = 10
DECIMAL_CALC_INT_OFFSET = 1
DECIMAL_PERCENT_PLACES_DB = 5
DECIMAL_PERCENT_PLACES_CALC = 6
DECIMAL_PERCENT_MAX_DIGITS = 12
DECIMAL_CONTEXT_PREC = 50  # глобальная точность Decimal

# Бизнес-лимиты для централизованного crypto-guard
CRYPTO_WD_MIN_MIN = 0
CRYPTO_WD_MIN_MAX = 100_000
CRYPTO_WD_FEE_FIX_MAX = 100_000

# ───────────────────────────────────────────────────────────────────────────────
# Провайдеры: политика синхронизации (DEV значения)
# ───────────────────────────────────────────────────────────────────────────────
# Эти настройки читает app_market.providers.base.UnifiedProviderBase через getattr(settings, ...).
# В DEV делаем максимально удобные значения, чтобы не мешать отладке/тестам.
PROVIDER_SYNC_WRITE_ENABLED = True              # писать в БД (выключай при dry-run)
PROVIDER_SYNC_LOCK_TTL_SECONDS = 120            # lock живёт 2 минуты
PROVIDER_SYNC_DEBOUNCE_SECONDS = 0              # дебаунс отключён в dev
PROVIDER_SYNC_DB_CHUNK_SIZE = 200               # поменьше батч для читаемых логов
PROVIDER_SYNC_FAIL_THRESHOLD = 3                # после 3 подряд фейлов считаем деградацией
PROVIDER_SYNC_CIRCUIT_TTL_SECONDS = 300         # «пробка» на 5 минут

# ───────────────────────────────────────────────────────────────────────────────
# Заготовки под Celery / Sentry — добавим, когда понадобятся
# ───────────────────────────────────────────────────────────────────────────────
# CELERY_BROKER_URL = ""
# CELERY_RESULT_BACKEND = ""
# CELERY_TASK_ALWAYS_EAGER = False
# CELERY_TIMEZONE = TIME_ZONE
# CELERY_BEAT_SCHEDULE = {}
#
# SENTRY_DSN = ""
# (Инициализацию Sentry включим в проде, когда появится DSN)

# ───────────────────────────────────────────────────────────────────────────────
# Логирование (DEV): минимум — CSP-отчёты в консоль
# ───────────────────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        # отчёты CSP — в консоль
        "app_main.views_security": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
