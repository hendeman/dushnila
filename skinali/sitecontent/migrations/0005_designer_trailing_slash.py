from django.db import migrations


def replace_designer_path(value, old_path, new_path):
    return '\n'.join(
        new_path if path == old_path else path
        for path in value.splitlines()
    )


def update_designer_path(apps, schema_editor, old_path, new_path):
    alias = schema_editor.connection.alias
    menu_item_model = apps.get_model('sitecontent', 'MenuItem')
    menu_item_model.objects.using(alias).filter(url=old_path).update(url=new_path)

    for app_label, model_name in (('pict', 'Integration'), ('quiz', 'Quiz')):
        model = apps.get_model(app_label, model_name)
        paths_to_update = list(
            model.objects.using(alias)
            .filter(page_paths__contains=old_path)
            .values_list('pk', 'page_paths')
        )
        for pk, page_paths in paths_to_update:
            updated = replace_designer_path(page_paths, old_path, new_path)
            if updated != page_paths:
                model.objects.using(alias).filter(pk=pk).update(page_paths=updated)


def forwards(apps, schema_editor):
    update_designer_path(apps, schema_editor, '/designer', '/designer/')


def backwards(apps, schema_editor):
    update_designer_path(apps, schema_editor, '/designer/', '/designer')


class Migration(migrations.Migration):
    dependencies = [
        ('sitecontent', '0004_leadconnection'),
        ('pict', '0037_lead_deliveries'),
        ('quiz', '0004_quiz_launcher_position_choices'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
