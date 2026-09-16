import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pict', '0027_taxonomy_seo_content'),
        ('sitecontent', '0003_sitepage_updated_at'),
    ]

    operations = [
        migrations.RenameField(
            model_name='pict',
            old_name='time_update',
            new_name='created_at',
        ),
        migrations.AddField(
            model_name='category',
            name='updated_at',
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                verbose_name='Время изменения публичного содержимого',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='finishedwork',
            name='updated_at',
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                verbose_name='Время изменения',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='pict',
            name='updated_at',
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                verbose_name='Время изменения',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='tagpict',
            name='updated_at',
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                verbose_name='Время изменения публичного содержимого',
            ),
            preserve_default=False,
        ),
    ]
