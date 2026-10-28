from django.db import migrations, models


def add_price_page(apps, schema_editor):
    alias = schema_editor.connection.alias
    apps.get_model('sitecontent', 'SitePage').objects.using(alias).get_or_create(code='price')
    menu = apps.get_model('sitecontent', 'SiteMenu').objects.using(alias).filter(code='main').first()
    items = apps.get_model('sitecontent', 'MenuItem').objects.using(alias)
    if menu is not None and not items.filter(menu=menu, url='/price/').exists():
        catalog = items.filter(menu=menu, url='/skinali/').first()
        position = catalog.position + 1 if catalog else 25
        items.create(menu=menu, title='Цена', url='/price/', position=position, is_visible=True)


def remove_price_page(apps, schema_editor):
    alias = schema_editor.connection.alias
    apps.get_model('sitecontent', 'SitePage').objects.using(alias).filter(code='price').delete()
    apps.get_model('sitecontent', 'MenuItem').objects.using(alias).filter(
        menu__code='main', url='/price/', title='Цена',
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('sitecontent', '0009_site_settings_admin_name')]

    operations = [
        migrations.AlterField(
            model_name='sitepage', name='code',
            field=models.CharField('Системный код', choices=[
                ('home', 'Главная страница'), ('skinali', 'Каталог скинали'), ('price', 'Цена'),
                ('finished_works', 'Наши работы'), ('designer', 'Услуги дизайнера'),
                ('article_list', 'Полезно знать'), ('about', 'Связаться с нами'),
            ], editable=False, max_length=50, primary_key=True, serialize=False),
        ),
        migrations.RunPython(add_price_page, remove_price_page),
    ]
