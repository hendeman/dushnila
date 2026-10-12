import re
import unicodedata
from functools import lru_cache

import django.db.models.deletion
from django.db import migrations, models


def populate_search_lemmas(apps, schema_editor):
    """Заполняет индекс исторических моделей правилами на момент внедрения."""
    Lemma = apps.get_model('pict', 'TagSearchLemma')
    using = schema_editor.connection.alias
    separator = re.compile(r'[\s,#:;–—-]+')
    russian_word = re.compile(r'[а-я]+')
    analyzer = None

    def normalize(value):
        value = unicodedata.normalize('NFKC', value or '').casefold().replace('ё', 'е')
        return separator.sub(' ', value).strip()

    @lru_cache(maxsize=2048)
    def lemmatize(term):
        nonlocal analyzer
        if not russian_word.fullmatch(term):
            return term
        if analyzer is None:
            from pymorphy3 import MorphAnalyzer

            analyzer = MorphAnalyzer(lang='ru')
        parsed = analyzer.parse(term)
        return normalize(parsed[0].normal_form) if parsed else term

    for model_name, owner_field, value_field in (
        ('TagPict', 'tag', 'normalized_tag'),
        ('TagAlias', 'alias', 'normalized_alias'),
    ):
        Owner = apps.get_model('pict', model_name)
        batch = []
        for owner in Owner.objects.using(using).only('pk', value_field).iterator(chunk_size=200):
            lemmas = {lemmatize(term) for term in normalize(getattr(owner, value_field)).split()}
            batch.extend(
                Lemma(lemma=lemma, **{f'{owner_field}_id': owner.pk})
                for lemma in sorted(lemmas)
            )
            if len(batch) >= 500:
                Lemma.objects.using(using).bulk_create(batch, batch_size=500)
                batch.clear()
        if batch:
            Lemma.objects.using(using).bulk_create(batch, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('pict', '0037_lead_deliveries'),
    ]

    operations = [
        migrations.CreateModel(
            name='TagSearchLemma',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('lemma', models.CharField(db_index=True, editable=False, max_length=200)),
                ('alias', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='search_lemmas', to='pict.tagalias')),
                ('tag', models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='search_lemmas', to='pict.tagpict')),
            ],
            options={
                'constraints': [models.CheckConstraint(condition=models.Q(models.Q(('alias__isnull', True), ('tag__isnull', False)), models.Q(('alias__isnull', False), ('tag__isnull', True)), _connector='OR'), name='search_lemma_has_one_owner'), models.UniqueConstraint(fields=('tag', 'lemma'), name='unique_tag_search_lemma'), models.UniqueConstraint(fields=('alias', 'lemma'), name='unique_alias_search_lemma')],
            },
        ),
        migrations.RunPython(populate_search_lemmas, migrations.RunPython.noop),
    ]
