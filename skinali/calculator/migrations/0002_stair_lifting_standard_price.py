import django.core.validators
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0001_calculator_admin'),
    ]

    operations = [
        migrations.AlterField(
            model_name='calculatorsettings',
            name='stair_lifting_min_price',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Базовая стоимость подъёма в пределах включённых этажей. Пустое поле — тариф не задан.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Стандартная стоимость подъёма'),
        ),
        migrations.AlterField(
            model_name='calculatorsettings',
            name='stair_lifting_price_per_panel_floor',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Доплата за каждый этаж сверх включённого порога. Для 3 и 4 панелей применяется коэффициент 2. Бригада — два человека. Пустое поле — тариф не задан.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Подъём одной панели на один этаж'),
        ),
    ]
