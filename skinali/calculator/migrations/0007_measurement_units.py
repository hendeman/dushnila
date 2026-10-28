import django.db.models.deletion
from django.db import migrations, models


INITIAL_UNITS = (
    ('Единица', 'ед.'), ('Квадратный метр', 'м²'), ('Погонный метр', 'пог. м'),
    ('Штука', 'шт.'), ('Километр', 'км'), ('Заказ', 'заказ'),
    ('Миллиметр', 'мм'), ('Дополнительный этаж', 'доп. этаж'),
)


def copy_units(apps, schema_editor):
    unit_model = apps.get_model('calculator', 'MeasurementUnit')
    service_model = apps.get_model('calculator', 'CalculatorService')
    alias = schema_editor.connection.alias
    for position, (name, symbol) in enumerate(INITIAL_UNITS):
        unit_model.objects.using(alias).create(name=name, symbol=symbol, position=position * 10)
    for service in service_model.objects.using(alias).all().iterator():
        symbol = (service.legacy_unit or '').strip()
        if symbol:
            unit, _created = unit_model.objects.using(alias).get_or_create(
                symbol=symbol, defaults={'name': f'Единица «{symbol}»', 'position': 100},
            )
            service.unit_id = unit.pk
            service.save(using=alias, update_fields=['unit'])


def restore_units(apps, schema_editor):
    service_model = apps.get_model('calculator', 'CalculatorService')
    alias = schema_editor.connection.alias
    for service in service_model.objects.using(alias).select_related('unit').all().iterator():
        service.legacy_unit = service.unit.symbol if service.unit_id else ''
        service.save(using=alias, update_fields=['legacy_unit'])


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0006_editable_services'),
    ]

    operations = [
        migrations.CreateModel(
            name='MeasurementUnit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='Название')),
                ('symbol', models.CharField(max_length=30, unique=True, verbose_name='Обозначение')),
                ('position', models.PositiveIntegerField(default=0, verbose_name='Порядок')),
            ],
            options={
                'verbose_name': 'Единица измерения',
                'verbose_name_plural': 'Единицы измерения',
                'ordering': ('position', 'pk'),
            },
        ),
        migrations.RenameField(
            model_name='calculatorservice', old_name='unit', new_name='legacy_unit',
        ),
        migrations.AddField(
            model_name='calculatorservice',
            name='unit',
            field=models.ForeignKey(blank=True, help_text='Выберите единицу из справочника. На формулу стоимости обозначение не влияет.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='services', to='calculator.measurementunit', verbose_name='Единица измерения'),
        ),
        migrations.RunPython(copy_units, restore_units),
        migrations.RemoveField(model_name='calculatorservice', name='legacy_unit'),
    ]
