from django.db import migrations, models


def preserve_middle_positions(apps, schema_editor):
    quiz_model = apps.get_model('quiz', 'Quiz')
    quiz_model.objects.filter(launcher_position='left').update(
        launcher_position='left-middle'
    )
    quiz_model.objects.filter(launcher_position='right').update(
        launcher_position='right-middle'
    )


def restore_original_positions(apps, schema_editor):
    quiz_model = apps.get_model('quiz', 'Quiz')
    quiz_model.objects.filter(launcher_position='left-middle').update(
        launcher_position='left'
    )
    quiz_model.objects.filter(launcher_position='right-middle').update(
        launcher_position='right'
    )


class Migration(migrations.Migration):
    dependencies = [
        ('quiz', '0003_quiz_launcher_icon_and_position'),
    ]

    operations = [
        migrations.AlterField(
            model_name='quiz',
            name='launcher_position',
            field=models.CharField(
                choices=[
                    ('left', 'Слева'),
                    ('right', 'Справа'),
                    ('left-middle', 'Слева посередине'),
                    ('right-middle', 'Справа посередине'),
                ],
                default='left-middle',
                help_text=(
                    'На компьютере варианты «посередине» показываются вертикально. '
                    'На мобильном все левые и правые варианты сводятся '
                    'к соответствующему краю.'
                ),
                max_length=12,
                verbose_name='Сторона кнопки запуска',
            ),
        ),
        migrations.RunPython(
            preserve_middle_positions,
            reverse_code=restore_original_positions,
        ),
    ]
