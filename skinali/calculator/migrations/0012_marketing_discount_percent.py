from decimal import Decimal, ROUND_HALF_UP, localcontext

import django.core.validators
from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError


def multiplier_to_percent(apps, schema_editor):
    settings = apps.get_model('calculator', 'CalculatorSettings')
    rows = settings.objects.using(schema_editor.connection.alias)
    with localcontext() as context:
        context.prec = 50
        for row in rows.values('code', 'marketing_discount_percent'):
            multiplier = row['marketing_discount_percent']
            percent = ((Decimal('1') - Decimal('1') / multiplier) * Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP,
            )
            rows.filter(code=row['code']).update(marketing_discount_percent=percent)


def percent_to_multiplier(apps, schema_editor):
    settings = apps.get_model('calculator', 'CalculatorSettings')
    rows = settings.objects.using(schema_editor.connection.alias)
    with localcontext() as context:
        context.prec = 50
        for row in rows.values('code', 'marketing_discount_percent'):
            percent = row['marketing_discount_percent']
            multiplier = (Decimal('100') / (Decimal('100') - percent)).quantize(
                Decimal('0.0001'), rounding=ROUND_HALF_UP,
            )
            if multiplier > Decimal('999.9999'):
                raise IrreversibleError('Маркетинговая скидка не помещается в прежний формат коэффициента.')
            rows.filter(code=row['code']).update(marketing_discount_percent=multiplier)


class Migration(migrations.Migration):
    dependencies = [('calculator', '0011_promotion_settings')]

    operations = [
        migrations.RemoveConstraint(model_name='calculatorsettings', name='calc_marketing_multiplier_gte1'),
        migrations.RenameField(
            model_name='calculatorsettings', old_name='marketing_multiplier', new_name='marketing_discount_percent',
        ),
        migrations.RunPython(multiplier_to_percent, percent_to_multiplier),
        migrations.AlterField(
            model_name='calculatorsettings', name='marketing_discount_percent',
            field=models.DecimalField(
                decimal_places=2, default=Decimal('0'), max_digits=5,
                validators=[django.core.validators.MinValueValidator(Decimal('0')), django.core.validators.MaxValueValidator(Decimal('99.99'))],
                verbose_name='Маркетинговая скидка, %',
                help_text='Скидка относительно зачёркнутой цены. При 20% итог 800 соответствует зачёркнутой цене 1000. 0 — без скидки.',
            ),
        ),
        migrations.AddConstraint(
            model_name='calculatorsettings',
            constraint=models.CheckConstraint(
                condition=models.Q(marketing_discount_percent__gte=0, marketing_discount_percent__lt=100),
                name='calc_marketing_discount_range',
            ),
        ),
    ]
