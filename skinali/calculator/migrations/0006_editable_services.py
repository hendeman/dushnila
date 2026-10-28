import calculator.models
import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


LEGACY_SERVICES = (
    ('backlight', 'Подсветка', 'show_backlight', 'backlight_price_per_meter', 'Подсветка: цена за погонный метр', 'Длина, пог. м', 'пог. м', False, False),
    ('railing', 'Рейлинги', 'show_railing', 'railing_price_per_meter', 'Рейлинги: цена за погонный метр', 'Длина, пог. м', 'пог. м', False, False),
    ('sockets', 'Блоки розеток', 'show_sockets', 'socket_price_per_block', 'Цена за один блок розеток', 'Количество блоков розеток', 'шт.', False, True),
    ('hydrophobic', 'Гидрофобный слой', 'show_hydrophobic', 'hydrophobic_price_per_sqm', 'Гидрофобный слой: доплата за 1 м²', 'Площадь, м²', 'м²', True, False),
    ('delivery', 'Доставка', 'show_delivery', 'delivery_price_per_km', 'Доставка: цена за 1 км', 'Расстояние доставки, км', 'км', False, False),
    ('measurement', 'Замер', 'show_measurement', None, 'Замер', 'Количество', 'заказ', False, True),
    ('installation', 'Монтаж', 'show_installation', None, 'Монтаж', 'Количество', 'заказ', False, True),
)


def copy_services(apps, schema_editor):
    settings_model = apps.get_model('calculator', 'CalculatorSettings')
    service_model = apps.get_model('calculator', 'CalculatorService')
    alias = schema_editor.connection.alias
    rows = []
    for settings in settings_model.objects.using(alias).all():
        for position, (code, name, visibility, price, label, quantity, unit, area, whole) in enumerate(LEGACY_SERVICES, 1):
            rows.append(service_model(
                settings_id=settings.pk, code=code, name=name,
                visibility_label=str(settings_model._meta.get_field(visibility).verbose_name),
                price_label=label, is_visible=getattr(settings, visibility), has_price=price is not None,
                price_per_unit=getattr(settings, price) if price else None,
                quantity_label=quantity, unit=unit, use_panel_area=area, whole_quantity=whole, position=position * 10,
            ))
    service_model.objects.using(alias).bulk_create(rows)


def restore_services(apps, schema_editor):
    settings_model = apps.get_model('calculator', 'CalculatorSettings')
    service_model = apps.get_model('calculator', 'CalculatorService')
    alias = schema_editor.connection.alias
    for settings in settings_model.objects.using(alias).all():
        for code, _name, visibility, price, *_unused in LEGACY_SERVICES:
            service = service_model.objects.using(alias).filter(settings_id=settings.pk, code=code).first()
            values = {visibility: bool(service and service.is_visible)}
            if price:
                values[price] = service.price_per_unit if service else None
            settings_model.objects.using(alias).filter(pk=settings.pk).update(**values)


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0005_stair_panels_limit_six'),
    ]

    operations = [
        migrations.CreateModel(
            name='CalculatorService',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(default=calculator.models.service_code, editable=False, max_length=32, unique=True)),
                ('name', models.CharField(max_length=100, verbose_name='Название услуги')),
                ('visibility_label', models.CharField(blank=True, max_length=180, verbose_name='Подпись чекбокса показа')),
                ('price_label', models.CharField(blank=True, max_length=200, verbose_name='Описание тарифа')),
                ('is_visible', models.BooleanField(default=False, verbose_name='Показывать услугу')),
                ('has_price', models.BooleanField(default=True, help_text='Выключите, если услуга включена в стоимость.', verbose_name='Указывать стоимость')),
                ('price_per_unit', models.DecimalField(blank=True, decimal_places=2, help_text='Пустое поле — тариф не задан. Укажите 0 для бесплатной услуги.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Цена за одну единицу')),
                ('quantity_label', models.CharField(default='Количество', max_length=100, verbose_name='Название поля количества')),
                ('unit', models.CharField(blank=True, default='ед.', help_text='Подпись в расчёте, например м, км, шт. На формулу не влияет.', max_length=30, verbose_name='Обозначение единицы')),
                ('use_panel_area', models.BooleanField(default=False, help_text='Общая площадь вместо ручного ввода количества.', verbose_name='Количество по площади панелей')),
                ('whole_quantity', models.BooleanField(default=False, verbose_name='Только целое количество')),
                ('position', models.PositiveIntegerField(default=0, verbose_name='Порядок')),
                ('settings', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='services', to='calculator.calculatorsettings')),
            ],
            options={
                'verbose_name': 'Услуга калькулятора',
                'verbose_name_plural': 'Дополнительные услуги',
                'ordering': ('position', 'pk'),
            },
        ),
        migrations.RunPython(copy_services, restore_services),
        migrations.RemoveConstraint(
            model_name='calculatorsettings',
            name='calc_backlight_price_per_meter_gte0',
        ),
        migrations.RemoveConstraint(
            model_name='calculatorsettings',
            name='calc_railing_price_per_meter_gte0',
        ),
        migrations.RemoveConstraint(
            model_name='calculatorsettings',
            name='calc_socket_price_per_block_gte0',
        ),
        migrations.RemoveConstraint(
            model_name='calculatorsettings',
            name='calc_hydrophobic_price_per_sqm_gte0',
        ),
        migrations.RemoveConstraint(
            model_name='calculatorsettings',
            name='calc_delivery_price_per_km_gte0',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='backlight_price_per_meter',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='delivery_price_per_km',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='hydrophobic_price_per_sqm',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='railing_price_per_meter',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='show_backlight',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='show_delivery',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='show_hydrophobic',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='show_installation',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='show_measurement',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='show_railing',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='show_sockets',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='socket_price_per_block',
        ),
        migrations.AddConstraint(
            model_name='calculatorservice',
            constraint=models.CheckConstraint(condition=models.Q(('price_per_unit__gte', 0), ('price_per_unit__isnull', True), _connector='OR'), name='calc_service_price_gte0'),
        ),
    ]
