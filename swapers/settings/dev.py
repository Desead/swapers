from .base import *

ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:8000", "http://localhost:8000"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "dev@localhost"

ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http"

INSTALLED_APPS += ["rosetta"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        # отчёты CSP в консоль
        "app_main.views_security": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}