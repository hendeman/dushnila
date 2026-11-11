import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
from django.db import models
from django.db import router, transaction
from django.conf import settings
from django.core.validators import MaxLengthValidator
from django.urls import reverse
from django.utils import timezone
from pict.page_paths import matches_public_page_path, normalize_public_page_paths

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
    """Название и SEO-настройки постоянной внутренней страницы сайта."""

    class Code(models.TextChoices):
        HOME = 'home', 'Главная страница'
        CATALOG = 'skinali', 'Каталог скинали'
        PRICE = 'price', 'Цена'
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
    menu_item = models.ForeignKey(
        'MenuItem', on_delete=models.SET_NULL, null=True, blank=True, related_name='site_pages',
        editable=False,
    )

    @property
    def navigation_title(self):
        if self.menu_item_id:
            title = self.menu_item.title.strip()
            if title:
                return title
        return self.get_code_display()

    @classmethod
    def bind_unlinked_menu_item(cls, item, *, using, changed_at):
        """Восстанавливает только пустую связь при сохранении точного пути раздела."""
        code = next((code for code in cls.Code if item.url == reverse(code)), None)
        if code is None:
            return 0
        candidates = MenuItem.objects.using(using).filter(
            menu_id=item.menu_id, menu__code=SiteMenu.MAIN_CODE, url=item.url,
        ).order_by('position', 'pk')
        return (
            cls.objects.using(using).filter(pk=code, menu_item__isnull=True)
            .filter(models.Exists(candidates))
            .update(
                menu_item_id=models.Subquery(candidates.values('pk')[:1]),
                updated_at=changed_at,
            )
        )

    @classmethod
    def for_request(cls, request):
        """Один общий запрос названий и SEO-полей на время HTTP-запроса."""
        if not hasattr(request, '_sitecontent_pages'):
            request._sitecontent_pages = {
                page.code: page
                for page in cls.objects.select_related('menu_item').only(
                    'code', 'seo_title', 'seo_description', 'menu_item__title',
                )
            }
        return request._sitecontent_pages

    class Meta:
        verbose_name = 'Страница сайта'
        verbose_name_plural = 'Страницы сайта'

    def __str__(self):
        return self.navigation_title


class CatalogSearchSettings(models.Model):
    """Единая системная карточка настроек сайта с типизированными полями."""

    CODE = 'catalog'
    DEFAULT_HEADER_SCHEDULE = 'ПН–ВС · ПРИЁМ ЗАКАЗОВ 10:00–21:00'
    code = models.CharField(max_length=20, primary_key=True, default=CODE, editable=False)
    header_schedule = models.CharField(
        'Текст в шапке', max_length=40, blank=True, default=DEFAULT_HEADER_SCHEDULE,
        help_text=(
            'До 40 символов: режим работы, акция или другая короткая информация. '
            'Общий текст для всех размеров экрана. Пустое поле скрывает подпись.'
        ),
    )
    header_menu_item = models.ForeignKey(
        'MenuItem', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        limit_choices_to={'menu__code': 'main'},
        verbose_name='Пункт рядом с меню',
        help_text=(
            'Ссылка с иконкой в свёрнутой шапке. Название и адрес берутся из выбранного пункта '
            'и не зависят от порядка меню. Скрытый пункт не показывается в шапке.'
        ),
    )
    use_lemmatization = models.BooleanField(
        'Учитывать словоформы при поиске', default=True,
        help_text=(
            'Включено — точные совпадения и начальные формы слов, без поиска по фрагментам. '
            'Выключено — поиск по фрагментам слов в тегах и синонимах.'
        ),
    )

    @classmethod
    def is_lemmatization_enabled(cls):
        value = cls.objects.filter(pk=cls.CODE).values_list('use_lemmatization', flat=True).first()
        return True if value is None else value

    def __str__(self):
        return str(self._meta.verbose_name)

    class Meta:
        verbose_name = 'Настройки сайта'
        verbose_name_plural = 'Настройки сайта'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code='catalog'), name='catalog_search_settings_singleton',
            ),
        ]


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
    title = models.CharField(
        'Название', max_length=100,
        help_text='Для связанной страницы также задаёт название в хлебных крошках и «Страницах сайта».',
    )
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


class ValidatedPriceTableContent(models.Model):
    """Проверяет текст и порядок информационных таблиц при обычном сохранении."""

    position = models.PositiveIntegerField('Порядок', default=0, db_index=True)

    def clean(self):
        super().clean()
        errors = {}
        for field in self._meta.fields:
            if isinstance(field, (models.CharField, models.TextField)):
                value = getattr(self, field.name)
                if isinstance(value, str):
                    setattr(self, field.name, value.strip())
                    if not field.blank and not value.strip():
                        errors[field.name] = 'Заполните это поле.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    class Meta:
        abstract = True
        ordering = ['position', 'pk']


class PriceTable(ValidatedPriceTableContent):
    """Самостоятельная информационная таблица страницы «Цена»."""

    title = models.CharField('Заголовок', max_length=200)
    service_column = models.CharField('Название первой колонки', max_length=100, default='Услуга')
    price_column = models.CharField('Название второй колонки', max_length=100, default='Стоимость')
    note = models.TextField(
        'Примечание под таблицей', max_length=2000, blank=True, validators=[MaxLengthValidator(2000)],
    )
    is_published = models.BooleanField('Показывать на сайте', default=False)

    class Meta(ValidatedPriceTableContent.Meta):
        verbose_name = 'Таблица страницы «Цена»'
        verbose_name_plural = 'Таблицы страницы «Цена»'

    def __str__(self):
        return self.title


class PriceTableRow(ValidatedPriceTableContent):
    """Строка услуги с текстовой стоимостью без связи с тарифами калькулятора."""

    table = models.ForeignKey(PriceTable, on_delete=models.CASCADE, related_name='rows', verbose_name='Таблица')
    description = models.TextField('Услуга / описание', max_length=2000, validators=[MaxLengthValidator(2000)])
    price = models.TextField(
        'Стоимость', max_length=500, validators=[MaxLengthValidator(500)],
        help_text='Например: Бесплатно, от 25 руб., 3 руб. за каждый макет или По согласованию.',
    )

    class Meta(ValidatedPriceTableContent.Meta):
        verbose_name = 'Строка таблицы'
        verbose_name_plural = 'Строки таблицы'

    def __str__(self):
        return self.description[:80]


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
        kwargs['using'] = using
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
        db_table = 'pict_integration'
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
        db_table = 'pict_integrationrevision'
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
