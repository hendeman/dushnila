# Generated by Django 4.1.5 on 2023-08-25 21:06

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pict', '0008_pict_alt_alter_pict_color'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pict',
            name='color',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='pict.color', verbose_name='Цвет'),
        ),
    ]
