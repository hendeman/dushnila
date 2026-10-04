from datetime import timedelta

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.utils import timezone

from pict.services.photo_cleanup import (
    PHOTO_DIRECTORIES,
    PHOTO_TABLE_DIRECTORIES,
    get_referenced_photo_names,
    iter_stored_photos,
    remove_unused_photo,
)


class Command(BaseCommand):
    help = 'Находит неиспользуемые фотографии; удаляет только с флагом --delete.'

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            '--delete', action='store_true',
            help='Удалить найденные файлы и миниатюры.',
        )
        mode.add_argument(
            '--dry-run', action='store_true',
            help='Только отчёт (режим по умолчанию).',
        )
        parser.add_argument(
            '--min-age-hours', type=int, default=24,
            help='Минимальный возраст файла в часах, не менее 1 (по умолчанию 24).',
        )
        parser.add_argument(
            '--database', default=DEFAULT_DB_ALIAS, choices=tuple(connections),
            help='База данных, с которой сравниваются пути файлов.',
        )
        parser.add_argument(
            '--table', choices=('all', *PHOTO_TABLE_DIRECTORIES), default='all',
            help=(
                'Таблица: images — Изображения, finished-works — Готовые работы; '
                'по умолчанию all — обе таблицы.'
            ),
        )

    def handle(self, *args, **options):
        table = options['table']
        if table == 'all':
            directories = PHOTO_DIRECTORIES
        elif table in PHOTO_TABLE_DIRECTORIES:
            directories = (PHOTO_TABLE_DIRECTORIES[table],)
        else:
            raise CommandError('Неизвестная таблица: используйте all, images или finished-works.')
        if options['min_age_hours'] < 1:
            raise CommandError('--min-age-hours должен быть не менее 1.')
        try:
            cutoff = timezone.now() - timedelta(hours=options['min_age_hours'])
        except OverflowError as error:
            raise CommandError('Слишком большое значение --min-age-hours.') from error
        using = options['database']
        deleting = options['delete']
        counts = dict(candidates=0, bytes=0, deleted=0, retained=0, recent=0, errors=0)
        self.stdout.write('Режим удаления.' if deleting else 'Режим отчёта: файлы не удаляются.')
        self.stdout.write(f'Папки: {", ".join(directories)}.')
        try:
            referenced = get_referenced_photo_names(using=using)
            for name in iter_stored_photos(default_storage, directories=directories):
                if name in referenced:
                    continue
                try:
                    if default_storage.get_modified_time(name) >= cutoff:
                        counts['recent'] += 1
                        continue
                    size = default_storage.size(name)
                except FileNotFoundError:
                    continue
                counts['candidates'] += 1
                counts['bytes'] += size
                if deleting:
                    # Повторно проверяем ссылки и возраст непосредственно перед удалением.
                    result = remove_unused_photo(
                        name, storage=default_storage, using=using, older_than=cutoff,
                    )
                    if result == 'deleted':
                        counts['deleted'] += 1
                    elif result == 'failed':
                        counts['errors'] += 1
                    else:
                        counts['retained'] += 1
                    self.stdout.write(f'{result}: {name} ({size} байт)')
                else:
                    self.stdout.write(f'{name} ({size} байт)')
        except Exception as error:
            raise CommandError(f'Очистка прервана: {error}') from error
        self.stdout.write(
            f'Неиспользуемых файлов: {counts["candidates"]}; '
            f'объём оригиналов: {counts["bytes"]} байт; '
            f'удалено: {counts["deleted"]}; пропущено при перепроверке: {counts["retained"]}; '
            f'свежих файлов пропущено: {counts["recent"]}; ошибок: {counts["errors"]}.'
        )
        if counts['errors']:
            raise CommandError('Не все файлы удалены; подробности в журнале приложения.')
