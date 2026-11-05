from django.contrib.auth import get_user_model
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import connection
from django.template import RequestContext, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from pict.views import resolve_site_page_metadata, set_page_metadata

from .admin import SitePageAdmin
from .models import MenuItem, SiteMenu, SitePage


class SitePageModelTests(TestCase):
    def test_migration_creates_all_internal_site_pages_with_empty_seo(self):
        self.assertEqual(
            {
                page.code: (
                    str(page),
                    page.seo_title,
                    page.seo_description,
                )
                for page in SitePage.objects.all()
            },
            {
                SitePage.Code.HOME: ('Главная страница', '', ''),
                SitePage.Code.CATALOG: ('Каталог скинали', '', ''),
                SitePage.Code.PRICE: ('Цена', '', ''),
                SitePage.Code.FINISHED_WORKS: ('Наши работы', '', ''),
                SitePage.Code.DESIGNER: ('Услуги дизайнера', '', ''),
                SitePage.Code.ARTICLES: ('Полезно знать', '', ''),
                SitePage.Code.ABOUT: ('Связаться с нами', '', ''),
            },
        )

    def test_empty_and_whitespace_seo_values_use_defaults(self):
        page = SitePage.objects.get(pk=SitePage.Code.HOME)
        page.seo_title = '  Новый заголовок  '
        page.seo_description = '   '

        self.assertEqual(
            page.resolve_seo_value('seo_title', 'Стандартный заголовок'),
            'Новый заголовок',
        )
        self.assertEqual(
            page.resolve_seo_value('seo_description', 'Стандартное описание'),
            'Стандартное описание',
        )


class SitePageMenuLinkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser(
            username='page-menu-owner', email='page-menu@example.com', password='test-password',
        )

    def setUp(self):
        self.page = SitePage.objects.select_related('menu_item').get(pk=SitePage.Code.PRICE)
        self.item = self.page.menu_item

    def assert_price_title(self, expected):
        response = self.client.get(reverse('price'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['breadcrumbs'][-1]['name'], expected)
        self.assertContains(response, f'https://odium.by{reverse("price")}')
        self.assertEqual(str(SitePage.objects.get(pk=self.page.pk)), expected)
        data = json.loads(response.content.decode().split(
            '<script id="breadcrumb-structured-data" type="application/ld+json">',
        )[1].split('</script>')[0])
        self.assertEqual(data['itemListElement'][-1]['name'], expected)
        return response

    def test_migration_links_all_pages_to_existing_menu_items(self):
        for page in SitePage.objects.select_related('menu_item'):
            with self.subTest(code=page.code):
                self.assertIsNotNone(page.menu_item_id)
                self.assertEqual(page.menu_item.url, reverse(page.code))

    def test_rename_through_menu_admin_updates_public_and_admin_titles(self):
        self.client.force_login(self.superuser)
        items = list(self.item.menu.items.all())
        data = {
            'items-TOTAL_FORMS': str(len(items)), 'items-INITIAL_FORMS': str(len(items)),
            'items-MIN_NUM_FORMS': '0', 'items-MAX_NUM_FORMS': '1000', '_save': 'Сохранить',
        }
        for index, item in enumerate(items):
            prefix = f'items-{index}-'
            data.update({
                prefix + 'id': str(item.pk), prefix + 'menu': str(item.menu_id),
                prefix + 'position': str(item.position), prefix + 'url': item.url,
                prefix + 'title': 'Рассчитать стоимость' if item.pk == self.item.pk else item.title,
                prefix + 'is_visible': 'on',
            })
        response = self.client.post(
            reverse('admin:sitecontent_sitemenu_change', args=[self.item.menu_id]), data,
        )
        self.assertEqual(response.status_code, 302)
        public = self.assert_price_title('Рассчитать стоимость')
        self.assertEqual(public.context['title'], 'Рассчитайте стоимость скинали')
        self.assertEqual(public.context['page_title'], 'Цена скинали — калькулятор стоимости | ОДИУМ')
        self.assertEqual(public.context['canonical_url'], 'https://odium.by/price/')
        listing = self.client.get(reverse('admin:sitecontent_sitepage_changelist'))
        self.assertContains(listing, 'Рассчитать стоимость')
        editor = self.client.get(reverse('admin:sitecontent_sitepage_change', args=[self.page.pk]))
        self.assertContains(editor, '<h2>Рассчитать стоимость</h2>', html=True)

    def test_saving_renamed_menu_item_restores_missing_link(self):
        SitePage.objects.filter(pk=self.page.pk).update(menu_item=None)
        self.assert_price_title(SitePage.Code.PRICE.label)

        self.item.title = 'Получить цену'
        self.item.save(update_fields=['title'])

        self.page.refresh_from_db()
        self.assertEqual(self.page.menu_item_id, self.item.pk)
        self.assert_price_title('Получить цену')
        self.client.force_login(self.superuser)
        listing = self.client.get(reverse('admin:sitecontent_sitepage_changelist'))
        self.assertContains(listing, 'Получить цену')

    def test_saving_menu_items_restores_missing_links_for_all_sections(self):
        pages = list(SitePage.objects.select_related('menu_item'))
        SitePage.objects.update(menu_item=None)
        for page in pages:
            with self.subTest(code=page.code):
                item = page.menu_item
                item.title = f'Название {page.code}'
                item.save(update_fields=['title'])
                page.refresh_from_db()
                self.assertEqual(page.menu_item_id, item.pk)
                self.assertEqual(str(page), item.title)

    def test_creating_menu_item_restores_link_after_previous_item_deleted(self):
        self.item.delete()
        item = MenuItem.objects.create(
            menu=self.item.menu, title='Новый расчёт', url='/price/', is_visible=False,
        )
        self.page.refresh_from_db()
        self.assertEqual(self.page.menu_item_id, item.pk)
        self.assert_price_title(item.title)

    def test_missing_link_uses_first_exact_match_even_when_another_duplicate_saved(self):
        item = MenuItem.objects.create(
            menu=self.item.menu, title='Первый пункт', url='/price/', position=0, is_visible=False,
        )
        SitePage.objects.filter(pk=self.page.pk).update(menu_item=None)
        self.item.title = 'Второй пункт'
        self.item.save(update_fields=['title'])
        self.page.refresh_from_db()
        self.assertEqual(self.page.menu_item_id, item.pk)
        self.assert_price_title(item.title)

    def test_external_or_query_links_do_not_bind_unlinked_page(self):
        SitePage.objects.filter(pk=self.page.pk).update(menu_item=None)
        for url in ('https://example.com/price/', '/price/?source=menu', '/price/#form', '/custom/'):
            with self.subTest(url=url):
                MenuItem.objects.create(menu=self.item.menu, title='Произвольная ссылка', url=url)
                self.page.refresh_from_db()
                self.assertIsNone(self.page.menu_item_id)
        self.assert_price_title(SitePage.Code.PRICE.label)

    def test_link_survives_hiding_reordering_url_change_and_duplicate(self):
        self.item.title = 'Расчёт'
        self.item.is_visible = False
        self.item.position = 999
        self.item.url = 'https://example.com/calculation'
        self.item.save()
        MenuItem.objects.create(menu=self.item.menu, title='Другая ссылка', url='/price/', position=0)
        response = self.assert_price_title('Расчёт')
        self.assertNotContains(response, self.item.url)

    def test_deleting_linked_item_uses_default_without_selecting_duplicate(self):
        MenuItem.objects.create(menu=self.item.menu, title='Дубликат', url='/price/', position=0)
        old_timestamp = timezone.now() - timedelta(days=1)
        SitePage.objects.filter(pk=self.page.pk).update(updated_at=old_timestamp)
        self.item.delete()
        self.page.refresh_from_db()
        self.assertIsNone(self.page.menu_item_id)
        self.assertGreater(self.page.updated_at, old_timestamp)
        self.assert_price_title(SitePage.Code.PRICE.label)

    def test_missing_page_uses_default_breadcrumb_and_seo(self):
        self.page.delete()
        response = self.client.get(reverse('price'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['breadcrumbs'][-1]['name'], SitePage.Code.PRICE.label)
        self.assertEqual(response.context['page_title'], 'Цена скинали — калькулятор стоимости | ОДИУМ')

    def test_editing_seo_cannot_change_internal_menu_link(self):
        item = MenuItem.objects.create(menu=self.item.menu, title='Другая ссылка', url='/price/')
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse('admin:sitecontent_sitepage_change', args=[self.page.pk]),
            {'menu_item': item.pk, 'seo_title': '', 'seo_description': 'Описание', '_save': 'Сохранить'},
        )
        self.assertEqual(response.status_code, 302)
        self.page.refresh_from_db()
        self.assertEqual(self.page.menu_item_id, self.item.pk)
        self.assertEqual(self.page.seo_description, 'Описание')
        self.assert_price_title(self.item.title)

    def test_all_sections_and_parent_breadcrumbs_use_linked_titles(self):
        for page in SitePage.objects.select_related('menu_item'):
            page.menu_item.title = f'Раздел {page.code}'
            page.menu_item.save(update_fields=['title'])
        for code in SitePage.Code:
            if code == SitePage.Code.HOME:
                continue
            with self.subTest(code=code):
                response = self.client.get(reverse(code))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    tuple(item['name'] for item in response.context['breadcrumbs']),
                    ('Раздел home', f'Раздел {code}'),
                )

    def test_names_are_escaped_in_html_and_remain_valid_in_json_ld(self):
        self.item.title = 'Расчёт </script><script>alert(1)</script>'
        self.item.save(update_fields=['title'])
        response = self.assert_price_title(self.item.title)
        self.assertNotIn(self.item.title, response.content.decode())

    def test_one_query_for_metadata_and_breadcrumbs_and_fresh_names_next_request(self):
        def metadata(request):
            title, description = resolve_site_page_metadata(
                SitePage.Code.PRICE, request, default_page_title='Цена', default_meta_description='',
            )
            return set_page_metadata(
                {}, request, page_title=title, meta_description=description, canonical_path='/price/',
                breadcrumbs=((SitePage.Code.HOME, '/'), (SitePage.Code.PRICE, None)),
            )

        with self.assertNumQueries(1):
            context = metadata(RequestFactory().get('/price/'))
        self.assertEqual(context['breadcrumbs'][-1]['name'], 'Цена')
        self.item.title = 'Новое название'
        self.item.save(update_fields=['title'])
        with self.assertNumQueries(1):
            context = metadata(RequestFactory().get('/price/'))
        self.assertEqual(context['breadcrumbs'][-1]['name'], 'Новое название')

    def test_data_migration_preserves_renamed_hidden_items_and_existing_links(self):
        self.item.title = 'Рассчитать стоимость'
        self.item.is_visible = False
        self.item.save()
        SitePage.objects.filter(pk=self.page.pk).update(menu_item=None)
        unrelated = MenuItem.objects.create(menu=self.item.menu, title='Внешняя ссылка', url='https://example.com')
        SitePage.objects.filter(pk=SitePage.Code.ABOUT).update(menu_item=unrelated)
        migrate = import_module('sitecontent.migrations.0014_sitepage_menu_item').link_existing_menu_items
        migrate(apps, SimpleNamespace(connection=connection))
        self.page.refresh_from_db()
        self.assertEqual(self.page.menu_item_id, self.item.pk)
        self.assertEqual(str(self.page), 'Рассчитать стоимость')
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_visible)
        self.assertEqual(SitePage.objects.get(pk=SitePage.Code.ABOUT).menu_item_id, unrelated.pk)


class SiteMenuModelTests(TestCase):
    def setUp(self):
        self.menu = SiteMenu.objects.get(code=SiteMenu.MAIN_CODE)

    def test_initial_menu_preserves_existing_links_and_order(self):
        self.assertEqual(
            list(self.menu.items.values_list('title', 'url', 'position', 'is_visible')),
            [
                ('Главная страница', '/', 10, True),
                ('Каталог скинали', '/skinali/', 20, True),
                ('Цена', '/price/', 21, True),
                ('Наши работы', '/foto-skinali-iz-stekla/', 30, True),
                ('Услуги дизайнера', '/designer/', 40, True),
                ('Полезно знать', '/polezno-znat/', 45, True),
                ('Связаться с нами', '/about/', 50, True),
            ],
        )

    def test_only_one_menu_can_be_created(self):
        with self.assertRaises(ValidationError):
            SiteMenu(name='Другое меню', code='secondary').full_clean()

    def test_new_item_is_visible_by_default_and_items_are_ordered(self):
        self.menu.items.all().delete()
        later = MenuItem.objects.create(menu=self.menu, title='Позже', url='/later/', position=20)
        earlier = MenuItem.objects.create(menu=self.menu, title='Раньше', url='/earlier/', position=10)

        self.assertTrue(later.is_visible)
        self.assertEqual(list(self.menu.items.all()), [earlier, later])

    def test_safe_link_types_are_supported(self):
        safe_urls = (
            '/about/?source=menu#contacts',
            '#contacts',
            'https://example.com/page',
            'http://example.com/page',
            'tel:+375 (29) 123-45-67',
            'mailto:hello@example.com?subject=Order%20request',
        )
        for index, url in enumerate(safe_urls):
            with self.subTest(url=url):
                MenuItem(
                    menu=self.menu,
                    title=f'Ссылка {index}',
                    url=url,
                    position=index,
                ).full_clean()

    def test_unsafe_or_ambiguous_links_are_rejected(self):
        invalid_urls = (
            'javascript:alert(1)',
            'data:text/html,test',
            '//example.com',
            'relative/path',
            '#',
            'tel:+++',
        )
        for index, url in enumerate(invalid_urls):
            with self.subTest(url=url):
                with self.assertRaises(ValidationError):
                    MenuItem(
                        menu=self.menu,
                        title=f'Ссылка {index}',
                        url=url,
                        position=index,
                    ).full_clean()


class SiteMenuRenderingTests(TestCase):
    def setUp(self):
        self.menu = SiteMenu.objects.get(code=SiteMenu.MAIN_CODE)
        self.menu.items.all().delete()

    def test_visible_items_render_in_one_order_in_header_and_footer(self):
        MenuItem.objects.create(
            menu=self.menu,
            title='Внутренний раздел',
            url='/',
            position=10,
        )
        MenuItem.objects.create(
            menu=self.menu,
            title='Внешний раздел',
            url='https://example.com/',
            open_in_new_tab=True,
            position=20,
        )
        MenuItem.objects.create(
            menu=self.menu,
            title='Скрытый раздел',
            url='/hidden/',
            position=0,
            is_visible=False,
        )

        response = self.client.get(reverse('home'))
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Внутренний раздел', count=2)
        self.assertContains(response, 'Внешний раздел', count=2)
        self.assertNotContains(response, 'Скрытый раздел')
        self.assertContains(
            response,
            '<a href="https://example.com/" target="_blank" rel="noopener noreferrer">Внешний раздел</a>',
            count=2,
            html=True,
        )
        self.assertLess(content.index('Внутренний раздел'), content.index('Внешний раздел'))
        self.assertContains(
            response,
            '<span aria-current="page">Внутренний раздел</span>',
            count=2,
            html=True,
        )
        self.assertNotContains(response, '<a href="/">Внутренний раздел</a>', html=True)
        self.assertContains(response, 'data-favorites-menu')
        self.assertContains(response, 'class="mainmenu__callback-button"')

    def test_visibility_change_is_applied_on_the_next_request(self):
        item = MenuItem.objects.create(
            menu=self.menu,
            title='Переключаемый пункт',
            url='/toggle/',
            position=10,
            is_visible=False,
        )
        self.assertNotContains(self.client.get(reverse('home')), item.title)

        item.is_visible = True
        item.save(update_fields=['is_visible'])

        self.assertContains(self.client.get(reverse('home')), item.title, count=2)

    def test_hidden_finished_works_item_hides_only_homepage_link_card(self):
        item = MenuItem.objects.create(
            menu=self.menu,
            title='Наши работы',
            url=reverse('finished_works'),
            position=10,
        )

        visible_response = self.client.get(reverse('home'))

        self.assertContains(visible_response, 'class="home-recent-works"')
        self.assertContains(visible_response, 'home-recent-work-card--all')
        self.assertIn(
            reverse('finished_works'),
            visible_response.context['visible_site_menu_urls'],
        )

        item.is_visible = False
        item.save(update_fields=['is_visible'])
        hidden_response = self.client.get(reverse('home'))

        self.assertContains(hidden_response, 'class="home-recent-works"')
        self.assertNotContains(hidden_response, 'home-recent-work-card--all')
        self.assertNotContains(hidden_response, 'Смотреть все фото')
        self.assertNotIn(
            reverse('finished_works'),
            hidden_response.context['visible_site_menu_urls'],
        )

    def test_same_queryset_is_reused_for_header_and_footer(self):
        MenuItem.objects.create(
            menu=self.menu,
            title='Один запрос',
            url='/',
            position=10,
        )
        request = RequestFactory().get('/')
        template = Template(
            '{% for item in site_menu_items %}{{ item.title }}{% endfor %}|'
            '{% for item in site_menu_items %}{{ item.title }}{% endfor %}'
        )

        with self.assertNumQueries(1):
            content = template.render(RequestContext(request))

        self.assertEqual(content, 'Один запрос|Один запрос')


class SiteMenuAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.menu = SiteMenu.objects.get(code=SiteMenu.MAIN_CODE)
        user_model = get_user_model()
        cls.superuser = user_model.objects.create_superuser(
            username='menu-owner',
            email='owner@example.com',
            password='test-password',
        )
        cls.staff_user = user_model.objects.create_user(
            username='menu-staff',
            password='test-password',
            is_staff=True,
        )
        cls.staff_user.user_permissions.set(Permission.objects.filter(content_type__app_label='sitecontent'))

    def test_menu_link_opens_the_single_inline_editor(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse('admin:sitecontent_sitemenu_changelist'))

        self.assertRedirects(
            response,
            reverse('admin:sitecontent_sitemenu_change', args=[self.menu.pk]),
            fetch_redirect_response=False,
        )
        editor = self.client.get(reverse('admin:sitecontent_sitemenu_change', args=[self.menu.pk]))
        self.assertContains(editor, 'Пункты меню')
        self.assertContains(editor, 'Открывать в новой вкладке')
        self.assertContains(editor, 'Отображать')
        self.assertNotContains(editor, 'Удалить</a>')

    def test_site_pages_admin_exposes_only_two_editable_seo_fields(self):
        self.client.force_login(self.superuser)

        changelist = self.client.get(reverse('admin:sitecontent_sitepage_changelist'))
        editor_url = reverse(
            'admin:sitecontent_sitepage_change',
            args=[SitePage.Code.HOME],
        )
        editor = self.client.get(editor_url)

        self.assertEqual(changelist.status_code, 200)
        for page_name in dict(SitePage.Code.choices).values():
            self.assertContains(changelist, page_name)
        self.assertEqual(SitePageAdmin.fields, ('seo_title', 'seo_description'))
        self.assertEqual(set(editor.context['adminform'].form.fields), {'seo_title', 'seo_description'})
        self.assertNotContains(editor, 'name="menu_item"')
        self.assertNotContains(editor, 'Пункт меню')
        self.assertContains(editor, 'SEO-title')
        self.assertContains(editor, 'Meta description')
        self.assertNotContains(editor, 'Системный код')
        self.assertNotContains(editor, 'Удалить</a>')
        self.assertEqual(
            self.client.get(reverse('admin:sitecontent_sitepage_add')).status_code,
            403,
        )

        response = self.client.post(editor_url, {
            'seo_title': 'Новый SEO-title',
            'seo_description': 'Новое описание страницы',
            '_save': 'Сохранить',
        })

        self.assertEqual(response.status_code, 302)
        page = SitePage.objects.get(pk=SitePage.Code.HOME)
        self.assertEqual(page.seo_title, 'Новый SEO-title')
        self.assertEqual(page.seo_description, 'Новое описание страницы')
        self.assertIsNotNone(page.menu_item_id)

    def test_staff_cannot_open_menu_even_with_model_permissions(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse('admin:sitecontent_sitemenu_change', args=[self.menu.pk]))

        self.assertEqual(response.status_code, 403)

    def test_inline_editor_can_add_edit_hide_and_delete_items(self):
        self.menu.items.all().delete()
        edited_item = MenuItem.objects.create(
            menu=self.menu,
            title='Изменить',
            url='/old/',
            position=10,
        )
        deleted_item = MenuItem.objects.create(
            menu=self.menu,
            title='Удалить',
            url='/delete/',
            position=20,
        )
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse('admin:sitecontent_sitemenu_change', args=[self.menu.pk]),
            {
                'items-TOTAL_FORMS': '3',
                'items-INITIAL_FORMS': '2',
                'items-MIN_NUM_FORMS': '0',
                'items-MAX_NUM_FORMS': '1000',
                'items-0-id': str(edited_item.pk),
                'items-0-menu': str(self.menu.pk),
                'items-0-position': '15',
                'items-0-title': 'Изменено',
                'items-0-url': 'https://example.com/changed',
                'items-0-open_in_new_tab': 'on',
                'items-1-id': str(deleted_item.pk),
                'items-1-menu': str(self.menu.pk),
                'items-1-position': '20',
                'items-1-title': deleted_item.title,
                'items-1-url': deleted_item.url,
                'items-1-is_visible': 'on',
                'items-1-DELETE': 'on',
                'items-2-id': '',
                'items-2-menu': str(self.menu.pk),
                'items-2-position': '30',
                'items-2-title': 'Добавлено',
                'items-2-url': 'mailto:hello@example.com',
                'items-2-is_visible': 'on',
                '_save': 'Сохранить',
            },
        )

        self.assertEqual(response.status_code, 302)
        edited_item.refresh_from_db()
        self.assertEqual(edited_item.title, 'Изменено')
        self.assertEqual(edited_item.position, 15)
        self.assertTrue(edited_item.open_in_new_tab)
        self.assertFalse(edited_item.is_visible)
        self.assertFalse(MenuItem.objects.filter(pk=deleted_item.pk).exists())
        self.assertTrue(self.menu.items.filter(title='Добавлено', is_visible=True).exists())
        self.assertTrue(LogEntry.objects.filter(
            action_flag=CHANGE,
            object_id=str(self.menu.pk),
            user=self.superuser,
        ).exists())
        public = self.client.get(reverse('home'))
        self.assertNotContains(public, edited_item.url)
        self.assertNotContains(public, deleted_item.url)
        self.assertContains(public, 'mailto:hello@example.com', count=2)
import json
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
