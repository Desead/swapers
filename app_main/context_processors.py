# app_main/context_processors.py
from .services.site_setup import get_site_setup

def site_settings(request):
    """
    Возвращает объект SiteSetup (через кэш) в шаблоны.
    Пример использования: {{ site_setup.admin_path }}
    """
    return {"site_setup": get_site_setup()}
