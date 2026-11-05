from importlib import import_module

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('sitecontent', '0015_sitepage_menu_item_internal')]

    operations = [
        migrations.RunPython(
            import_module('sitecontent.migrations.0014_sitepage_menu_item').link_existing_menu_items,
            migrations.RunPython.noop,
        ),
    ]
