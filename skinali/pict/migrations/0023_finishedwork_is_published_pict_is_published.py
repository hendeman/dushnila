from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pict', '0022_contactrequest_image_purchase'),
    ]

    operations = [
        migrations.AddField(
            model_name='finishedwork',
            name='is_published',
            field=models.BooleanField(default=True, verbose_name='Опубликовано'),
        ),
        migrations.AddField(
            model_name='pict',
            name='is_published',
            field=models.BooleanField(default=True, verbose_name='Опубликовано'),
        ),
    ]
