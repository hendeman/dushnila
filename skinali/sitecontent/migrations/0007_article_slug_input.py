from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sitecontent', '0006_articles'),
    ]

    operations = [
        migrations.AlterField(
            model_name='article',
            name='slug',
            field=models.SlugField(blank=True, help_text='Необязательно. Русский или латинский текст преобразуется в адрес. Если оставить пустым, используется заголовок. После первого сохранения адрес не меняется.', max_length=220, unique=True, verbose_name='Адрес статьи'),
        ),
    ]
