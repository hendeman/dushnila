from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from pict.admin import CategoryAdmin, FinishedWorkAdmin, PictAdmin, TagPictAdmin
from pict.models import Category, FinishedWork, Pict, TagPict

from .admin import ArticleAdmin, SiteMenuAdmin, SitePageAdmin
from .models import Article, SiteMenu, SitePage


class SeoAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username='seo-admin', email='seo@example.com', password='test-password',
        )
        # PictAdminForm предлагает следующий номер по существующей записи.
        Pict.objects.create(name=1001, alt='Тест SEO', photo='')

    def setUp(self):
        self.request = RequestFactory().get('/admin/')
        self.request.user = self.user

    def seo_admins(self):
        for model, model_admin in (
            (Pict, PictAdmin), (Category, CategoryAdmin), (TagPict, TagPictAdmin),
            (SitePage, SitePageAdmin), (Article, ArticleAdmin),
        ):
            yield model, model_admin(model, admin.site)

    def test_recommendations_and_counters_are_shared_by_all_seo_admins(self):
        for model, model_admin in self.seo_admins():
            with self.subTest(model=model.__name__):
                fields = model_admin.get_form(self.request).base_fields
                for name, recommendation in (
                    ('seo_title', '50–60 символов'),
                    ('seo_description', '140–160 символов'),
                ):
                    self.assertIn(recommendation, fields[name].help_text)
                    self.assertIn(model._meta.get_field(name).help_text, fields[name].help_text)
                    self.assertEqual(fields[name].widget.attrs['data-seo-counter'], 'true')
                    self.assertIn('admin-seo-field', fields[name].widget.attrs['class'].split())
                if 'seo_h1' in fields:
                    self.assertEqual(fields['seo_h1'].widget.attrs['data-seo-counter'], 'true')
                    self.assertIn('admin-seo-field', fields['seo_h1'].widget.attrs['class'].split())

    def test_recommendations_do_not_reduce_existing_length_limits(self):
        for model, model_admin in self.seo_admins():
            with self.subTest(model=model.__name__):
                fields = model_admin.get_form(self.request).base_fields
                for name, maximum in (('seo_title', 200), ('seo_description', 320)):
                    field = fields[name]
                    self.assertEqual(field.max_length, maximum)
                    self.assertEqual(field.widget.attrs['maxlength'], str(maximum))
                    self.assertEqual(field.clean(''), '')
                    self.assertEqual(field.clean('а' * maximum), 'а' * maximum)
                    with self.assertRaises(ValidationError):
                        field.clean('а' * (maximum + 1))

    def test_model_help_text_is_not_mutated_or_repeated_between_form_builds(self):
        for model, model_admin in self.seo_admins():
            with self.subTest(model=model.__name__):
                original = model._meta.get_field('seo_title').help_text
                for _ in range(2):
                    field = model_admin.get_form(self.request).base_fields['seo_title']
                    self.assertEqual(field.help_text.count('Рекомендуемая длина:'), 1)
                    self.assertEqual(model._meta.get_field('seo_title').help_text, original)

    def test_page_text_fields_share_width_without_unneeded_counters(self):
        for model, model_admin in self.seo_admins():
            fields = model_admin.get_form(self.request).base_fields
            for name in ('intro_text', 'page_description'):
                if name in fields:
                    with self.subTest(model=model.__name__, field=name):
                        self.assertIn('admin-seo-field', fields[name].widget.attrs['class'].split())
                        self.assertNotIn('data-seo-counter', fields[name].widget.attrs)

    def test_shared_assets_are_loaded_once_and_other_admin_assets_are_preserved(self):
        for model, model_admin in self.seo_admins():
            with self.subTest(model=model.__name__):
                self.assertEqual(model_admin.media._css['all'].count('skinali/css/admin-seo-landing-fields.css'), 1)
                self.assertEqual(model_admin.media._js.count('skinali/js/admin-seo-fields.js'), 1)
                self.assertIn('admin/js/core.js', model_admin.media._js)
                if model is Pict:
                    self.assertIn('skinali/css/admin-image-preview.css', model_admin.media._css['all'])
                    self.assertIn('skinali/js/admin-image-preview.js', model_admin.media._js)
                if model is Category:
                    self.assertIn('skinali/js/admin-category-order.js', model_admin.media._js)

    def test_non_seo_admins_and_fields_remain_unchanged(self):
        for model, model_admin in ((FinishedWork, FinishedWorkAdmin), (SiteMenu, SiteMenuAdmin)):
            self.assertNotIn('skinali/js/admin-seo-fields.js', model_admin(model, admin.site).media._js)
        field = CategoryAdmin(Category, admin.site).get_form(self.request).base_fields['cat']
        self.assertNotIn('data-seo-counter', field.widget.attrs)
        self.assertNotIn('admin-seo-field', field.widget.attrs.get('class', '').split())

    def test_all_admin_editors_render_recommendations_and_counter_hooks(self):
        self.client.force_login(self.user)
        for url_name in (
            'admin:pict_pict_add', 'admin:pict_category_add', 'admin:pict_tagpict_add',
            'admin:sitecontent_article_add',
        ):
            with self.subTest(url=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '50–60 символов')
                self.assertContains(response, '140–160 символов')
                self.assertContains(response, 'data-seo-counter="true"')
                self.assertContains(response, 'skinali/js/admin-seo-fields.js', count=1)
                self.assertContains(response, 'skinali/css/admin-seo-landing-fields.css', count=1)
                if url_name == 'admin:sitecontent_article_add':
                    self.assertContains(response, 'sitecontent/vendor/quill/quill.js')
                    self.assertContains(response, 'sitecontent/js/quill-editor.js')
        response = self.client.get(reverse('admin:sitecontent_sitepage_change', args=[SitePage.Code.HOME]))
        self.assertContains(response, '50–60 символов')
        self.assertContains(response, '140–160 символов')
        self.assertContains(response, 'skinali/js/admin-seo-fields.js', count=1)

    def test_site_page_saves_values_outside_recommended_ranges(self):
        self.client.force_login(self.user)
        title = 'З' * 80
        description = 'О' * 180
        response = self.client.post(
            reverse('admin:sitecontent_sitepage_change', args=[SitePage.Code.HOME]),
            {'seo_title': title, 'seo_description': description, '_save': 'Сохранить'},
        )
        self.assertEqual(response.status_code, 302)
        page = SitePage.objects.get(pk=SitePage.Code.HOME)
        self.assertEqual(page.seo_title, title)
        self.assertEqual(page.seo_description, description)

    def test_shared_width_includes_image_description_and_keeps_article_overrides(self):
        styles = Path(settings.BASE_DIR, 'pict/static/skinali/css/admin-seo-landing-fields.css').read_text(encoding='utf-8')
        for selector in ('#id_seo_h1', '#id_seo_title', '#id_seo_description', '#id_page_description', '#id_intro_text'):
            self.assertIn(selector, styles)
        self.assertIn('width: 48em;', styles)
        self.assertIn('max-width: 100%;', styles)
        self.assertIn('.app-sitecontent.model-article #id_title', styles)
        self.assertIn('.app-sitecontent.model-article #id_slug', styles)
