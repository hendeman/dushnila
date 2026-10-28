import django.core.validators
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0012_marketing_discount_percent'),
    ]

    operations = [
        migrations.AlterField(
            model_name='calculatorsettings',
            name='area_discount_percent',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), help_text='Скидка действует только при общей площади больше 2 м². Тогда первый м² — по полной цене, каждый следующий дешевле предыдущего на указанный процент. Неполный метр считается пропорционально. Только для стекла и декорирования; 0 — без скидки.', max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal('0')), django.core.validators.MaxValueValidator(Decimal('100'))], verbose_name='Скидка за каждый следующий м², %'),
        ),
    ]
