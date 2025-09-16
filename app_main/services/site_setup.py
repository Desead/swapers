from django.core.cache import cache
from django.apps import apps

_CACHE_KEY = "site_setup_singleton"
_CACHE_TTL = 300  # 5 минут; в проде можно больше


def get_site_setup():
    """
    Быстрый доступ к singleton-настройкам через Django cache.
    Возвращает КЭШИРОВАННЫЙ объект модели SiteSetup.
    ВАЖНО: не мутируйте его поля «на месте», вместо этого правьте через админку/ORM и заново получайте объект.
    """
    obj = cache.get(_CACHE_KEY)
    if obj is None:
        Model = apps.get_model("app_main", "SiteSetup")
        obj = Model.get_solo()
        cache.set(_CACHE_KEY, obj, _CACHE_TTL)
    return obj


def clear_site_setup_cache():
    """Инвалидация кэша настроек (вызывается после сохранения/удаления SiteSetup)."""
    cache.delete(_CACHE_KEY)


def get_admin_prefix() -> str:
    """Удобный хелпер, уважает кэш настроек."""
    setup = get_site_setup()
    return (setup.admin_path or "admin").strip("/")
