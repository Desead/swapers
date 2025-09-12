from django.contrib.sitemaps import Sitemap
from django.urls import reverse

class StaticViewSitemap(Sitemap):
    changefreq = "daily"
    priority = 1.0

    def items(self):
        # укажи имена URL, которые должны попасть в sitemap
        return ["home"]  # добавляй сюда свои именованные маршруты

    def location(self, name):
        return reverse(name)
