from django.core.management.base import BaseCommand, CommandError

from pict.services.contact_delivery import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_PROCESSING_TIMEOUT_SECONDS,
    TelegramConfigurationError,
    process_pending_telegram_deliveries,
)


class Command(BaseCommand):
    help = 'Отправляет ожидающие контактные заявки в Telegram.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=20,
            help='Максимальное количество доставок за один запуск.',
        )
        parser.add_argument(
            '--max-attempts',
            type=int,
            default=DEFAULT_MAX_ATTEMPTS,
            help='Число попыток до окончательного статуса ошибки.',
        )
        parser.add_argument(
            '--stale-after',
            type=int,
            default=DEFAULT_PROCESSING_TIMEOUT_SECONDS,
            help='Через сколько секунд оборванную отправку вернуть в очередь.',
        )

    def handle(self, *args, **options):
        try:
            stats = process_pending_telegram_deliveries(
                limit=options['limit'],
                max_attempts=options['max_attempts'],
                stale_after_seconds=options['stale_after'],
            )
        except (TelegramConfigurationError, ValueError) as error:
            raise CommandError(str(error)) from error

        self.stdout.write(self.style.SUCCESS(
            'Обработка Telegram завершена: '
            f'восстановлено={stats["recovered"]}, '
            f'взято={stats["claimed"]}, '
            f'отправлено={stats["sent"]}, '
            f'повтор={stats["retry"]}, '
            f'ошибка={stats["failed"]}.'
        ))
