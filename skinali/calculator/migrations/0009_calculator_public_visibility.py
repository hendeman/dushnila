from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0008_fixed_service_price'),
    ]

    operations = [
        migrations.AddField(
            model_name='calculatorsettings',
            name='is_enabled',
            field=models.BooleanField(default=False, help_text='Выключите, чтобы полностью скрыть калькулятор на сайте. Проверочный расчёт в админке остаётся доступным.', verbose_name='Показывать калькулятор на сайте'),
        ),
    ]
