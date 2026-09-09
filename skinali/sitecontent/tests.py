from django.contrib.auth import get_user_model
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.template import RequestContext, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .models import MenuItem, SiteMenu


class SiteMenuModelTests(TestCase):
    def setUp(self):
        self.menu = SiteMenu.objects.get(code=SiteMenu.MAIN_CODE)

    def test_initial_menu_preserves_existing_links_and_order(self):
        self.assertEqual(
            list(self.menu.items.values_list('title', 'url', 'position', 'is_visible')),
            [
                ('Главная страница', '/', 10, True),
                ('Каталог скинали', '/skinali/', 20, True),
                ('Наши работы', '/foto-skinali-iz-stekla/', 30, True),
                ('Услуги дизайнера', '/designer', 40, True),
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
        self.assertNotContains(response, 'class="is-active"')
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
