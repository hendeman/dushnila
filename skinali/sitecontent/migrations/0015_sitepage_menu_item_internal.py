import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('sitecontent', '0014_sitepage_menu_item')]

    operations = [
        migrations.AlterField(
            model_name='sitepage', name='menu_item',
            field=models.ForeignKey(
                blank=True, editable=False, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='site_pages', to='sitecontent.menuitem',
            ),
        ),
    ]
