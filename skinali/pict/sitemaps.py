from types import SimpleNamespace
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.db.models import Max, Q
from django.db.models.functions import Greatest
from django.urls import reverse
from sitecontent.models import SitePage

from .models import Category, Pict, TagPict


class PublicOriginSitemap(Sitemap):
    """Строит абсолютные URL только от настроенного публичного origin."""

    def get_urls(self, page=1, site=None, protocol=None):
        public_origin = urlsplit(settings.PUBLIC_SITE_ORIGIN)
        public_site = SimpleNamespace(domain=public_origin.netloc)
        return super().get_urls(
            page=page,
            site=public_site,
            protocol=public_origin.scheme,
        )


class StaticViewSitemap(PublicOriginSitemap):
    """Постоянные публичные страницы без персональных и служебных URL."""

    changefreq = 'monthly'
    priority = 0.5
    view_names = (
        'home',
        'skinali',
        'finished_works',
        'designer',
        'about',
    )

    def items(self):
        self.lastmod_by_view_name = dict(
            SitePage.objects.filter(code__in=self.view_names).values_list(
                'code',
                'updated_at',
            )
        )
        return self.view_names

    def location(self, view_name):
        return reverse(view_name)

    def lastmod(self, view_name):
        return self.lastmod_by_view_name.get(view_name)


class PublishedPictureSitemap(PublicOriginSitemap):
    """Общая выборка разделов, содержащих опубликованные изображения."""

    changefreq = 'weekly'
    priority = 0.6
    model = None
    picture_relation = ''

    def items(self):
        relation = self.picture_relation
        return (
            self.model.objects.only('slug', 'updated_at').annotate(
                latest_pict_update=Max(
                    f'{relation}__updated_at',
                    filter=Q(**{f'{relation}__is_published': True}),
                ),
            )
            .filter(latest_pict_update__isnull=False)
            .annotate(
                sitemap_lastmod=Greatest('updated_at', 'latest_pict_update'),
            )
            .order_by('slug')
        )

    def lastmod(self, item):
        return item.sitemap_lastmod


class CategorySitemap(PublishedPictureSitemap):
    """Категории, в которых есть опубликованные изображения."""

    model = Category
    picture_relation = 'pict'
    priority = 0.7


class TagSitemap(PublishedPictureSitemap):
    """Теги, в которых есть опубликованные изображения."""

    model = TagPict
    picture_relation = 'tags'


class PictureSitemap(PublicOriginSitemap):
    """Отдельные страницы опубликованных изображений каталога."""

    changefreq = 'monthly'
    priority = 0.8

    def items(self):
        return (
            Pict.objects.published()
            .only('slug', 'updated_at')
            .order_by('slug')
        )

    def lastmod(self, item):
        return item.updated_at
