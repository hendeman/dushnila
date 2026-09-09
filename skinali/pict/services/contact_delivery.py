import logging
from datetime import timedelta
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from pict.models import ContactRequestDelivery


logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_PROCESSING_TIMEOUT_SECONDS = 10 * 60
RETRY_DELAYS_SECONDS = (60, 5 * 60, 15 * 60, 60 * 60)


class TelegramConfigurationError(Exception):
    """Настройки Telegram отсутствуют или имеют некорректное значение."""


class TelegramDeliveryError(Exception):
    """Контролируемая ошибка Telegram с признаком возможности повтора."""

    def __init__(self, message, *, retryable, retry_after=None):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


def get_telegram_configuration():
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    missing = []
    if not token:
        missing.append('TELEGRAM_BOT_TOKEN')
    if not chat_id:
        missing.append('TELEGRAM_CHAT_ID')
    if missing:
        raise TelegramConfigurationError(
            f'Не заданы переменные окружения: {", ".join(missing)}.'
        )

    connect_timeout = settings.TELEGRAM_CONNECT_TIMEOUT
    read_timeout = settings.TELEGRAM_READ_TIMEOUT
    if connect_timeout <= 0 or read_timeout <= 0:
        raise TelegramConfigurationError(
            'Тайм-ауты Telegram должны быть положительными числами.'
        )

    proxy_url = settings.TELEGRAM_PROXY_URL
    if proxy_url:
        try:
            parsed_proxy = urlparse(proxy_url)
            proxy_port = parsed_proxy.port
        except ValueError as error:
            raise TelegramConfigurationError(
                'TELEGRAM_PROXY_URL содержит некорректный порт.'
            ) from error
        if (
            parsed_proxy.scheme not in {'http', 'https'}
            or not parsed_proxy.hostname
            or proxy_port is None
        ):
            raise TelegramConfigurationError(
                'TELEGRAM_PROXY_URL должен иметь формат http(s)://host:port.'
            )
    return token, chat_id, (connect_timeout, read_timeout), proxy_url


def format_contact_request_message(contact_request):
    created_at = timezone.localtime(contact_request.created_at)
    lines = [
        f'Новая заявка № {contact_request.pk}',
        f'Тип: {contact_request.get_request_type_display()}',
        f'Имя: {contact_request.name}',
    ]
    if contact_request.phone:
        lines.append(f'Телефон: {contact_request.phone}')
    if contact_request.email:
        lines.append(f'Email: {contact_request.email}')
    if contact_request.question:
        lines.append(f'Вопрос: {contact_request.question}')
    if contact_request.comment:
        lines.append(f'Комментарий: {contact_request.comment}')
    if contact_request.image_number is not None:
        lines.append(f'Изображение: №{contact_request.image_number}')
    lines.append(f'Создана: {created_at:%d.%m.%Y %H:%M}')
    return '\n'.join(lines)


def send_telegram_message(
    contact_request,
    *,
    token,
    chat_id,
    timeout,
    proxy_url='',
):
    """Отправляет обычный текст без parse_mode и возвращает ID сообщения."""
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    proxies = None
    if proxy_url:
        proxies = {'http': proxy_url, 'https': proxy_url}

    # Не учитываем HTTP_PROXY/NO_PROXY процесса: режим зависит только от .env.
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.post(
            url,
            json={
                'chat_id': chat_id,
                'text': format_contact_request_message(contact_request),
            },
            timeout=timeout,
            proxies=proxies,
        )
    except requests.Timeout as error:
        raise TelegramDeliveryError(
            'Telegram не ответил за отведённое время.',
            retryable=True,
        ) from error
    except requests.RequestException as error:
        # Текст исключения requests может содержать URL с токеном, поэтому не сохраняем его.
        raise TelegramDeliveryError(
            'Сетевая ошибка при обращении к Telegram.',
            retryable=True,
        ) from error
    finally:
        session.close()

    try:
        payload = response.json()
    except ValueError as error:
        raise TelegramDeliveryError(
            f'Telegram вернул некорректный ответ (HTTP {response.status_code}).',
            retryable=response.status_code >= 500,
        ) from error

    if not isinstance(payload, dict) or payload.get('ok') is not True:
        error_code = payload.get('error_code') if isinstance(payload, dict) else None
        description = payload.get('description') if isinstance(payload, dict) else None
        parameters = payload.get('parameters', {}) if isinstance(payload, dict) else {}
        retry_after = parameters.get('retry_after') if isinstance(parameters, dict) else None
        try:
            retry_after = max(1, int(retry_after)) if retry_after is not None else None
        except (TypeError, ValueError):
            retry_after = None

        retryable = (
            error_code is None
            or error_code == 429
            or (isinstance(error_code, int) and error_code >= 500)
        )
        message = description or f'Telegram отклонил запрос (HTTP {response.status_code}).'
        raise TelegramDeliveryError(
            str(message)[:1000],
            retryable=retryable,
            retry_after=retry_after,
        )

    result = payload.get('result')
    message_id = result.get('message_id') if isinstance(result, dict) else None
    if not isinstance(message_id, int) or isinstance(message_id, bool):
        raise TelegramDeliveryError(
            'Telegram подтвердил запрос без корректного ID сообщения.',
            retryable=True,
        )
    return message_id


def recover_stale_deliveries(*, stale_after_seconds, max_attempts):
    """Возвращает в очередь задачу, оборванную вместе с процессом-отправителем."""
    now = timezone.now()
    cutoff = now - timedelta(seconds=stale_after_seconds)
    stale = ContactRequestDelivery.objects.filter(
        channel=ContactRequestDelivery.Channel.TELEGRAM,
        status=ContactRequestDelivery.Status.PROCESSING,
        processing_started_at__lt=cutoff,
    )
    failed = stale.filter(attempts__gte=max_attempts).update(
        status=ContactRequestDelivery.Status.FAILED,
        next_attempt_at=None,
        processing_started_at=None,
        last_error='Предыдущая отправка была прервана на последней попытке.',
        updated_at=now,
    )
    retried = stale.filter(attempts__lt=max_attempts).update(
        status=ContactRequestDelivery.Status.RETRY,
        next_attempt_at=now,
        processing_started_at=None,
        last_error='Предыдущая отправка была прервана и возвращена в очередь.',
        updated_at=now,
    )
    return failed + retried


def claim_delivery(delivery_id, *, max_attempts):
    """Коротким атомарным UPDATE закрепляет задачу за одним процессом."""
    now = timezone.now()
    claimed = ContactRequestDelivery.objects.filter(
        pk=delivery_id,
        channel=ContactRequestDelivery.Channel.TELEGRAM,
        status__in=[
            ContactRequestDelivery.Status.PENDING,
            ContactRequestDelivery.Status.RETRY,
        ],
        attempts__lt=max_attempts,
    ).filter(
        Q(next_attempt_at__lte=now) | Q(next_attempt_at__isnull=True)
    ).update(
        status=ContactRequestDelivery.Status.PROCESSING,
        attempts=F('attempts') + 1,
        processing_started_at=now,
        updated_at=now,
    )
    if not claimed:
        return None
    return ContactRequestDelivery.objects.select_related('contact_request').get(
        pk=delivery_id
    )


def mark_delivery_sent(delivery, message_id):
    now = timezone.now()
    ContactRequestDelivery.objects.filter(
        pk=delivery.pk,
        status=ContactRequestDelivery.Status.PROCESSING,
    ).update(
        status=ContactRequestDelivery.Status.SENT,
        next_attempt_at=None,
        processing_started_at=None,
        sent_at=now,
        external_message_id=message_id,
        last_error='',
        updated_at=now,
    )


def mark_delivery_failed(delivery, error, *, max_attempts):
    exhausted = delivery.attempts >= max_attempts
    should_retry = error.retryable and not exhausted
    if should_retry:
        delay_index = min(delivery.attempts - 1, len(RETRY_DELAYS_SECONDS) - 1)
        delay_seconds = error.retry_after or RETRY_DELAYS_SECONDS[delay_index]
        status = ContactRequestDelivery.Status.RETRY
        next_attempt_at = timezone.now() + timedelta(seconds=delay_seconds)
    else:
        status = ContactRequestDelivery.Status.FAILED
        next_attempt_at = None

    ContactRequestDelivery.objects.filter(
        pk=delivery.pk,
        status=ContactRequestDelivery.Status.PROCESSING,
    ).update(
        status=status,
        next_attempt_at=next_attempt_at,
        processing_started_at=None,
        last_error=str(error)[:2000],
        updated_at=timezone.now(),
    )
    return status


def process_pending_telegram_deliveries(
    *,
    limit=20,
    max_attempts=DEFAULT_MAX_ATTEMPTS,
    stale_after_seconds=DEFAULT_PROCESSING_TIMEOUT_SECONDS,
):
    """Обрабатывает ограниченную пачку без транзакции вокруг сетевого запроса."""
    if limit <= 0 or max_attempts <= 0 or stale_after_seconds <= 0:
        raise ValueError('Параметры обработчика должны быть положительными числами.')

    token, chat_id, timeout, proxy_url = get_telegram_configuration()
    stats = {
        'recovered': recover_stale_deliveries(
            stale_after_seconds=stale_after_seconds,
            max_attempts=max_attempts,
        ),
        'claimed': 0,
        'sent': 0,
        'retry': 0,
        'failed': 0,
    }

    now = timezone.now()
    delivery_ids = list(
        ContactRequestDelivery.objects.filter(
            channel=ContactRequestDelivery.Channel.TELEGRAM,
            status__in=[
                ContactRequestDelivery.Status.PENDING,
                ContactRequestDelivery.Status.RETRY,
            ],
            attempts__lt=max_attempts,
        ).filter(
            Q(next_attempt_at__lte=now) | Q(next_attempt_at__isnull=True)
        ).order_by('next_attempt_at', 'id').values_list('id', flat=True)[:limit]
    )

    for delivery_id in delivery_ids:
        delivery = claim_delivery(delivery_id, max_attempts=max_attempts)
        if delivery is None:
            continue
        stats['claimed'] += 1

        try:
            message_id = send_telegram_message(
                delivery.contact_request,
                token=token,
                chat_id=chat_id,
                timeout=timeout,
                proxy_url=proxy_url,
            )
        except TelegramDeliveryError as error:
            status = mark_delivery_failed(
                delivery,
                error,
                max_attempts=max_attempts,
            )
            stats['retry' if status == ContactRequestDelivery.Status.RETRY else 'failed'] += 1
        except Exception as error:  # Защита очереди от зависания в processing.
            logger.error(
                'Непредвиденная ошибка доставки заявки %s: %s',
                delivery.contact_request_id,
                type(error).__name__,
            )
            status = mark_delivery_failed(
                delivery,
                TelegramDeliveryError(
                    'Непредвиденная ошибка обработчика Telegram.',
                    retryable=True,
                ),
                max_attempts=max_attempts,
            )
            stats['retry' if status == ContactRequestDelivery.Status.RETRY else 'failed'] += 1
        else:
            mark_delivery_sent(delivery, message_id)
            stats['sent'] += 1

    return stats
