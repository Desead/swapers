from django.apps import AppConfig
from django.contrib import admin
from django.apps import apps as django_apps
from django.contrib.admin.sites import NotRegistered
from django.db.models.signals import post_migrate
from importlib import import_module
from django.utils.translation import gettext_lazy as _


class AppMainConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app_main"
    verbose_name = _("Управление сайтом")

    def ready(self):
        # подключаем сигналы (внутри файла нет запросов при импорте)
        from . import signals  # noqa

        # прячем сервисные модели allauth в админке (это не бьёт БД)
        try:
            for label, model in (
                ("account", "EmailAddress"),
                ("account", "EmailConfirmation"),
            ):
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

        # Гарантировать наличие SiteSetup + дефолтного перевода и применить issuer ПОСЛЕ миграций
        def _ensure_and_apply_setup(**kwargs):
            try:
                from django.conf import settings
                from .models import SiteSetup

                # 1) гарантируем singleton
                setup = SiteSetup.get_solo()

                # 2) гарантируем перевод по умолчанию (чтобы Parler не падал на первом рендере)
                # определяем код языка по умолчанию
                default_lang = getattr(settings, "PARLER_DEFAULT_LANGUAGE_CODE", None)
                if not default_lang:
                    try:
                        default_lang = (
                            settings.PARLER_LANGUAGES.get(None, [{}])[0].get("code")
                        )
                    except Exception:
                        default_lang = None
                if not default_lang:
                    default_lang = getattr(settings, "LANGUAGE_CODE", "en")
                default_lang = default_lang.split("-")[0].lower()

                try:
                    if hasattr(setup, "has_translation") and not setup.has_translation(
                        default_lang
                    ):
                        # создаём пустой перевод (поля могут быть blank=True)
                        setup.set_current_language(default_lang)
                        for attr in ("main_h1", "title", "description"):
                            if hasattr(setup, attr) and getattr(setup, attr) is None:
                                setattr(setup, attr, "")
                        setup.save()
                except Exception:
                    # Не блокируем запуск, если вдруг что-то пойдёт не так
                    pass

                # 3) применяем issuer для текущего процесса
                try:
                    settings.OTP_TOTP_ISSUER = setup.otp_issuer
                except Exception:
                    pass

            except Exception:
                # На ранних стадиях (до создания таблиц) просто молчим
                pass

        # Подписываемся — сработает после `migrate` этого приложения
        post_migrate.connect(_ensure_and_apply_setup, sender=self)
        # ВАЖНО: не вызываем _ensure_and_apply_setup() здесь, чтобы не трогать БД во время импорта


# Кастомный конфиг для django-axes c русским названием
try:
    AxesBaseConfig = getattr(import_module("axes.apps"), "AxesConfig")
except Exception:  # на случай экзотичных версий
    AxesBaseConfig = AppConfig


class AxesRusConfig(AxesBaseConfig):
    """
    Кастомный конфиг для django-axes с русским названием,
    но с name/label 'axes', чтобы это оставалось тем же приложением.
    """
    name = "axes"
    label = "axes"
    verbose_name = _("Блокировки входа")
    default_auto_field = "django.db.models.AutoField"
