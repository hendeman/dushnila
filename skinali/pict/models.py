import re
import unicodedata
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from sitecontent.models import SeoMetadataFields

from .page_paths import matches_public_page_path, normalize_public_page_paths
from .search import normalize_search_value


PICT_FILENAME_STEM_MAX_LENGTH = 200
PICT_PAGE_SLUG_MAX_LENGTH = 220
FINISHED_WORK_FILENAME_STEM_MAX_LENGTH = 200
CYRILLIC_FILENAME_TRANSLITERATION = str.maketrans({
    'а': 'a',
    'б': 'b',
    'в': 'v',
    'г': 'g',
    'д': 'd',
    'е': 'e',
    'ё': 'yo',
    'ж': 'zh',
    'з': 'z',
    'и': 'i',
    'й': 'y',
    'к': 'k',
    'л': 'l',
    'м': 'm',
    'н': 'n',
    'о': 'o',
    'п': 'p',
    'р': 'r',
    'с': 's',
    'т': 't',
    'у': 'u',
    'ф': 'f',
    'х': 'kh',
    'ц': 'ts',
    'ч': 'ch',
    'ш': 'sh',
    'щ': 'shch',
    'ъ': '',
    'ы': 'y',
    'ь': '',
    'э': 'e',
    'ю': 'yu',
    'я': 'ya',
    'і': 'i',
    'ї': 'yi',
    'є': 'ye',
    'ґ': 'g',
    'ў': 'u',
})
FINISHED_WORK_FILENAME_TRANSLITERATION = {
    **CYRILLIC_FILENAME_TRANSLITERATION,
    ord('х'): 'h',
}


def transliterate_filename_part(
    value,
    translation_table=CYRILLIC_FILENAME_TRANSLITERATION,
):
    """Преобразует текст в безопасную латинскую часть имени файла."""
    normalized_value = unicodedata.normalize('NFKC', value).casefold()
    transliterated_value = normalized_value.translate(
        translation_table,
    )
    ascii_value = (
        unicodedata.normalize('NFKD', transliterated_value)
        .encode('ascii', 'ignore')
        .decode('ascii')
    )
    return '-'.join(re.findall(r'[a-z0-9]+', ascii_value))


def build_description_number_slug(description, image_number, max_length):
    """Объединяет транслитерированное описание и номер изображения."""
    description_slug = transliterate_filename_part(description) or 'izobrazhenie'
    number_slug = str(image_number)
    number_suffix = f'-{number_slug}'

    if description_slug == number_slug:
        description_slug = 'izobrazhenie'
    elif description_slug.endswith(number_suffix):
        description_slug = description_slug[:-len(number_suffix)]

    description_length = max(
        1,
        max_length - len(number_suffix),
    )
    description_slug = description_slug[:description_length].rstrip('-')
    return f'{description_slug or "izobrazhenie"}{number_suffix}'


def pict_photo_upload_to(instance, original_filename):
    """Формирует имя оригинала из описания и поля «Номер изображения»."""
    original_path = Path(original_filename)
    filename_stem = build_description_number_slug(
        instance.alt,
        instance.name,
        PICT_FILENAME_STEM_MAX_LENGTH,
    )
    return f'photos/{filename_stem}{original_path.suffix.lower()}'


def finished_work_photo_upload_to(instance, original_filename):
    """Формирует имя фотографии готовой работы из поля «Имя»."""
    original_path = Path(original_filename)
    filename_stem = (
        transliterate_filename_part(
            instance.name,
            FINISHED_WORK_FILENAME_TRANSLITERATION,
        )
        or 'gotovaya-rabota'
    )
    filename_stem = (
        filename_stem[:FINISHED_WORK_FILENAME_STEM_MAX_LENGTH].rstrip('-')
        or 'gotovaya-rabota'
    )
    return f'finished_works/{filename_stem}{original_path.suffix.lower()}'


def build_pict_page_slug(description, image_number):
    """Формирует стабильный slug страницы из описания и номера изображения."""
    return build_description_number_slug(
        description,
        image_number,
        PICT_PAGE_SLUG_MAX_LENGTH,
    )


class PublicationQuerySet(models.QuerySet):
    """Единая выборка контента, разрешённого к показу на публичном сайте."""

    def published(self):
        return self.filter(is_published=True)


class SeoPageContent(SeoMetadataFields):
    """Общие редактируемые SEO-поля индексируемых страниц каталога."""

    seo_h1 = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='SEO-заголовок H1',
        help_text='Оставьте пустым, чтобы использовать стандартный заголовок.',
    )

    class Meta:
        abstract = True


class SeoLandingContent(SeoPageContent):
    """Редактируемый вводный текст страниц справочников каталога."""

    intro_text = models.TextField(
        blank=True,
        verbose_name='Вводный текст',
        help_text='Отображается под заголовком страницы.',
    )

    class Meta:
        abstract = True


class Color(models.Model):
    color = models.CharField(max_length=100, verbose_name='Цвет')
    slug_color = models.SlugField(max_length=100, unique=True, db_index=True, verbose_name='Slug')

    def __str__(self):
        return self.color

    class Meta:
        verbose_name = 'Цвет'
        verbose_name_plural = 'Цвета'


class TagPict(SeoLandingContent):
    tag = models.CharField(max_length=100, db_index=True, verbose_name='Ключевое слово')
    normalized_tag = models.CharField(
        max_length=200,
        unique=True,
        editable=False,
        verbose_name='Нормализованное значение',
    )
    slug = models.SlugField(max_length=100, db_index=True, unique=True, verbose_name="Slug")

    def clean(self):
        super().clean()
        self.normalized_tag = normalize_search_value(self.tag)
        if not any(character.isalnum() for character in self.normalized_tag):
            raise ValidationError({
                'tag': 'Тег должен содержать хотя бы одну букву или цифру.',
            })
        duplicate_tag = TagPict.objects.filter(
            normalized_tag=self.normalized_tag,
        ).exclude(pk=self.pk)
        if duplicate_tag.exists():
            raise ValidationError({
                'tag': 'Такой тег уже существует с учетом регистра и разделителей.',
            })
        if TagAlias.objects.filter(normalized_alias=self.normalized_tag).exists():
            raise ValidationError({
                'tag': 'Такое поисковое значение уже используется синонимом.',
            })

    def save(self, *args, **kwargs):
        self.normalized_tag = normalize_search_value(self.tag)
        # Проверяем инварианты и при сохранении вне ModelForm.
        self.clean()
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'tag' in update_fields:
            kwargs['update_fields'] = set(update_fields) | {'normalized_tag'}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.tag

    def get_absolute_url(self):
        return reverse('tag', kwargs={'tag_slug': self.slug})

    class Meta:
        verbose_name = 'Ключевое слово'
        verbose_name_plural = 'Ключевые слова'


class TagAlias(models.Model):
    tag = models.ForeignKey(
        TagPict,
        on_delete=models.CASCADE,
        related_name='search_aliases',
        verbose_name='Основной тег',
    )
    alias = models.CharField(max_length=100, verbose_name='Синоним')
    normalized_alias = models.CharField(
        max_length=200,
        unique=True,
        editable=False,
        verbose_name='Нормализованное значение',
    )

    def clean(self):
        super().clean()
        self.normalized_alias = normalize_search_value(self.alias)
        if not any(character.isalnum() for character in self.normalized_alias):
            raise ValidationError({
                'alias': 'Синоним должен содержать хотя бы одну букву или цифру.',
            })
        if ' ' in self.normalized_alias:
            raise ValidationError({
                'alias': 'Укажите один синоним без пробелов и разделителей.',
            })
        duplicate_alias = TagAlias.objects.filter(
            normalized_alias=self.normalized_alias,
        ).exclude(pk=self.pk)
        if duplicate_alias.exists():
            raise ValidationError({
                'alias': 'Такой поисковый синоним уже существует.',
            })
        if TagPict.objects.filter(normalized_tag=self.normalized_alias).exists():
            raise ValidationError({
                'alias': 'Такое поисковое значение уже используется основным тегом.',
            })

    def save(self, *args, **kwargs):
        self.normalized_alias = normalize_search_value(self.alias)
        # Прямое сохранение модели не должно обходить правила поискового словаря.
        self.clean()
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'alias' in update_fields:
            kwargs['update_fields'] = set(update_fields) | {'normalized_alias'}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.alias

    class Meta:
        verbose_name = 'Поисковый синоним'
        verbose_name_plural = 'Поисковые синонимы'
        ordering = ['alias']


class Category(SeoLandingContent):
    cat = models.CharField(max_length=100, verbose_name='Категория')
    slug = models.SlugField(max_length=100, unique=True, db_index=True, verbose_name='Slug')

    def __str__(self):
        return self.cat

    def get_absolute_url(self):
        return reverse('skinali', kwargs={'slug_cat': self.slug})

    class Meta:
        verbose_name = 'Категории'
        verbose_name_plural = 'Категории'


class Pict(SeoPageContent):
    name = models.IntegerField(
        unique=True,
        db_index=True,
        verbose_name='Номер изображения',
    )
    alt = models.CharField(max_length=250, verbose_name='Описание')
    slug = models.SlugField(
        max_length=PICT_PAGE_SLUG_MAX_LENGTH,
        unique=True,
        editable=False,
        verbose_name='Slug страницы',
    )
    page_description = models.TextField(
        blank=True,
        verbose_name='Описание страницы',
        help_text=(
            'Оставьте пустым, чтобы сформировать описание из названия и номера.'
        ),
    )
    photo = models.ImageField(
        upload_to=pict_photo_upload_to,
        max_length=255,
        verbose_name='Изображение',
    )
    is_popular = models.BooleanField(
        default=False,
        verbose_name='Популярное изображение',
    )
    is_published = models.BooleanField(default=True, verbose_name='Опубликовано')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время добавления')
    cat = models.ManyToManyField(Category, verbose_name="Категории")
    tags = models.ManyToManyField(TagPict, blank=True, related_name="tags", verbose_name="Теги")
    color = models.ManyToManyField(Color, verbose_name="Цвет")

    objects = PublicationQuerySet.as_manager()

    def save(self, *args, **kwargs):
        slug_was_created = not self.slug
        if slug_was_created:
            base_slug = build_pict_page_slug(self.alt, self.name)
            self.slug = base_slug
            collision_number = 2
            while (
                type(self).objects
                .filter(slug=self.slug)
                .exclude(pk=self.pk)
                .exists()
            ):
                collision_suffix = f'-{collision_number}'
                self.slug = (
                    f'{base_slug[:PICT_PAGE_SLUG_MAX_LENGTH - len(collision_suffix)].rstrip("-")}'
                    f'{collision_suffix}'
                )
                collision_number += 1

        update_fields = kwargs.get('update_fields')
        if update_fields is not None and slug_was_created:
            kwargs['update_fields'] = set(update_fields) | {'slug'}
        super().save(*args, **kwargs)

    def __str__(self):
        return str(self.name)

    def __add__(self, other):
        return int(Pict.objects.first().name) + other

    def get_absolute_url(self):
        return reverse('pict_detail', kwargs={'slug': self.slug})

    def get_page_heading(self):
        description = self.alt.strip()
        default_heading = (
            f'{description} — изображение для скинали №{self.name}'
            if description else f'Изображение для скинали №{self.name}'
        )
        return self.resolve_seo_value('seo_h1', default_heading)

    def get_page_description(self):
        description = self.alt.strip()
        default_description = f'Изображение №{self.name}'
        if description:
            default_description += f' «{description}»'
        default_description += (
            ' для печати на скинали. Уточните возможность покупки оригинала '
            'и подготовки макета под размеры кухни.'
        )
        return self.page_description.strip() or default_description

    def get_page_title(self):
        description = self.alt.strip()
        default_title = (
            f'{description} — изображение для скинали №{self.name}'
            if description else f'Изображение для скинали №{self.name}'
        )
        return f'{self.resolve_seo_value("seo_title", default_title)} | ОДИУМ'

    def get_meta_description(self):
        description = self.alt.strip()
        default_description = f'Изображение №{self.name}'
        if description:
            default_description += f' «{description}»'
        default_description += (
            ' для скинали из стекла. Посмотрите полноразмерный вариант, '
            'характеристики и похожие изображения.'
        )
        return self.resolve_seo_value(
            'seo_description',
            default_description[:320].rstrip(),
        )

    class Meta:
        verbose_name = 'Изображения'
        verbose_name_plural = 'Изображения'
        ordering = ['-id']


class FinishedWork(models.Model):
    class GlassType(models.TextChoices):
        STANDARD = 'standard', 'Обычное'
        OPTIWHITE = 'optiwhite', 'Optiwhite'
        DIAMANT = 'diamant', 'Diamant'

    class SkinaliType(models.TextChoices):
        PRINT = 'print', 'Печать'
        PAINT = 'paint', 'Покраска'
        TRANSPARENT = 'transparent', 'Прозрачное'

    name = models.CharField(max_length=200, verbose_name='Имя')
    description = models.TextField(blank=True, verbose_name='Описание')
    photo = models.ImageField(
        upload_to=finished_work_photo_upload_to,
        max_length=255,
        verbose_name='Фото',
    )
    is_published = models.BooleanField(default=True, verbose_name='Опубликовано')
    glass_type = models.CharField(
        max_length=10,
        choices=GlassType.choices,
        default=GlassType.STANDARD,
        verbose_name='Тип стекла',
    )
    skinali_type = models.CharField(
        max_length=11,
        choices=SkinaliType.choices,
        default=SkinaliType.PRINT,
        verbose_name='Тип скинали',
    )
    paint_color = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='Цвет покраски',
        help_text='Например: RAL 9000.',
    )
    catalog_image = models.ForeignKey(
        Pict,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finished_works',
        verbose_name='Номер изображения',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время добавления')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Время изменения')

    objects = PublicationQuerySet.as_manager()

    def clean(self):
        super().clean()
        paint_color = self.paint_color.strip()
        errors = {}

        if self.skinali_type == self.SkinaliType.PAINT:
            if self.catalog_image_id:
                errors['catalog_image'] = (
                    'Номер изображения доступен только для печати.'
                )
            if not paint_color:
                errors['paint_color'] = 'Укажите цвет для скинали с покраской.'
        else:
            if paint_color:
                errors['paint_color'] = (
                    'Цвет можно указывать только для скинали с покраской.'
                )
            if (
                self.skinali_type == self.SkinaliType.TRANSPARENT
                and self.catalog_image_id
            ):
                errors['catalog_image'] = (
                    'Номер изображения доступен только для печати.'
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.paint_color = self.paint_color.strip()
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            kwargs['update_fields'] = set(update_fields) | {'updated_at'}
        super().save(*args, **kwargs)

    def __str__(self):
        if self.catalog_image:
            return f'{self.name} — изображение № {self.catalog_image.name}'
        return self.name

    class Meta:
        verbose_name = 'Готовая работа'
        verbose_name_plural = 'Готовые работы'
        ordering = ['-created_at', '-id']
        constraints = [
            models.CheckConstraint(
                name='finished_work_fields_match_skinali_type',
                condition=(
                    models.Q(
                        skinali_type='print',
                        paint_color='',
                    )
                    | models.Q(
                        skinali_type='paint',
                        catalog_image__isnull=True,
                    ) & ~models.Q(paint_color='')
                    | models.Q(
                        skinali_type='transparent',
                        catalog_image__isnull=True,
                        paint_color='',
                    )
                ),
            ),
        ]


class ContactRequest(models.Model):
    """Заявка посетителя, прошедшая серверную валидацию и антиспам-проверки."""

    class RequestType(models.TextChoices):
        CALLBACK = 'callback', 'Обратный звонок'
        QUESTION = 'question', 'Вопрос'
        EMAIL_MESSAGE = 'email_message', 'Сообщение по email'
        IMAGE_PURCHASE = 'image_purchase', 'Покупка изображения'
        QUIZ = 'quiz', 'Квиз'

    request_type = models.CharField(
        max_length=20,
        choices=RequestType.choices,
        verbose_name='Тип заявки',
    )
    name = models.CharField(max_length=20, verbose_name='Имя')
    phone = models.CharField(max_length=20, blank=True, verbose_name='Телефон')
    email = models.EmailField(max_length=254, blank=True, default='', verbose_name='Email')
    question = models.CharField(max_length=250, blank=True, verbose_name='Вопрос')
    comment = models.CharField(
        max_length=250,
        blank=True,
        default='',
        verbose_name='Комментарий',
    )
    catalog_image = models.ForeignKey(
        Pict,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='purchase_requests',
        verbose_name='Изображение каталога',
    )
    # Номер сохраняется отдельно, чтобы заявка оставалась понятной после удаления Pict.
    image_number = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Номер изображения на момент заявки',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время создания')
    # Момент первого открытия в admin хранится отдельно от редактирования заявки.
    viewed_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        verbose_name='Время просмотра',
    )

    def __str__(self):
        contact = self.phone or self.email or 'без контактных данных'
        return f'{self.name} — {contact}'

    class Meta:
        verbose_name = 'Заявка'
        verbose_name_plural = 'Заявки'
        ordering = ['-created_at', '-id']


class ContactRequestDelivery(models.Model):
    """Состояние доставки одной заявки по одному внешнему каналу."""

    class Channel(models.TextChoices):
        TELEGRAM = 'telegram', 'Telegram'
        EMAIL = 'email', 'Email'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Ожидает отправки'
        PROCESSING = 'processing', 'Отправляется'
        RETRY = 'retry', 'Ожидает повтора'
        SENT = 'sent', 'Отправлено'
        FAILED = 'failed', 'Ошибка отправки'

    contact_request = models.ForeignKey(
        ContactRequest,
        on_delete=models.CASCADE,
        related_name='deliveries',
        verbose_name='Заявка',
    )
    channel = models.CharField(
        max_length=20,
        choices=Channel.choices,
        verbose_name='Канал',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name='Статус',
    )
    attempts = models.PositiveSmallIntegerField(default=0, verbose_name='Попытки')
    next_attempt_at = models.DateTimeField(
        default=timezone.now,
        null=True,
        blank=True,
        db_index=True,
        verbose_name='Следующая попытка',
    )
    processing_started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Начало обработки',
    )
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Время отправки',
    )
    external_message_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name='ID внешнего сообщения',
    )
    last_error = models.TextField(blank=True, verbose_name='Последняя ошибка')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время создания')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Время изменения')

    def __str__(self):
        return f'{self.get_channel_display()}: заявка № {self.contact_request_id}'

    class Meta:
        verbose_name = 'Доставка заявки'
        verbose_name_plural = 'Доставки заявок'
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['contact_request', 'channel'],
                name='unique_contact_request_delivery_channel',
            ),
        ]
        indexes = [
            models.Index(
                fields=['channel', 'status', 'next_attempt_at'],
                name='pict_delivery_due_idx',
            ),
        ]





class Integration(models.Model):
    """Доверенные вставки публичного сайта; изменения через admin версионируются."""

    SNAPSHOT_FIELDS = (
        'name', 'description', 'is_enabled', 'position', 'page_paths',
        'head_html', 'body_start_html', 'body_end_html',
    )
    name = models.CharField('Название', max_length=200)
    description = models.TextField('Описание', blank=True)
    is_enabled = models.BooleanField('Включена', default=False, db_index=True)
    position = models.PositiveIntegerField('Порядок подключения', default=0)
    page_paths = models.TextField(
        'Страницы', blank=True,
        help_text='Пусто — все публичные страницы. Или точные пути, по одному на строку: '
                  '/about/ или /skinali/. Параметры после ? не учитываются. '
                  'Для категории укажите её полный путь. Маски не поддерживаются.',
    )
    head_html = models.TextField('Код перед </head>', blank=True)
    body_start_html = models.TextField('Код сразу после <body>', blank=True)
    body_end_html = models.TextField('Код перед </body>', blank=True)
    updated_at = models.DateTimeField('Изменена', auto_now=True)

    class Meta:
        verbose_name = 'Интеграция'
        verbose_name_plural = 'Интеграции'
        ordering = ['position', 'pk']

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        try:
            self.page_paths = normalize_public_page_paths(self.page_paths)
        except ValidationError as error:
            raise ValidationError({'page_paths': error.messages}) from error
        if self.is_enabled and not any((self.head_html.strip(), self.body_start_html.strip(), self.body_end_html.strip())):
            raise ValidationError({'is_enabled': 'Для включения добавьте код хотя бы в одно поле.'})

    def matches_path(self, path):
        return matches_public_page_path(self.page_paths, path)

    def save_with_revision(self, user, note=''):
        # Снимок и настройки записываются атомарно, чтобы история не расходилась с публикацией.
        with transaction.atomic():
            self.full_clean()
            self.save()
            IntegrationRevision.objects.create(
                integration=self, author=user, note=note,
                snapshot={field: getattr(self, field) for field in self.SNAPSHOT_FIELDS},
            )


class IntegrationRevision(models.Model):
    integration = models.ForeignKey(Integration, on_delete=models.CASCADE, related_name='revisions', verbose_name='Интеграция')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, verbose_name='Автор')
    created_at = models.DateTimeField('Дата', auto_now_add=True)
    note = models.CharField('Действие', max_length=200, blank=True)
    snapshot = models.JSONField('Снимок настроек')

    class Meta:
        verbose_name = 'Версия интеграции'
        verbose_name_plural = 'Версии интеграций'
        ordering = ['-pk']

    def __str__(self):
        return f'Версия № {self.pk}'

    def restore(self, user):
        # Восстановление сохраняет историю и создаёт новую версию, включая флаг включения.
        integration = self.integration
        for field in Integration.SNAPSHOT_FIELDS:
            setattr(integration, field, self.snapshot[field])
        integration.save_with_revision(user, f'Восстановлена версия № {self.pk}')
        return integration
