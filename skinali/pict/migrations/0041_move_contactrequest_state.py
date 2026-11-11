from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('pict', '0040_remove_integration_state'),
        ('quiz', '0006_alter_quizsubmission_contact_request'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name='ContactRequestDelivery'),
                migrations.DeleteModel(name='ContactRequest'),
            ],
        ),
    ]
