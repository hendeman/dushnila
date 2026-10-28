import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('calculator', '0014_public_hints'),
    ]

    operations = [
        migrations.AddField(
            model_name='calculatorsettings',
            name='marketing_discount_description',
            field=models.TextField(blank=True, default='', help_text='Необязательный текст с описанием условий акции. До 2000 символов.', max_length=2000, validators=[django.core.validators.MaxLengthValidator(2000)], verbose_name='Описание маркетинговой скидки'),
        ),
    ]
