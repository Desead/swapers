from django.contrib.sitemaps import Sitemap
from django.urls import reverse

class StaticViewSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.6
    i18n = True          # генерить URL на все языки
    alternates = True    # добавлять <xhtml:link hreflang="..."> к каждому URL
    # x_default = True   # (опционально) добавить hreflang="x-default"

    def items(self):
        return ["home"]

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        return 1.0 if item == "home" else 0.6
