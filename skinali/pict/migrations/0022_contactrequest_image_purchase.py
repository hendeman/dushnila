from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pict', '0021_contactrequest_email_message_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='contactrequest',
            name='request_type',
            field=models.CharField(
                choices=[
                    ('callback', 'Обратный звонок'),
                    ('question', 'Вопрос'),
                    ('email_message', 'Сообщение по email'),
                    ('image_purchase', 'Покупка изображения'),
                ],
                max_length=20,
                verbose_name='Тип заявки',
            ),
        ),
        migrations.AddField(
            model_name='contactrequest',
            name='catalog_image',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='purchase_requests',
                to='pict.pict',
                verbose_name='Изображение каталога',
            ),
        ),
        migrations.AddField(
            model_name='contactrequest',
            name='image_number',
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                verbose_name='Номер изображения на момент заявки',
            ),
        ),
    ]
