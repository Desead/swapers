from django.contrib.sitemaps import Sitemap
from django.urls import reverse

class StaticViewSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.6
    i18n = True  # ← джанго сам добавит alternate hreflang для LANGUAGES

    def items(self):
        # перечисляем именованные урлы публичной части
        return [
            "home",
            # "faq", "pricing", "contacts", ...  ← добавишь по мере появления
        ]

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        return 1.0 if item == "home" else 0.6
