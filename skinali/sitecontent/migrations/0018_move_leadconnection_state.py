from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('pict', '0041_move_contactrequest_state'),
        ('sitecontent', '0017_move_integrations'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name='LeadConnection',
                ),
            ],
        ),
    ]
