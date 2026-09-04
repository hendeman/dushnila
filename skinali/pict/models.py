from django.db import models
from django.urls import reverse
from django.utils import timezone


class PublicationQuerySet(models.QuerySet):
    """Единая выборка контента, разрешённого к показу на публичном сайте."""

    def published(self):
        return self.filter(is_published=True)


class Color(models.Model):
    color = models.CharField(max_length=100, verbose_name='Цвет')
    slug_color = models.SlugField(max_length=100, unique=True, db_index=True, verbose_name='Slug')

    def __str__(self):
        return self.color

    class Meta:
        verbose_name = 'Цвет'
        verbose_name_plural = 'Цвета'


class TagPict(models.Model):
    tag = models.CharField(max_length=100, db_index=True, verbose_name='Ключевое слово')
    slug = models.SlugField(max_length=100, db_index=True, unique=True, verbose_name="Slug")

    def __str__(self):
        return self.tag

    def get_absolute_url(self):
        return reverse('tag', kwargs={'tag_slug': self.slug})

    class Meta:
        verbose_name = 'Ключевое слово'
        verbose_name_plural = 'Ключевые слова'


class Category(models.Model):
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



