import django.core.validators
from django.db import migrations, models


def transfer_public_hints(apps, schema_editor):
    alias = schema_editor.connection.alias
    apps.get_model('calculator', 'CalculatorTariffs').objects.using(alias).update(
        panels_hint=('Укажите ширину слева и высоту справа в миллиметрах. Пустая панель не учитывается. '
                     'Допустимый размер каждой стороны: от 1 до 6000 мм.'),
        glass_type_hint='Выберите стекло для панелей. Стоимость рассчитывается по общей площади.',
        decoration_type_hint='Выберите оформление стекла. Доплата рассчитывается по общей площади панелей.',
        stair_lifting_hint=('Для подъёма по лестнице укажите этаж и количество панелей более 0,5 м². '
                            'Доплата зависит от выбранного способа подъёма.'),
    )
    services = apps.get_model('calculator', 'CalculatorService').objects.using(alias)
    for service in services.all().iterator():
        if not service.has_price:
            hint = 'Эта услуга включена в стоимость. Доплата не начисляется.'
        elif service.fixed_price:
            hint = 'Отметьте, если услуга нужна. Фиксированная стоимость начисляется один раз за весь заказ.'
        elif service.use_panel_area:
            hint = 'Отметьте, если услуга нужна. Количество рассчитывается по общей площади панелей.'
        else:
            hint = 'Отметьте, если услуга нужна, и укажите количество в появившемся поле.'
        services.filter(pk=service.pk).update(hint=hint)


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0013_area_discount_activation_threshold'),
    ]

    operations = [
        migrations.AddField(
            model_name='calculatorservice',
            name='hint',
            field=models.TextField(blank=True, default='', help_text='Обычный текст без HTML. Оставьте пустым, чтобы скрыть значок «?» на сайте.', max_length=2000, validators=[django.core.validators.MaxLengthValidator(2000)], verbose_name='Подсказка на сайте'),
        ),
        migrations.AddField(
            model_name='calculatortariffs',
            name='decoration_type_hint',
            field=models.TextField(blank=True, default='', help_text='Обычный текст без HTML. Оставьте пустым, чтобы скрыть значок «?» на сайте.', max_length=2000, validators=[django.core.validators.MaxLengthValidator(2000)], verbose_name='Подсказка к декорированию'),
        ),
        migrations.AddField(
            model_name='calculatortariffs',
            name='glass_type_hint',
            field=models.TextField(blank=True, default='', help_text='Обычный текст без HTML. Оставьте пустым, чтобы скрыть значок «?» на сайте.', max_length=2000, validators=[django.core.validators.MaxLengthValidator(2000)], verbose_name='Подсказка к выбору стекла'),
        ),
        migrations.AddField(
            model_name='calculatortariffs',
            name='panels_hint',
            field=models.TextField(blank=True, default='', help_text='Обычный текст без HTML. Оставьте пустым, чтобы скрыть значок «?» на сайте.', max_length=2000, validators=[django.core.validators.MaxLengthValidator(2000)], verbose_name='Подсказка к размерам панелей'),
        ),
        migrations.AddField(
            model_name='calculatortariffs',
            name='stair_lifting_hint',
            field=models.TextField(blank=True, default='', help_text='Обычный текст без HTML. Оставьте пустым, чтобы скрыть значок «?» на сайте.', max_length=2000, validators=[django.core.validators.MaxLengthValidator(2000)], verbose_name='Подсказка к подъёму'),
        ),
        migrations.RunPython(transfer_public_hints, migrations.RunPython.noop),
    ]
