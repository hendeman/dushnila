import django.core.validators
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0015_marketing_discount_description'),
    ]

    operations = [
        migrations.AddField(
            model_name='calculatorservice',
            name='max_quantity',
            field=models.DecimalField(blank=True, decimal_places=3, help_text='Необязательный предел ручного ввода. Для целого количества укажите целое число. Пустое поле — отдельный предел не задан.', max_digits=12, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.001'))], verbose_name='Максимальное количество'),
        ),
        migrations.AddConstraint(
            model_name='calculatorservice',
            constraint=models.CheckConstraint(condition=models.Q(('max_quantity__isnull', True), ('max_quantity__gte', Decimal('0.001')), _connector='OR'), name='calc_service_max_quantity_positive'),
        ),
    ]
