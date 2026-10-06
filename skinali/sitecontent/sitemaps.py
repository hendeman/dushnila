from pict.sitemaps import PublicOriginSitemap

from .models import Article


class ArticleSitemap(PublicOriginSitemap):
    changefreq = 'monthly'
    priority = 0.6

    def items(self):
        return Article.objects.published().only('slug', 'updated_at').order_by('slug')

    def lastmod(self, item):
        return item.updated_at
