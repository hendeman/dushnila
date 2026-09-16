from django.db import migrations, models


SITE_PAGES = (
    ('home', 'Главная страница'),
    ('skinali', 'Каталог скинали'),
    ('finished_works', 'Наши работы'),
    ('designer', 'Услуги дизайнера'),
    ('about', 'Связаться с нами'),
)


def create_site_pages(apps, schema_editor):
    """Создаёт SEO-карточки постоянных внутренних страниц."""
    site_page_model = apps.get_model('sitecontent', 'SitePage')
    site_page_model.objects.bulk_create([
        site_page_model(code=code, seo_title='', seo_description='')
        for code, _label in SITE_PAGES
    ])


def remove_site_pages(apps, schema_editor):
    site_page_model = apps.get_model('sitecontent', 'SitePage')
    site_page_model.objects.filter(
        code__in=[code for code, _label in SITE_PAGES],
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('sitecontent', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SitePage',
            fields=[
                (
                    'seo_title',
                    models.CharField(
                        blank=True,
                        help_text='Без «| ОДИУМ»: бренд и номер страницы добавятся автоматически.',
                        max_length=200,
                        verbose_name='SEO-title',
                    ),
                ),
                (
                    'seo_description',
                    models.CharField(
                        blank=True,
                        help_text='Оставьте пустым, чтобы использовать стандартное описание.',
                        max_length=320,
                        verbose_name='Meta description',
                    ),
                ),
                (
                    'code',
                    models.CharField(
                        choices=[
                            ('home', 'Главная страница'),
                            ('skinali', 'Каталог скинали'),
                            ('finished_works', 'Наши работы'),
                            ('designer', 'Услуги дизайнера'),
                            ('about', 'Связаться с нами'),
                        ],
                        editable=False,
                        max_length=50,
                        primary_key=True,
                        serialize=False,
                        verbose_name='Системный код',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Страница сайта',
                'verbose_name_plural': 'Страницы сайта',
            },
        ),
        migrations.RunPython(create_site_pages, remove_site_pages),
    ]
