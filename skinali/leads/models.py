import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, validate_email
from django.db import models
from django.utils import timezone


class ContactRequest(models.Model):
    """Заявка посетителя, прошедшая серверную валидацию и антиспам-проверки."""

    class RequestType(models.TextChoices):
        CALLBACK = 'callback', 'Обратный звонок'
        QUESTION = 'question', 'Вопрос'
        EMAIL_MESSAGE = 'email_message', 'Сообщение по email'
        IMAGE_PURCHASE = 'image_purchase', 'Покупка изображения'
        QUIZ = 'quiz', 'Квиз'
        CALCULATOR_ORDER = 'calculator_order', 'Заказ из калькулятора'

    request_type = models.CharField(
        max_length=20,
        choices=RequestType.choices,
        verbose_name='Тип заявки',
    )
    name = models.CharField(max_length=20, verbose_name='Имя')
    phone = models.CharField(max_length=20, blank=True, verbose_name='Телефон')
    calculation_url = models.CharField(
        'Ссылка на расчёт', max_length=8192, blank=True, default='', editable=False,
    )
    email = models.EmailField(max_length=254, blank=True, default='', verbose_name='Email')
    question = models.CharField(max_length=250, blank=True, verbose_name='Вопрос')
    comment = models.CharField(
        max_length=250,
        blank=True,
        default='',
        verbose_name='Комментарий',
    )
    catalog_image = models.ForeignKey(
        'pict.Pict',
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
        db_table = 'pict_contactrequest'
        verbose_name = 'Заявка'
        verbose_name_plural = 'Заявки'
        ordering = ['-created_at', '-id']


class ContactRequestDelivery(models.Model):
    """Состояние доставки заявки или теста одному получателю подключения."""

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
        null=True,
        blank=True,
    )
    connection = models.ForeignKey('LeadConnection', on_delete=models.PROTECT, related_name='deliveries', verbose_name='Подключение')
    recipient = models.CharField('Получатель', max_length=254, blank=True)
    test_batch_id = models.UUIDField('Группа тестовой отправки', null=True, blank=True, editable=False)
    message_key = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
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
    external_message_id = models.CharField(
        max_length=255,
        default='',
        blank=True,
        verbose_name='ID внешнего сообщения',
    )
    last_error = models.TextField(blank=True, verbose_name='Последняя ошибка')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Время создания')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Время изменения')

    def __str__(self):
        subject = f'заявка № {self.contact_request_id}' if self.contact_request_id else 'тест подключения'
        return f'{self.get_channel_display()}: {subject}'

    class Meta:
        db_table = 'pict_contactrequestdelivery'
        verbose_name = 'Доставка заявки'
        verbose_name_plural = 'Доставки заявок'
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['contact_request', 'connection', 'recipient'],
                name='unique_request_connection_target',
            ),
            models.CheckConstraint(
                condition=(models.Q(contact_request__isnull=False, test_batch_id__isnull=True) | models.Q(contact_request__isnull=True, test_batch_id__isnull=False)),
                name='delivery_request_or_test',
            ),
        ]
        indexes = [
            models.Index(
                fields=['connection', 'status', 'next_attempt_at'],
                name='pict_connection_due_idx',
            ),
        ]


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
        db_table = 'sitecontent_leadconnection'
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
