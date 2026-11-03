from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.template import RequestContext, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .context_processors import site_navigation
from .models import CatalogSearchSettings, MenuItem, SiteMenu


class SiteHeaderTests(TestCase):
    def setUp(self):
        self.settings = CatalogSearchSettings.objects.get(pk=CatalogSearchSettings.CODE)
        self.catalog = self.settings.header_menu_item

    @staticmethod
    def shortcut_html(response):
        return response.content.decode().split('data-header-shortcut>', 1)[1].split('</div>', 1)[0]

    def test_migration_selects_catalog_even_though_home_is_first(self):
        self.assertEqual(self.catalog.url, reverse('skinali'))
        self.assertNotEqual(self.catalog, MenuItem.objects.first())
        self.assertEqual(
            self.settings.header_schedule,
            'ПН–ВС · ПРИЁМ ЗАКАЗОВ 10:00–21:00',
        )
        response = self.client.get(reverse('home'))
        self.assertContains(response, self.settings.header_schedule, count=1)
        self.assertContains(response, 'data-header-shortcut>', count=1)
        self.assertContains(response, 'data-header-shortcut-item', count=1)
        self.assertContains(response, 'class="site-navigation-shortcut__icon"', count=1)
        self.assertIn('Каталог скинали', self.shortcut_html(response))

    def test_reordering_renaming_and_changing_url_preserve_selected_record(self):
        self.catalog.title = 'Новая подпись раздела'
        self.catalog.url = 'https://example.com/new-catalog/'
        self.catalog.position = 100
        self.catalog.open_in_new_tab = True
        self.catalog.save()
        MenuItem.objects.create(
            menu=self.catalog.menu, title='Теперь первый', url='/skinali/', position=0,
        )

        response = self.client.get(reverse('home'))
        shortcut = self.shortcut_html(response)

        self.assertEqual(response.context['site_header_menu_item'].pk, self.catalog.pk)
        self.assertIn('Новая подпись раздела', shortcut)
        self.assertIn('href="https://example.com/new-catalog/"', shortcut)
        self.assertIn('target="_blank" rel="noopener noreferrer"', shortcut)
        self.assertNotIn('Теперь первый', shortcut)
        self.assertContains(response, 'data-header-shortcut-item', count=1)

    def test_current_shortcut_uses_same_non_link_markup_as_menu(self):
        response = self.client.get(reverse('skinali'))
        shortcut = self.shortcut_html(response)

        self.assertIn('<span aria-current="page">', shortcut)
        self.assertIn('site-navigation-shortcut__icon', shortcut)
        self.assertNotIn('<a ', shortcut)

    def test_empty_favorites_hide_both_menu_entries(self):
        response = self.client.get(reverse('home'))
        html = response.content.decode()
        self.assertContains(response, 'data-favorites-menu hidden', count=2)
        self.assertContains(response, 'data-header-favorites data-favorites-menu hidden>')
        self.assertLess(html.index('data-header-shortcut>'), html.index('data-header-favorites'))
        self.assertLess(html.index('data-header-favorites'), html.index('data-mobile-menu-open'))

    def test_current_favorites_shortcut_has_no_self_link(self):
        response = self.client.get(reverse('favorites'))
        favorites = response.content.decode().split('data-header-favorites data-favorites-menu hidden>', 1)[1].split('</div>', 1)[0]
        self.assertIn('<span aria-current="page">', favorites)
        self.assertIn('site-navigation-favorites__label">Избранное</span>', favorites)
        self.assertIn('data-favorites-count>0</span>', favorites)
        self.assertNotIn('<a ', favorites)

    def test_hiding_and_showing_item_updates_shortcut_on_next_request(self):
        self.catalog.is_visible = False
        self.catalog.save(update_fields=['is_visible'])
        hidden = self.client.get(reverse('home'))
        self.assertNotContains(hidden, 'data-header-shortcut')
        self.assertFalse(hidden.context['site_header_menu_item'])

        self.catalog.is_visible = True
        self.catalog.save(update_fields=['is_visible'])
        visible = self.client.get(reverse('home'))
        self.assertIn(self.catalog.title, self.shortcut_html(visible))

    def test_deleting_item_does_not_select_another_item_with_same_url(self):
        menu = self.catalog.menu
        self.catalog.delete()
        MenuItem.objects.create(menu=menu, title='Новый каталог', url='/skinali/', position=0)

        response = self.client.get(reverse('home'))
        self.settings.refresh_from_db()

        self.assertIsNone(self.settings.header_menu_item_id)
        self.assertFalse(response.context['site_header_menu_item'])
        self.assertNotContains(response, 'data-header-shortcut')
        self.assertContains(response, 'Новый каталог', count=2)

    def test_schedule_changes_are_escaped_and_empty_text_is_hidden(self):
        self.settings.header_schedule = '<b>Пн–Пт 09:00–18:00</b>'
        self.settings.save(update_fields=['header_schedule'])
        changed = self.client.get(reverse('home'))
        self.assertContains(changed, '&lt;b&gt;Пн–Пт 09:00–18:00&lt;/b&gt;', count=1)
        self.assertNotContains(changed, '<b>Пн–Пт 09:00–18:00</b>')

        self.settings.header_schedule = ''
        self.settings.save(update_fields=['header_schedule'])
        self.assertNotContains(self.client.get(reverse('home')), 'class="site-header__schedule"')

    def test_context_is_lazy_and_reuses_one_settings_and_one_menu_query(self):
        with self.assertNumQueries(0):
            context = site_navigation(RequestFactory().get('/'))
        with self.assertNumQueries(2):
            self.assertEqual(context['site_header_menu_item'].pk, self.catalog.pk)
            self.assertEqual(context['site_header_settings'].header_schedule, self.settings.header_schedule)
            first = list(context['site_menu_items'])
            self.assertEqual(list(context['site_menu_items']), first)
            self.assertIn(reverse('skinali'), context['visible_site_menu_urls'])

    def test_missing_settings_preserve_schedule_and_full_menu_without_shortcut(self):
        CatalogSearchSettings.objects.all().delete()
        request = RequestFactory().get('/')
        template = Template(
            '{{ site_header_settings.header_schedule }}|'
            '{% if site_header_menu_item %}shortcut{% endif %}'
            '{% for item in site_menu_items %}{{ item.title }};{% endfor %}'
        )
        with self.assertNumQueries(2):
            content = template.render(RequestContext(request))
        self.assertTrue(content.startswith(CatalogSearchSettings.DEFAULT_HEADER_SCHEDULE + '|'))
        self.assertIn(self.catalog.title, content)
        self.assertNotIn('shortcut', content)

    def test_model_validates_schedule_limit(self):
        self.settings.header_schedule = 'Я' * 40
        self.settings.full_clean()
        self.settings.header_schedule += 'Я'
        with self.assertRaises(ValidationError) as error:
            self.settings.full_clean()
        self.assertIn('header_schedule', error.exception.message_dict)


class SiteHeaderAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser(
            username='header-owner', email='header@example.com', password=None,
        )
        cls.settings_url = reverse(
            'admin:sitecontent_catalogsearchsettings_change', args=[CatalogSearchSettings.CODE],
        )

    def setUp(self):
        self.client.force_login(self.superuser)
        self.settings = CatalogSearchSettings.objects.get(pk=CatalogSearchSettings.CODE)

    def test_admin_exposes_header_group_and_browser_length_limit(self):
        response = self.client.get(self.settings_url)
        form = response.context['adminform'].form
        self.assertContains(response, 'Шапка сайта')
        self.assertEqual(form.fields['header_schedule'].label, 'Текст в шапке')
        self.assertIn('акция', form.fields['header_schedule'].help_text)
        self.assertEqual(form.fields['header_schedule'].max_length, 40)
        self.assertEqual(form.fields['header_schedule'].widget.attrs['maxlength'], '40')
        self.assertIn('header_menu_item', form.fields)

    def test_admin_accepts_40_characters_and_rejects_41_without_saving(self):
        for length, expected_status in ((40, 302), (41, 200)):
            with self.subTest(length=length):
                response = self.client.post(self.settings_url, {
                    'header_schedule': 'Я' * length,
                    'header_menu_item': self.settings.header_menu_item_id,
                    'use_lemmatization': 'on',
                    '_save': 'Сохранить',
                })
                self.assertEqual(response.status_code, expected_status)
                self.settings.refresh_from_db()
                self.assertEqual(self.settings.header_schedule, 'Я' * 40)
                if length == 41:
                    self.assertIn('header_schedule', response.context['adminform'].form.errors)

    def test_admin_can_choose_another_specific_item(self):
        item = MenuItem.objects.get(menu__code=SiteMenu.MAIN_CODE, url='/price/')
        response = self.client.post(self.settings_url, {
            'header_schedule': 'Пн–Пт 09:00–18:00',
            'header_menu_item': item.pk,
            'use_lemmatization': 'on',
            '_save': 'Сохранить',
        })
        self.assertEqual(response.status_code, 302)
        public = self.client.get(reverse('home'))
        self.assertEqual(public.context['site_header_menu_item'].pk, item.pk)
        self.assertIn('Цена', SiteHeaderTests.shortcut_html(public))
        self.assertContains(public, 'Пн–Пт 09:00–18:00', count=1)

    def test_unchecking_visibility_in_admin_removes_items_from_all_navigation(self):
        menu = SiteMenu.objects.get(code=SiteMenu.MAIN_CODE)
        items = list(menu.items.all())
        hidden_ids = {self.settings.header_menu_item_id, items[0].pk}
        data = {
            'items-TOTAL_FORMS': len(items),
            'items-INITIAL_FORMS': len(items),
            'items-MIN_NUM_FORMS': 0,
            'items-MAX_NUM_FORMS': 1000,
            '_save': 'Сохранить',
        }
        for index, item in enumerate(items):
            prefix = f'items-{index}-'
            data.update({
                prefix + 'id': item.pk,
                prefix + 'menu': menu.pk,
                prefix + 'position': item.position,
                prefix + 'title': item.title,
                prefix + 'url': item.url,
            })
            if item.open_in_new_tab:
                data[prefix + 'open_in_new_tab'] = 'on'
            if item.pk not in hidden_ids:
                data[prefix + 'is_visible'] = 'on'

        saved = self.client.post(reverse('admin:sitecontent_sitemenu_change', args=[menu.pk]), data)
        self.assertEqual(saved.status_code, 302)
        public = self.client.get(reverse('home'))
        html = public.content.decode()
        main_navigation = html.split('<nav class="main-navigation"', 1)[1].split('</nav>', 1)[0]
        footer = html.split('<footer class="site-footer">', 1)[1].split('</footer>', 1)[0]
        self.assertNotContains(public, 'data-header-shortcut')
        self.assertFalse(public.context['site_header_menu_item'])
        for item in items:
            with self.subTest(item=item.title):
                if item.pk in hidden_ids:
                    self.assertNotIn(item.title, main_navigation)
                    self.assertNotIn(item.title, footer)
                else:
                    self.assertIn(item.title, main_navigation)
                    self.assertIn(item.title, footer)
