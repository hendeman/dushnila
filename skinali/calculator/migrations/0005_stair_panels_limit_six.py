import django.core.validators
from django.db import migrations, models


def trim_stair_rules(apps, schema_editor):
    rule_model = apps.get_model('calculator', 'StairLiftingRule')
    rule_model.objects.using(schema_editor.connection.alias).filter(panel_count__gt=6).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0004_dynamic_stair_lifting_rules'),
    ]

    operations = [
        migrations.RunPython(trim_stair_rules, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='stairliftingrule',
            name='calc_stair_panel_count_range',
        ),
        migrations.AlterField(
            model_name='stairliftingrule',
            name='panel_count',
            field=models.PositiveSmallIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(6)], verbose_name='Панелей'),
        ),
        migrations.AddConstraint(
            model_name='stairliftingrule',
            constraint=models.CheckConstraint(condition=models.Q(('panel_count__gte', 1), ('panel_count__lte', 6)), name='calc_stair_panel_count_range'),
        ),
    ]
