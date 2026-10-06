"""Проверка, перерасохранение и учёт изображений статей."""

import warnings
from io import BytesIO
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_ARTICLE_IMAGE_BYTES = 5 * 1024 * 1024
MAX_ARTICLE_IMAGE_PIXELS = 12_000_000
MAX_ARTICLE_IMAGE_SIDE = 6000
ARTICLE_IMAGE_OUTPUT_SIDE = 1920


class PreparedArticleImage(ContentFile):
    """Файл, уже проверенный и перекодированный внутри приложения."""


def prepare_article_image(upload):
    """Определяет настоящий формат и удаляет метаданные при перекодировании."""
    if isinstance(upload, PreparedArticleImage):
        upload.seek(0)
        return upload
    if upload.size > MAX_ARTICLE_IMAGE_BYTES:
        raise ValidationError('Изображение должно быть не больше 5 МБ.')
    upload.seek(0)
    data = upload.read(MAX_ARTICLE_IMAGE_BYTES + 1)
    if len(data) > MAX_ARTICLE_IMAGE_BYTES:
        raise ValidationError('Изображение должно быть не больше 5 МБ.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                image_format = source.format
                if image_format not in ('JPEG', 'PNG', 'WEBP'):
                    raise ValidationError('Допустимы только JPEG, PNG и WebP.')
                if (source.width * source.height > MAX_ARTICLE_IMAGE_PIXELS
                        or max(source.size) > MAX_ARTICLE_IMAGE_SIDE):
                    raise ValidationError('Максимум 12 мегапикселей и 6000 пикселей по стороне.')
                if getattr(source, 'is_animated', False):
                    raise ValidationError('Используйте неподвижное изображение.')
                source.load()
                image = ImageOps.exif_transpose(source).convert(
                    'RGBA' if image_format != 'JPEG' and (
                        'A' in source.getbands() or 'transparency' in source.info
                    ) else 'RGB'
                )
                image.info.clear()
                image.thumbnail((ARTICLE_IMAGE_OUTPUT_SIDE, ARTICLE_IMAGE_OUTPUT_SIDE), Image.Resampling.LANCZOS)
                output = BytesIO()
                image.save(output, format=image_format, **(
                    {'quality': 88} if image_format in ('JPEG', 'WEBP') else {}
                ))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as error:
        raise ValidationError('Файл не является корректным изображением.') from error
    extension = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}[image_format]
    return PreparedArticleImage(output.getvalue(), name=f'{uuid4().hex}.{extension}')


def delete_unreferenced_article_images(image_ids, *, using):
    from .models import ArticleImage

    # Повторная проверка после commit сохраняет изображения, используемые другой статьёй.
    with transaction.atomic(using=using):
        ArticleImage.objects.using(using).filter(
            pk__in=image_ids, articles__isnull=True,
        ).delete()
