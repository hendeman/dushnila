from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from sitecontent.models import SeoMetadataFields

from .search import normalize_search_value


class PublicationQuerySet(models.QuerySet):
    """Единая выборка контента, разрешённого к показу на публичном сайте."""

    def published(self):
        return self.filter(is_published=True)


class SeoLandingContent(SeoMetadataFields):
    """Общие редактируемые SEO-поля страниц справочников каталога."""

    seo_h1 = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='SEO-заголовок H1',
        help_text='Оставьте пустым, чтобы использовать стандартный заголовок.',
    )
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


class Pict(models.Model):
    name = models.IntegerField(unique=True, db_index=True, verbose_name='Имя файла')
    # name = models.CharField(max_length=10, unique=True, db_index=True, verbose_name='Имя файла')
    alt = models.CharField(max_length=250, blank=True, verbose_name='Описание')
    photo = models.ImageField(upload_to="photos/", verbose_name='Изображение')
    is_published = models.BooleanField(default=True, verbose_name='Опубликовано')
    time_update = models.DateTimeField(auto_now_add=True, verbose_name='Время добавления')
    cat = models.ManyToManyField(Category, verbose_name="Категории")
    tags = models.ManyToManyField(TagPict, blank=True, related_name="tags", verbose_name="Теги")
    color = models.ManyToManyField(Color, verbose_name="Цвет")

    objects = PublicationQuerySet.as_manager()

    def __str__(self):
        return str(self.name)

    def __add__(self, other):
        return int(Pict.objects.first().name) + other

    class Meta:
        verbose_name = 'Изображения'
        verbose_name_plural = 'Изображения'
        ordering = ['-id']


class FinishedWork(models.Model):
    name = models.CharField(max_length=200, verbose_name='Имя')
    description = models.TextField(blank=True, verbose_name='Описание')
    photo = models.ImageField(upload_to='finished_works/', verbose_name='Фото')
    is_published = models.BooleanField(default=True, verbose_name='Опубликовано')
    catalog_image = models.ForeignKey(
        Pict,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='finished_works',
        verbose_name='Номер изображения',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время добавления')

    objects = PublicationQuerySet.as_manager()

    def __str__(self):
        if self.catalog_image:
            return f'{self.name} — изображение № {self.catalog_image.name}'
        return self.name

    class Meta:
        verbose_name = 'Готовая работа'
        verbose_name_plural = 'Готовые работы'
        ordering = ['-created_at', '-id']


class ContactRequest(models.Model):
    """Заявка посетителя, прошедшая серверную валидацию и антиспам-проверки."""

    class RequestType(models.TextChoices):
        CALLBACK = 'callback', 'Обратный звонок'
        QUESTION = 'question', 'Вопрос'
        EMAIL_MESSAGE = 'email_message', 'Сообщение по email'
        IMAGE_PURCHASE = 'image_purchase', 'Покупка изображения'

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
        paths = list(dict.fromkeys(line.strip() for line in self.page_paths.splitlines() if line.strip()))
        for path in paths:
            if (not path.startswith('/') or path.startswith('//')
                    or any(char in path for char in '?#*\\')
                    or any(char.isspace() or ord(char) < 32 for char in path)):
                raise ValidationError({'page_paths': 'Укажите локальные пути с / без домена, параметров и масок.'})
        self.page_paths = '\n'.join(paths)
        if self.is_enabled and not any((self.head_html.strip(), self.body_start_html.strip(), self.body_end_html.strip())):
            raise ValidationError({'is_enabled': 'Для включения добавьте код хотя бы в одно поле.'})

    def matches_path(self, path):
        return not self.page_paths or path in self.page_paths.splitlines()

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
