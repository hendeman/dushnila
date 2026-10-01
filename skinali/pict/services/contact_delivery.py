import logging
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from sitecontent.models import LeadConnection

from pict.models import ContactRequestDelivery
from . import email_delivery, telegram_delivery
from .delivery_errors import DeliveryConfigurationError, DeliveryError
from .delivery_messages import format_contact_request_message


logger = logging.getLogger(__name__)
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_PROCESSING_TIMEOUT_SECONDS = 10 * 60
RETRY_DELAYS_SECONDS = (60, 5 * 60, 15 * 60, 60 * 60)
ADAPTERS = {
    LeadConnection.Provider.TELEGRAM: telegram_delivery,
    LeadConnection.Provider.EMAIL: email_delivery,
}
WAITING_STATUSES = (ContactRequestDelivery.Status.PENDING, ContactRequestDelivery.Status.RETRY)


@transaction.atomic
def enqueue_contact_request(contact_request):
    """Создаёт недостающие доставки подходящим подключениям без внешних запросов."""
    created_count = 0
    for connection in LeadConnection.objects.filter(is_enabled=True):
        if not connection.accepts(contact_request.request_type):
            continue
        # Адрес исторической отправки неизвестен даже после смены источника настроек.
        if contact_request.deliveries.filter(connection=connection, recipient='').exists():
            continue
        for recipient in connection.get_recipients():
            _, created = ContactRequestDelivery.objects.get_or_create(
                contact_request=contact_request, connection=connection, recipient=recipient,
                defaults={'channel': connection.provider},
            )
            created_count += int(created)
    return created_count


@transaction.atomic
def enqueue_connection_test(connection):
    """Отдельная группа тестовых сообщений не создаёт фиктивные заявки клиентов."""
    recipients = connection.get_recipients()
    if not recipients or any(not value for value in recipients):
        raise ValidationError('Укажите получателей тестового сообщения.')
    get_configuration(connection)
    batch_id = uuid.uuid4()
    ContactRequestDelivery.objects.bulk_create([
        ContactRequestDelivery(connection=connection, channel=connection.provider, recipient=recipient, test_batch_id=batch_id)
        for recipient in recipients
    ])
    return len(recipients)


def get_configuration(connection):
    adapter = ADAPTERS.get(connection.provider)
    if adapter is None:
        raise DeliveryConfigurationError('Обработчик выбранного сервиса не установлен.')
    return adapter.get_configuration(connection)


def recover_stale_deliveries(*, stale_after_seconds, max_attempts):
    now = timezone.now()
    stale = ContactRequestDelivery.objects.filter(
        status=ContactRequestDelivery.Status.PROCESSING,
        processing_started_at__lt=now - timedelta(seconds=stale_after_seconds),
    )
    failed = stale.filter(attempts__gte=max_attempts).update(
        status=ContactRequestDelivery.Status.FAILED, next_attempt_at=None,
        processing_started_at=None, last_error='Предыдущая отправка была прервана на последней попытке.', updated_at=now,
    )
    retried = stale.filter(attempts__lt=max_attempts).update(
        status=ContactRequestDelivery.Status.RETRY, next_attempt_at=now,
        processing_started_at=None, last_error='Предыдущая отправка была прервана и возвращена в очередь.', updated_at=now,
    )
    return failed + retried


def ready_deliveries(*, max_attempts):
    return ContactRequestDelivery.objects.filter(
        status__in=WAITING_STATUSES, attempts__lt=max_attempts,
    ).filter(
        Q(next_attempt_at__lte=timezone.now()) | Q(next_attempt_at__isnull=True),
    ).filter(Q(connection__is_enabled=True) | Q(test_batch_id__isnull=False))


def claim_delivery(delivery_id, *, max_attempts):
    """Сетевой запрос выполняется после короткого атомарного захвата записи."""
    now = timezone.now()
    claimed = ready_deliveries(max_attempts=max_attempts).filter(pk=delivery_id).update(
        status=ContactRequestDelivery.Status.PROCESSING,
        attempts=F('attempts') + 1, processing_started_at=now, updated_at=now,
    )
    if not claimed:
        return None
    return ContactRequestDelivery.objects.select_related(
        'connection', 'contact_request', 'contact_request__quiz_submission',
    ).get(pk=delivery_id)


def owned_delivery(delivery):
    # Ответ старого процесса не должен перезаписывать новую попытку после восстановления.
    return ContactRequestDelivery.objects.filter(
        pk=delivery.pk, status=ContactRequestDelivery.Status.PROCESSING,
        processing_started_at=delivery.processing_started_at, attempts=delivery.attempts,
    )


def mark_delivery_sent(delivery, message_id):
    return owned_delivery(delivery).update(
        status=ContactRequestDelivery.Status.SENT, next_attempt_at=None, processing_started_at=None,
        sent_at=timezone.now(), external_message_id=message_id, last_error='', updated_at=timezone.now(),
    )


def mark_delivery_failed(delivery, error, *, max_attempts):
    if error.retryable and delivery.attempts < max_attempts:
        delay = error.retry_after or RETRY_DELAYS_SECONDS[min(delivery.attempts - 1, len(RETRY_DELAYS_SECONDS) - 1)]
        status = ContactRequestDelivery.Status.RETRY
        next_attempt = timezone.now() + timedelta(seconds=delay)
    else:
        status = ContactRequestDelivery.Status.FAILED
        next_attempt = None
    owned_delivery(delivery).update(
        status=status, next_attempt_at=next_attempt, processing_started_at=None,
        last_error=str(error)[:2000], updated_at=timezone.now(),
    )
    return status


def retry_failed_deliveries(queryset):
    return queryset.filter(status__in=[ContactRequestDelivery.Status.RETRY, ContactRequestDelivery.Status.FAILED]).update(
        status=ContactRequestDelivery.Status.RETRY, attempts=0, next_attempt_at=timezone.now(),
        processing_started_at=None, last_error='', updated_at=timezone.now(),
    )


def process_pending_deliveries(*, limit=20, max_attempts=DEFAULT_MAX_ATTEMPTS, stale_after_seconds=DEFAULT_PROCESSING_TIMEOUT_SECONDS):
    if limit <= 0 or max_attempts <= 0 or stale_after_seconds <= 0:
        raise ValueError('Параметры обработчика должны быть положительными числами.')
    stats = {
        'recovered': recover_stale_deliveries(stale_after_seconds=stale_after_seconds, max_attempts=max_attempts),
        'claimed': 0, 'sent': 0, 'retry': 0, 'failed': 0, 'configuration_errors': 0,
    }
    configurations = {}
    legacy_recipients = {}
    unresolved_connections = []
    connection_ids = ready_deliveries(max_attempts=max_attempts).order_by().values('connection_id').distinct()
    for connection in LeadConnection.objects.filter(pk__in=connection_ids):
        try:
            configurations[connection.pk] = get_configuration(connection)
        except (DeliveryConfigurationError, ValidationError) as error:
            configurations.pop(connection.pk, None)
            message = '; '.join(error.messages) if isinstance(error, ValidationError) else str(error)
            LeadConnection.objects.filter(pk=connection.pk).update(configuration_error=message)
            stats['configuration_errors'] += 1
        else:
            legacy_recipients[connection.pk] = connection.get_legacy_recipient()
            if not legacy_recipients[connection.pk] and ready_deliveries(max_attempts=max_attempts).filter(connection=connection, recipient='').exists():
                unresolved_connections.append(connection.pk)
                LeadConnection.objects.filter(pk=connection.pk).update(
                    configuration_error='Для старой очереди укажите TELEGRAM_CHAT_ID или единственного Telegram-получателя. Отправки с сохранёнными адресами продолжаются.',
                )
                stats['configuration_errors'] += 1
            else:
                LeadConnection.objects.filter(pk=connection.pk).exclude(configuration_error='').update(configuration_error='')

    delivery_ids = list(ready_deliveries(max_attempts=max_attempts).filter(
        connection_id__in=configurations,
    ).exclude(recipient='', connection_id__in=unresolved_connections).order_by('next_attempt_at', 'id').values_list('id', flat=True)[:limit])
    for delivery_id in delivery_ids:
        delivery = claim_delivery(delivery_id, max_attempts=max_attempts)
        if delivery is None:
            continue
        stats['claimed'] += 1
        try:
            if not delivery.recipient:
                delivery.recipient = legacy_recipients[delivery.connection_id]
                owned_delivery(delivery).update(recipient=delivery.recipient)
            if not delivery.recipient:
                raise DeliveryError('Для отправки не указан получатель.', retryable=False)
            message_id = ADAPTERS[delivery.connection.provider].send(delivery, configurations[delivery.connection_id])
        except DeliveryError as error:
            status = mark_delivery_failed(delivery, error, max_attempts=max_attempts)
            stats['retry' if status == ContactRequestDelivery.Status.RETRY else 'failed'] += 1
        except Exception as error:
            logger.error('Непредвиденная ошибка доставки %s: %s', delivery.pk, type(error).__name__)
            status = mark_delivery_failed(delivery, DeliveryError('Непредвиденная ошибка обработчика доставки.', retryable=True), max_attempts=max_attempts)
            stats['retry' if status == ContactRequestDelivery.Status.RETRY else 'failed'] += 1
        else:
            stats['sent'] += mark_delivery_sent(delivery, message_id)
    return stats
