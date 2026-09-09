from django.contrib.sitemaps import Sitemap
from django.db.models import Max, Q
from django.urls import reverse

from .models import Category, TagPict


class StaticViewSitemap(Sitemap):
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
        return self.view_names

    def location(self, view_name):
        return reverse(view_name)


class PublishedPictureSitemap(Sitemap):
    """Общая выборка разделов, содержащих опубликованные изображения."""

    changefreq = 'weekly'
    priority = 0.6
    model = None
    picture_relation = ''

    def items(self):
        relation = self.picture_relation
        return (
            self.model.objects.annotate(
                latest_pict_update=Max(
                    f'{relation}__time_update',
                    filter=Q(**{f'{relation}__is_published': True}),
                ),
            )
            .filter(latest_pict_update__isnull=False)
            .order_by('slug')
        )

    def lastmod(self, item):
        return item.latest_pict_update


class CategorySitemap(PublishedPictureSitemap):
    """Категории, в которых есть опубликованные изображения."""

    model = Category
    picture_relation = 'pict'
    priority = 0.7


class TagSitemap(PublishedPictureSitemap):
    """Теги, в которых есть опубликованные изображения."""

    model = TagPict
    picture_relation = 'tags'
