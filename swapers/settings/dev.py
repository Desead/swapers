from pathlib import Path
from datetime import timedelta
from django.utils.translation import gettext_lazy as _t
import os

# ───────────────────────────────────────────────────────────────────────────────
# БАЗОВОЕ
# ───────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # swapers/
DEBUG = True  # прод переопределит на False
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "CHANGE_ME_IN_PROD")
ALLOWED_HOSTS: list[str] = ["*"]  # dev: удобно *, в prod — список доменов
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:8000", "http://localhost:8000"]
ALLOW_INDEXING = False  # dev: запрещаем индексацию (middleware уважает)
SECURE_BROWSER_XSS_FILTER = True
SESSION_COOKIE_AGE = 60 * 60 * 24 * 7  # 7 дней
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
    # Админка с OTP (наш конфиг)
    "swapers.admin.OTPAdminConfig",

    # Django core
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Наши приложения
    "app_library.apps.AppLibraryConfig",
    "app_main.apps.AxesRusConfig",          # обёртка над axes
    "app_market.apps.AppMarketConfig",
    "app_main.apps.AppMainConfig",          # чтобы сработал ready()

    # Сторонние
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "parler",
    "django_ckeditor_5",
]
# Dev-only тулзы
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
    "app_main.middleware_lang.LanguageVariantNormalizeMiddleware",
    "django.middleware.locale.LocaleMiddleware",

    # Блок-лист + Axes (после Session, до Auth)
    "app_main.middleware_blacklist.BlacklistBlockMiddleware",
    "axes.middleware.AxesMiddleware",

    # Общие
    "django.middleware.common.CommonMiddleware",
    "app_main.middleware_noindex.GlobalNoIndexMiddleware",

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

    # Подстраховка по CSP (fallback-хедер)
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
        "CONN_MAX_AGE": 0,
        "ATOMIC_REQUESTS": False,
    }
}

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
    "axes.backends.AxesStandaloneBackend",                # сначала Axes
    "allauth.account.auth_backends.AuthenticationBackend" # затем allauth
]

# Почта (DEV — консоль)
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "no-reply@localhost"

# Cookies
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Allauth: логин по email, жёсткая верификация
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_CONFIRM_EMAIL_ON_GET = True
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http"
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
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365
LANGUAGE_COOKIE_SAMESITE = "Lax"
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
PROVIDER_SYNC_WRITE_ENABLED = True
PROVIDER_SYNC_LOCK_TTL_SECONDS = 120
PROVIDER_SYNC_DEBOUNCE_SECONDS = 0
PROVIDER_SYNC_DB_CHUNK_SIZE = 200
PROVIDER_SYNC_FAIL_THRESHOLD = 3
PROVIDER_SYNC_CIRCUIT_TTL_SECONDS = 300
PROVIDER_SYNC_GLOBAL_MAX_CONCURRENT = 0
PROVIDER_SYNC_GLOBAL_SLOT_TTL_SECONDS = 1800
BYBIT_RECV_WINDOW = 5000  # ms
MEXC_RECV_WINDOW = 20000  # ms
PROVIDER_SYNC_GLOBAL_WAIT_SECONDS = 0

# Rapira: добавлять синтетический FIAT RUB в список активов + подтверждения
RAPIRA_INCLUDE_RUB = True
RAPIRA_RUB_PRECISION = 2
RAPIRA_CONFIRMATIONS = {
    ("USDT", "ETH"): 6,
    ("USDT", "TRX"): 20,
    ("USDT", "BSC"): 10,
    ("BTC", "BTC"): 2,
    ("BTC", "BSC"): 10,
    ("ETH", "OP"): 6,
    ("ETH", "ETH"): 6,
    ("ETH", "BSC"): 10,
    ("TON", "TON"): 4,
    ("USDC", "ETH"): 6,
    ("USDC", "BSC"): 10,
}

# ───────────────────────────────────────────────────────────────────────────────
# LOGGING (DEV)
# ───────────────────────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "app_main.views_security": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # Коллекторы — поднимай до DEBUG при отладке
        "app_market.collectors": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# ───────────────────────────────────────────────────────────────────────────────
# REDIS / КЭШ / CELERY
# ───────────────────────────────────────────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# Логические БД Redis
REDIS_DB_CACHE = 0
REDIS_DB_CELERY_BROKER = 1
REDIS_DB_CELERY_RESULT = 2
REDIS_DB_PRICES = 3  # цены/стримы collectors

def _redis_dsn(db: int) -> str:
    auth = f":{REDIS_PASSWORD}@" if REDIS_PASSWORD else ""
    return f"redis://{auth}{REDIS_HOST}:{REDIS_PORT}/{db}"

PRICES_REDIS_URL = _redis_dsn(REDIS_DB_PRICES)
# Выровняем фолбэк URL для collectors на случай отсутствия django-redis:
REDIS_URL = PRICES_REDIS_URL

# Django cache → Redis (dev)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": PRICES_REDIS_URL,
        "TIMEOUT": 300,
        "KEY_PREFIX": "swapers",
    },
}

# Celery (dev): брокер/результаты в Redis
CELERY_BROKER_URL = _redis_dsn(REDIS_DB_CELERY_BROKER)
CELERY_RESULT_BACKEND = _redis_dsn(REDIS_DB_CELERY_RESULT)
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TIMEZONE = TIME_ZONE

# ───────────────────────────────────────────────────────────────────────────────
# COLLECTORS: реестр, sinks и интервалы
# ───────────────────────────────────────────────────────────────────────────────

# Функция idempotent-upsert ассетов кошелька в БД
COLLECTORS_WALLET_UPSERT_FUNC = "app_market.services.wallet_upsert:upsert_assets"

# Реестр провайдеров (адаптеры и возможности)
COLLECTORS_PROVIDER_REGISTRY = {
    # CEX
    "BYBIT": {
        "path": "app_market.providers.cex.bybit:BybitAdapter",
        "cap": {"wallet_assets": True, "prices_spot": True, "markets": True},
        "enabled": True,
        "needs_api": True,   # BYBIT часто требует ключи для кошелька
    },
    "MEXC": {
        "path": "app_market.providers.cex.mexc:MexcAdapter",
        "cap": {"wallet_assets": True, "prices_spot": True, "markets": True},
        "enabled": True,
        "needs_api": False,
    },
    "KUCOIN": {
        "path": "app_market.providers.cex.kucoin:KucoinAdapter",
        "cap": {"wallet_assets": True, "prices_spot": True, "markets": True},
        "enabled": True,
        "needs_api": False,
    },
    "HTX": {
        "path": "app_market.providers.cex.htx:HtxAdapter",
        "cap": {"wallet_assets": True, "prices_spot": True, "markets": True},
        "enabled": True,
        "needs_api": False,
    },
    "WHITEBIT": {
        "path": "app_market.providers.cex.whitebit:WhitebitAdapter",
        "cap": {"wallet_assets": True, "prices_spot": True, "markets": True},
        "enabled": True,
        "needs_api": False,
    },
    "RAPIRA": {
        "path": "app_market.providers.cex.rapira:RapiraAdapter",
        "cap": {"wallet_assets": True, "prices_spot": True, "markets": True},
        "enabled": True,
        "needs_api": False,
    },

    # Cash / FX (не кошелёк, но источники цен)
    "TWELVEDATA": {
        "path": "app_market.providers.cash.twelvedata:TwelveDataCashAdapter",
        "cap": {"wallet_assets": False, "prices_spot": True, "markets": False},
        "enabled": False,
        "needs_api": False,
    },
    "OPENEXCHANGERATES": {
        "path": "app_market.providers.cash.openexchangerates:OpenExchangeRatesCashAdapter",
        "cap": {"wallet_assets": False, "prices_spot": True, "markets": False},
        "enabled": False,
        "needs_api": False,
    },
}

# Redis-sinks для цен + «зеркало» в админку без истории
COLLECTORS_PRICES_STREAM = "prices:l1"
COLLECTORS_PRICES_HASH_PREFIX = "prices:last"
COLLECTORS_PRICES_HASH_TTL = 3600
# COLLECTORS_PRICES_STREAM_MAXLEN = 10000
COLLECTORS_PRICE_FRESHNESS_MINUTES = 10

# Оркестрация/периодичность (Celery подключим в конце)
COLLECTORS_MAX_PARALLEL_PROVIDERS = 2
COLLECTORS_WALLET_INTERVAL_S = 3600
COLLECTORS_PRICES_INTERVAL_S = 10
COLLECTORS_DUMP_ENABLED = True
