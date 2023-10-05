# Generated by Django 4.1.5 on 2023-03-01 12:51

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cat', models.CharField(max_length=100)),
            ],
        ),
        migrations.CreateModel(
            name='Pict',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=10)),
                ('title', models.CharField(max_length=100)),
                ('photo', models.ImageField(upload_to='photos/')),
                ('time_update', models.DateTimeField(auto_now_add=True)),
                ('cat', models.ManyToManyField(to='pict.category')),
            ],
        ),
    ]
