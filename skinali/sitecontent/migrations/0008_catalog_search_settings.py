from django.db import migrations, models


def create_catalog_search_settings(apps, schema_editor):
    Settings = apps.get_model('sitecontent', 'CatalogSearchSettings')
    Settings.objects.using(schema_editor.connection.alias).get_or_create(
        code='catalog', defaults={'use_lemmatization': True},
    )


class Migration(migrations.Migration):

    dependencies = [
        ('sitecontent', '0007_article_slug_input'),
    ]

    operations = [
        migrations.CreateModel(
            name='CatalogSearchSettings',
            fields=[
                ('code', models.CharField(default='catalog', editable=False, max_length=20, primary_key=True, serialize=False)),
                ('use_lemmatization', models.BooleanField(default=True, help_text='Включено — точные совпадения и начальные формы слов, без поиска по фрагментам. Выключено — поиск по фрагментам слов в тегах и синонимах.', verbose_name='Учитывать словоформы при поиске')),
            ],
            options={
                'verbose_name': 'Поиск по каталогу',
                'verbose_name_plural': 'Поиск по каталогу',
                'constraints': [models.CheckConstraint(condition=models.Q(('code', 'catalog')), name='catalog_search_settings_singleton')],
            },
        ),
        migrations.RunPython(create_catalog_search_settings, migrations.RunPython.noop),
    ]
