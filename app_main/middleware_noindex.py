# app_main/middleware_noindex.py
from django.conf import settings
from .models import SiteSetup

class GlobalNoIndexMiddleware:
    """
    Ставит 'X-Robots-Tag: noindex, nofollow' в ответ:
      - всегда в DEBUG;
      - либо если включён флаг SiteSetup.block_indexing.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            block = settings.DEBUG or SiteSetup.get_solo().block_indexing
        except Exception:
            block = settings.DEBUG
        if block:
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response
