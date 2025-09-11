from .base import *
from pathlib import Path
LOG_DIR = Path(BASE_DIR, "logs")
LOG_DIR.mkdir(exist_ok=True)

# ВПИШИ СВОЙ ДОМЕН
ALLOWED_HOSTS = ["swapers.example.com", "www.swapers.example.com"]
CSRF_TRUSTED_ORIGINS = ["https://swapers.example.com", "https://www.swapers.example.com"]

# СЕКРЕТ в коде держать не рекомендуется —
SECRET_KEY = "PUT-A-STRONG-SECRET-KEY-HERE"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "swapers",
        "USER": "swapers",
        "PASSWORD": "CHANGE_ME",
        "HOST": "127.0.0.1",
        "PORT": "5432",
    }
}

# SMTP
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.example.com"
EMAIL_PORT = 587
EMAIL_HOST_USER = "no-reply@swapers.example.com"
EMAIL_HOST_PASSWORD = "CHANGE_ME"
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
SERVER_EMAIL = EMAIL_HOST_USER

# SSL/безопасность
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 60  # увеличите до 31536000 после проверки
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Логи
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
        "app_main.views_security": {
            "handlers": ["csp_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}