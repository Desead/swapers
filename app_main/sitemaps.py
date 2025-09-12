from django.contrib.sitemaps import Sitemap
from django.urls import reverse

class StaticViewSitemap(Sitemap):
    changefreq = "daily"
    priority = 1
    i18n = True
    alternates = True  # важно для <xhtml:link rel="alternate" hreflang="...">

    def items(self):
        return ["home"]

    def location(self, name):
        return reverse(name)
