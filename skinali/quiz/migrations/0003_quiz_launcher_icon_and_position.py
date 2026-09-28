from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('quiz', '0002_seed_skinali_quiz'),
    ]

    operations = [
        migrations.AddField(
            model_name='quiz',
            name='launcher_icon',
            field=models.ImageField(
                blank=True,
                default='',
                help_text=(
                    'Рекомендуется квадратное изображение с прозрачным фоном. '
                    'Если поле пустое, используется стандартная иконка.'
                ),
                max_length=255,
                upload_to='quiz/launcher/',
                verbose_name='Иконка кнопки запуска',
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='quiz',
            name='launcher_position',
            field=models.CharField(
                choices=[
                    ('left', 'Слева посередине'),
                    ('right', 'Справа посередине'),
                ],
                default='left',
                help_text=(
                    'На компьютере кнопка закреплена посередине выбранной стороны, '
                    'на мобильном — у выбранного края.'
                ),
                max_length=10,
                verbose_name='Сторона кнопки запуска',
            ),
        ),
    ]
