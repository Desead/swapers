from django.contrib.sitemaps import Sitemap
from django.urls import reverse

class StaticViewSitemap(Sitemap):
    changefreq = "daily"
    priority = 1
    i18n = True        # генерирует URL для всех LANGUAGES
    # alternates = True  # добавит <xhtml:link rel="alternate" ...>

    def items(self):
        # укажи имена URL, которые должны попасть в sitemap
        return ["home"]  # добавляй сюда свои именованные маршруты

    def location(self, name):
        return reverse(name)
