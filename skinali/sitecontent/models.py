import re
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
from django.db import models


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
