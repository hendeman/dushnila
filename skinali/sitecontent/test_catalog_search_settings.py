from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from pict.models import Category, Pict, TagAlias, TagPict
from pict.search import apply_catalog_search, parse_search_query
from pict.tests import create_test_image_file

from .models import CatalogSearchSettings


class CatalogSearchSettingsModelTests(TestCase):
    def test_migration_creates_one_enabled_settings_card(self):
        self.assertEqual(CatalogSearchSettings.objects.count(), 1)
        settings = CatalogSearchSettings.objects.get(pk=CatalogSearchSettings.CODE)
        self.assertTrue(settings.use_lemmatization)
        self.assertEqual(str(settings), 'Настройки сайта')

    def test_database_and_validation_reject_another_settings_card(self):
        with self.assertRaises(ValidationError):
            CatalogSearchSettings(code='other').full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CatalogSearchSettings.objects.create(code='other')

    def test_mode_is_read_fresh_with_one_query(self):
        with self.assertNumQueries(1):
            self.assertTrue(CatalogSearchSettings.is_lemmatization_enabled())
        CatalogSearchSettings.objects.update(use_lemmatization=False)
        with self.assertNumQueries(1):
            self.assertFalse(CatalogSearchSettings.is_lemmatization_enabled())

    def test_missing_settings_card_preserves_enabled_mode(self):
        CatalogSearchSettings.objects.all().delete()
        self.assertTrue(CatalogSearchSettings.is_lemmatization_enabled())


class CatalogSearchSettingsAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.superuser = users.objects.create_superuser(
            username='search-settings-owner', email='owner@example.com', password=None,
        )
        cls.staff = users.objects.create_user(username='search-settings-staff', is_staff=True)
        cls.staff.user_permissions.set(Permission.objects.filter(
            content_type__app_label__in=('sitecontent', 'pict'),
        ))
        cls.card_url = reverse(
            'admin:sitecontent_catalogsearchsettings_change',
            args=[CatalogSearchSettings.CODE],
        )
        cls.list_url = reverse('admin:sitecontent_catalogsearchsettings_changelist')
        cls.tags_url = reverse('admin:pict_tagpict_changelist')

    def setUp(self):
        self.client.force_login(self.superuser)

    def test_settings_link_opens_single_card_with_one_checkbox(self):
        response = self.client.get(self.list_url)
        self.assertRedirects(response, self.card_url, fetch_redirect_response=False)
        editor = self.client.get(self.card_url)
        self.assertEqual(list(editor.context['adminform'].form.fields), ['use_lemmatization'])
        self.assertContains(editor, 'Учитывать словоформы при поиске')
        self.assertContains(editor, 'поиск по фрагментам слов в тегах и синонимах')

    def test_setting_can_be_disabled_and_enabled_with_admin_history(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                data = {'_save': 'Сохранить'}
                if enabled:
                    data['use_lemmatization'] = 'on'
                response = self.client.post(self.card_url, data)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(CatalogSearchSettings.is_lemmatization_enabled(), enabled)
        self.assertEqual(LogEntry.objects.filter(
            object_id=CatalogSearchSettings.CODE, action_flag=CHANGE,
        ).count(), 2)

    def test_system_card_cannot_be_added_or_deleted(self):
        self.assertEqual(self.client.get(reverse('admin:sitecontent_catalogsearchsettings_add')).status_code, 403)
        self.assertEqual(self.client.post(reverse(
            'admin:sitecontent_catalogsearchsettings_delete', args=[CatalogSearchSettings.CODE],
        ), {'post': 'yes'}).status_code, 403)

    def test_tags_link_is_available_only_to_superuser(self):
        response = self.client.get(self.tags_url)
        self.assertContains(response, f'<a href="{self.list_url}">Настройки сайта</a>', html=True)
        self.client.force_login(self.staff)
        response = self.client.get(self.tags_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, f'<a href="{self.list_url}">Настройки сайта</a>', html=True)
        self.assertEqual(self.client.get(self.card_url).status_code, 403)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)

    def test_csrf_is_required_to_change_global_mode(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.superuser)
        self.assertEqual(client.post(self.card_url, {'_save': 'Сохранить'}).status_code, 403)
        self.assertTrue(CatalogSearchSettings.is_lemmatization_enabled())


class CatalogSearchModeTests(TestCase):
    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        media_settings = override_settings(MEDIA_ROOT=media.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        self.card = CatalogSearchSettings.objects.get(pk=CatalogSearchSettings.CODE)
        self.category = Category.objects.create(cat='Первая', slug='mode-first')
        self.other_category = Category.objects.create(cat='Вторая', slug='mode-second')
        self.sea_tag = TagPict.objects.create(tag='Море', slug='mode-sea')
        self.sunset_tag = TagPict.objects.create(tag='Закат', slug='mode-sunset')
        self.partial_tag = TagPict.objects.create(tag='Океанариум', slug='mode-oceanarium')
        TagAlias.objects.create(tag=self.sea_tag, alias='Океан')
        self.sea = self.picture(6001, self.category, self.sea_tag, self.sunset_tag)
        self.partial = self.picture(6002, self.category, self.partial_tag)
        self.other_sea = self.picture(6003, self.other_category, self.sea_tag)
        self.hidden = self.picture(6004, self.category, self.sea_tag, is_published=False)

    @staticmethod
    def picture(number, category, *tags, is_published=True):
        picture = Pict.objects.create(
            name=number, alt=f'Изображение {number}',
            photo=create_test_image_file(f'mode-{number}.jpg', size=(100, 20)),
            is_published=is_published,
        )
        picture.cat.add(category)
        picture.tags.add(*tags)
        return picture

    def set_mode(self, enabled):
        self.card.use_lemmatization = enabled
        self.card.save(update_fields={'use_lemmatization'})

    def search(self, query, url=None):
        response = self.client.get(url or reverse('skinali'), {'q': query})
        self.assertEqual(response.status_code, 200)
        return list(response.context['object_list'])

    def test_mode_changes_apply_on_next_request(self):
        self.assertEqual(self.search('оке'), [])
        self.assertEqual(self.search('океанами'), [self.other_sea, self.sea])
        self.set_mode(False)
        self.assertEqual(self.search('оке'), [self.other_sea, self.partial, self.sea])
        self.assertEqual(self.search('океанами'), [])
        self.set_mode(True)
        self.assertEqual(self.search('оке'), [])
        self.assertEqual(self.search('океанами'), [self.other_sea, self.sea])

    def test_disabled_mode_matches_tag_and_alias_fragments_without_morphology(self):
        self.set_mode(False)
        with patch('pict.search.lemmatize_search_term') as lemmatizer:
            self.assertEqual(self.search('оке'), [self.other_sea, self.partial, self.sea])
        lemmatizer.assert_not_called()

    def test_disabled_mode_preserves_exact_alias_ranking(self):
        self.set_mode(False)
        self.assertEqual(self.search('океан'), [self.other_sea, self.sea, self.partial])

    def test_disabled_mode_preserves_and_and_category_scope(self):
        self.set_mode(False)
        self.assertEqual(self.search('оке зак'), [self.sea])
        self.assertEqual(self.search('оке', self.category.get_absolute_url()), [self.partial, self.sea])

    def test_non_search_invalid_and_numeric_queries_do_not_read_setting(self):
        with patch.object(CatalogSearchSettings, 'is_lemmatization_enabled') as setting:
            self.client.get(reverse('skinali'))
            self.search('мо')
            self.assertEqual(self.search('6001'), [self.sea])
        setting.assert_not_called()

    def test_pure_orm_disabled_search_uses_one_query_for_any_number_of_terms(self):
        for query in ('оке', 'оке зак лес рек пол'):
            with self.subTest(query=query), self.assertNumQueries(1):
                apply_catalog_search(
                    Pict.objects.published(), parse_search_query(query),
                    use_lemmatization=False,
                ).count()

    def test_lemma_index_keeps_updating_while_search_mode_is_disabled(self):
        self.set_mode(False)
        self.sea_tag.tag = 'Моря'
        self.sea_tag.save(update_fields={'tag'})
        self.assertEqual(set(self.sea_tag.search_lemmas.values_list('lemma', flat=True)), {'море'})
        self.set_mode(True)
        self.assertEqual(self.search('морями'), [self.other_sea, self.sea])
