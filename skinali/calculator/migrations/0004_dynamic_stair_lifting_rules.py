import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.db import migrations, models


def copy_stair_rules(apps, schema_editor):
    settings_model = apps.get_model('calculator', 'CalculatorSettings')
    rule_model = apps.get_model('calculator', 'StairLiftingRule')
    alias = schema_editor.connection.alias
    rows = []
    for settings in settings_model.objects.using(alias).all():
        for count in range(1, 5):
            rows.append(rule_model(
                settings_id=settings.pk, panel_count=count,
                included_floor=getattr(settings, f'stair_lifting_floor_{count}'),
                multiplier=getattr(settings, f'stair_lifting_multiplier_{count}'),
            ))
    rule_model.objects.using(alias).bulk_create(rows)


def restore_stair_fields(apps, schema_editor):
    settings_model = apps.get_model('calculator', 'CalculatorSettings')
    rule_model = apps.get_model('calculator', 'StairLiftingRule')
    alias = schema_editor.connection.alias
    for rule in rule_model.objects.using(alias).filter(panel_count__lte=4):
        settings_model.objects.using(alias).filter(pk=rule.settings_id).update(**{
            f'stair_lifting_floor_{rule.panel_count}': rule.included_floor,
            f'stair_lifting_multiplier_{rule.panel_count}': rule.multiplier,
        })


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0003_stair_lifting_rules'),
    ]

    operations = [
        migrations.CreateModel(
            name='StairLiftingRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('panel_count', models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(10)], verbose_name='Панелей')),
                ('included_floor', models.PositiveIntegerField(validators=[django.core.validators.MaxValueValidator(999999999)], verbose_name='Этаж')),
                ('multiplier', models.DecimalField(decimal_places=2, max_digits=6, validators=[django.core.validators.MinValueValidator(Decimal('0'))], verbose_name='Коэффициент сложности')),
                ('settings', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stair_lifting_rules', to='calculator.calculatorsettings', verbose_name='Настройки калькулятора')),
            ],
            options={
                'verbose_name': 'Правило подъёма по лестнице',
                'verbose_name_plural': 'Правила подъёма по лестнице',
                'ordering': ('panel_count',),
            },
        ),
        migrations.RunPython(copy_stair_rules, restore_stair_fields),
        migrations.RemoveConstraint(
            model_name='calculatorsettings',
            name='calc_stair_multiplier_1_gte0',
        ),
        migrations.RemoveConstraint(
            model_name='calculatorsettings',
            name='calc_stair_multiplier_2_gte0',
        ),
        migrations.RemoveConstraint(
            model_name='calculatorsettings',
            name='calc_stair_multiplier_3_gte0',
        ),
        migrations.RemoveConstraint(
            model_name='calculatorsettings',
            name='calc_stair_multiplier_4_gte0',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='stair_lifting_floor_1',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='stair_lifting_floor_2',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='stair_lifting_floor_3',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='stair_lifting_floor_4',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='stair_lifting_multiplier_1',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='stair_lifting_multiplier_2',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='stair_lifting_multiplier_3',
        ),
        migrations.RemoveField(
            model_name='calculatorsettings',
            name='stair_lifting_multiplier_4',
        ),
        migrations.AlterField(
            model_name='calculatorsettings',
            name='stair_lifting_price_per_panel_floor',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Доплата за каждый этаж сверх порога из таблицы с выбранным коэффициентом сложности. Пустое поле — тариф не задан.', max_digits=10, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Подъём одной панели на один этаж'),
        ),
        migrations.AddConstraint(
            model_name='stairliftingrule',
            constraint=models.UniqueConstraint(fields=('settings', 'panel_count'), name='calc_stair_unique_panel_count'),
        ),
        migrations.AddConstraint(
            model_name='stairliftingrule',
            constraint=models.CheckConstraint(condition=models.Q(('panel_count__gte', 1), ('panel_count__lte', 10)), name='calc_stair_panel_count_range'),
        ),
        migrations.AddConstraint(
            model_name='stairliftingrule',
            constraint=models.CheckConstraint(condition=models.Q(('multiplier__gte', 0)), name='calc_stair_multiplier_gte0'),
        ),
    ]
