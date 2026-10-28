import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


def create_calculator_settings(apps, schema_editor):
    Settings = apps.get_model('calculator', 'CalculatorSettings')
    Settings.objects.using(schema_editor.connection.alias).get_or_create(code='skinali')


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='DecorationType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='Название')),
                ('position', models.PositiveIntegerField(default=0, verbose_name='Порядок')),
                ('is_visible', models.BooleanField(default=True, verbose_name='Показывать в калькуляторе')),
                ('price_per_sqm', models.DecimalField(decimal_places=2, help_text='Неотрицательная сумма с точностью до двух знаков после запятой.', max_digits=10, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Доплата за 1 м²')),
            ],
            options={
                'verbose_name': 'Декорирование',
                'verbose_name_plural': 'Декорирование',
                'ordering': ('position', 'pk'),
                'abstract': False,
                'constraints': [models.CheckConstraint(condition=models.Q(('price_per_sqm__gte', 0)), name='calc_decorationtype_price_gte0')],
            },
        ),
        migrations.CreateModel(
            name='GlassType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='Название')),
                ('price_per_sqm', models.DecimalField(decimal_places=2, help_text='Неотрицательная сумма с точностью до двух знаков после запятой.', max_digits=10, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Цена за 1 м²')),
                ('position', models.PositiveIntegerField(default=0, verbose_name='Порядок')),
                ('is_visible', models.BooleanField(default=True, verbose_name='Показывать в калькуляторе')),
            ],
            options={
                'verbose_name': 'Тип стекла',
                'verbose_name_plural': 'Типы стекла',
                'ordering': ('position', 'pk'),
                'abstract': False,
                'constraints': [models.CheckConstraint(condition=models.Q(('price_per_sqm__gte', 0)), name='calc_glasstype_price_gte0')],
            },
        ),
        migrations.CreateModel(
            name='CalculatorSettings',
            fields=[
                ('code', models.CharField(default='skinali', editable=False, max_length=20, primary_key=True, serialize=False)),
                ('show_glass_type', models.BooleanField(default=True, verbose_name='Показывать выбор стекла')),
                ('show_decoration_type', models.BooleanField(default=True, verbose_name='Показывать выбор декорирования')),
                ('show_backlight', models.BooleanField(default=False, verbose_name='Показывать подсветку')),
                ('backlight_price_per_meter', models.DecimalField(blank=True, decimal_places=2, help_text='Пустое поле — тариф не задан. Укажите 0 для бесплатной услуги.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Подсветка: цена за погонный метр')),
                ('show_railing', models.BooleanField(default=False, verbose_name='Показывать рейлинги')),
                ('railing_price_per_meter', models.DecimalField(blank=True, decimal_places=2, help_text='Пустое поле — тариф не задан. Укажите 0 для бесплатной услуги.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Рейлинги: цена за погонный метр')),
                ('show_sockets', models.BooleanField(default=False, verbose_name='Показывать блоки розеток')),
                ('socket_price_per_block', models.DecimalField(blank=True, decimal_places=2, help_text='Пустое поле — тариф не задан. Укажите 0 для бесплатной услуги.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Цена за один блок розеток')),
                ('show_hydrophobic', models.BooleanField(default=False, verbose_name='Показывать гидрофобный слой')),
                ('hydrophobic_price_per_sqm', models.DecimalField(blank=True, decimal_places=2, help_text='Пустое поле — тариф не задан. Укажите 0 для бесплатной услуги.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Гидрофобный слой: доплата за 1 м²')),
                ('show_delivery', models.BooleanField(default=False, verbose_name='Показывать доставку')),
                ('delivery_price_per_km', models.DecimalField(blank=True, decimal_places=2, help_text='Пустое поле — тариф не задан. Укажите 0 для бесплатной услуги.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Доставка: цена за 1 км')),
                ('show_stair_lifting', models.BooleanField(default=False, verbose_name='Показывать подъём по лестнице')),
                ('stair_lifting_min_price', models.DecimalField(blank=True, decimal_places=2, help_text='Пустое поле — тариф не задан. Укажите 0 для бесплатной услуги.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Минимальная стоимость подъёма')),
                ('stair_lifting_price_per_panel_floor', models.DecimalField(blank=True, decimal_places=2, help_text='Тариф для бригады из двух человек. Пустое поле — тариф не задан.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Подъём одной панели на один этаж')),
                ('show_measurement', models.BooleanField(default=True, verbose_name='Показывать замер')),
                ('show_installation', models.BooleanField(default=True, verbose_name='Показывать монтаж')),
                ('default_decoration_type', models.ForeignKey(blank=True, help_text='Применяется также при скрытом выборе. Для варианта без доплаты укажите цену 0.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='default_for_settings', to='calculator.decorationtype', verbose_name='Декорирование по умолчанию')),
                ('default_glass_type', models.ForeignKey(blank=True, help_text='Применяется также при скрытом выборе стекла. Сначала добавьте варианты стекла.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='default_for_settings', to='calculator.glasstype', verbose_name='Стекло по умолчанию')),
            ],
            options={
                'verbose_name': 'Настройки калькулятора',
                'verbose_name_plural': 'Настройки калькулятора',
                'constraints': [models.CheckConstraint(condition=models.Q(('code', 'skinali')), name='calculator_settings_singleton'), models.CheckConstraint(condition=models.Q(('backlight_price_per_meter__gte', 0), ('backlight_price_per_meter__isnull', True), _connector='OR'), name='calc_backlight_price_per_meter_gte0'), models.CheckConstraint(condition=models.Q(('railing_price_per_meter__gte', 0), ('railing_price_per_meter__isnull', True), _connector='OR'), name='calc_railing_price_per_meter_gte0'), models.CheckConstraint(condition=models.Q(('socket_price_per_block__gte', 0), ('socket_price_per_block__isnull', True), _connector='OR'), name='calc_socket_price_per_block_gte0'), models.CheckConstraint(condition=models.Q(('hydrophobic_price_per_sqm__gte', 0), ('hydrophobic_price_per_sqm__isnull', True), _connector='OR'), name='calc_hydrophobic_price_per_sqm_gte0'), models.CheckConstraint(condition=models.Q(('delivery_price_per_km__gte', 0), ('delivery_price_per_km__isnull', True), _connector='OR'), name='calc_delivery_price_per_km_gte0'), models.CheckConstraint(condition=models.Q(('stair_lifting_min_price__gte', 0), ('stair_lifting_min_price__isnull', True), _connector='OR'), name='calc_stair_lifting_min_price_gte0'), models.CheckConstraint(condition=models.Q(('stair_lifting_price_per_panel_floor__gte', 0), ('stair_lifting_price_per_panel_floor__isnull', True), _connector='OR'), name='calc_stair_lifting_price_per_panel_floor_gte0')],
            },
        ),
        migrations.RunPython(create_calculator_settings, migrations.RunPython.noop),
    ]
