import django.db.models.deletion
from django.db import migrations, models


def copy_public_settings(apps, schema_editor):
    settings = apps.get_model('calculator', 'CalculatorSettings')
    tariffs = apps.get_model('calculator', 'CalculatorTariffs')
    alias = schema_editor.connection.alias
    for row in tariffs.objects.using(alias).values('code', 'is_enabled'):
        settings.objects.using(alias).create(**row)


def restore_public_settings(apps, schema_editor):
    settings = apps.get_model('calculator', 'CalculatorSettings')
    tariffs = apps.get_model('calculator', 'CalculatorTariffs')
    alias = schema_editor.connection.alias
    for row in settings.objects.using(alias).values('code', 'is_enabled'):
        tariffs.objects.using(alias).filter(code=row['code']).update(is_enabled=row['is_enabled'])


class Migration(migrations.Migration):
    dependencies = [('calculator', '0009_calculator_public_visibility')]

    operations = [
        migrations.RenameModel(old_name='CalculatorSettings', new_name='CalculatorTariffs'),
        migrations.AlterModelOptions(
            name='calculatortariffs',
            options={'verbose_name': 'Тарифы и услуги', 'verbose_name_plural': 'Тарифы и услуги'},
        ),
        migrations.RemoveConstraint(model_name='calculatortariffs', name='calculator_settings_singleton'),
        migrations.AddConstraint(
            model_name='calculatortariffs',
            constraint=models.CheckConstraint(condition=models.Q(code='skinali'), name='calculator_tariffs_singleton'),
        ),
        migrations.CreateModel(
            name='CalculatorSettings',
            fields=[
                ('code', models.CharField(default='skinali', editable=False, max_length=20, primary_key=True, serialize=False)),
                ('is_enabled', models.BooleanField(
                    default=False, verbose_name='Показывать калькулятор на сайте',
                    help_text='Выключите, чтобы полностью скрыть калькулятор на сайте. Проверочный расчёт в админке остаётся доступным.',
                )),
            ],
            options={
                'verbose_name': 'Настройки калькулятора', 'verbose_name_plural': 'Настройки калькулятора',
                'constraints': [models.CheckConstraint(condition=models.Q(code='skinali'), name='calculator_settings_singleton')],
            },
        ),
        migrations.RunPython(copy_public_settings, restore_public_settings),
        migrations.RemoveField(model_name='calculatortariffs', name='is_enabled'),
        migrations.AlterField(
            model_name='stairliftingrule', name='settings',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name='stair_lifting_rules',
                to='calculator.calculatortariffs', verbose_name='Тарифы и услуги',
            ),
        ),
    ]
