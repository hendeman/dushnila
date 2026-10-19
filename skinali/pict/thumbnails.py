"""Нумерованные имена превью и восстановление удалённых файлов кеша."""

from posixpath import splitext

from django.db.models.fields.files import ImageFieldFile
from sorl.thumbnail import default
from sorl.thumbnail.base import ThumbnailBackend
from sorl.thumbnail.images import ImageFile

from .models import Pict


class CatalogThumbnailBackend(ThumbnailBackend):
    def get_thumbnail(self, file_, geometry_string, **options):
        if isinstance(file_, ImageFieldFile) and isinstance(file_.instance, Pict):
            options.setdefault('catalog_image_number', file_.instance.name)
        thumbnail = super().get_thumbnail(file_, geometry_string, **options)
        # Отдельный процесс очистки не сбрасывает LocMemCache работающего Django.
        if not thumbnail.exists() and default.kvstore.get(thumbnail) is not None:
            default.kvstore.delete(thumbnail, delete_thumbnails=False)
            # Запись источника в БД тоже могла исчезнуть при очистке кеша.
            default.kvstore.delete(ImageFile(file_), delete_thumbnails=False)
            thumbnail = super().get_thumbnail(file_, geometry_string, **options)
        return thumbnail

    def _get_thumbnail_filename(self, source, geometry_string, options):
        # Номер меняет только суффикс: исходный хеш и параметры обработки прежние.
        image_number = options.pop('catalog_image_number', None)
        filename = super()._get_thumbnail_filename(source, geometry_string, options)
        if image_number is None:
            return filename
        stem, extension = splitext(filename)
        return f'{stem}-{int(image_number)}{extension}'
