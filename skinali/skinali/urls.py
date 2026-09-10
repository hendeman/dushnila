"""Корневая маршрутизация проекта Skinali."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from django.urls import include, path, reverse
from django.views.decorators.http import require_safe

from pict.sitemaps import CategorySitemap, StaticViewSitemap, TagSitemap
from pict.views import pageNotFound, serverError

admin.site.site_header = "Админка skinali"
admin.site.index_title = "Админка"


@require_safe
def robots_txt(request):
    """Возвращает правила обхода и адрес XML-карты для поисковых роботов."""
    tracking_parameters = '&'.join((
        'utm_source',
        'utm_medium',
        'utm_campaign',
        'utm_content',
        'utm_term',
        'yclid',
        'gclid',
    ))
    lines = (
        'User-agent: *',
        f'Disallow: /{settings.ADMIN_URL}',
        f'Disallow: {reverse("contact_submit")}',
        f'Clean-param: {tracking_parameters}',
        '',
        f'Sitemap: {settings.PUBLIC_SITE_ORIGIN}{reverse("sitemap")}',
        '',
    )
    response = HttpResponse(
        '\n'.join(lines),
        content_type='text/plain; charset=utf-8',
    )
    response['Cache-Control'] = 'public, max-age=3600'
    return response


urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path(
        'sitemap.xml',
        sitemap,
        {
            'sitemaps': {
                'static': StaticViewSitemap,
                'categories': CategorySitemap,
                'tags': TagSitemap,
            },
        },
        name='sitemap',
    ),
]

if settings.ENABLE_DEBUG_TOOLBAR:
    urlpatterns.append(path('__debug__/', include('debug_toolbar.urls')))

urlpatterns.append(path('', include('pict.urls')))

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = pageNotFound
handler500 = serverError
