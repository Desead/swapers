"""
Django settings — PROD.
Импортируем всё из dev-настроек и ПЕРЕОПРЕДЕЛЯЕМ критичное для прода:
- DEBUG=False, индексация включена
- ALLOWED_HOSTS/CSRF_TRUSTED_ORIGINS
- PostgreSQL
- Безопасность (SSL/HSTS/secure-cookies)
- SMTP
- Кэш: DatabaseCache (кросс-процесс, если Redis ещё нет)
- CSP: режим enforce, запрет inline-скриптов (nonce), мягкий режим для стилей
"""

from .dev import *  # импортируем dev-базу и переопределяем ниже
from pathlib import Path

# ───────────────────────────────────────────────────────────────────────────────
# Общие
# ───────────────────────────────────────────────────────────────────────────────
DEBUG = False
ALLOW_INDEXING = True

# Впиши реальные домены (и схемы — для CSRF)
ALLOWED_HOSTS = ["swapers.example.com", "www.swapers.example.com"]
CSRF_TRUSTED_ORIGINS = ["https://swapers.example.com", "https://www.swapers.example.com"]

# Секретный ключ (держать в коде нежелательно, но по требованию — без .env)
SECRET_KEY = "PUT-A-STRONG-SECRET-KEY-HERE"

# Мини-страховка от человеческого фактора:
assert DEBUG is False, "DEBUG must be False in production"
assert ALLOWED_HOSTS and ALLOWED_HOSTS != ["*"], "ALLOWED_HOSTS must be set explicitly"

# ───────────────────────────────────────────────────────────────────────────────
# PostgreSQL
# ───────────────────────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "swapers",
        "USER": "swapers",
        "PASSWORD": "CHANGE_ME",
        "HOST": "127.0.0.1",
        "PORT": "5432",
        "CONN_MAX_AGE": 60,         # держим соединение подольше
        "CONN_HEALTH_CHECKS": True, # авто-хелсчеки для долгоживущих коннектов
        "ATOMIC_REQUESTS": False,
    }
}

# ───────────────────────────────────────────────────────────────────────────────
# Кэш (кросс-процесс без Redis)
# ───────────────────────────────────────────────────────────────────────────────
# Рекомендуемая настройка до появления Redis. Создай таблицу один раз:
#   python manage.py createcachetable django_cache
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
        "TIMEOUT": 300,
        "KEY_PREFIX": "swapers",
    }
}
# Когда появится Redis — переключишься на RedisCache (см. комментарий в dev settings).

# ───────────────────────────────────────────────────────────────────────────────
# Почта (SMTP)
# ───────────────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.example.com"
EMAIL_PORT = 587
EMAIL_HOST_USER = "no-reply@swapers.example.com"
EMAIL_HOST_PASSWORD = "CHANGE_ME"
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
SERVER_EMAIL = EMAIL_HOST_USER

# ───────────────────────────────────────────────────────────────────────────────
# Безопасность (SSL/Headers)
# ───────────────────────────────────────────────────────────────────────────────
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_EMBEDDER_POLICY = None  # если есть сторонние виджеты/iframe

# HSTS: наращивай после первичных проверок HTTPS на фронте/балансере
SECURE_HSTS_SECONDS = 60
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"  # при работе в iframe на другом домене потребуется "None"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
LANGUAGE_COOKIE_SECURE = True

# ───────────────────────────────────────────────────────────────────────────────
# CSP (боевой режим)
# ───────────────────────────────────────────────────────────────────────────────
# У dev-настроек CSP_REPORT_ONLY=True — переопределяем на enforce.
CSP_REPORT_ONLY = False

# Список источников ужесточаем: уносим 'unsafe-inline' из script-src — используем nonce.
# Для стилей оставляем 'unsafe-inline' как переходный шаг, чтобы ничего не сломать.
# Когда перепишешь инлайн-стили на классы/файлы/nonce — просто убери 'unsafe-inline' ниже.
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = (
    "'self'",
    "https://cdn.jsdelivr.net",
    "https://cdnjs.cloudflare.com",
)
CSP_STYLE_SRC = (
    "'self'",
    "'unsafe-inline'",  # ← временно; убери, когда переведёшь инлайн-стили на nonce/файлы
    "https://cdn.jsdelivr.net",
    "https://fonts.googleapis.com",
)
CSP_IMG_SRC = ("'self'", "data:")
CSP_FONT_SRC = ("'self'", "data:", "https://fonts.gstatic.com")
CSP_CONNECT_SRC = ("'self'", "https://fonts.gstatic.com", "https://fonts.googleapis.com")
CSP_FRAME_ANCESTORS = ("'self'",)
CSP_FORM_ACTION = ("'self'",)
CSP_BASE_URI = ("'self'",)
CSP_OBJECT_SRC = ("'none'",)
CSP_INCLUDE_NONCE_IN = ("script-src", "style-src")
# CSP_REPORT_URI наследуется из dev (если нужен сбор отчётов)

# ───────────────────────────────────────────────────────────────────────────────
# Провайдеры: политика синхронизации (PROD значения)
# ───────────────────────────────────────────────────────────────────────────────
# Эти настройки читает app_market.providers.base.UnifiedProviderBase через getattr(settings, ...).
PROVIDER_SYNC_WRITE_ENABLED = True              # в проде пишем в БД
PROVIDER_SYNC_LOCK_TTL_SECONDS = 1800           # lock на 30 минут
PROVIDER_SYNC_DEBOUNCE_SECONDS = 180            # минимум 3 минуты между полными синками
PROVIDER_SYNC_DB_CHUNK_SIZE = 500               # крупнее батчи, меньше накладных
PROVIDER_SYNC_FAIL_THRESHOLD = 3                # после 3 подряд фейлов — деградация
PROVIDER_SYNC_CIRCUIT_TTL_SECONDS = 3600        # «пробка» на 1 час

# ───────────────────────────────────────────────────────────────────────────────
# Логи (пример: CSP-отчёты в файл + консоль)
# ───────────────────────────────────────────────────────────────────────────────
LOG_DIR = Path(BASE_DIR, "logs")
LOG_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "csp_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "csp.log"),
            "maxBytes": 1_048_576,  # 1 MB
            "backupCount": 3,
            "encoding": "utf-8",
        },
    },
    "loggers": {
        # отчёты CSP — и в файл, и в stdout (чтобы ловил supervisor/systemd)
        "app_main.views_security": {"handlers": ["csp_file", "console"], "level": "INFO", "propagate": False},
    },
}

# Удаляем dev-only приложения, добавленные в dev.py
DEV_ONLY_APPS = globals().get("DEV_ONLY_APPS", [])
INSTALLED_APPS = [a for a in INSTALLED_APPS if a not in DEV_ONLY_APPS]

# ───────────────────────────────────────────────────────────────────────────────
# Заготовки под Celery / Sentry — добавим, когда понадобятся
# ───────────────────────────────────────────────────────────────────────────────
# CELERY_BROKER_URL = "redis://127.0.0.1:6379/1"
# CELERY_RESULT_BACKEND = "redis://127.0.0.1:6379/2"
# CELERY_TASK_ALWAYS_EAGER = False
# CELERY_TIMEZONE = TIME_ZONE
# CELERY_BEAT_SCHEDULE = {}
#
# SENTRY_DSN = ""
# if SENTRY_DSN:
#     import sentry_sdk
#     sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.0, profiles_sample_rate=0.0,
#                     environment="prod", release="swapers-1.0.0")
