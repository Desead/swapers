from django.apps import AppConfig
from django.contrib import admin
from django.apps import apps as django_apps
from django.contrib.admin.sites import NotRegistered
from django.db.models.signals import post_migrate
# ВАЖНО: не импортируем модели и не лезем в БД на уровне модуля/ready()

class AppMainConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_main"

    def ready(self):
        # подключаем сигналы (внутри файла нет запросов при импорте)
        from . import signals  # noqa

        # прячем сервисные модели allauth в админке (это не бьёт БД)
        try:
            for label, model in (("account", "EmailAddress"), ("account", "EmailConfirmation")):
                try:
                    Model = django_apps.get_model(label, model)
                except LookupError:
                    continue
                try:
                    admin.site.unregister(Model)
                except NotRegistered:
                    pass
        except Exception:
            pass

        # Гарантировать наличие SiteSetup и применить issuer ТОЛЬКО ПОСЛЕ миграций
        def _ensure_and_apply_setup(**kwargs):
            try:
                from django.conf import settings
                from .models import SiteSetup
                setup = SiteSetup.get_solo()  # создастся при первой миграции
                # применяем issuer для текущего процесса
                settings.OTP_TOTP_ISSUER = setup.otp_issuer
            except Exception:
                # На ранних стадиях (до создания таблиц) просто молчим
                pass

        # Подписываемся — сработает после `migrate`
        post_migrate.connect(_ensure_and_apply_setup, sender=self)

        # ВАЖНО: НЕ вызываем _ensure_and_apply_setup() здесь, чтобы не трогать БД во время импорта
