from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('quiz', '0004_quiz_launcher_position_choices'),
    ]

    operations = [
        migrations.AlterField(
            model_name='quiz',
            name='page_paths',
            field=models.TextField(
                blank=True,
                help_text=(
                    'Пусто — все публичные страницы. Локальные пути по одному на строку: '
                    '/ — только главная, /skinali/ — только эта страница, '
                    '/polezno-znat/* — раздел и все вложенные страницы. '
                    'Без домена и параметров. Маска /* разрешена только в конце пути.'
                ),
                verbose_name='Страницы',
            ),
        ),
    ]
