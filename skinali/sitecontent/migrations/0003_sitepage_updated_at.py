import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sitecontent', '0002_sitepage'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitepage',
            name='updated_at',
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                verbose_name='Время изменения публичного содержимого',
            ),
            preserve_default=False,
        ),
    ]
