import re
import unicodedata

import django.db.models.deletion
from django.db import migrations, models


SEARCH_SEPARATOR_RE = re.compile(r'[\s,#:;–—-]+')


def normalize_search_value(value):
    normalized = unicodedata.normalize('NFKC', value or '')
    normalized = normalized.casefold().replace('ё', 'е')
    return SEARCH_SEPARATOR_RE.sub(' ', normalized).strip()


def populate_normalized_tags(apps, schema_editor):
    TagPict = apps.get_model('pict', 'TagPict')
    database_alias = schema_editor.connection.alias
    tags = list(TagPict.objects.using(database_alias).all())
    normalized_owners = {}

    for tag in tags:
        normalized_tag = normalize_search_value(tag.tag)
        if not any(character.isalnum() for character in normalized_tag):
            raise RuntimeError(
                f'Тег id={tag.pk} не содержит букв или цифр после нормализации.'
            )
        if len(normalized_tag) > 200:
            raise RuntimeError(
                f'Нормализованное значение тега id={tag.pk} длиннее 200 символов.'
            )
        if normalized_tag in normalized_owners:
            owner = normalized_owners[normalized_tag]
            raise RuntimeError(
                'Найдены конфликтующие теги после нормализации: '
                f'id={owner.pk} ({owner.tag!r}) и id={tag.pk} ({tag.tag!r}).'
            )
        normalized_owners[normalized_tag] = tag
        tag.normalized_tag = normalized_tag

    TagPict.objects.using(database_alias).bulk_update(
        tags,
        ['normalized_tag'],
        batch_size=500,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('pict', '0025_integrations'),
    ]

    operations = [
        migrations.AddField(
            model_name='tagpict',
            name='normalized_tag',
            field=models.CharField(
                editable=False,
                max_length=200,
                null=True,
                verbose_name='Нормализованное значение',
            ),
        ),
        migrations.RunPython(
            populate_normalized_tags,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='tagpict',
            name='normalized_tag',
            field=models.CharField(
                editable=False,
                max_length=200,
                unique=True,
                verbose_name='Нормализованное значение',
            ),
        ),
        migrations.CreateModel(
            name='TagAlias',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('alias', models.CharField(max_length=100, verbose_name='Синоним')),
                (
                    'normalized_alias',
                    models.CharField(
                        editable=False,
                        max_length=200,
                        unique=True,
                        verbose_name='Нормализованное значение',
                    ),
                ),
                (
                    'tag',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='search_aliases',
                        to='pict.tagpict',
                        verbose_name='Основной тег',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Поисковый синоним',
                'verbose_name_plural': 'Поисковые синонимы',
                'ordering': ['alias'],
            },
        ),
    ]
