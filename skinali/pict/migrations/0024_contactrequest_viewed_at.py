from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pict', '0023_finishedwork_is_published_pict_is_published'),
    ]

    operations = [
        migrations.AddField(
            model_name='contactrequest',
            name='viewed_at',
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
                verbose_name='Время просмотра',
            ),
        ),
    ]
