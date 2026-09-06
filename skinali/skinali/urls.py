"""Корневая маршрутизация проекта Skinali."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from pict.views import pageNotFound

admin.site.site_header = "Админка skinali"
admin.site.index_title = "Админка"

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
]

if settings.ENABLE_DEBUG_TOOLBAR:
    urlpatterns.append(path('__debug__/', include('debug_toolbar.urls')))

urlpatterns.append(path('', include('pict.urls')))

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = pageNotFound
