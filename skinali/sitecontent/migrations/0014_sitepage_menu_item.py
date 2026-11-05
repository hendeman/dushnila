import django.db.models.deletion
from django.db import migrations, models


def link_existing_menu_items(apps, schema_editor):
    """Сохраняет текущие названия, однократно выбирая пункты по точному пути."""
    alias = schema_editor.connection.alias
    pages = apps.get_model('sitecontent', 'SitePage').objects.using(alias)
    items = apps.get_model('sitecontent', 'MenuItem').objects.using(alias)
    paths = {
        'home': '/',
        'skinali': '/skinali/',
        'price': '/price/',
        'finished_works': '/foto-skinali-iz-stekla/',
        'designer': '/designer/',
        'article_list': '/polezno-znat/',
        'about': '/about/',
    }
    for code, path in paths.items():
        item_id = (
            items.filter(menu__code='main', url=path)
            .order_by('position', 'pk').values_list('pk', flat=True).first()
        )
        if item_id is not None:
            pages.filter(pk=code, menu_item__isnull=True).update(menu_item_id=item_id)


class Migration(migrations.Migration):
    dependencies = [('sitecontent', '0013_header_text_label')]

    operations = [
        migrations.AddField(
            model_name='sitepage', name='menu_item',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='site_pages', limit_choices_to={'menu__code': 'main'},
                to='sitecontent.menuitem', verbose_name='Пункт меню',
                help_text=(
                    'Название выбранного пункта используется в хлебных крошках и названии этой карточки, '
                    'даже если пункт скрыт. Переименовывайте его в «Меню → Пункты меню». '
                    'Без связи используется стандартное название страницы; адрес, H1 и SEO не меняются.'
                ),
            ),
        ),
        migrations.AlterField(
            model_name='menuitem', name='title',
            field=models.CharField(
                'Название', max_length=100,
                help_text='Для связанной страницы также задаёт название в хлебных крошках и «Страницах сайта».',
            ),
        ),
        migrations.RunPython(link_existing_menu_items, migrations.RunPython.noop),
    ]
