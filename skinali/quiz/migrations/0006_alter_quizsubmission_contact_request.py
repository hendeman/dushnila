import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0001_initial'),
        ('quiz', '0005_quiz_page_paths_mask_help'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name='quizsubmission',
                    name='contact_request',
                    field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='quiz_submission', to='leads.contactrequest', verbose_name='Заявка'),
                ),
            ],
        ),
    ]
