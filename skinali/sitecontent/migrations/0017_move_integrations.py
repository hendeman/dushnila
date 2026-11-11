import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def _move_content_types(apps, schema_editor, source, destination):
    content_type = apps.get_model('contenttypes', 'ContentType')
    # Сохраняем идентификаторы типов, на которые ссылаются права и журнал admin.
    content_type.objects.using(schema_editor.connection.alias).filter(
        app_label=source,
        model__in=('integration', 'integrationrevision'),
    ).update(app_label=destination)


def forwards(apps, schema_editor):
    _move_content_types(apps, schema_editor, 'pict', 'sitecontent')


def backwards(apps, schema_editor):
    _move_content_types(apps, schema_editor, 'sitecontent', 'pict')


class Migration(migrations.Migration):
    dependencies = [
        ('sitecontent', '0016_restore_missing_page_menu_links'),
        ('pict', '0040_remove_integration_state'),
        ('contenttypes', '0002_remove_content_type_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Integration',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('name', models.CharField(max_length=200, verbose_name='Название')),
                        ('description', models.TextField(blank=True, verbose_name='Описание')),
                        ('is_enabled', models.BooleanField(db_index=True, default=False, verbose_name='Включена')),
                        ('position', models.PositiveIntegerField(default=0, verbose_name='Порядок подключения')),
                        ('page_paths', models.TextField(
                            blank=True,
                            help_text='Пусто — все публичные страницы. Или точные пути, по одному на строку: '
                                      '/about/ или /skinali/. Параметры после ? не учитываются. '
                                      'Для категории укажите её полный путь. Маски не поддерживаются.',
                            verbose_name='Страницы',
                        )),
                        ('head_html', models.TextField(blank=True, verbose_name='Код перед </head>')),
                        ('body_start_html', models.TextField(blank=True, verbose_name='Код сразу после <body>')),
                        ('body_end_html', models.TextField(blank=True, verbose_name='Код перед </body>')),
                        ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Изменена')),
                    ],
                    options={
                        'db_table': 'pict_integration',
                        'verbose_name': 'Интеграция',
                        'verbose_name_plural': 'Интеграции',
                        'ordering': ['position', 'pk'],
                    },
                ),
                migrations.CreateModel(
                    name='IntegrationRevision',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Дата')),
                        ('note', models.CharField(blank=True, max_length=200, verbose_name='Действие')),
                        ('snapshot', models.JSONField(verbose_name='Снимок настроек')),
                        ('author', models.ForeignKey(
                            null=True, on_delete=django.db.models.deletion.SET_NULL,
                            to=settings.AUTH_USER_MODEL, verbose_name='Автор',
                        )),
                        ('integration', models.ForeignKey(
                            on_delete=django.db.models.deletion.CASCADE, related_name='revisions',
                            to='sitecontent.integration', verbose_name='Интеграция',
                        )),
                    ],
                    options={
                        'db_table': 'pict_integrationrevision',
                        'verbose_name': 'Версия интеграции',
                        'verbose_name_plural': 'Версии интеграций',
                        'ordering': ['-pk'],
                    },
                ),
            ],
        ),
        migrations.RunPython(forwards, backwards),
    ]
