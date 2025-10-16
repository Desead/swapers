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
        "CONN_MAX_AGE": 60,  # держим соединение подольше
        "CONN_HEALTH_CHECKS": True,  # авто-хелсчеки для долгоживущих коннектов
        "ATOMIC_REQUESTS": False,
    }
}

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
PROVIDER_SYNC_WRITE_ENABLED = True  # в проде пишем в БД
PROVIDER_SYNC_LOCK_TTL_SECONDS = 1800  # lock на 30 минут
PROVIDER_SYNC_DEBOUNCE_SECONDS = 300  # минимум 5 минут между полными синками
PROVIDER_SYNC_DB_CHUNK_SIZE = 500  # крупнее батчи, меньше накладных
PROVIDER_SYNC_FAIL_THRESHOLD = 3  # после 3 подряд фейлов — деградация
PROVIDER_SYNC_CIRCUIT_TTL_SECONDS = 3600  # «пробка» на 1 час
# Ограничим одновременное число провайдеров (примерно 2–3; подбери под железо/БД)
PROVIDER_SYNC_GLOBAL_MAX_CONCURRENT = 2
# TTL слота (обычно равен или чуть меньше LOCK_TTL, чтобы не залипало)
PROVIDER_SYNC_GLOBAL_SLOT_TTL_SECONDS = 1800
# RECV_WINDOW для подписанных API (prod)
BYBIT_RECV_WINDOW = 10000  # мс (чуть больше для запаса по времени)
MEXC_RECV_WINDOW = 30000  # мс

PROVIDER_SYNC_GLOBAL_WAIT_SECONDS = 600

# Rapira: добавлять синтетический FIAT RUB в список активов
RAPIRA_INCLUDE_RUB = True
RAPIRA_RUB_PRECISION = 2
RAPIRA_CONFIRMATIONS = {
    ("USDT", "ETH"): 6,  # ERC20
    ("USDT", "TRX"): 20,  # TRC20
    ("USDT", "BSC"): 10,  # BEP20
    ("BTC", "BTC"): 2,  # native BTC
    ("BTC", "BSC"): 10,  # BTC на BSC (BEP20)
    ("ETH", "OP"): 6,  # Optimism
    ("ETH", "ETH"): 6,  # Optimism
    ("ETH", "BSC"): 10,  # Optimism
    ("TON", "TON"): 4,  # Toncoin
    ("USDC", "ETH"): 6,  # ERC20
    ("USDC", "ETH"): 6,  # ERC20
    ("USDC", "BSC"): 10,  # ERC20
}
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
# Redis / Prices (L1)
# ───────────────────────────────────────────────────────────────────────────────
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_PASSWORD = ""  # укажи, если Redis с паролем/ACL (в проде так и должно быть)

REDIS_DB_CACHE = 0
REDIS_DB_CELERY_BROKER = 1
REDIS_DB_CELERY_RESULT = 2
REDIS_DB_PRICES = 3

def _redis_dsn(db: int) -> str:
    auth = f":{REDIS_PASSWORD}@" if REDIS_PASSWORD else ""
    return f"redis://{auth}{REDIS_HOST}:{REDIS_PORT}/{db}"

PRICES_REDIS_URL = _redis_dsn(REDIS_DB_PRICES)
PRICES_L1_KEY_PREFIX = "price:l1"
PRICES_L1_STREAM_KEY = "prices:l1:updates"

PRICES_TTL_SECONDS = {"CEX": 10, "DEX": 90, "PSP": 180, "OTC": 300, "MANUAL": 600}
PRICES_PUBLISH_EPSILON_PCT = {"CEX": 0.10, "DEX": 0.20, "PSP": 0.50, "OTC": 0.50, "MANUAL": 1.00}
PRICES_MAX_PUBLISH_INTERVAL_SEC = {"CEX": 3, "DEX": 60, "PSP": 120, "OTC": 120, "MANUAL": 300}

PRICES_DB_SAMPLE_MIN_INTERVAL_SEC = 60    # в проде пишем ещё реже
PRICES_DB_SAMPLE_MIN_DELTA_PCT = 0.30
