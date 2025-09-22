from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AppLibraryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app_library'
    verbose_name = _("Библиотека")
