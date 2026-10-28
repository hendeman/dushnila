from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0007_measurement_units'),
    ]

    operations = [
        migrations.AddField(
            model_name='calculatorservice',
            name='fixed_price',
            field=models.BooleanField(default=False, help_text='При выборе услуги сумма начисляется один раз, без ввода количества.', verbose_name='Фиксированная стоимость на весь заказ'),
        ),
    ]
