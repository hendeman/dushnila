import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
from django.db import models
from django.db import router, transaction
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.urls import reverse
from django.utils import timezone

from .querysets import PublicationQuerySet
from .rich_text import ArticleHTMLReferences, sanitize_article_html


class SeoMetadataFields(models.Model):
    """Общие редактируемые поля SEO без собственной таблицы."""

    seo_title = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='SEO-title',
        help_text='Без «| ОДИУМ»: бренд и номер страницы добавятся автоматически.',
    )
    seo_description = models.CharField(
        max_length=320,
        blank=True,
        verbose_name='Meta description',
        help_text='Оставьте пустым, чтобы использовать стандартное описание.',
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Время изменения публичного содержимого',
    )

    def save(self, *args, **kwargs):
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            kwargs['update_fields'] = set(update_fields) | {'updated_at'}
        super().save(*args, **kwargs)

    def resolve_seo_value(self, field_name, default):
        """Возвращает заполненное SEO-поле или стандартное значение."""
        return getattr(self, field_name).strip() or default

    class Meta:
        abstract = True


class SitePage(SeoMetadataFields):
    """SEO-настройки постоянной внутренней страницы сайта."""

    class Code(models.TextChoices):
        HOME = 'home', 'Главная страница'
        CATALOG = 'skinali', 'Каталог скинали'
        FINISHED_WORKS = 'finished_works', 'Наши работы'
        DESIGNER = 'designer', 'Услуги дизайнера'
        ARTICLES = 'article_list', 'Полезно знать'
        ABOUT = 'about', 'Связаться с нами'

    code = models.CharField(
        'Системный код',
        max_length=50,
        choices=Code.choices,
        primary_key=True,
        editable=False,
    )

    class Meta:
        verbose_name = 'Страница сайта'
        verbose_name_plural = 'Страницы сайта'

    def __str__(self):
        return self.get_code_display()


class SiteMenu(models.Model):
    """Единственное общее меню, используемое в шапке и подвале сайта."""

    MAIN_CODE = 'main'

    name = models.CharField('Название', max_length=100, default='Основное меню', editable=False)
    code = models.SlugField('Системный код', max_length=50, default=MAIN_CODE, unique=True, editable=False)

    class Meta:
        verbose_name = 'Меню'
        verbose_name_plural = 'Меню'

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if SiteMenu.objects.exclude(pk=self.pk).exists():
            raise ValidationError('На сайте может существовать только одно основное меню.')

    def save(self, *args, **kwargs):
        # Ограничение singleton действует и при сохранении модели вне Django Admin.
        self.full_clean()
        return super().save(*args, **kwargs)


class MenuItem(models.Model):
    """Редактируемая текстовая ссылка общего меню сайта."""

    menu = models.ForeignKey(
        SiteMenu,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='Меню',
    )
    title = models.CharField('Название', max_length=100)
    url = models.CharField(
        'Ссылка',
        max_length=500,
        help_text=(
            'Допустимы внутренние пути с /, якоря #, http/https, tel: и mailto:. '
            'Например: /about/, https://example.com, #contacts или tel:+375291234567.'
        ),
    )
    open_in_new_tab = models.BooleanField('Открывать в новой вкладке', default=False)
    position = models.PositiveIntegerField('Порядок', default=0)
    is_visible = models.BooleanField('Отображать', default=True)

    class Meta:
        verbose_name = 'Пункт меню'
        verbose_name_plural = 'Пункты меню'
        ordering = ['position', 'pk']

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        self.title = self.title.strip()
        self.url = self.url.strip()

        errors = {}
        if not self.title:
            errors['title'] = 'Введите название пункта меню.'
        try:
            self._validate_url(self.url)
        except ValidationError as error:
            errors['url'] = error.messages
        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _validate_url(value):
        """Разрешает только ссылки, безопасные для вывода в HTML-атрибуте href."""
        error = ValidationError(
            'Укажите внутренний путь с /, якорь #, ссылку http/https, tel: или mailto:.'
        )
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise error

        if value.startswith('/'):
            if value.startswith('//') or '\\' in value or any(char.isspace() for char in value):
                raise error
            return

        if value.startswith('#'):
            if len(value) == 1 or '\\' in value or any(char.isspace() for char in value):
                raise error
            return

        normalized_value = value.casefold()
        if normalized_value.startswith(('http://', 'https://')):
            URLValidator(schemes=['http', 'https'])(value)
            return

        if normalized_value.startswith('mailto:'):
            mailto_value = value[len('mailto:'):]
            recipients, _, query = mailto_value.partition('?')
            if not recipients or any(char.isspace() for char in query):
                raise error
            for recipient in recipients.split(','):
                validate_email(recipient)
            return

        if normalized_value.startswith('tel:'):
            phone = value[len('tel:'):]
            if (
                not any(char.isdigit() for char in phone)
                or not re.fullmatch(r'[0-9+*#().,;\-\s]+', phone)
            ):
                raise error
            return

        # urlsplit фиксирует намерение: схемы вне белого списка, включая javascript/data, запрещены.
        if urlsplit(value).scheme:
            raise error
        raise error

    def save(self, *args, **kwargs):
        # Валидация протокола обязательна и для служебных сохранений вне admin-формы.
        self.full_clean()
        return super().save(*args, **kwargs)


class ArticleImage(models.Model):
    """Загруженный файл текста статьи, включая ещё не сохранённые вставки."""

    image = models.ImageField('Изображение', upload_to='articles/content/', max_length=255)
    created_at = models.DateTimeField('Загружено', auto_now_add=True, db_index=True)

    def save(self, *args, **kwargs):
        from .article_media import prepare_article_image

        if self.image and not self.image._committed:
            self.image = prepare_article_image(self.image.file)
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Изображение статьи'
        verbose_name_plural = 'Изображения статей'


class Article(SeoMetadataFields):
    """Статья с постоянным адресом и HTML, очищенным на сервере."""

    title = models.CharField('Заголовок', max_length=200)
    slug = models.SlugField(
        'Адрес статьи', max_length=220, unique=True, blank=True,
        help_text=(
            'Необязательно. Русский или латинский текст преобразуется в адрес. '
            'Если оставить пустым, используется заголовок. После первого сохранения адрес не меняется.'
        ),
    )
    summary = models.TextField('Краткое описание', max_length=600)
    cover = models.ImageField('Обложка', upload_to='articles/covers/', max_length=255)
    body = models.TextField('Текст статьи')
    is_published = models.BooleanField('Опубликовано', default=False)
    published_at = models.DateTimeField(
        'Дата первой публикации', null=True, blank=True,
        help_text='Заполнится при первой публикации. Можно изменить вручную для порядка статей.',
    )
    images = models.ManyToManyField(ArticleImage, related_name='articles', editable=False, blank=True)
    objects = PublicationQuerySet.as_manager()

    class Meta:
        verbose_name = 'Статья'
        verbose_name_plural = 'Статьи'
        ordering = ('-published_at', '-pk')
        indexes = [models.Index(fields=('is_published', '-published_at', '-id'), name='article_publication_order')]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('article_detail', kwargs={'slug': self.slug})

    @classmethod
    def slug_from_text(cls, value):
        from pict.models import transliterate_filename_part

        max_length = cls._meta.get_field('slug').max_length
        return transliterate_filename_part(value or '')[:max_length].rstrip('-') or 'statya'

    def _prepare_slug(self):
        using = router.db_for_write(type(self), instance=self)
        previous_slug = (
            type(self).objects.using(using).filter(pk=self.pk).values_list('slug', flat=True).first()
            if self.pk else None
        )
        self.slug = previous_slug or self.slug_from_text((self.slug or '').strip() or self.title)

    def full_clean(self, exclude=None, validate_unique=True, validate_constraints=True):
        # Адрес нормализуется до проверки SlugField, в том числе при обычном ORM-сохранении.
        self._prepare_slug()
        return super().full_clean(
            exclude=exclude, validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    def validate_unique(self, exclude=None):
        excluded = set(exclude or ())
        super().validate_unique(exclude=excluded | {'slug'})
        if 'slug' in excluded:
            return
        self._prepare_slug()
        using = router.db_for_write(type(self), instance=self)
        if type(self).objects.using(using).filter(slug=self.slug).exclude(pk=self.pk).exists():
            raise ValidationError({'slug': ValidationError(
                'Адрес «%(slug)s» уже используется другой статьёй. Введите другой адрес.',
                code='unique', params={'slug': self.slug},
            )})

    def clean(self):
        super().clean()
        self.title = self.title.strip()
        self.summary = self.summary.strip()
        errors = {}
        if not self.title:
            errors['title'] = 'Введите заголовок статьи.'
        if not self.summary:
            errors['summary'] = 'Введите краткое описание.'
        if errors:
            raise ValidationError(errors)
        try:
            self.body = sanitize_article_html(self.body)
        except ValidationError as error:
            raise ValidationError({'body': error.messages}) from error
        if not ArticleHTMLReferences(self.body).has_content:
            raise ValidationError({'body': 'Введите текст статьи.'})
        if self.is_published and self.published_at is None:
            self.published_at = timezone.now()

    def save(self, *args, **kwargs):
        from .article_media import delete_unreferenced_article_images, prepare_article_image

        using = kwargs.get('using') or router.db_for_write(type(self), instance=self)
        if self.cover and not self.cover._committed:
            self.cover = prepare_article_image(self.cover.file)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            kwargs['update_fields'] = set(update_fields) | {'published_at'}
        self.full_clean()
        with transaction.atomic(using=using):
            super().save(*args, **kwargs)
            if update_fields is None or 'body' in update_fields:
                references = ArticleHTMLReferences(self.body).image_names
                old_ids = set(self.images.values_list('pk', flat=True))
                new_images = list(ArticleImage.objects.using(using).filter(image__in=references))
                self.images.set(new_images)
                removed = old_ids - {image.pk for image in new_images}
                if removed:
                    transaction.on_commit(
                        lambda: delete_unreferenced_article_images(removed, using=using), using=using,
                    )


class LeadConnection(models.Model):
    """Подключение внешнего сервиса и правила передачи заявок."""

    class Provider(models.TextChoices):
        TELEGRAM = 'telegram', 'Telegram'
        EMAIL = 'email', 'Email'

    class EmailSecurity(models.TextChoices):
        STARTTLS = 'starttls', 'STARTTLS'
        SSL = 'ssl', 'SSL/TLS'

    name = models.CharField('Название', max_length=100)
    provider = models.CharField('Сервис', max_length=20, choices=Provider.choices)
    is_enabled = models.BooleanField('Включено', default=False)
    all_request_types = models.BooleanField('Все типы заявок', default=True)
    request_types = models.JSONField('Типы заявок', default=list, blank=True)
    recipients = models.JSONField('Получатели', default=list, blank=True)
    use_environment = models.BooleanField('Использовать настройки Telegram из окружения', default=False)
    telegram_token_encrypted = models.TextField(blank=True, editable=False)
    proxy_url_encrypted = models.TextField(blank=True, editable=False)
    smtp_host = models.CharField('SMTP-сервер', max_length=253, blank=True)
    smtp_port = models.PositiveIntegerField('Порт', default=587, validators=[MinValueValidator(1), MaxValueValidator(65535)])
    smtp_security = models.CharField('Защита соединения', max_length=20, choices=EmailSecurity.choices, default=EmailSecurity.STARTTLS)
    smtp_username = models.CharField('Логин SMTP', max_length=254, blank=True)
    smtp_password_encrypted = models.TextField(blank=True, editable=False)
    from_email = models.EmailField('Адрес отправителя', blank=True)
    from_name = models.CharField('Имя отправителя', max_length=100, blank=True)
    connect_timeout = models.PositiveSmallIntegerField('Тайм-аут соединения, сек.', default=3, validators=[MinValueValidator(1), MaxValueValidator(30)])
    read_timeout = models.PositiveSmallIntegerField('Тайм-аут ответа, сек.', default=5, validators=[MinValueValidator(1), MaxValueValidator(30)])
    configuration_error = models.TextField('Ошибка настройки', blank=True, editable=False)
    created_at = models.DateTimeField('Создано', auto_now_add=True)
    updated_at = models.DateTimeField('Изменено', auto_now=True)

    class Meta:
        verbose_name = 'Подключение'
        verbose_name_plural = 'Обработка заявок'
        ordering = ['name', 'pk']

    def __str__(self):
        return self.name

    def get_recipients(self):
        # Пустой адрес сохраняет прежнюю очередь при ещё не заполненном окружении.
        if self.use_environment and not self.recipients:
            return [settings.TELEGRAM_CHAT_ID]
        return list(self.recipients)

    def accepts(self, request_type):
        return self.all_request_types or request_type in self.request_types

    def get_legacy_recipient(self):
        """Старая очередь Telegram не содержала снимка адреса получателя."""
        if self.provider != self.Provider.TELEGRAM:
            return ''
        if settings.TELEGRAM_CHAT_ID:
            return settings.TELEGRAM_CHAT_ID
        return self.recipients[0] if len(self.recipients) == 1 else ''

    def clean(self):
        super().clean()
        from pict.models import ContactRequest

        errors = {}
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values_list('provider', flat=True).first()
            if previous is not None and previous != self.provider:
                errors['provider'] = 'Сервис существующего подключения нельзя изменить. Создайте новое подключение.'
        if self.use_environment and self.provider != self.Provider.TELEGRAM:
            errors['use_environment'] = 'Настройки окружения доступны только для Telegram.'
        if not isinstance(self.request_types, list) or any(
            not isinstance(value, str) or value not in ContactRequest.RequestType.values
            for value in self.request_types
        ):
            errors['request_types'] = 'Указан неизвестный тип заявки.'
        elif not self.all_request_types and not self.request_types:
            errors['request_types'] = 'Выберите хотя бы один тип заявки или включите все типы.'
        if not isinstance(self.recipients, list) or any(not isinstance(value, str) for value in self.recipients):
            errors['recipients'] = 'Получатели должны быть списком адресов.'
        else:
            normalized = []
            for address in self.recipients:
                address = address.strip()
                if len(address) > 254:
                    errors['recipients'] = 'Адрес получателя не должен превышать 254 символа.'
                    continue
                if self.provider == self.Provider.EMAIL:
                    address = address.lower()
                    try:
                        validate_email(address)
                    except ValidationError:
                        errors['recipients'] = 'Проверьте email каждого получателя.'
                elif not re.fullmatch(r'-?[0-9]+|@[A-Za-z0-9_]{5,32}', address):
                    errors['recipients'] = 'Для Telegram укажите числовой ID чата или @username.'
                else:
                    address = address.lower() if address.startswith('@') else str(int(address))
                if address not in normalized:
                    normalized.append(address)
            self.recipients = normalized
            if self.is_enabled and not normalized and not self.use_environment and 'recipients' not in errors:
                errors['recipients'] = 'Добавьте хотя бы одного получателя.'
        for field in ('smtp_host', 'smtp_username', 'from_name'):
            if any(ord(char) < 32 or ord(char) == 127 for char in getattr(self, field)):
                errors[field] = 'Управляющие символы недопустимы.'
        if self.smtp_host and (any(char.isspace() for char in self.smtp_host) or any(char in self.smtp_host for char in '/@')):
            errors['smtp_host'] = 'Укажите имя сервера без протокола, пути и учётных данных.'
        if self.is_enabled and self.provider == self.Provider.TELEGRAM:
            if not self.use_environment and not self.telegram_token_encrypted:
                errors['__all__'] = 'Для включения Telegram сохраните токен бота.'
        if self.is_enabled and self.provider == self.Provider.EMAIL:
            for field in ('smtp_host', 'from_email'):
                if not getattr(self, field):
                    errors[field] = 'Заполните это поле для включения email.'
            if self.smtp_username and not self.smtp_password_encrypted:
                errors['__all__'] = 'Для указанного SMTP-логина необходим пароль.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
