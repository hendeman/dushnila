# Создано Django 5.2.17: интеграции публичного сайта и история их версий.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pict', '0024_contactrequest_viewed_at'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Integration',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='Название')),
                ('description', models.TextField(blank=True, verbose_name='Описание')),
                ('is_enabled', models.BooleanField(db_index=True, default=False, verbose_name='Включена')),
                ('position', models.PositiveIntegerField(default=0, verbose_name='Порядок подключения')),
                ('page_paths', models.TextField(blank=True, help_text='Пусто — все публичные страницы. Или точные пути, по одному на строку: /about/ или /skinali/. Параметры после ? не учитываются. Для категории укажите её полный путь. Маски не поддерживаются.', verbose_name='Страницы')),
                ('head_html', models.TextField(blank=True, verbose_name='Код перед </head>')),
                ('body_start_html', models.TextField(blank=True, verbose_name='Код сразу после <body>')),
                ('body_end_html', models.TextField(blank=True, verbose_name='Код перед </body>')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Изменена')),
            ],
            options={
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
                ('author', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='Автор')),
                ('integration', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='revisions', to='pict.integration', verbose_name='Интеграция')),
            ],
            options={
                'verbose_name': 'Версия интеграции',
                'verbose_name_plural': 'Версии интеграций',
                'ordering': ['-pk'],
            },
        ),
    ]
