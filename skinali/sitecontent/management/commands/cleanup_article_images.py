from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.utils import timezone

from sitecontent.article_media import delete_unreferenced_article_images
from sitecontent.models import ArticleImage


class Command(BaseCommand):
    help = 'Находит забытые загрузки редактора; удаление только с флагом --delete.'

    def add_arguments(self, parser):
        parser.add_argument('--delete', action='store_true')
        parser.add_argument('--min-age-hours', type=int, default=24)
        parser.add_argument('--database', default=DEFAULT_DB_ALIAS, choices=tuple(connections))

    def handle(self, *args, **options):
        if options['min_age_hours'] < 1:
            raise CommandError('Минимальный возраст должен быть не менее часа.')
        try:
            cutoff = timezone.now() - timedelta(hours=options['min_age_hours'])
        except OverflowError as error:
            raise CommandError('Слишком большой возраст.') from error
        using = options['database']
        images = ArticleImage.objects.using(using).filter(
            articles__isnull=True, created_at__lt=cutoff,
        ).only('id', 'image').order_by('pk')
        count = 0
        for image in images.iterator(chunk_size=100):
            self.stdout.write(image.image.name)
            if options['delete']:
                delete_unreferenced_article_images({image.pk}, using=using)
            count += 1
        self.stdout.write(f'Найдено: {count}. ' + ('Удаление выполнено.' if options['delete'] else 'Режим отчёта.'))
