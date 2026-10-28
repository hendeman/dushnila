import django.core.validators
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0002_stair_lifting_standard_price'),
    ]

    operations = [
        migrations.AddField(
            model_name='calculatorsettings',
            name='stair_lifting_floor_1',
            field=models.PositiveIntegerField(default=9, validators=[django.core.validators.MaxValueValidator(999999999)], verbose_name='Включённый этаж: панелей 1'),
        ),
        migrations.AddField(
            model_name='calculatorsettings',
            name='stair_lifting_floor_2',
            field=models.PositiveIntegerField(default=4, validators=[django.core.validators.MaxValueValidator(999999999)], verbose_name='Включённый этаж: панелей 2'),
        ),
        migrations.AddField(
            model_name='calculatorsettings',
            name='stair_lifting_floor_3',
            field=models.PositiveIntegerField(default=3, validators=[django.core.validators.MaxValueValidator(999999999)], verbose_name='Включённый этаж: панелей 3'),
        ),
        migrations.AddField(
            model_name='calculatorsettings',
            name='stair_lifting_floor_4',
            field=models.PositiveIntegerField(default=2, validators=[django.core.validators.MaxValueValidator(999999999)], verbose_name='Включённый этаж: панелей 4'),
        ),
        migrations.AddField(
            model_name='calculatorsettings',
            name='stair_lifting_multiplier_1',
            field=models.DecimalField(decimal_places=2, default=Decimal('1.00'), max_digits=6, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Коэффициент сложности: панелей 1'),
        ),
        migrations.AddField(
            model_name='calculatorsettings',
            name='stair_lifting_multiplier_2',
            field=models.DecimalField(decimal_places=2, default=Decimal('1.00'), max_digits=6, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Коэффициент сложности: панелей 2'),
        ),
        migrations.AddField(
            model_name='calculatorsettings',
            name='stair_lifting_multiplier_3',
            field=models.DecimalField(decimal_places=2, default=Decimal('2.00'), max_digits=6, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Коэффициент сложности: панелей 3'),
        ),
        migrations.AddField(
            model_name='calculatorsettings',
            name='stair_lifting_multiplier_4',
            field=models.DecimalField(decimal_places=2, default=Decimal('2.00'), max_digits=6, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Коэффициент сложности: панелей 4'),
        ),
        migrations.AlterField(
            model_name='calculatorsettings',
            name='stair_lifting_price_per_panel_floor',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Доплата за каждый этаж сверх порога из таблицы с выбранным коэффициентом сложности. Бригада — два человека. Пустое поле — тариф не задан.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Подъём одной панели на один этаж'),
        ),
        migrations.AddConstraint(
            model_name='calculatorsettings',
            constraint=models.CheckConstraint(condition=models.Q(('stair_lifting_multiplier_1__gte', 0)), name='calc_stair_multiplier_1_gte0'),
        ),
        migrations.AddConstraint(
            model_name='calculatorsettings',
            constraint=models.CheckConstraint(condition=models.Q(('stair_lifting_multiplier_2__gte', 0)), name='calc_stair_multiplier_2_gte0'),
        ),
        migrations.AddConstraint(
            model_name='calculatorsettings',
            constraint=models.CheckConstraint(condition=models.Q(('stair_lifting_multiplier_3__gte', 0)), name='calc_stair_multiplier_3_gte0'),
        ),
        migrations.AddConstraint(
            model_name='calculatorsettings',
            constraint=models.CheckConstraint(condition=models.Q(('stair_lifting_multiplier_4__gte', 0)), name='calc_stair_multiplier_4_gte0'),
        ),
    ]
