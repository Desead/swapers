# app_main/services/site_setup.py
from django.core.cache import cache
from django.apps import apps

_CACHE_KEY = "site_setup_singleton"
_CACHE_TTL = 300  # 5 минут; в проде можно больше

def get_site_setup():
    obj = cache.get(_CACHE_KEY)
    if obj is None:
        Model = apps.get_model("app_main", "SiteSetup")
        obj = Model.get_solo()
        cache.set(_CACHE_KEY, obj, _CACHE_TTL)
    return obj

def get_admin_prefix() -> str:
    setup = get_site_setup()
    return (setup.admin_path or "admin").strip("/")
