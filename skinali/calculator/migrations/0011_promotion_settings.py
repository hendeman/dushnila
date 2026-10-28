import django.core.validators
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0010_separate_settings_and_tariffs'),
    ]

    operations = [
        migrations.AddField(
            model_name='calculatorsettings',
            name='area_discount_percent',
            field=models.DecimalField(
                decimal_places=2, default=Decimal('0'), max_digits=5,
                validators=[django.core.validators.MinValueValidator(Decimal('0')), django.core.validators.MaxValueValidator(Decimal('100'))],
                verbose_name='Скидка за каждый следующий м², %',
                help_text='Первый м² — по полной цене. Каждый следующий дешевле предыдущего на указанный процент. Неполный метр считается пропорционально. Только для стекла и декорирования; 0 — без скидки.',
            ),
        ),
        migrations.AddField(
            model_name='calculatorsettings',
            name='marketing_multiplier',
            field=models.DecimalField(decimal_places=4, default=Decimal('1'), help_text='Множитель итога заказа для зачёркнутой цены. Цена к оплате не меняется. 1 — без повышения; 1,2 — повышение на 20%.', max_digits=7, validators=[django.core.validators.MinValueValidator(Decimal('1'))], verbose_name='Маркетинговый коэффициент'),
        ),
        migrations.AddConstraint(
            model_name='calculatorsettings',
            constraint=models.CheckConstraint(
                condition=models.Q(area_discount_percent__gte=0, area_discount_percent__lte=100),
                name='calc_area_discount_percent_range',
            ),
        ),
        migrations.AddConstraint(
            model_name='calculatorsettings',
            constraint=models.CheckConstraint(condition=models.Q(('marketing_multiplier__gte', 1)), name='calc_marketing_multiplier_gte1'),
        ),
    ]
