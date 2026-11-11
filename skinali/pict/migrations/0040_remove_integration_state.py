from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('pict', '0039_calculator_order_requests'),
        ('sitecontent', '0016_restore_missing_page_menu_links'),
    ]

    operations = [
        # Таблицы и данные сохраняются для моделей приложения sitecontent.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name='IntegrationRevision'),
                migrations.DeleteModel(name='Integration'),
            ],
        ),
    ]
