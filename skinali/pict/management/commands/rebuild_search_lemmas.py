from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS, connections

from pict.models import TagAlias, TagPict


class Command(BaseCommand):
    help = 'Перестраивает сохранённые леммы тегов и поисковых синонимов.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--database', default=DEFAULT_DB_ALIAS, choices=list(connections),
            help='База данных, в которой нужно обновить поисковый индекс.',
        )

    def handle(self, *args, **options):
        using = options['database']
        counts = []
        for model in (TagPict, TagAlias):
            count = 0
            for owner in model.objects.using(using).order_by('pk').iterator(chunk_size=200):
                owner.rebuild_search_lemmas(using=using)
                count += 1
            counts.append(count)
        self.stdout.write(self.style.SUCCESS(
            f'Леммы обновлены: тегов — {counts[0]}, синонимов — {counts[1]}.'
        ))
