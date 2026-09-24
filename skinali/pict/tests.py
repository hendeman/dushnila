import json
import re
import time
import xml.etree.ElementTree as ElementTree
from datetime import timedelta
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import requests
from PIL import Image
from django.apps import apps
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.core.paginator import Paginator
from django.db import connection
from django.template import RequestContext, Template
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.html import escape
from sitecontent.models import SitePage
from sorl.thumbnail.shortcuts import get_thumbnail

from .admin import (
    CategoryAdmin,
    ContactRequestAdmin,
    ContactRequestDeliveryInline,
    FinishedWorkAdmin,
    PictAdmin,
    TagPictAdmin,
)
from .context_processors import site_identity
from .forms import (
    CONTACT_FORM_TOKEN_SALT,
    BaseContactForm,
    CallbackContactForm,
    CatalogSearchForm,
    EmailCommentContactForm,
    FinishedWorkAdminForm,
    ImagePurchaseContactForm,
    IntegrationAdminForm,
    PhoneContactForm,
    QuestionContactForm,
)
from .models import (
    Category,
    Color,
    ContactRequest,
    ContactRequestDelivery,
    FinishedWork,
    Integration,
    IntegrationRevision,
    Pict,
    TagAlias,
    TagPict,
)
from .search import format_image_count, normalize_search_value, parse_search_query
from .services.contact_delivery import format_contact_request_message
from .views import SkinaliAll, serverError, set_page_metadata


TEST_MEDIA_DIRECTORY = TemporaryDirectory()
TEST_MEDIA_SETTINGS = override_settings(MEDIA_ROOT=TEST_MEDIA_DIRECTORY.name)


def setUpModule():
    """Изолирует создаваемые тестами изображения от рабочего media-каталога."""
    TEST_MEDIA_SETTINGS.enable()


def tearDownModule():
    TEST_MEDIA_SETTINGS.disable()
    TEST_MEDIA_DIRECTORY.cleanup()


def create_test_image_file(filename, size=(1000, 200)):
    """Возвращает настоящий JPEG для проверок ImageField и sorl-thumbnail."""
    image_bytes = BytesIO()
    Image.new('RGB', size, color='#7f9f74').save(image_bytes, format='JPEG')
    return SimpleUploadedFile(
        filename,
        image_bytes.getvalue(),
        content_type='image/jpeg',
    )


def get_json_ld(response, element_id):
    html = response.content.decode()
    marker = f'<script id="{element_id}" type="application/ld+json">'
    start = html.index(marker) + len(marker)
    end = html.index('</script>', start)
    return json.loads(html[start:end])


def get_breadcrumb_structured_data(response):
    return get_json_ld(response, 'breadcrumb-structured-data')


def get_sitemap_lastmods(response):
    root = ElementTree.fromstring(response.content)
    namespace = {'sitemap': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    return {
        url.find('sitemap:loc', namespace).text: url.find(
            'sitemap:lastmod',
            namespace,
        ).text
        for url in root.findall('sitemap:url', namespace)
        if url.find('sitemap:lastmod', namespace) is not None
    }


class DeploymentConfigurationTests(SimpleTestCase):
    def test_deploy_script_covers_all_local_python_packages(self):
        deploy_script_path = (
            settings.BASE_DIR.parent / 'ops' / 'deploy_hostland.sh'
        )
        deploy_script = deploy_script_path.read_text(encoding='utf-8')
        directories_match = re.search(
            r'^readonly -a CODE_DIRECTORIES=\(([^)]*)\)$',
            deploy_script,
            re.MULTILINE,
        )

        self.assertIsNotNone(directories_match)
        deployed_directories = set(directories_match.group(1).split())
        local_app_directories = {
            Path(app_config.path).name
            for app_config in apps.get_app_configs()
            if Path(app_config.path).parent == settings.BASE_DIR
        }
        self.assertEqual(
            deployed_directories,
            local_app_directories | {'skinali'},
        )
        self.assertEqual(
            deploy_script.count('for directory in "${CODE_DIRECTORIES[@]}"; do'),
            4,
        )


class PopularTagsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first_category = Category.objects.create(cat='Первая', slug='first')
        cls.second_category = Category.objects.create(cat='Вторая', slug='second')
        cls.selected_color = Color.objects.create(color='Красный', slug_color='red')
        cls.second_color = Color.objects.create(color='Синий', slug_color='blue')
        cls.third_color = Color.objects.create(color='Зелёный', slug_color='green')
        cls.fourth_color = Color.objects.create(color='Жёлтый', slug_color='yellow')

        cls.first_tag = TagPict.objects.create(tag='Первый тег', slug='first-tag')
        cls.second_tag = TagPict.objects.create(tag='Второй тег', slug='second-tag')
        cls.cross_category_tag = TagPict.objects.create(tag='Общий тег', slug='cross-category-tag')

        first_category_pictures = cls.create_pictures(cls.first_category, 100, 3)
        second_category_pictures = cls.create_pictures(cls.second_category, 200, 3)
        first_category_pictures[0].color.add(
            cls.selected_color,
            cls.second_color,
            cls.third_color,
        )
        first_category_pictures[1].color.add(
            cls.selected_color,
            cls.second_color,
        )
        first_category_pictures[2].color.add(
            cls.selected_color,
            cls.third_color,
        )

        cls.first_tag.tags.add(*first_category_pictures)
        cls.second_tag.tags.add(*second_category_pictures)
        cls.cross_category_tag.tags.add(
            *first_category_pictures[:2],
            *second_category_pictures[:2],
        )
        cls.single_picture_tags = []
        for index in range(10):
            tag = TagPict.objects.create(
                tag=f'Одиночный тег {index:02d}',
                slug=f'single-picture-tag-{index:02d}',
            )
            tag.tags.add(first_category_pictures[0])
            cls.single_picture_tags.append(tag)

    @staticmethod
    def create_pictures(category, start_name, count):
        pictures = []
        for offset in range(count):
            picture = Pict.objects.create(
                name=start_name + offset,
                alt=f'Описание изображения {start_name + offset}',
                photo=create_test_image_file(f'{start_name + offset}.jpg'),
            )
            picture.cat.add(category)
            pictures.append(picture)
        return pictures

    def test_category_uses_global_tags_sorted_and_limited_to_ten(self):
        response = self.client.get(
            reverse('skinali', kwargs={'slug_cat': self.first_category.slug})
        )

        tags = list(response.context['list_tag'])
        totals = [tag.total for tag in tags]
        tag_slugs = {tag.slug for tag in tags}

        self.assertEqual(len(tags), 10)
        self.assertEqual(totals, sorted(totals, reverse=True))
        self.assertEqual(tags[0].slug, self.cross_category_tag.slug)
        self.assertEqual(tags[0].total, 4)
        self.assertTrue(any(tag.total == 1 for tag in tags))
        self.assertIn(self.first_tag.slug, tag_slugs)
        self.assertIn(self.second_tag.slug, tag_slugs)
        self.assertContains(response, f'>{self.first_tag.tag}</a>', html=False)
        self.assertNotContains(response, f'{self.first_tag.tag} (3)')
        self.assertContains(response, 'Популярные темы:')
        self.assertContains(response, 'data-fancybox="catalog-gallery"')
        self.assertContains(response, 'data-caption-template="catalog-gallery-caption-')
        self.assertContains(response, 'data-caption="Описание изображения 100"')
        self.assertContains(
            response,
            '<span class="catalog-thumbnail__image-number">'
            '<span class="catalog-thumbnail__image-number-text">№ 100</span>'
            '</span>',
            html=True,
        )
        self.assertContains(response, 'class="catalog-modal__title"')
        self.assertNotContains(response, 'class="catalog-modal__image-number"')
        self.assertContains(response, 'Описание изображения 100')
        self.assertContains(response, '<span>#Первый тег</span>', html=True)
        self.assertContains(response, '<dd>№100</dd>', html=True)
        self.assertContains(response, self.first_category.cat)
        self.assertContains(response, 'class="catalog-modal__nav catalog-modal__nav--prev"')
        self.assertContains(response, 'class="catalog-modal__nav catalog-modal__nav--next"')
        self.assertNotContains(response, 'catalog-modal__counter')
        self.assertContains(response, 'data-favorite-toggle')
        self.assertContains(response, 'class="catalog-modal__share"')
        self.assertContains(response, 'data-share-kind="image"')
        self.assertContains(response, 'data-share-toggle')
        first_picture = Pict.objects.get(name=100)
        self.assertContains(
            response,
            f'data-share-image-url="{first_picture.photo.url}"',
        )
        self.assertContains(response, 'data-share-service="telegram"')
        self.assertContains(response, 'data-share-service="viber"')
        self.assertContains(response, 'data-share-service="whatsapp"')
        self.assertContains(response, 'skinali/js/image-sharing.js')
        self.assertContains(response, 'class="catalog-modal__purchase"')
        self.assertContains(response, 'data-image-purchase-open')
        self.assertContains(response, 'data-image-number="100"')
        response_html = response.content.decode()
        self.assertGreater(
            response_html.index('class="catalog-modal__share"'),
            response_html.index('class="catalog-modal__purchase"'),
        )
        self.assertContains(
            response,
            f'<a href="{reverse("skinali")}">Все</a>',
            html=True,
        )

    def test_all_catalog_keeps_global_counts_and_ten_tag_limit(self):
        response = self.client.get(reverse('skinali'))
        mobile_filters_script = Path(
            settings.BASE_DIR,
            'pict/static/skinali/js/mobile-filters.js',
        ).read_text(encoding='utf-8')
        styles = Path(
            settings.BASE_DIR,
            'pict/static/skinali/css/styles.css',
        ).read_text(encoding='utf-8')

        tags = list(response.context['list_tag'])
        totals = [tag.total for tag in tags]
        tag_slugs = {tag.slug for tag in tags}

        self.assertEqual(len(tags), 10)
        self.assertEqual(totals, sorted(totals, reverse=True))
        self.assertEqual(tags[0].slug, self.cross_category_tag.slug)
        self.assertEqual(tags[0].total, 4)
        self.assertIn(self.first_tag.slug, tag_slugs)
        self.assertIn(self.second_tag.slug, tag_slugs)
        self.assertContains(
            response,
            '<li class="page-num page-num-selected">Все</li>',
            html=True,
        )
        self.assertNotContains(
            response,
            f'<a href="{reverse("skinali")}">Все</a>',
            html=True,
        )
        self.assertContains(response, '<div class="list-all">Все цвета</div>', html=True)
        self.assertContains(response, 'placeholder="Поиск, например море"')
        self.assertContains(response, 'href="/static/skinali/css/styles.css"')
        self.assertContains(response, 'skinali/images/logo_skinali.png', count=1)
        self.assertContains(response, 'skinali/images/logo_skinali_white.png', count=1)
        self.assertTrue(
            Path(
                settings.BASE_DIR,
                'pict/static/skinali/images/logo_skinali_white.png',
            ).is_file()
        )
        self.assertContains(response, 'class="site-header__logo-image"')
        self.assertContains(response, 'class="site-footer__logo-image"')
        self.assertNotContains(response, 'class="site-header__logo-mark"')
        self.assertContains(response, 'ПН–ВС · ПРИЁМ ЗАКАЗОВ')
        self.assertContains(response, '10:00–21:00')
        self.assertContains(
            response,
            '<span class="site-header__phone-icon" aria-hidden="true">☎</span>',
            html=True,
        )
        self.assertContains(response, 'class="site-topbar"')
        self.assertContains(response, 'class="site-info-panel"')
        self.assertContains(response, 'class="site-navigation-panel"')
        self.assertContains(response, 'class="site-navigation-panel__inner"')
        self.assertContains(response, '<main class="site-main">')
        self.assertContains(response, '<div class="site-content">')
        self.assertContains(response, 'class="site-search__form"')
        self.assertContains(response, 'Популярные темы:')
        self.assertContains(response, 'class="container catalog-gallery"')
        self.assertContains(
            response,
            'Выберите сюжет по теме и цвету. Нажмите на изображение, '
            'чтобы увидеть его номер, теги и раздел каталога.',
        )
        self.assertContains(response, 'class="catalog-intro"')
        self.assertContains(response, 'class="site-footer"')
        self.assertContains(response, 'href="tel:+375291498838"')
        self.assertContains(response, 'data-mobile-menu-open')
        self.assertContains(response, 'id="mobile-site-menu"')
        self.assertNotContains(response, 'data-mobile-menu-close')
        self.assertContains(response, 'src="/static/skinali/js/site-menu.js"')
        self.assertContains(response, 'data-mobile-filter-open="mobile-category-filter"')
        self.assertContains(response, 'data-mobile-filter-open="mobile-color-filter"')
        self.assertContains(response, 'id="mobile-category-filter"')
        self.assertContains(response, 'id="mobile-color-filter"')
        self.assertContains(response, 'mobile-catalog-filters__chevron')
        self.assertContains(response, 'src="/static/skinali/js/mobile-filters.js"')
        self.assertContains(response, 'data-mobile-color-form')
        self.assertContains(response, 'data-mobile-color-checkbox')
        self.assertContains(response, 'class="mobile-color-filter__apply"')
        self.assertContains(response, 'Применить цвета')
        self.assertContains(
            response,
            'Можно выбрать до 3 цветов. После выбора нажмите кнопку '
            '«Применить цвета».',
        )
        self.assertNotContains(response, 'data-mobile-color-reset')
        self.assertContains(
            response,
            '<span class="mobile-filter-dialog__check" '
            'data-mobile-color-all-check aria-hidden="true">✓</span>',
            html=True,
        )
        self.assertContains(
            response,
            '<span class="mobile-filter-dialog__check" '
            'data-mobile-color-check aria-hidden="true" hidden>✓</span>',
            count=4,
            html=True,
        )
        self.assertIn("'.catalog-categories a'", mobile_filters_script)
        self.assertIn("'.list-pages-color a'", mobile_filters_script)
        self.assertIn("'.mobile-filter-dialog a'", mobile_filters_script)
        self.assertIn('window.sessionStorage.setItem', mobile_filters_script)
        self.assertIn(
            'window.scrollTo(savedScroll.left, savedScroll.top);',
            mobile_filters_script,
        )
        self.assertIn("form.addEventListener('submit'", mobile_filters_script)
        self.assertIn('clearColorSelection', mobile_filters_script)
        self.assertIn('.mobile-color-filter__apply {', styles)
        self.assertIn('background: #1f2722;', styles)
        self.assertIn('border-radius: 3px;', styles)
        self.assertIn('color: #fff;', styles)
        self.assertIn('.mobile-filter-dialog__check[hidden] {', styles)
        self.assertIn(
            '.mobile-filter-dialog__item--color.is-selected {\n'
            '\t\tbackground-color: #f2f2f2;',
            styles,
        )
        self.assertIn('inset 0 0 0 1px #6f8a68,', styles)
        self.assertIn(
            'inset 0 0 12px rgba(111, 138, 104, .24);',
            styles,
        )
        self.assertIn(
            '.mobile-filter-dialog__item--color > '
            '.mobile-filter-dialog__check {',
            styles,
        )
        self.assertIn('position: absolute;', styles)
        self.assertIn('width: 24px;', styles)
        self.assertIn('height: 24px;', styles)
        self.assertNotContains(response, '?v=')
        self.assertContains(response, 'data-catalog-favorite-toggle')
        self.assertContains(response, 'skinali/images/icon-favorite-inactive.png')
        self.assertContains(response, 'skinali/images/icon-favorite-active.png')

    def test_homepage_shows_hero_and_redirects_legacy_search(self):
        finished_works = [
            FinishedWork.objects.create(
                name=f'Готовая работа {index}',
                description=f'Описание готовой работы {index}',
                photo=create_test_image_file(f'home-work-{index}.jpg'),
            )
            for index in range(1, 5)
        ]
        response = self.client.get(reverse('home'))
        styles = Path(
            settings.BASE_DIR,
            'pict/static/skinali/css/styles.css',
        ).read_text(encoding='utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="home-hero"')
        self.assertContains(response, 'Скинали из')
        self.assertContains(response, 'Заказать скинали')
        self.assertContains(response, 'Выбрать изображение')
        self.assertContains(response, 'skinali/images/odium-hero-glass-v2.jpg')
        self.assertContains(response, 'class="home-offers"')
        self.assertContains(
            response,
            '<h2 id="home-offers-title">Больше возможностей<br>для вашей кухни</h2>',
            html=True,
        )
        self.assertNotContains(response, 'для вашей кухни.</h2>')
        self.assertContains(response, 'class="home-offer-card"', count=3)
        self.assertContains(response, 'skinali/images/home-offer-designer.jpg')
        self.assertContains(response, 'skinali/images/home-offer-hood.jpg')
        self.assertContains(response, 'skinali/images/home-offer-lighting.jpg')
        self.assertContains(response, 'class="home-benefits"')
        self.assertContains(
            response,
            '<h2 id="home-benefits-title">Почему выбирают<br>стекло для кухни?</h2>',
            html=True,
        )
        self.assertNotContains(response, 'Почему стекло<br>выбирают для кухни')
        self.assertContains(response, 'class="home-benefit-card"', count=6)
        self.assertContains(response, 'skinali/images/home-benefit-strength.jpg')
        self.assertContains(response, 'skinali/images/home-benefit-variants.jpg')
        expected_home_card_texts = (
            'Вы можете предварительно до замера примерить несколько изображений на фотографию Вашей кухни.',
            'Но мы сделаем Вам этот подарок!',
            'При заказе скинали у нас - монтаж светодиодной подсветки БЕСПЛАТНО.',
            'УФ-печать не теряет с годами насыщенность красок.',
            'Надоевшее изображение можно перепечатать на новое в любое время.',
            'стыковочные швы практически не видны и не нарушают целость всего изображения',
            'разместив на скинали фотографии семьи или детей, любимые места отдыха и т.д.',
            'словно ремонт был только вчера.',
            'Каждый их трех вариантов исполнения подбирается под определенный дизайн кухни.',
        )
        for expected_text in expected_home_card_texts:
            with self.subTest(expected_text=expected_text):
                self.assertContains(response, expected_text)
        home_offer_card_styles = styles.split(
            '.home-offer-card {',
            maxsplit=1,
        )[1].split('}', maxsplit=1)[0]
        home_offer_grid_styles = styles.split(
            '.home-offers__cards {',
            maxsplit=1,
        )[1].split('}', maxsplit=1)[0]
        home_offer_image_styles = styles.split(
            '.home-offer-card__image {',
            maxsplit=1,
        )[1].split('}', maxsplit=1)[0]
        self.assertIn('min-height: 405px;', home_offer_card_styles)
        self.assertNotIn('\n\theight: 405px;', home_offer_card_styles)
        self.assertIn('grid-auto-rows: 1fr;', home_offer_grid_styles)
        self.assertIn('flex: 0 0 auto;', home_offer_image_styles)
        self.assertIn('height: 185px;', home_offer_image_styles)
        home_offer_text_styles = styles.split(
            '.home-offer-card > p {',
            maxsplit=1,
        )[1].split('}', maxsplit=1)[0]
        self.assertIn('margin: 0;', home_offer_text_styles)
        self.assertNotIn('margin: auto 0 0;', home_offer_text_styles)
        self.assertContains(response, 'class="home-recent-works"')
        self.assertContains(
            response,
            'Ниже представлены свежие работы, выполненные нашей командой за последнюю неделю.',
        )
        self.assertContains(response, 'class="home-recent-work-card ', count=4)
        self.assertContains(response, 'data-fancybox="finished-works"')
        self.assertContains(response, 'class="home-recent-work-card__link"', count=3)
        self.assertContains(response, finished_works[-1].name)
        self.assertNotContains(response, finished_works[-1].description)
        self.assertEqual(
            list(response.context['recent_finished_works']),
            list(reversed(finished_works[1:])),
        )
        self.assertNotContains(response, finished_works[0].photo.url)
        self.assertContains(response, 'Смотреть все фото')
        self.assertContains(
            response,
            f'class="home-hero__primary-action" href="{reverse("about")}"',
        )
        self.assertContains(
            response,
            f'class="home-hero__catalog-link" href="{reverse("skinali")}"',
        )

        picture = Pict.objects.order_by('pk').first()
        legacy_search_response = self.client.get(
            reverse('home'),
            {'product-number': picture.name},
        )

        self.assertRedirects(
            legacy_search_response,
            f'{reverse("skinali")}?q={picture.name}',
            fetch_redirect_response=False,
        )

    @override_settings(PUBLIC_SITE_ORIGIN='https://odium.by')
    def test_homepage_exposes_website_and_organization_structured_data(self):
        with self.assertNumQueries(0):
            identity = site_identity(RequestFactory().get('/'))['site_identity']

        self.assertEqual(identity['url'], 'https://odium.by/')
        self.assertEqual(
            identity['logo_url'],
            'https://odium.by/static/skinali/images/logo_skinali.png',
        )

        response = self.client.get(reverse('home'))
        structured_data = get_json_ld(response, 'site-structured-data')
        graph = {
            item['@type']: item
            for item in structured_data['@graph']
        }
        website = graph['WebSite']
        organization = graph['Organization']

        self.assertEqual(structured_data['@context'], 'https://schema.org')
        self.assertEqual(website['@id'], 'https://odium.by/#website')
        self.assertEqual(website['url'], 'https://odium.by/')
        self.assertEqual(website['name'], 'ОДИУМ')
        self.assertEqual(website['publisher']['@id'], organization['@id'])
        self.assertEqual(organization['@id'], 'https://odium.by/#organization')
        self.assertEqual(organization['name'], 'ОДИУМ')
        self.assertEqual(organization['telephone'], '+375291498838')
        self.assertEqual(organization['email'], 'odiumglass@gmail.com')
        self.assertEqual(
            organization['logo'],
            {
                '@type': 'ImageObject',
                'url': 'https://odium.by/static/skinali/images/logo_skinali.png',
                'width': 300,
                'height': 120,
            },
        )
        self.assertEqual(
            organization['sameAs'],
            [
                'https://instagram.com/odium.steklo',
                'https://vk.com/odium.steklo',
            ],
        )
        self.assertNotIn('address', organization)
        self.assertContains(
            response,
            'href="https://instagram.com/odium.steklo" '
            'target="_blank" rel="noopener noreferrer">Instagram</a>',
        )
        self.assertContains(
            response,
            'href="https://vk.com/odium.steklo" '
            'target="_blank" rel="noopener noreferrer">ВКонтакте</a>',
        )
        response_html = response.content.decode()
        self.assertLess(
            response_html.index('id="site-structured-data"'),
            response_html.index('</head>'),
        )

        category_response = self.client.get(self.first_category.get_absolute_url())
        self.assertNotContains(category_response, 'id="site-structured-data"')

    def test_category_links_keep_selected_color(self):
        selected_color = self.selected_color.slug_color
        response = self.client.get(
            reverse('skinali', kwargs={'slug_cat': self.first_category.slug}),
            {'color': selected_color},
        )

        self.assertContains(
            response,
            f'<a href="{reverse("skinali")}?color={selected_color}">Все</a>',
            html=True,
        )
        self.assertContains(
            response,
            (
                f'<a href="{self.second_category.get_absolute_url()}'
                f'?color={selected_color}">{self.second_category.cat}</a>'
            ),
            html=True,
        )
        self.assertContains(response, 'class="page-num color-option color-option--selected"')
        self.assertContains(response, 'class="color-filter__options"')
        self.assertContains(response, 'mobile-filter-dialog__item--color is-selected')
        self.assertContains(response, 'mobile-filter-dialog__check')
        self.assertContains(response, self.first_category.cat)
        self.assertContains(response, self.selected_color.color)
        self.assertContains(
            response,
            'class="color-option__selected-mark" aria-hidden="true"',
        )
        self.assertContains(response, 'class="list-all__reset"')
        self.assertContains(
            response,
            'class="list-all__reset-icon" aria-hidden="true">&times;</span>',
        )
        self.assertContains(response, 'Сбросить цвета')
        self.assertNotContains(response, 'data-mobile-color-reset')
        self.assertNotContains(
            response,
            'class="page-num page-num-selected" style="background-color: red;"',
        )

    def test_multiple_colors_use_strict_and_filter_and_preserve_query(self):
        response = self.client.get(
            self.first_category.get_absolute_url(),
            [
                ('color', self.selected_color.slug_color),
                ('color', self.second_color.slug_color),
            ],
        )

        self.assertEqual(
            {picture.name for picture in response.context['object_list']},
            {100, 101},
        )
        self.assertEqual(
            response.context['selected_color_slugs'],
            ('red', 'blue'),
        )
        self.assertContains(response, 'Выбранные цвета: Красный, Синий')
        self.assertContains(
            response,
            (
                f'<a href="{self.second_category.get_absolute_url()}'
                '?color=red&amp;color=blue">Вторая</a>'
            ),
            html=True,
        )

    def test_desktop_color_links_and_mobile_deferred_selection(self):
        response = self.client.get(
            self.first_category.get_absolute_url(),
            [
                ('color', self.selected_color.slug_color),
                ('color', self.second_color.slug_color),
            ],
        )

        remove_url = f'{self.first_category.get_absolute_url()}?color=blue'
        add_url = (
            f'{self.first_category.get_absolute_url()}'
            '?color=red&amp;color=blue&amp;color=green'
        )
        self.assertContains(response, f'href="{remove_url}"', count=1)
        self.assertContains(
            response,
            'aria-label="Убрать цвет: Красный"',
            count=1,
        )
        self.assertContains(
            response,
            'class="mobile-filter-dialog__item '
            'mobile-filter-dialog__item--color is-selected"',
        )
        self.assertContains(
            response,
            '<input class="mobile-color-filter__checkbox" type="checkbox" '
            'name="color" value="red" data-mobile-color-checkbox checked>',
            html=True,
        )
        self.assertContains(
            response,
            '<input class="mobile-color-filter__checkbox" type="checkbox" '
            'name="color" value="blue" data-mobile-color-checkbox checked>',
            html=True,
        )
        self.assertContains(
            response,
            '<span class="mobile-filter-dialog__check" '
            'data-mobile-color-all-check aria-hidden="true" hidden>✓</span>',
            html=True,
        )
        self.assertContains(
            response,
            '<span class="mobile-filter-dialog__check" '
            'data-mobile-color-check aria-hidden="true">✓</span>',
            count=2,
            html=True,
        )
        self.assertContains(response, f'href="{add_url}"', count=1)
        self.assertContains(
            response,
            'aria-label="Добавить цвет: Зелёный"',
            count=1,
        )

    def test_color_selection_is_limited_to_three(self):
        response = self.client.get(
            self.first_category.get_absolute_url(),
            [
                ('color', self.selected_color.slug_color),
                ('color', self.second_color.slug_color),
                ('color', self.third_color.slug_color),
                ('color', self.fourth_color.slug_color),
            ],
        )

        self.assertEqual(
            response.context['selected_color_slugs'],
            ('red', 'blue', 'green'),
        )
        self.assertEqual(
            [picture.name for picture in response.context['object_list']],
            [100],
        )
        self.assertContains(response, 'color-option color-option--disabled')
        self.assertContains(response, 'mobile-filter-dialog__item--color is-disabled')
        self.assertNotContains(response, 'color=yellow')

    def test_category_links_have_no_color_parameter_when_color_is_not_selected(self):
        response = self.client.get(
            reverse('skinali', kwargs={'slug_cat': self.first_category.slug})
        )

        self.assertContains(
            response,
            f'<a href="{self.second_category.get_absolute_url()}">{self.second_category.cat}</a>',
            html=True,
        )

    def test_nested_category_uses_root_relative_static_urls(self):
        response = self.client.get(self.first_category.get_absolute_url())

        self.assertEqual(settings.STATIC_URL, '/static/')
        self.assertContains(
            response,
            'href="/static/skinali/css/styles.css',
        )
        self.assertContains(
            response,
            'src="/static/skinali/js/site-menu.js',
        )
        self.assertNotContains(
            response,
            'href="static/skinali/',
        )
        self.assertNotContains(
            response,
            'src="static/skinali/',
        )


@override_settings(PUBLIC_SITE_ORIGIN='https://odium.by')
class TagPageAndSitemapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(cat='Цветы', slug='tag-page-flowers')
        cls.empty_category = Category.objects.create(
            cat='Пустая категория',
            slug='sitemap-empty-category',
        )
        cls.hidden_category = Category.objects.create(
            cat='Скрытая категория',
            slug='sitemap-hidden-category',
        )
        cls.tag = TagPict.objects.create(tag='Розы', slug='tag-page-roses')
        cls.empty_tag = TagPict.objects.create(
            tag='Пустая тема',
            slug='tag-page-empty',
        )
        cls.hidden_tag = TagPict.objects.create(
            tag='Скрытая тема',
            slug='tag-page-hidden',
        )
        cls.picture = Pict.objects.create(
            name=650,
            alt='Красные розы',
            photo=create_test_image_file('tag-page-roses.jpg'),
        )
        cls.picture.cat.add(cls.category)
        cls.picture.tags.add(cls.tag)
        cls.hidden_picture = Pict.objects.create(
            name=651,
            alt='Скрытые цветы',
            photo=create_test_image_file('tag-page-hidden.jpg'),
            is_published=False,
        )
        cls.hidden_picture.cat.add(cls.hidden_category)
        cls.hidden_picture.tags.add(cls.hidden_tag)

    def test_tag_page_uses_catalog_cards_and_seo_metadata(self):
        response = self.client.get(self.tag.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['object_list']), [self.picture])
        self.assertEqual(response.context['tag'], self.tag)
        self.assertEqual(response.context['result_count'], 1)
        self.assertEqual(response.context['result_summary'], 'Найдено 1 изображение')
        self.assertContains(response, 'Изображения с тегом «Розы»')
        self.assertContains(
            response,
            '<title>Изображения для скинали: Розы | ОДИУМ</title>',
            html=True,
        )
        self.assertContains(response, '<meta name="description"')
        self.assertContains(
            response,
            f'<link rel="canonical" href="https://odium.by{self.tag.get_absolute_url()}">',
            html=True,
        )
        self.assertNotContains(response, '<meta name="robots"')
        self.assertNotContains(response, 'class="site-search"')
        self.assertContains(response, 'class="container catalog-gallery"')
        self.assertContains(response, 'Hash: false', count=1)
        self.assertContains(
            response,
            '<span class="catalog-thumbnail__image-number">'
            '<span class="catalog-thumbnail__image-number-text">№ 650</span>'
            '</span>',
            html=True,
        )
        self.assertContains(response, 'data-caption-template="catalog-gallery-caption-')
        self.assertContains(response, 'data-catalog-favorite-toggle')
        self.assertContains(response, 'class="catalog-modal__purchase"')
        self.assertContains(response, '<span>#Розы</span>', html=True)
        self.assertNotContains(
            response,
            f'<a href="{self.tag.get_absolute_url()}">#Розы</a>',
            html=True,
        )

    def test_tag_page_uses_managed_seo_content(self):
        self.tag.seo_h1 = 'Панорамные розы для кухни'
        self.tag.seo_title = 'Розы для стеклянного фартука'
        self.tag.seo_description = 'Подборка изображений роз для кухонного фартука.'
        self.tag.intro_text = 'Красные и светлые розы.\nВыберите подходящий сюжет.'
        self.tag.save(update_fields=[
            'seo_h1',
            'seo_title',
            'seo_description',
            'intro_text',
        ])

        response = self.client.get(self.tag.get_absolute_url())

        self.assertContains(response, '<h1>Панорамные розы для кухни</h1>', html=True)
        self.assertContains(
            response,
            '<title>Розы для стеклянного фартука | ОДИУМ</title>',
            html=True,
        )
        self.assertContains(
            response,
            '<meta name="description" '
            'content="Подборка изображений роз для кухонного фартука.">',
            html=True,
        )
        self.assertContains(response, 'Красные и светлые розы.<br>')
        self.assertContains(response, 'Выберите подходящий сюжет.')

    def test_category_page_uses_managed_seo_content(self):
        self.category.seo_h1 = 'Каталог изображений цветов'
        self.category.seo_title = 'Цветы для скинали'
        self.category.seo_description = 'Изображения цветов для печати на стекле.'
        self.category.intro_text = 'Коллекция цветочных панорам для кухни.'
        self.category.save(update_fields=[
            'seo_h1',
            'seo_title',
            'seo_description',
            'intro_text',
        ])

        response = self.client.get(self.category.get_absolute_url())

        self.assertContains(response, '<h1>Каталог изображений цветов</h1>', html=True)
        self.assertContains(response, '<title>Цветы для скинали | ОДИУМ</title>', html=True)
        self.assertContains(
            response,
            '<meta name="description" '
            'content="Изображения цветов для печати на стекле.">',
            html=True,
        )
        self.assertContains(response, 'Коллекция цветочных панорам для кухни.')
        self.assertNotContains(response, '<p>Цветы</p>', html=True)

    def test_empty_tag_page_is_available_and_missing_tag_returns_404(self):
        response = self.client.get(self.empty_tag.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['result_count'], 0)
        self.assertContains(response, 'Пока нет изображений')
        self.assertContains(
            response,
            '<meta name="robots" content="noindex,follow">',
            html=True,
        )
        self.assertNotContains(response, 'class="container catalog-gallery"')
        self.assertEqual(
            self.client.get('/tag/missing-tag/').status_code,
            404,
        )

    @override_settings(ALLOWED_HOSTS=['technical-preview.example'])
    def test_sitemap_contains_static_pages_and_only_nonempty_taxonomies(self):
        response = self.client.get(
            reverse('sitemap'),
            HTTP_HOST='technical-preview.example',
        )
        xml = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('application/xml'))
        for view_name in ('home', 'skinali', 'finished_works', 'designer', 'about'):
            self.assertIn(
                f'<loc>https://odium.by{reverse(view_name)}</loc>',
                xml,
            )
        self.assertNotIn('technical-preview.example', xml)
        self.assertNotIn('http://testserver', xml)
        self.assertIn(self.category.get_absolute_url(), xml)
        self.assertNotIn(self.empty_category.get_absolute_url(), xml)
        self.assertNotIn(self.hidden_category.get_absolute_url(), xml)
        self.assertIn(self.tag.get_absolute_url(), xml)
        self.assertNotIn(self.empty_tag.get_absolute_url(), xml)
        self.assertNotIn(self.hidden_tag.get_absolute_url(), xml)
        self.assertIn(self.picture.get_absolute_url(), xml)
        self.assertNotIn(self.hidden_picture.get_absolute_url(), xml)

    def test_sitemap_lastmod_uses_freshest_relevant_timestamp(self):
        taxonomy_changed_at = timezone.now() - timedelta(days=10)
        picture_changed_at = timezone.now() - timedelta(days=2)
        home_changed_at = timezone.now() - timedelta(days=4)
        Category.objects.filter(pk=self.category.pk).update(
            updated_at=taxonomy_changed_at,
        )
        TagPict.objects.filter(pk=self.tag.pk).update(
            updated_at=taxonomy_changed_at,
        )
        Pict.objects.filter(pk=self.picture.pk).update(
            updated_at=picture_changed_at,
        )
        SitePage.objects.filter(pk=SitePage.Code.HOME).update(
            updated_at=home_changed_at,
        )

        response = self.client.get(reverse('sitemap'))
        lastmods = get_sitemap_lastmods(response)

        self.assertEqual(
            lastmods[f'https://odium.by{self.category.get_absolute_url()}'],
            timezone.localdate(picture_changed_at).isoformat(),
        )
        self.assertEqual(
            lastmods[f'https://odium.by{self.tag.get_absolute_url()}'],
            timezone.localdate(picture_changed_at).isoformat(),
        )
        self.assertEqual(
            lastmods[f'https://odium.by{self.picture.get_absolute_url()}'],
            timezone.localdate(picture_changed_at).isoformat(),
        )
        self.assertEqual(
            lastmods[f'https://odium.by{reverse("home")}'],
            timezone.localdate(home_changed_at).isoformat(),
        )

        category_changed_at = timezone.now() - timedelta(days=1)
        Category.objects.filter(pk=self.category.pk).update(
            updated_at=category_changed_at,
        )

        updated_lastmods = get_sitemap_lastmods(
            self.client.get(reverse('sitemap')),
        )

        self.assertEqual(
            updated_lastmods[
                f'https://odium.by{self.category.get_absolute_url()}'
            ],
            timezone.localdate(category_changed_at).isoformat(),
        )
        self.assertEqual(
            updated_lastmods[f'https://odium.by{self.tag.get_absolute_url()}'],
            timezone.localdate(picture_changed_at).isoformat(),
        )

    def test_picture_save_and_tag_removal_touch_public_clocks(self):
        old_timestamp = timezone.now() - timedelta(days=30)
        Pict.objects.filter(pk=self.picture.pk).update(updated_at=old_timestamp)
        Category.objects.update(updated_at=old_timestamp)
        TagPict.objects.filter(pk=self.tag.pk).update(updated_at=old_timestamp)
        SitePage.objects.filter(
            pk__in=(SitePage.Code.CATALOG, SitePage.Code.FINISHED_WORKS),
        ).update(updated_at=old_timestamp)

        self.picture.refresh_from_db()
        self.picture.alt = 'Обновлённое описание роз'
        self.picture.save(update_fields=['alt'])
        self.category.refresh_from_db()
        self.tag.refresh_from_db()
        catalog_page = SitePage.objects.get(pk=SitePage.Code.CATALOG)
        finished_works_page = SitePage.objects.get(pk=SitePage.Code.FINISHED_WORKS)

        self.assertGreater(self.picture.updated_at, old_timestamp)
        self.assertGreater(self.category.updated_at, old_timestamp)
        self.assertGreater(self.tag.updated_at, old_timestamp)
        self.assertGreater(catalog_page.updated_at, old_timestamp)
        self.assertGreater(finished_works_page.updated_at, old_timestamp)

        Pict.objects.filter(pk=self.picture.pk).update(updated_at=old_timestamp)
        TagPict.objects.filter(pk=self.tag.pk).update(updated_at=old_timestamp)
        SitePage.objects.filter(pk=SitePage.Code.CATALOG).update(
            updated_at=old_timestamp,
        )

        self.picture.tags.remove(self.tag)
        self.picture.refresh_from_db()
        self.tag.refresh_from_db()
        catalog_page.refresh_from_db()

        self.assertGreater(self.picture.updated_at, old_timestamp)
        self.assertGreater(self.tag.updated_at, old_timestamp)
        self.assertGreater(catalog_page.updated_at, old_timestamp)

    def test_picture_deletion_touches_previous_taxonomies_and_static_pages(self):
        old_timestamp = timezone.now() - timedelta(days=30)
        Category.objects.update(updated_at=old_timestamp)
        TagPict.objects.filter(pk=self.tag.pk).update(updated_at=old_timestamp)
        SitePage.objects.filter(
            pk__in=(SitePage.Code.CATALOG, SitePage.Code.FINISHED_WORKS),
        ).update(updated_at=old_timestamp)

        self.picture.delete()
        self.category.refresh_from_db()
        self.tag.refresh_from_db()
        catalog_page = SitePage.objects.get(pk=SitePage.Code.CATALOG)
        finished_works_page = SitePage.objects.get(pk=SitePage.Code.FINISHED_WORKS)

        self.assertGreater(self.category.updated_at, old_timestamp)
        self.assertGreater(self.tag.updated_at, old_timestamp)
        self.assertGreater(catalog_page.updated_at, old_timestamp)
        self.assertGreater(finished_works_page.updated_at, old_timestamp)

    def test_finished_work_save_and_delete_touch_home_and_gallery_clocks(self):
        work = FinishedWork.objects.create(
            name='Работа для проверки lastmod',
            photo='finished_works/sitemap-clock.jpg',
        )
        old_timestamp = timezone.now() - timedelta(days=30)
        FinishedWork.objects.filter(pk=work.pk).update(updated_at=old_timestamp)
        SitePage.objects.filter(
            pk__in=(SitePage.Code.HOME, SitePage.Code.FINISHED_WORKS),
        ).update(updated_at=old_timestamp)

        work.refresh_from_db()
        work.name = 'Изменённая работа для проверки lastmod'
        work.save(update_fields=['name'])
        home_page = SitePage.objects.get(pk=SitePage.Code.HOME)
        finished_works_page = SitePage.objects.get(pk=SitePage.Code.FINISHED_WORKS)

        self.assertGreater(work.updated_at, old_timestamp)
        self.assertGreater(home_page.updated_at, old_timestamp)
        self.assertGreater(finished_works_page.updated_at, old_timestamp)

        SitePage.objects.filter(
            pk__in=(SitePage.Code.HOME, SitePage.Code.FINISHED_WORKS),
        ).update(updated_at=old_timestamp)
        work.delete()
        home_page.refresh_from_db()
        finished_works_page.refresh_from_db()

        self.assertGreater(home_page.updated_at, old_timestamp)
        self.assertGreater(finished_works_page.updated_at, old_timestamp)

    def test_catalog_navigation_contains_only_categories_with_published_pictures(self):
        with self.assertNumQueries(1):
            categories = list(SkinaliAll.get_catalog_categories())

        self.assertEqual(categories, [self.category])

        response = self.client.get(reverse('skinali'))

        self.assertEqual(list(response.context['list_cat']), [self.category])
        self.assertContains(response, self.category.get_absolute_url())
        self.assertNotContains(response, self.empty_category.get_absolute_url())
        self.assertNotContains(response, self.hidden_category.get_absolute_url())

    def test_public_pages_render_visible_breadcrumbs_and_json_ld(self):
        cases = (
            (
                reverse('skinali'),
                ('Главная', 'Каталог'),
                (reverse('home'), reverse('skinali')),
            ),
            (
                self.category.get_absolute_url(),
                ('Главная', 'Каталог', self.category.cat),
                (reverse('home'), reverse('skinali'), self.category.get_absolute_url()),
            ),
            (
                self.tag.get_absolute_url(),
                ('Главная', 'Каталог', self.tag.tag),
                (reverse('home'), reverse('skinali'), self.tag.get_absolute_url()),
            ),
            (
                reverse('finished_works'),
                ('Главная', 'Наши работы'),
                (reverse('home'), reverse('finished_works')),
            ),
            (
                reverse('designer'),
                ('Главная', 'Услуги дизайнера'),
                (reverse('home'), reverse('designer')),
            ),
            (
                reverse('about'),
                ('Главная', 'Связаться с нами'),
                (reverse('home'), reverse('about')),
            ),
        )

        for path, expected_names, expected_paths in cases:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(
                    tuple(item['url'] for item in response.context['breadcrumbs']),
                    expected_paths,
                )
                self.assertContains(
                    response,
                    '<nav class="breadcrumbs" aria-label="Хлебные крошки">',
                )
                structured_data = get_breadcrumb_structured_data(response)
                self.assertEqual(structured_data['@context'], 'https://schema.org')
                self.assertEqual(structured_data['@type'], 'BreadcrumbList')
                items = structured_data['itemListElement']
                self.assertEqual(
                    [item['position'] for item in items],
                    list(range(1, len(expected_names) + 1)),
                )
                self.assertEqual([item['name'] for item in items], list(expected_names))
                self.assertEqual(
                    [item['item'] for item in items],
                    [f'https://odium.by{item_path}' for item_path in expected_paths],
                )

        home_response = self.client.get(reverse('home'))
        self.assertNotContains(home_response, 'class="breadcrumbs"')
        self.assertNotContains(home_response, 'id="breadcrumb-structured-data"')

    def test_noindex_pages_keep_visible_breadcrumbs_without_json_ld(self):
        for path in (
            self.empty_tag.get_absolute_url(),
            f'{reverse("skinali")}?q=розы',
            reverse('favorites'),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertContains(response, 'class="breadcrumbs"')
                self.assertContains(
                    response,
                    '<meta name="robots" content="noindex,follow">',
                    html=True,
                )
                self.assertNotContains(response, 'id="breadcrumb-structured-data"')

    def test_breadcrumb_metadata_is_query_free_and_escapes_dynamic_names(self):
        request = RequestFactory().get(
            '/skinali/?page=2',
            HTTP_HOST='preview.example',
        )
        with self.assertNumQueries(0):
            context = set_page_metadata(
                {},
                request,
                page_title='Каталог — страница 2',
                meta_description='Каталог',
                canonical_path='/skinali/',
                page_number=2,
                breadcrumbs=(('Главная', '/'), ('Каталог', None)),
            )
        self.assertEqual(
            context['canonical_url'],
            'https://odium.by/skinali/?page=2',
        )
        self.assertEqual(
            context['breadcrumbs'][1]['absolute_url'],
            'https://odium.by/skinali/?page=2',
        )

        unsafe_name = 'Розы </script><script>alert(1)</script>'
        self.tag.tag = unsafe_name
        self.tag.save()

        response = self.client.get(self.tag.get_absolute_url())
        structured_data = get_breadcrumb_structured_data(response)

        self.assertEqual(structured_data['itemListElement'][-1]['name'], unsafe_name)
        self.assertNotIn(unsafe_name, response.content.decode())

    def test_public_sitemap_pages_have_metadata_and_filters_are_noindex(self):
        for view_name in ('home', 'skinali', 'finished_works', 'designer', 'about'):
            with self.subTest(view_name=view_name):
                path = reverse(view_name)
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['page_title'])
                self.assertTrue(response.context['meta_description'])
                self.assertEqual(
                    response.context['canonical_url'],
                    f'https://odium.by{path}',
                )
                self.assertFalse(response.context['meta_robots'])

        catalog_response = self.client.get(reverse('skinali'))
        self.assertContains(
            catalog_response,
            '<h1>Каталог изображений для скинали</h1>',
            html=True,
        )

        category_response = self.client.get(self.category.get_absolute_url())
        self.assertContains(
            category_response,
            '<title>Изображения для скинали: Цветы | ОДИУМ</title>',
            html=True,
        )
        self.assertContains(
            category_response,
            '<h1>Изображения для скинали: Цветы</h1>',
            html=True,
        )
        self.assertEqual(
            category_response.context['canonical_url'],
            f'https://odium.by{self.category.get_absolute_url()}',
        )
        self.assertFalse(category_response.context['meta_robots'])

        search_response = self.client.get(reverse('skinali'), {'q': 'розы'})
        self.assertEqual(search_response.context['meta_robots'], 'noindex,follow')
        self.assertEqual(
            search_response.context['canonical_url'],
            f'https://odium.by{reverse("skinali")}',
        )

        color_response = self.client.get(
            self.category.get_absolute_url(),
            {'color': 'missing'},
        )
        self.assertEqual(color_response.context['meta_robots'], 'noindex,follow')
        self.assertEqual(
            color_response.context['canonical_url'],
            f'https://odium.by{self.category.get_absolute_url()}',
        )


class RobotsTxtTests(SimpleTestCase):
    @override_settings(
        ADMIN_URL='private-admin/',
        PUBLIC_SITE_ORIGIN='https://odium.by',
    )
    def test_robots_txt_exposes_crawl_rules_and_sitemap(self):
        response = self.client.get(reverse('robots_txt'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain; charset=utf-8')
        self.assertEqual(response['Cache-Control'], 'public, max-age=3600')
        self.assertEqual(
            response.content.decode(),
            'User-agent: *\n'
            'Disallow: /private-admin/\n'
            f'Disallow: {reverse("contact_submit")}\n'
            'Disallow: /quiz/\n'
            'Clean-param: '
            'utm_source&utm_medium&utm_campaign&utm_content&utm_term&yclid&gclid\n'
            '\n'
            f'Sitemap: https://odium.by{reverse("sitemap")}\n',
        )

    def test_robots_txt_allows_only_safe_methods(self):
        self.assertEqual(self.client.head(reverse('robots_txt')).status_code, 200)

        response = self.client.post(reverse('robots_txt'))

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response['Allow'], 'GET, HEAD')

    @override_settings(SITE_NOINDEX=True)
    def test_preview_blocks_crawling_and_marks_every_response_noindex(self):
        robots_response = self.client.get(reverse('robots_txt'))
        method_not_allowed_response = self.client.get(reverse('contact_submit'))

        self.assertEqual(
            robots_response.content.decode(),
            'User-agent: *\nDisallow: /\n',
        )
        self.assertEqual(robots_response['Cache-Control'], 'no-store')
        self.assertEqual(
            robots_response['X-Robots-Tag'],
            'noindex, nofollow',
        )
        self.assertEqual(
            method_not_allowed_response['X-Robots-Tag'],
            'noindex, nofollow',
        )


class TaxonomySeoAdminTests(SimpleTestCase):
    def test_category_and_tag_admin_expose_shared_seo_fields(self):
        expected_fields = {
            'seo_h1',
            'seo_title',
            'seo_description',
            'intro_text',
        }

        for model_admin in (
            CategoryAdmin(Category, AdminSite()),
            TagPictAdmin(TagPict, AdminSite()),
        ):
            with self.subTest(model_admin=model_admin.__class__.__name__):
                fieldsets = model_admin.get_fieldsets(request=None)
                seo_fields = set(fieldsets[1][1]['fields'])
                self.assertEqual(seo_fields, expected_fields)


class RemovedTestRouteTests(SimpleTestCase):
    def test_legacy_numeric_category_route_is_not_available(self):
        with self.assertRaises(NoReverseMatch):
            reverse('cat', kwargs={'catid': 1})

        self.assertEqual(self.client.get('/cats/1/').status_code, 404)


@override_settings(DEBUG=False)
class NotFoundPageTests(TestCase):
    def test_unknown_url_returns_branded_noindex_page(self):
        with self.assertNumQueries(0):
            response = self.client.get('/missing-public-page/')

        self.assertEqual(response.status_code, 404)
        self.assertContains(
            response,
            '<title>Страница не найдена | ОДИУМ</title>',
            status_code=404,
            html=True,
        )
        self.assertContains(
            response,
            '<meta name="robots" content="noindex,follow">',
            status_code=404,
            html=True,
        )
        self.assertContains(
            response,
            '<h1 id="not-found-title">Страница не найдена</h1>',
            status_code=404,
            html=True,
        )
        self.assertContains(
            response,
            f'<a href="{reverse("home")}">Вернуться на главную</a>',
            status_code=404,
            html=True,
        )
        self.assertContains(
            response,
            f'<a href="{reverse("skinali")}">Перейти в каталог</a>',
            status_code=404,
            html=True,
        )
        self.assertNotContains(
            response,
            'rel="canonical"',
            status_code=404,
        )
        self.assertNotContains(
            response,
            'type="application/ld+json"',
            status_code=404,
        )
        self.assertNotContains(
            response,
            'class="site-footer"',
            status_code=404,
        )


@override_settings(DEBUG=False)
class ServerErrorPageTests(SimpleTestCase):
    def test_handler500_returns_autonomous_noindex_page(self):
        from skinali.urls import handler500

        self.assertIs(handler500, serverError)

        response = handler500(RequestFactory().get('/broken-public-page/'))

        self.assertEqual(response.status_code, 500)
        self.assertContains(
            response,
            '<title>Ошибка сервера | ОДИУМ</title>',
            status_code=500,
            html=True,
        )
        self.assertContains(
            response,
            '<meta name="robots" content="noindex,nofollow">',
            status_code=500,
            html=True,
        )
        self.assertContains(
            response,
            '<h1 id="server-error-title">Что-то пошло не так</h1>',
            status_code=500,
            html=True,
        )
        self.assertContains(
            response,
            'Попробуйте обновить страницу через несколько минут.',
            status_code=500,
        )
        self.assertContains(
            response,
            f'<a href="{reverse("home")}">Перейти на главную</a>',
            status_code=500,
            html=True,
        )
        self.assertNotContains(response, 'rel="canonical"', status_code=500)
        self.assertNotContains(
            response,
            'type="application/ld+json"',
            status_code=500,
        )
        self.assertNotContains(response, 'Traceback', status_code=500)
        self.assertNotContains(response, 'Exception', status_code=500)


class SitePageSeoTests(TestCase):
    def test_custom_seo_is_used_by_all_internal_menu_pages(self):
        page_routes = (
            (SitePage.Code.HOME, 'home'),
            (SitePage.Code.CATALOG, 'skinali'),
            (SitePage.Code.FINISHED_WORKS, 'finished_works'),
            (SitePage.Code.DESIGNER, 'designer'),
            (SitePage.Code.ABOUT, 'about'),
        )

        for index, (page_code, route_name) in enumerate(page_routes, start=1):
            with self.subTest(page_code=page_code):
                page = SitePage.objects.get(pk=page_code)
                page.seo_title = f'Управляемый заголовок {index}'
                page.seo_description = f'Управляемое описание {index}'
                page.save(update_fields=['seo_title', 'seo_description'])

                response = self.client.get(reverse(route_name))

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context['page_title'],
                    f'Управляемый заголовок {index} | ОДИУМ',
                )
                self.assertEqual(
                    response.context['meta_description'],
                    f'Управляемое описание {index}',
                )
                self.assertContains(
                    response,
                    f'<title>Управляемый заголовок {index} | ОДИУМ</title>',
                    html=True,
                )
                self.assertContains(
                    response,
                    f'<meta name="description" content="Управляемое описание {index}">',
                    html=True,
                )

    def test_empty_site_page_seo_preserves_existing_defaults(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(
            response.context['page_title'],
            'Скинали из стекла для кухни | ОДИУМ',
        )
        self.assertEqual(
            response.context['meta_description'],
            'Скинали из стекла для кухни: каталог изображений, '
            'услуги дизайнера и примеры готовых работ ОДИУМ.',
        )

    def test_custom_paginated_title_gets_page_number_and_brand(self):
        SitePage.objects.filter(pk=SitePage.Code.FINISHED_WORKS).update(
            seo_title='Фото выполненных работ',
        )
        for index in range(7):
            FinishedWork.objects.create(
                name=f'Работа {index}',
                photo=create_test_image_file(f'seo-work-{index}.jpg'),
            )

        response = self.client.get(reverse('finished_works'), {'page': 2})

        self.assertEqual(
            response.context['page_title'],
            'Фото выполненных работ — страница 2 | ОДИУМ',
        )


class PaginatorTemplateTests(SimpleTestCase):
    @staticmethod
    def render_paginator(page_number, num_pages):
        page_obj = Paginator(range(num_pages), 1).page(page_number)
        return render_to_string(
            'pict/includes/paginator.html',
            {'page_obj': page_obj, 'col_tag': ''},
        )

    def test_five_page_jump_controls_use_exact_targets(self):
        html = self.render_paginator(page_number=6, num_pages=11)

        self.assertInHTML(
            '<a href="?page=1" aria-label="Назад на 5 страниц" '
            'title="Назад на 5 страниц">&laquo;</a>',
            html,
        )
        self.assertInHTML(
            '<a href="?page=11" aria-label="Вперёд на 5 страниц" '
            'title="Вперёд на 5 страниц">&raquo;</a>',
            html,
        )

    def test_five_page_jump_controls_require_a_full_jump(self):
        cases = (
            (5, 10, 'Назад на 5 страниц', 'Вперёд на 5 страниц'),
            (6, 10, 'Вперёд на 5 страниц', 'Назад на 5 страниц'),
        )

        for page_number, num_pages, hidden_label, visible_label in cases:
            with self.subTest(page_number=page_number, num_pages=num_pages):
                html = self.render_paginator(page_number, num_pages)
                self.assertNotIn(f'aria-label="{hidden_label}"', html)
                self.assertIn(f'aria-label="{visible_label}"', html)


class CatalogSearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first_category = Category.objects.create(cat='Первая', slug='search-first')
        cls.second_category = Category.objects.create(cat='Вторая', slug='search-second')
        cls.color = Color.objects.create(color='Синий', slug_color='search-blue')
        cls.sea_tag = TagPict.objects.create(tag='Море', slug='search-sea')
        cls.sunset_tag = TagPict.objects.create(tag='Закат', slug='search-sunset')
        cls.forest_tag = TagPict.objects.create(tag='Лес', slug='search-forest')
        cls.oceanarium_tag = TagPict.objects.create(
            tag='Океанариум',
            slug='search-oceanarium',
        )
        cls.ocean_alias = TagAlias.objects.create(tag=cls.sea_tag, alias='Океан')

        cls.both_picture = cls.create_picture(
            901,
            cls.second_category,
            [cls.sea_tag, cls.sunset_tag],
        )
        cls.sea_picture = cls.create_picture(
            902,
            cls.first_category,
            [cls.sea_tag],
        )
        cls.partial_picture = cls.create_picture(
            903,
            cls.first_category,
            [cls.oceanarium_tag],
        )
        cls.alt_only_picture = cls.create_picture(
            904,
            cls.first_category,
            [cls.forest_tag],
            alt='Океан и закат находятся только в описании',
        )
        cls.hidden_picture = cls.create_picture(
            905,
            cls.second_category,
            [cls.sea_tag, cls.sunset_tag],
            is_published=False,
        )

    @classmethod
    def create_picture(cls, name, category, tags, *, alt=None, is_published=True):
        picture = Pict.objects.create(
            name=name,
            alt=alt or f'Описание изображения {name}',
            photo=create_test_image_file(f'search-{name}.jpg', size=(100, 20)),
            is_published=is_published,
        )
        picture.cat.add(category)
        picture.color.add(cls.color)
        picture.tags.add(*tags)
        return picture

    def test_normalization_and_all_supported_separators(self):
        parsed = parse_search_query(
            '  #МОРЕ,\tзакат:лес;ночь-туман–река—поле\n'
        )

        self.assertEqual(
            parsed.terms,
            ('море', 'закат', 'лес', 'ночь', 'туман', 'река', 'поле'),
        )
        self.assertEqual(normalize_search_value('  Ёлка  '), 'елка')
        self.assertEqual(parse_search_query('#123').image_number, 123)

    def test_result_count_uses_correct_russian_word_form(self):
        self.assertEqual(format_image_count(1), 'Найдено 1 изображение')
        self.assertEqual(format_image_count(2), 'Найдено 2 изображения')
        self.assertEqual(format_image_count(5), 'Найдено 5 изображений')
        self.assertEqual(format_image_count(11), 'Найдено 11 изображений')
        self.assertEqual(format_image_count(21), 'Найдено 21 изображение')

    def test_search_form_validates_terms_and_deduplicates_them(self):
        valid_form = CatalogSearchForm({'q': '#Море, море; ЗАКАТ'})
        self.assertTrue(valid_form.is_valid())
        self.assertEqual(valid_form.parsed_query.terms, ('море', 'закат'))
        self.assertEqual(valid_form.cleaned_data['q'], 'море закат')

        number_form = CatalogSearchForm({'q': '1'})
        self.assertTrue(number_form.is_valid())
        self.assertEqual(number_form.parsed_query.image_number, 1)

        invalid_queries = (
            'я',
            'мо',
            '..',
            '#, : ; -',
            'один два три четыре пять шесть',
            '999999999999999999999999999999',
            'а' * 101,
        )
        for query in invalid_queries:
            with self.subTest(query=query):
                form = CatalogSearchForm({'q': query})
                self.assertFalse(form.is_valid())
                self.assertIn('q', form.errors)

    def test_models_normalize_values_and_validate_aliases(self):
        tag = TagPict.objects.create(tag='Ёлка', slug='search-fir-tree')
        self.assertEqual(tag.normalized_tag, 'елка')

        tag.tag = '  ЁЛКА  '
        tag.save(update_fields={'tag'})
        tag.refresh_from_db()
        self.assertEqual(tag.normalized_tag, 'елка')

        with self.assertRaises(ValidationError):
            TagPict(tag='#ЕЛКА', slug='search-duplicate-fir').save()

        alias = TagAlias(tag=tag, alias='#Хвойный')
        alias.full_clean()
        alias.save()
        self.assertEqual(alias.normalized_alias, 'хвойный')

        for invalid_alias in ('Море', '#ОКЕАН', 'морской пейзаж', '..'):
            with self.subTest(alias=invalid_alias):
                candidate = TagAlias(tag=tag, alias=invalid_alias)
                with self.assertRaises(ValidationError):
                    candidate.save()

    def test_multiple_words_use_global_and_search_with_aliases(self):
        response = self.client.get(
            reverse('skinali', kwargs={'slug_cat': self.first_category.slug}),
            {'q': '#ОКЕАН, ЗАКАТ', 'color': self.color.slug_color},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['object_list']), [self.both_picture])
        self.assertIsNone(response.context['selected_category'])
        self.assertEqual(response.context['col'], '')
        self.assertEqual(response.context['search_result_count'], 1)
        self.assertContains(response, '<h1 id="search-results-title">Результаты поиска</h1>')
        self.assertContains(response, 'Найдено 1 изображение')
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'value="#ОКЕАН, ЗАКАТ"')
        self.assertContains(response, 'Hash: false', count=1)
        self.assertContains(
            response,
            '<span class="catalog-thumbnail__image-number">'
            f'<span class="catalog-thumbnail__image-number-text">№ {self.both_picture.name}</span>'
            '</span>',
            html=True,
        )
        self.assertNotContains(response, 'data-mobile-filter-open')
        self.assertNotContains(response, 'Популярные запросы:')

        missing_category_response = self.client.get(
            reverse('skinali', kwargs={'slug_cat': 'missing-category'}),
            {'q': 'море'},
        )
        self.assertEqual(missing_category_response.status_code, 404)

    def test_exact_alias_precedes_partial_tag_match(self):
        response = self.client.get(reverse('skinali'), {'q': 'океан'})

        self.assertEqual(
            list(response.context['object_list']),
            [self.sea_picture, self.both_picture, self.partial_picture],
        )

    def test_number_search_is_exact_and_unpublished_picture_is_hidden(self):
        response = self.client.get(reverse('skinali'), {'q': '901'})
        hidden_response = self.client.get(reverse('skinali'), {'q': '905'})

        self.assertEqual(list(response.context['object_list']), [self.both_picture])
        self.assertEqual(list(hidden_response.context['object_list']), [])

    def test_description_is_not_part_of_search(self):
        response = self.client.get(reverse('skinali'), {'q': 'описании'})
        self.assertEqual(list(response.context['object_list']), [])

    def test_empty_state_and_term_removal_links(self):
        response = self.client.get(reverse('skinali'), {'q': '#ОКЕАН; ЛЕС'})

        self.assertEqual(response.context['search_result_count'], 0)
        self.assertContains(response, 'Ничего не найдено')
        self.assertContains(response, 'Удалите одно из слов или измените поисковый запрос.')
        self.assertNotContains(response, 'class="container catalog-gallery"')
        links = {
            item['label']: item['remove_url']
            for item in response.context['search_terms']
        }
        self.assertEqual(parse_qs(urlparse(links['океан']).query), {'q': ['лес']})
        self.assertEqual(parse_qs(urlparse(links['лес']).query), {'q': ['океан']})

        single_term_response = self.client.get(reverse('skinali'), {'q': 'океан'})
        self.assertEqual(
            single_term_response.context['search_terms'][0]['remove_url'],
            reverse('skinali'),
        )

    def test_invalid_query_shows_error_without_catalog_results(self):
        response = self.client.get(
            reverse('skinali'),
            {'q': 'один два три четыре пять шесть'},
        )

        self.assertFalse(response.context['search_is_valid'])
        self.assertContains(response, 'Введите не более 5 разных слов.')
        self.assertContains(response, 'role="alert"')
        self.assertNotContains(response, 'class="container catalog-gallery"')

    def test_catalog_and_tag_pages_use_thirty_items(self):
        catalog_response = self.client.get(reverse('skinali'))
        tag_response = self.client.get(
            reverse('tag', kwargs={'tag_slug': self.sea_tag.slug})
        )

        self.assertEqual(catalog_response.context['paginator'].per_page, 30)
        self.assertEqual(tag_response.context['paginator'].per_page, 30)

    def test_search_page_size_and_query_count_are_bounded(self):
        for offset in range(29):
            self.create_picture(
                1000 + offset,
                self.first_category,
                [self.sea_tag],
            )

        first_page = self.client.get(reverse('skinali'), {'q': 'океан'})
        second_page = self.client.get(reverse('skinali'), {'q': 'океан', 'page': 2})
        self.assertEqual(first_page.context['paginator'].count, 32)
        self.assertEqual(len(first_page.context['object_list']), 30)
        self.assertEqual(len(second_page.context['object_list']), 2)
        self.assertIn('q=%D0%BE%D0%BA%D0%B5%D0%B0%D0%BD', first_page.context['col_tag'])

        request = RequestFactory().get(reverse('skinali'), {'q': 'океан'})
        view = SkinaliAll()
        view.setup(request)
        queryset = view.get_queryset()
        with CaptureQueriesContext(connection) as query_context:
            queryset.count()
            pictures = list(queryset[:30])
            for picture in pictures:
                list(picture.tags.all())
                list(picture.cat.all())

        self.assertEqual(len(query_context), 4)

    def test_number_of_terms_does_not_increase_database_query_count(self):
        for query in ('море', 'море закат лес река поле'):
            with self.subTest(query=query):
                request = RequestFactory().get(reverse('skinali'), {'q': query})
                view = SkinaliAll()
                view.setup(request)

                with CaptureQueriesContext(connection) as query_context:
                    view.get_queryset().count()

                self.assertEqual(len(query_context), 1)


class CatalogThumbnailTests(TestCase):
    @staticmethod
    def get_thumbnail_url(response):
        html = response.content.decode()
        thumbnail_url_start = html.index('/media/cache/thumbnails/')
        thumbnail_url_end = html.index('"', thumbnail_url_start)
        return html[thumbnail_url_start:thumbnail_url_end]

    def test_catalog_uses_cached_thumbnail_and_lazy_loading(self):
        picture = Pict.objects.create(
            name=701,
            alt='Кешируемое превью',
            photo=create_test_image_file('catalog-thumbnail-source.jpg'),
        )

        response = self.client.get(reverse('skinali'))
        thumbnail_url = self.get_thumbnail_url(response)
        thumbnail_path = Path(settings.MEDIA_ROOT) / thumbnail_url.removeprefix(
            settings.MEDIA_URL
        )

        self.assertContains(response, f'href="{picture.photo.url}"')
        self.assertContains(response, 'width="760"')
        self.assertContains(response, 'loading="lazy"')
        self.assertContains(response, 'decoding="async"')
        self.assertNotEqual(thumbnail_url, picture.photo.url)
        self.assertTrue(thumbnail_path.exists())
        with Image.open(thumbnail_path) as thumbnail:
            self.assertEqual(thumbnail.width, 760)

        initial_mtime = thumbnail_path.stat().st_mtime_ns
        repeated_response = self.client.get(reverse('skinali'))

        self.assertEqual(self.get_thumbnail_url(repeated_response), thumbnail_url)
        self.assertEqual(thumbnail_path.stat().st_mtime_ns, initial_mtime)


class PictUploadNamingTests(TestCase):
    def test_admin_field_configuration(self):
        name_field = Pict._meta.get_field('name')
        alt_field = Pict._meta.get_field('alt')
        model_admin = PictAdmin(Pict, AdminSite())
        main_fieldset, seo_fieldset = model_admin.get_fieldsets(None)
        styles = Path(
            settings.BASE_DIR,
            'pict/static/skinali/css/admin-image-preview.css',
        ).read_text(encoding='utf-8')

        self.assertEqual(name_field.verbose_name, 'Номер изображения')
        self.assertFalse(alt_field.blank)
        self.assertTrue(alt_field.formfield().required)
        self.assertIn('#id_alt.vTextField {', styles)
        self.assertIn('width: 26em;', styles)
        self.assertIn('max-width: 100%;', styles)
        self.assertIsNone(main_fieldset[0])
        self.assertEqual(seo_fieldset[0], 'SEO и текст страницы')
        self.assertEqual(seo_fieldset[1]['classes'], ('collapse',))
        self.assertEqual(
            seo_fieldset[1]['fields'],
            (
                'page_description',
                'seo_h1',
                'seo_title',
                'seo_description',
            ),
        )
        self.assertIn('slug', model_admin.readonly_fields)

    def test_new_upload_uses_transliterated_description_and_image_number(self):
        picture = Pict.objects.create(
            name=901,
            alt='Спелая вишня на тёмном фоне',
            photo=create_test_image_file('IMG_0273-v2.JPG'),
        )

        self.assertEqual(
            picture.photo.name,
            'photos/spelaya-vishnya-na-tyomnom-fone-901.jpg',
        )

    def test_filename_ignores_original_digits_and_does_not_repeat_image_number(self):
        picture = Pict.objects.create(
            name=902,
            alt='Изображение 902',
            photo=create_test_image_file('275.jpg'),
        )

        self.assertEqual(picture.photo.name, 'photos/izobrazhenie-902.jpg')

    def test_upload_without_original_digits_still_uses_image_number(self):
        picture = Pict.objects.create(
            name=904,
            alt='Летний пейзаж',
            photo=create_test_image_file('source.jpg'),
        )

        self.assertEqual(picture.photo.name, 'photos/letniy-peyzazh-904.jpg')

    def test_editing_description_does_not_rename_saved_file(self):
        picture = Pict.objects.create(
            name=903,
            alt='Лесная панорама',
            photo=create_test_image_file('forest-903.jpg'),
        )
        original_photo_name = picture.photo.name

        picture.alt = 'Обновлённое описание'
        picture.save(update_fields=['alt'])
        picture.refresh_from_db()

        self.assertEqual(picture.photo.name, original_photo_name)

    def test_page_slug_uses_description_and_number_and_stays_stable(self):
        picture = Pict.objects.create(
            name=906,
            alt='Яблоки на снегу 906',
            photo=create_test_image_file('source-906.jpg'),
        )

        self.assertEqual(picture.slug, 'yabloki-na-snegu-906')
        self.assertEqual(
            picture.get_absolute_url(),
            '/skinali/image/yabloki-na-snegu-906/',
        )

        picture.alt = 'Новое описание'
        picture.name = 907
        picture.save(update_fields=['alt', 'name'])
        picture.refresh_from_db()

        self.assertEqual(picture.slug, 'yabloki-na-snegu-906')

        replacement = Pict.objects.create(
            name=906,
            alt='Яблоки на снегу 906',
            photo=create_test_image_file('replacement-906.jpg'),
        )
        self.assertEqual(replacement.slug, 'yabloki-na-snegu-906-2')


@override_settings(PUBLIC_SITE_ORIGIN='https://odium.by')
class PictDetailPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(
            cat='Природа',
            slug='detail-nature',
        )
        cls.other_category = Category.objects.create(
            cat='Абстракция',
            slug='detail-abstract',
        )
        cls.tag = TagPict.objects.create(tag='Яблоки', slug='detail-apples')
        cls.other_tag = TagPict.objects.create(tag='Линии', slug='detail-lines')
        cls.color = Color.objects.create(color='Красный', slug_color='detail-red')
        cls.other_color = Color.objects.create(color='Синий', slug_color='detail-blue')

        cls.picture = cls.create_picture(810, 'Яблоки на снегу')
        cls.picture.cat.add(cls.category)
        cls.picture.tags.add(cls.tag)
        cls.picture.color.add(cls.color)

        cls.similar_all = cls.create_picture(811, 'Красные яблоки')
        cls.similar_all.cat.add(cls.category)
        cls.similar_all.tags.add(cls.tag)
        cls.similar_all.color.add(cls.color)

        cls.similar_tag = cls.create_picture(812, 'Яблоневый сад')
        cls.similar_tag.cat.add(cls.other_category)
        cls.similar_tag.tags.add(cls.tag)
        cls.similar_tag.color.add(cls.other_color)

        cls.similar_category = cls.create_picture(813, 'Зимний лес')
        cls.similar_category.cat.add(cls.category)
        cls.similar_category.tags.add(cls.other_tag)
        cls.similar_category.color.add(cls.other_color)

        cls.similar_color = cls.create_picture(814, 'Красная абстракция')
        cls.similar_color.cat.add(cls.other_category)
        cls.similar_color.tags.add(cls.other_tag)
        cls.similar_color.color.add(cls.color)

        cls.unrelated = cls.create_picture(815, 'Синие линии')
        cls.unrelated.cat.add(cls.other_category)
        cls.unrelated.tags.add(cls.other_tag)
        cls.unrelated.color.add(cls.other_color)

        cls.hidden = cls.create_picture(
            816,
            'Скрытые яблоки',
            is_published=False,
        )
        cls.hidden.cat.add(cls.category)
        cls.hidden.tags.add(cls.tag)
        cls.hidden.color.add(cls.color)

    @staticmethod
    def create_picture(name, alt, *, is_published=True):
        return Pict.objects.create(
            name=name,
            alt=alt,
            photo=create_test_image_file(f'detail-{name}.jpg'),
            is_published=is_published,
        )

    def test_detail_page_renders_content_metadata_and_structured_data(self):
        response = self.client.get(self.picture.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<h1>Яблоки на снегу — изображение для скинали №810</h1>',
            html=True,
        )
        self.assertContains(
            response,
            '<title>Яблоки на снегу — изображение для скинали №810 | ОДИУМ</title>',
            html=True,
        )
        self.assertContains(
            response,
            '<meta name="description" content="Изображение №810 '
            '«Яблоки на снегу» для скинали из стекла. Посмотрите '
            'полноразмерный вариант, характеристики и похожие изображения.">',
            html=True,
        )
        self.assertContains(response, 'Изображение №810 «Яблоки на снегу»')
        self.assertContains(response, f'href="{self.picture.photo.url}"')
        self.assertContains(response, f'src="{self.picture.photo.url}"')
        self.assertContains(response, self.category.get_absolute_url())
        self.assertContains(response, self.tag.get_absolute_url())
        self.assertContains(response, 'Красный')
        self.assertContains(response, 'data-image-purchase-open')
        self.assertContains(response, 'data-image-number="810"')
        self.assertContains(
            response,
            f'<link rel="canonical" href="https://odium.by{self.picture.get_absolute_url()}">',
            html=True,
        )
        self.assertEqual(
            tuple(item['name'] for item in response.context['breadcrumbs']),
            ('Главная', 'Каталог', 'Изображение №810'),
        )
        image_data = get_json_ld(response, 'image-structured-data')
        self.assertEqual(image_data['@type'], 'ImageObject')
        self.assertEqual(
            image_data['contentUrl'],
            f'https://odium.by{self.picture.photo.url}',
        )
        self.assertEqual(
            image_data['url'],
            f'https://odium.by{self.picture.get_absolute_url()}',
        )

    def test_detail_page_uses_managed_content_and_seo_fields(self):
        self.picture.page_description = 'Авторское описание страницы.\nВторая строка.'
        self.picture.seo_h1 = 'Яблоки для светлой кухни'
        self.picture.seo_title = 'Панорамное изображение яблок'
        self.picture.seo_description = 'Уникальное SEO-описание изображения.'
        self.picture.save(update_fields=[
            'page_description',
            'seo_h1',
            'seo_title',
            'seo_description',
        ])

        response = self.client.get(self.picture.get_absolute_url())

        self.assertContains(
            response,
            '<h1>Яблоки для светлой кухни</h1>',
            html=True,
        )
        self.assertContains(response, 'Авторское описание страницы.<br>')
        self.assertContains(response, 'Вторая строка.')
        self.assertContains(
            response,
            '<title>Панорамное изображение яблок | ОДИУМ</title>',
            html=True,
        )
        self.assertContains(
            response,
            '<meta name="description" content="Уникальное SEO-описание изображения.">',
            html=True,
        )

    def test_similar_pictures_are_ranked_and_exclude_hidden_or_unrelated(self):
        response = self.client.get(self.picture.get_absolute_url())

        self.assertEqual(
            list(response.context['similar_pictures']),
            [
                self.similar_all,
                self.similar_tag,
                self.similar_category,
                self.similar_color,
            ],
        )
        self.assertNotContains(response, self.hidden.get_absolute_url())
        self.assertNotContains(response, self.unrelated.get_absolute_url())
        self.assertContains(response, 'Похожие изображения')

    def test_unpublished_and_unknown_picture_pages_return_404(self):
        self.assertEqual(
            self.client.get(self.hidden.get_absolute_url()).status_code,
            404,
        )
        self.assertEqual(
            self.client.get('/skinali/image/missing-picture-999/').status_code,
            404,
        )

    def test_catalog_cards_keep_modal_page_link_without_detail_button(self):
        response = self.client.get(reverse('skinali'))

        self.assertContains(
            response,
            f'href="{self.picture.get_absolute_url()}"',
            count=1,
        )
        self.assertContains(response, 'class="catalog-modal__detail"')
        self.assertNotContains(response, 'class="catalog-detail-link"')

    def test_catalog_thumbnail_uses_edge_overlays(self):
        styles = Path(
            settings.BASE_DIR,
            'pict/static/skinali/css/styles.css',
        ).read_text(encoding='utf-8')
        number_styles = styles.split(
            '.catalog-thumbnail__image-number {',
            maxsplit=1,
        )[1].split('}', maxsplit=1)[0]
        number_text_styles = styles.split(
            '.catalog-thumbnail__image-number-text {',
            maxsplit=1,
        )[1].split('}', maxsplit=1)[0]
        favorite_styles = styles.split(
            '.catalog-favorite-toggle {',
            maxsplit=1,
        )[1].split('}', maxsplit=1)[0]
        favorite_hover_styles = styles.split(
            '.catalog-favorite-toggle:hover,',
            maxsplit=1,
        )[1].split('}', maxsplit=1)[0]

        self.assertIn('top: 0;', number_styles)
        self.assertIn('bottom: 0;', number_styles)
        self.assertIn('left: 0;', number_styles)
        self.assertIn('width: calc(1em + 18px);', number_styles)
        self.assertIn('border-radius: 3px 0 0 3px;', number_styles)
        self.assertIn('white-space: nowrap;', number_text_styles)
        self.assertIn('transform: rotate(-90deg);', number_text_styles)
        self.assertIn('top: 0;', favorite_styles)
        self.assertIn('right: 0;', favorite_styles)
        self.assertIn('width: 30px;', favorite_styles)
        self.assertIn('height: 30px;', favorite_styles)
        self.assertIn('border-radius: 0 3px 0 3px;', favorite_styles)
        self.assertIn('transition: background .16s;', favorite_styles)
        self.assertIn('background: #f2f2f2;', favorite_hover_styles)
        self.assertNotIn('.catalog-detail-link {', styles)


class PictAdminPhotoRenameTests(TestCase):
    def setUp(self):
        self.model_admin = PictAdmin(Pict, AdminSite())
        self.request = RequestFactory().post('/admin/pict/pict/')
        self.storage = Pict._meta.get_field('photo').storage

    def create_legacy_picture(self, *, name, alt, filename):
        stored_name = self.storage.save(
            f'photos/{filename}',
            create_test_image_file(filename),
        )
        return Pict.objects.create(name=name, alt=alt, photo=stored_name)

    def test_action_renames_original_deletes_old_file_and_clears_thumbnail(self):
        picture = self.create_legacy_picture(
            name=275,
            alt='Яблоки на снегу',
            filename='275.jpg',
        )
        old_name = picture.photo.name
        thumbnail = get_thumbnail(picture.photo, '760')
        self.assertTrue(thumbnail.storage.exists(thumbnail.name))

        with patch.object(self.model_admin, 'message_user') as message_user:
            self.model_admin.rename_photos_from_description(
                self.request,
                Pict.objects.filter(pk=picture.pk),
            )

        picture.refresh_from_db()
        self.assertEqual(picture.photo.name, 'photos/yabloki-na-snegu-275.jpg')
        self.assertTrue(self.storage.exists(picture.photo.name))
        self.assertFalse(self.storage.exists(old_name))
        self.assertFalse(thumbnail.storage.exists(thumbnail.name))
        self.assertEqual(message_user.call_args.kwargs['level'], messages.SUCCESS)

        with patch.object(self.model_admin, 'message_user'):
            self.model_admin.rename_photos_from_description(
                self.request,
                Pict.objects.filter(pk=picture.pk),
            )
        picture.refresh_from_db()
        self.assertEqual(picture.photo.name, 'photos/yabloki-na-snegu-275.jpg')

    def test_action_skips_historical_picture_without_description(self):
        picture = self.create_legacy_picture(
            name=905,
            alt='',
            filename='905.jpg',
        )
        old_name = picture.photo.name

        with patch.object(self.model_admin, 'message_user') as message_user:
            self.model_admin.rename_photos_from_description(
                self.request,
                Pict.objects.filter(pk=picture.pk),
            )

        picture.refresh_from_db()
        self.assertEqual(picture.photo.name, old_name)
        self.assertTrue(self.storage.exists(old_name))
        self.assertEqual(message_user.call_args.kwargs['level'], messages.WARNING)

    def test_action_keeps_storage_collision_suffix_stable_on_repeated_run(self):
        occupied_name = self.storage.save(
            'photos/yabloki-na-snegu-276.jpg',
            create_test_image_file('occupied.jpg'),
        )
        picture = self.create_legacy_picture(
            name=276,
            alt='Яблоки на снегу',
            filename='276.jpg',
        )

        with patch.object(self.model_admin, 'message_user'):
            self.model_admin.rename_photos_from_description(
                self.request,
                Pict.objects.filter(pk=picture.pk),
            )
        picture.refresh_from_db()
        collision_name = picture.photo.name

        self.assertNotEqual(collision_name, occupied_name)
        self.assertTrue(collision_name.startswith('photos/yabloki-na-snegu-276_'))
        self.assertTrue(collision_name.endswith('.jpg'))

        with patch.object(self.model_admin, 'message_user'):
            self.model_admin.rename_photos_from_description(
                self.request,
                Pict.objects.filter(pk=picture.pk),
            )
        picture.refresh_from_db()

        self.assertEqual(picture.photo.name, collision_name)

    def test_action_is_available_only_with_change_permission(self):
        action = self.model_admin.rename_photos_from_description

        self.assertIn('rename_photos_from_description', self.model_admin.actions)
        self.assertEqual(action.allowed_permissions, ['change'])


class PublicationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(cat='Публикация', slug='publication')
        cls.color = Color.objects.create(color='Синий', slug_color='blue')
        cls.published_tag = TagPict.objects.create(
            tag='Опубликованный тег',
            slug='published-tag',
        )
        cls.hidden_tag = TagPict.objects.create(
            tag='Скрытый тег',
            slug='hidden-tag',
        )
        cls.published_picture = Pict.objects.create(
            name=801,
            alt='Опубликованное изображение',
            photo=create_test_image_file('801.jpg'),
        )
        cls.hidden_picture = Pict.objects.create(
            name=802,
            alt='Скрытое изображение',
            photo=create_test_image_file('802.jpg'),
            is_published=False,
        )
        for picture in (cls.published_picture, cls.hidden_picture):
            picture.cat.add(cls.category)
            picture.color.add(cls.color)
        cls.published_picture.tags.add(cls.published_tag)
        cls.hidden_picture.tags.add(cls.hidden_tag)
        cls.published_work = FinishedWork.objects.create(
            name='Опубликованная работа',
            photo='finished_works/published.jpg',
        )

    def test_publication_defaults_and_admin_expose_editable_checkbox(self):
        pict_admin = PictAdmin(Pict, AdminSite())
        work_admin = FinishedWorkAdmin(FinishedWork, AdminSite())

        self.assertTrue(self.published_picture.is_published)
        self.assertTrue(self.published_work.is_published)
        self.assertIs(Pict._meta.get_field('is_published').default, True)
        self.assertIs(FinishedWork._meta.get_field('is_published').default, True)
        self.assertEqual(
            Pict._meta.get_field('is_published').verbose_name,
            'Опубликовано',
        )
        self.assertIn('is_published', pict_admin.list_display)
        self.assertIn('is_published', pict_admin.list_editable)
        self.assertIn('is_published', pict_admin.fieldsets[0][1]['fields'])
        self.assertIn('is_published', pict_admin.list_filter)
        self.assertIn('is_published', work_admin.list_display)
        self.assertIn('is_published', work_admin.list_editable)
        self.assertIn('is_published', work_admin.fields)
        self.assertIn('is_published', work_admin.list_filter)

    def test_catalog_routes_and_popular_tags_hide_unpublished_pictures(self):
        catalog_response = self.client.get(reverse('skinali'))
        category_response = self.client.get(
            reverse('skinali', kwargs={'slug_cat': self.category.slug}),
            {'color': self.color.slug_color},
        )
        tag_response = self.client.get(
            reverse('tag', kwargs={'tag_slug': self.hidden_tag.slug})
        )
        search_response = self.client.get(
            reverse('skinali'),
            {'q': self.hidden_picture.name},
        )

        self.assertEqual(
            list(catalog_response.context['object_list']),
            [self.published_picture],
        )
        self.assertEqual(
            list(category_response.context['object_list']),
            [self.published_picture],
        )
        self.assertEqual(list(tag_response.context['object_list']), [])
        self.assertEqual(list(search_response.context['object_list']), [])
        self.assertNotIn(
            self.hidden_tag,
            list(catalog_response.context['list_tag']),
        )
        self.assertNotContains(catalog_response, self.hidden_picture.photo.url)


class ContactPageTests(TestCase):
    def test_contact_page_shows_order_channels_and_service_area(self):
        response = self.client.get(reverse('about'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'tel:+375291498838')
        self.assertContains(response, 'mailto:odiumglass@gmail.com')
        self.assertContains(response, 'tel:+375295912453')
        self.assertContains(response, 'mailto:ra-dost@mail.ru')
        self.assertContains(
            response,
            'Свяжитесь с нами по телефону или электронной почте, чтобы получить консультацию и оформить заказ на скинали (кухонный фартук):',
        )
        self.assertContains(
            response,
            'Контакты для заказа услуги «Услуги дизайнера»:',
        )
        self.assertContains(response, 'skinali/images/service-area-map.jpg')
        self.assertContains(response, 'Основная зона обслуживания')
        self.assertContains(response, 'не более 75 км от Жодино')


class ContactFormSubmissionTests(TestCase):
    @staticmethod
    def create_token(age_seconds=3):
        return signing.dumps(
            {'issued_at': time.time() - age_seconds},
            salt=CONTACT_FORM_TOKEN_SALT,
            compress=True,
        )

    def callback_data(self, **overrides):
        data = {
            'form_kind': 'callback',
            'callback-name': 'Анна-Мария',
            'callback-phone': '+1 (202) 555-0198',
            'callback-website': '',
            'callback-form_token': self.create_token(),
        }
        data.update(overrides)
        return data

    def question_data(self, **overrides):
        data = {
            'form_kind': 'question',
            'question-name': 'Алексей',
            'question-phone': '+375 (29) 123-45-67',
            'question-question': '',
            'question-website': '',
            'question-form_token': self.create_token(),
        }
        data.update(overrides)
        return data

    def email_message_data(self, **overrides):
        data = {
            'form_kind': 'email_message',
            'email_message-name': 'Елена',
            'email_message-email': 'ELENA@example.com',
            'email_message-comment': 'Хочу уточнить стоимость.',
            'email_message-website': '',
            'email_message-form_token': self.create_token(),
        }
        data.update(overrides)
        return data

    def image_purchase_data(self, picture, **overrides):
        data = {
            'form_kind': 'image_purchase',
            'image_purchase-name': 'Елена',
            'image_purchase-email': 'BUYER@example.com',
            'image_purchase-comment': 'Хочу купить оригинал.',
            'image_purchase-pict_id': picture.pk,
            'image_purchase-website': '',
            'image_purchase-form_token': self.create_token(),
        }
        data.update(overrides)
        return data

    def test_forms_inherit_common_fields_and_keep_question_optional(self):
        self.assertTrue(issubclass(PhoneContactForm, BaseContactForm))
        self.assertTrue(issubclass(CallbackContactForm, PhoneContactForm))
        self.assertTrue(issubclass(QuestionContactForm, PhoneContactForm))
        self.assertTrue(issubclass(EmailCommentContactForm, BaseContactForm))
        self.assertTrue(issubclass(ImagePurchaseContactForm, EmailCommentContactForm))
        self.assertEqual(CallbackContactForm.base_fields['name'].min_length, 3)
        self.assertEqual(CallbackContactForm.base_fields['name'].max_length, 20)
        self.assertEqual(CallbackContactForm.base_fields['phone'].max_length, 20)
        self.assertEqual(QuestionContactForm.base_fields['question'].max_length, 250)
        self.assertFalse(QuestionContactForm.base_fields['question'].required)
        self.assertNotIn('phone', EmailCommentContactForm.base_fields)
        self.assertTrue(EmailCommentContactForm.base_fields['email'].required)
        self.assertEqual(EmailCommentContactForm.base_fields['comment'].max_length, 250)
        self.assertFalse(EmailCommentContactForm.base_fields['comment'].required)
        self.assertEqual(ImagePurchaseContactForm.base_fields['email'].max_length, 50)
        self.assertTrue(ImagePurchaseContactForm.base_fields['pict_id'].required)

    def test_menu_modal_and_contact_page_question_form_use_shared_markup(self):
        home_response = self.client.get(reverse('home'))
        contact_response = self.client.get(reverse('about'))
        contact_script = Path(
            settings.BASE_DIR,
            'pict/static/skinali/js/contact-forms.js',
        ).read_text(encoding='utf-8')
        styles = Path(
            settings.BASE_DIR,
            'pict/static/skinali/css/styles.css',
        ).read_text(encoding='utf-8')

        self.assertContains(home_response, 'class="mainmenu__callback-button"')
        self.assertContains(home_response, 'Перезвоните мне')
        self.assertContains(home_response, 'id="callback-dialog"')
        self.assertContains(home_response, 'id="image-purchase-dialog"')
        self.assertContains(home_response, 'Купить изображение №')
        self.assertContains(home_response, 'name="image_purchase-pict_id"')
        self.assertContains(home_response, 'data-image-purchase-pict')
        self.assertContains(home_response, 'name="image_purchase-email"')
        self.assertContains(home_response, 'maxlength="50"')
        self.assertNotContains(home_response, 'id="contact-success-dialog"')
        self.assertContains(home_response, 'id="contact-success-toast"')
        self.assertContains(home_response, 'data-contact-success-toast')
        self.assertContains(home_response, 'role="status"')
        self.assertContains(home_response, 'aria-live="polite"')
        self.assertContains(home_response, 'data-contact-success-message')
        self.assertIn("split(/\\r?\\n/)", contact_script)
        self.assertIn('showSuccessToast(result.message);', contact_script)
        self.assertIn('parentDialog.close();', contact_script)
        self.assertIn('}, 2000);', contact_script)
        self.assertIn('.contact-toast {', styles)
        self.assertIn('.contact-toast.is-visible {', styles)
        self.assertIn('width: fit-content;', styles)
        self.assertIn('border: 6px double #6f8a68;', styles)
        self.assertIn('background: #fff;', styles)
        self.assertIn('.contact-toast::before {', styles)
        self.assertIn('content: "✓";', styles)
        self.assertIn('.contact-toast__message span {', styles)
        self.assertIn('white-space: nowrap;', styles)
        self.assertNotContains(home_response, 'contact-toast__close')
        self.assertContains(
            home_response,
            'src="/static/skinali/js/contact-forms.js"',
        )
        self.assertLess(
            home_response.content.find(b'mainmenu__favorites'),
            home_response.content.find(b'mainmenu__callback'),
        )
        self.assertContains(contact_response, 'class="contact-request-card"')
        self.assertContains(contact_response, 'Остались вопросы?')
        self.assertContains(contact_response, 'name="question-question"')
        self.assertContains(contact_response, 'maxlength="250"')
        self.assertContains(contact_response, 'name="question-website"')
        self.assertNotContains(contact_response, 'id="email-message-title"')
        self.assertNotContains(contact_response, 'name="email_message-email"')

    def test_valid_ajax_post_saves_callback_request(self):
        response = self.client.post(
            reverse('contact_submit'),
            self.callback_data(),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'ok': True,
            'message': (
                'Спасибо! Заявка отправлена.\n'
                'Скоро мы с Вами свяжемся😊'
            ),
        })
        request = ContactRequest.objects.get()
        self.assertEqual(request.request_type, ContactRequest.RequestType.CALLBACK)
        self.assertEqual(request.name, 'Анна-Мария')
        self.assertEqual(request.phone, '+1 (202) 555-0198')
        self.assertEqual(request.question, '')
        delivery = request.deliveries.get()
        self.assertEqual(delivery.channel, ContactRequestDelivery.Channel.TELEGRAM)
        self.assertEqual(delivery.status, ContactRequestDelivery.Status.PENDING)
        self.assertEqual(delivery.attempts, 0)

    def test_valid_ajax_post_saves_email_message_and_queues_delivery(self):
        response = self.client.post(
            reverse('contact_submit'),
            self.email_message_data(),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        request = ContactRequest.objects.get()
        self.assertEqual(
            request.request_type,
            ContactRequest.RequestType.EMAIL_MESSAGE,
        )
        self.assertEqual(request.name, 'Елена')
        self.assertEqual(request.phone, '')
        self.assertEqual(request.email, 'elena@example.com')
        self.assertEqual(request.comment, 'Хочу уточнить стоимость.')
        self.assertEqual(
            request.deliveries.get().status,
            ContactRequestDelivery.Status.PENDING,
        )

    def test_email_message_rejects_invalid_email_and_long_comment(self):
        invalid_email_response = self.client.post(
            reverse('contact_submit'),
            self.email_message_data(**{
                'email_message-email': 'incorrect-address',
            }),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        long_comment_response = self.client.post(
            reverse('contact_submit'),
            self.email_message_data(**{
                'email_message-comment': 'Я' * 251,
            }),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(invalid_email_response.status_code, 422)
        self.assertIn('email', invalid_email_response.json()['errors'])
        self.assertEqual(long_comment_response.status_code, 422)
        self.assertIn('comment', long_comment_response.json()['errors'])
        self.assertFalse(ContactRequest.objects.exists())

    def test_valid_image_purchase_saves_catalog_link_snapshot_and_delivery(self):
        picture = Pict.objects.create(
            name=127,
            alt='Изображение для покупки',
            photo=create_test_image_file('127.jpg'),
        )

        response = self.client.post(
            reverse('contact_submit'),
            self.image_purchase_data(picture),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'ok': True,
            'message': (
                'Спасибо! Заявка отправлена.\n'
                'Скоро мы с Вами свяжемся😊'
            ),
        })
        request = ContactRequest.objects.get()
        self.assertEqual(
            request.request_type,
            ContactRequest.RequestType.IMAGE_PURCHASE,
        )
        self.assertEqual(request.name, 'Елена')
        self.assertEqual(request.email, 'buyer@example.com')
        self.assertEqual(request.comment, 'Хочу купить оригинал.')
        self.assertEqual(request.catalog_image, picture)
        self.assertEqual(request.image_number, 127)
        self.assertEqual(
            request.deliveries.get().status,
            ContactRequestDelivery.Status.PENDING,
        )

        picture.delete()
        request.refresh_from_db()
        self.assertIsNone(request.catalog_image)
        self.assertEqual(request.image_number, 127)

    def test_image_purchase_rejects_unknown_picture_and_email_over_50_characters(self):
        picture = Pict.objects.create(
            name=128,
            alt='Изображение для проверки',
            photo=create_test_image_file('128.jpg'),
        )
        missing_response = self.client.post(
            reverse('contact_submit'),
            self.image_purchase_data(picture, **{
                'image_purchase-pict_id': 999999,
            }),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        long_email_response = self.client.post(
            reverse('contact_submit'),
            self.image_purchase_data(picture, **{
                'image_purchase-email': f'{"a" * 39}@example.com',
            }),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(missing_response.status_code, 422)
        self.assertIn('pict_id', missing_response.json()['errors'])
        self.assertEqual(long_email_response.status_code, 422)
        self.assertIn('email', long_email_response.json()['errors'])
        self.assertFalse(ContactRequest.objects.exists())

    def test_image_purchase_rejects_unpublished_picture(self):
        picture = Pict.objects.create(
            name=129,
            alt='Снятое с публикации изображение',
            photo=create_test_image_file('129.jpg'),
            is_published=False,
        )

        response = self.client.post(
            reverse('contact_submit'),
            self.image_purchase_data(picture),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn('pict_id', response.json()['errors'])
        self.assertFalse(ContactRequest.objects.exists())

    def test_ajax_validation_reports_errors_for_name_and_phone(self):
        response = self.client.post(
            reverse('contact_submit'),
            self.callback_data(
                **{
                    'callback-name': 'Иван7',
                    'callback-phone': '123+456',
                }
            ),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 422)
        errors = response.json()['errors']
        self.assertIn('name', errors)
        self.assertIn('phone', errors)

    def test_question_is_optional_but_cannot_exceed_250_characters(self):
        optional_response = self.client.post(
            reverse('contact_submit'),
            self.question_data(),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        long_response = self.client.post(
            reverse('contact_submit'),
            self.question_data(**{'question-question': 'Я' * 251}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(optional_response.status_code, 200)
        self.assertEqual(long_response.status_code, 422)
        self.assertIn('question', long_response.json()['errors'])
        request = ContactRequest.objects.get()
        self.assertEqual(request.request_type, ContactRequest.RequestType.QUESTION)
        self.assertEqual(request.question, '')

    def test_honeypot_and_too_fast_token_return_indistinguishable_success(self):
        honeypot_response = self.client.post(
            reverse('contact_submit'),
            self.callback_data(**{'callback-website': 'https://spam.example'}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        fast_response = self.client.post(
            reverse('contact_submit'),
            self.callback_data(**{
                'callback-form_token': self.create_token(age_seconds=0),
            }),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(honeypot_response.status_code, 200)
        self.assertTrue(honeypot_response.json()['ok'])
        self.assertEqual(fast_response.status_code, 200)
        self.assertTrue(fast_response.json()['ok'])
        self.assertFalse(ContactRequest.objects.exists())

    def test_non_ajax_invalid_post_preserves_values_and_errors(self):
        response = self.client.post(
            reverse('contact_submit'),
            self.callback_data(**{'callback-name': 'Иван7'}),
        )

        self.assertEqual(response.status_code, 422)
        self.assertContains(response, 'value="Иван7"', status_code=422)
        self.assertContains(
            response,
            'Используйте только буквы, пробел, дефис или апостроф.',
            status_code=422,
        )
        self.assertNotContains(response, 'id="callback-dialog"', status_code=422)
        self.assertFalse(ContactRequest.objects.exists())

    def test_contact_requests_are_available_in_admin(self):
        site = AdminSite()
        request_admin = ContactRequestAdmin(ContactRequest, site)
        question_request = ContactRequest.objects.create(
            request_type=ContactRequest.RequestType.QUESTION,
            name='Мария',
            phone='+375 29 111-22-33',
            question='Когда можно выполнить замер?',
        )
        picture = Pict.objects.create(
            name=130,
            alt='Изображение из заявки',
            photo=create_test_image_file('130.jpg'),
        )
        purchase_request = ContactRequest.objects.create(
            request_type=ContactRequest.RequestType.IMAGE_PURCHASE,
            name='Елена',
            email='buyer@example.com',
            comment='Хочу купить оригинал.',
            catalog_image=picture,
            image_number=picture.name,
        )
        ContactRequestDelivery.objects.create(
            contact_request=purchase_request,
            channel=ContactRequestDelivery.Channel.TELEGRAM,
        )

        self.assertEqual(request_admin.list_display, [
            'get_request_name',
            'phone',
            'email',
            'request_type',
            'get_delivery_channel',
            'get_delivery_status',
            'created_at',
        ])
        self.assertEqual(request_admin.list_display[3], 'request_type')
        self.assertEqual(
            request_admin.get_fields(None, question_request),
            [
                'request_type',
                'name',
                'phone',
                'question',
                'get_delivery_status',
                'created_at',
            ],
        )
        self.assertEqual(
            request_admin.get_fields(None, purchase_request),
            [
                'request_type',
                'name',
                'email',
                'comment',
                'image_number',
                'get_catalog_image_thumbnail',
                'get_delivery_status',
                'created_at',
            ],
        )
        self.assertIn(
            'request_type',
            request_admin.get_readonly_fields(None, question_request),
        )
        thumbnail = str(request_admin.get_catalog_image_thumbnail(purchase_request))
        self.assertIn(picture.photo.url, thumbnail)
        self.assertIn('width="150"', thumbnail)
        self.assertIn('data-image-preview', thumbnail)
        self.assertEqual(request_admin.get_delivery_channel(purchase_request), 'Telegram')
        self.assertEqual(
            request_admin.get_delivery_status(purchase_request),
            'Ожидает отправки',
        )
        self.assertIn('phone', request_admin.search_fields)
        self.assertIn('email', request_admin.search_fields)
        self.assertIn('=image_number', request_admin.search_fields)
        self.assertIn('created_at', request_admin.readonly_fields)
        self.assertIn('queue_missing_telegram_deliveries', request_admin.actions)
        self.assertIn('retry_failed_telegram_deliveries', request_admin.actions)
        self.assertEqual(request_admin.inlines, [ContactRequestDeliveryInline])
        delivery_inline = ContactRequestDeliveryInline(ContactRequest, site)
        self.assertEqual(delivery_inline.fields, [
            'channel',
            'status',
            'attempts',
            'next_attempt_at',
            'sent_at',
            'external_message_id',
            'last_error',
        ])
        self.assertEqual(delivery_inline.readonly_fields, delivery_inline.fields)
        self.assertFalse(delivery_inline.can_delete)
        self.assertFalse(delivery_inline.has_add_permission(None, question_request))
        self.assertTrue(admin.site.is_registered(ContactRequest))
        self.assertFalse(admin.site.is_registered(ContactRequestDelivery))
        self.assertEqual(str(question_request), 'Мария — +375 29 111-22-33')
        with patch.object(request_admin, 'message_user'):
            request_admin.queue_missing_telegram_deliveries(
                None,
                ContactRequest.objects.select_related('catalog_image'),
            )
        self.assertEqual(ContactRequestDelivery.objects.count(), 2)

    def test_opening_contact_request_marks_its_name_as_viewed(self):
        contact_request = ContactRequest.objects.create(
            request_type=ContactRequest.RequestType.CALLBACK,
            name='Новая заявка',
            phone='+375 29 111-22-33',
        )
        request_admin = ContactRequestAdmin(ContactRequest, AdminSite())
        admin_user = get_user_model().objects.create_superuser(
            username='contact-view-test',
            email='contact-view@example.com',
            password='test-password',
        )
        self.client.force_login(admin_user)

        self.assertIsNone(contact_request.viewed_at)
        change_url = reverse(
            'admin:pict_contactrequest_change',
            args=[contact_request.pk],
        )
        self.assertHTMLEqual(
            str(request_admin.get_request_name(contact_request)),
            f'<a href="{change_url}">Новая заявка</a>',
        )
        self.assertIsNone(request_admin.list_display_links)

        response = self.client.get(change_url)
        contact_request.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(contact_request.viewed_at)
        self.assertHTMLEqual(
            str(request_admin.get_request_name(contact_request)),
            f'<a class="contact-request-name--viewed" href="{change_url}">'
            'Новая заявка</a>',
        )
        styles = Path(
            settings.BASE_DIR,
            'pict/static/skinali/css/admin-image-preview.css',
        ).read_text(encoding='utf-8')
        self.assertIn(
            '#result_list a.contact-request-name--viewed:link,',
            styles,
        )
        self.assertIn('color: #8baec0;', styles)


@override_settings(
    TELEGRAM_BOT_TOKEN='test-token',
    TELEGRAM_CHAT_ID='123456',
    TELEGRAM_PROXY_URL='',
    TELEGRAM_CONNECT_TIMEOUT=3,
    TELEGRAM_READ_TIMEOUT=5,
)
class ContactDeliveryTests(TestCase):
    def create_delivery(self, **overrides):
        contact_request = ContactRequest.objects.create(
            request_type=ContactRequest.RequestType.QUESTION,
            name='Мария',
            phone='+375 29 111-22-33',
            question='Когда можно выполнить замер?',
        )
        defaults = {
            'contact_request': contact_request,
            'channel': ContactRequestDelivery.Channel.TELEGRAM,
        }
        defaults.update(overrides)
        return ContactRequestDelivery.objects.create(**defaults)

    @patch('pict.services.contact_delivery.requests.Session')
    def test_management_command_marks_successful_telegram_delivery(self, session_class):
        delivery = self.create_delivery()
        session = session_class.return_value
        post = session.post
        response = Mock(status_code=200)
        response.json.return_value = {
            'ok': True,
            'result': {'message_id': 987},
        }
        post.return_value = response

        output = StringIO()
        call_command('process_contact_deliveries', stdout=output)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, ContactRequestDelivery.Status.SENT)
        self.assertEqual(delivery.attempts, 1)
        self.assertEqual(delivery.external_message_id, 987)
        self.assertIsNotNone(delivery.sent_at)
        self.assertIsNone(delivery.next_attempt_at)
        self.assertIn('отправлено=1', output.getvalue())
        request_payload = post.call_args.kwargs['json']
        self.assertEqual(request_payload['chat_id'], '123456')
        self.assertEqual(request_payload['parse_mode'], 'HTML')
        self.assertTrue(
            request_payload['text'].startswith(
                f'❔ <b>Новая заявка №{delivery.contact_request_id}</b>\n'
                '— <b><i>Вопрос</i></b> —\n\n'
            )
        )
        self.assertIn(
            '📞 +375 29 111-22-33',
            request_payload['text'],
        )
        self.assertIn(
            '❔ Когда можно выполнить замер?',
            request_payload['text'],
        )
        self.assertEqual(post.call_args.kwargs['timeout'], (3, 5))
        self.assertIsNone(post.call_args.kwargs['proxies'])
        self.assertFalse(session.trust_env)
        session.close.assert_called_once_with()

    @patch('pict.services.contact_delivery.requests.Session')
    def test_temporary_error_schedules_retry_without_losing_request(self, session_class):
        delivery = self.create_delivery()
        post = session_class.return_value.post
        post.side_effect = requests.Timeout()

        call_command('process_contact_deliveries', stdout=StringIO())

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, ContactRequestDelivery.Status.RETRY)
        self.assertEqual(delivery.attempts, 1)
        self.assertGreater(delivery.next_attempt_at, timezone.now())
        self.assertIn('не ответил', delivery.last_error)
        self.assertNotIn('test-token', delivery.last_error)

    @patch('pict.services.contact_delivery.requests.Session')
    def test_email_message_contains_email_and_comment_without_empty_phone(self, session_class):
        contact_request = ContactRequest.objects.create(
            request_type=ContactRequest.RequestType.EMAIL_MESSAGE,
            name='Елена',
            email='elena@example.com',
            comment='Хочу уточнить стоимость.',
        )
        ContactRequestDelivery.objects.create(
            contact_request=contact_request,
            channel=ContactRequestDelivery.Channel.TELEGRAM,
        )
        response = Mock(status_code=200)
        response.json.return_value = {
            'ok': True,
            'result': {'message_id': 988},
        }
        session_class.return_value.post.return_value = response

        call_command('process_contact_deliveries', stdout=StringIO())

        message = session_class.return_value.post.call_args.kwargs['json']['text']
        self.assertTrue(message.startswith('✉ <b>Новая заявка №'))
        self.assertIn(
            '— <b><i>Сообщение по email</i></b> —',
            message,
        )
        self.assertIn('✉ elena@example.com', message)
        self.assertIn(
            '💬 Хочу уточнить стоимость.',
            message,
        )
        self.assertNotIn('📞', message)

    @patch('pict.services.contact_delivery.requests.Session')
    def test_image_purchase_message_contains_catalog_image_number(self, session_class):
        contact_request = ContactRequest.objects.create(
            request_type=ContactRequest.RequestType.IMAGE_PURCHASE,
            name='Елена',
            email='buyer@example.com',
            comment='Хочу купить оригинал.',
            image_number=127,
        )
        ContactRequestDelivery.objects.create(
            contact_request=contact_request,
            channel=ContactRequestDelivery.Channel.TELEGRAM,
        )
        response = Mock(status_code=200)
        response.json.return_value = {
            'ok': True,
            'result': {'message_id': 989},
        }
        session_class.return_value.post.return_value = response

        call_command('process_contact_deliveries', stdout=StringIO())

        message = session_class.return_value.post.call_args.kwargs['json']['text']
        self.assertTrue(message.startswith('💲 <b>Новая заявка №'))
        self.assertIn(
            '— <b><i>Покупка изображения</i></b> —',
            message,
        )
        self.assertIn('✉ buyer@example.com', message)
        self.assertIn(
            '💬 Хочу купить оригинал.',
            message,
        )
        self.assertIn('🖼 №127', message)

    def test_callback_message_uses_pin_icon(self):
        contact_request = ContactRequest.objects.create(
            request_type=ContactRequest.RequestType.CALLBACK,
            name='Иван',
            phone='+7 999 123-45-67',
        )

        message = format_contact_request_message(contact_request)
        created_at = timezone.localtime(contact_request.created_at)

        self.assertEqual(
            message,
            f'📌 <b>Новая заявка №{contact_request.pk}</b>\n'
            '— <b><i>Обратный звонок</i></b> —\n\n'
            '👤 Иван\n'
            '📞 +7 999 123-45-67\n'
            f'🕒 {created_at:%d.%m.%Y %H:%M}',
        )

    def test_user_text_is_escaped_for_telegram_html(self):
        contact_request = ContactRequest.objects.create(
            request_type=ContactRequest.RequestType.QUESTION,
            name='Мария & Иван',
            phone='+375 29 111-22-33',
            question='Можно <сегодня> & завтра?',
        )

        message = format_contact_request_message(contact_request)

        self.assertIn('Мария &amp; Иван', message)
        self.assertIn('Можно &lt;сегодня&gt; &amp; завтра?', message)
        self.assertNotIn('Можно <сегодня>', message)

    @patch('pict.services.contact_delivery.requests.Session')
    def test_permanent_telegram_error_stops_automatic_retries(self, session_class):
        delivery = self.create_delivery()
        post = session_class.return_value.post
        response = Mock(status_code=400)
        response.json.return_value = {
            'ok': False,
            'error_code': 400,
            'description': 'Bad Request: chat not found',
        }
        post.return_value = response

        call_command('process_contact_deliveries', stdout=StringIO())

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, ContactRequestDelivery.Status.FAILED)
        self.assertIsNone(delivery.next_attempt_at)
        self.assertEqual(delivery.last_error, 'Bad Request: chat not found')

    @patch('pict.services.contact_delivery.requests.Session')
    def test_stale_processing_delivery_is_recovered_and_sent(self, session_class):
        delivery = self.create_delivery(
            status=ContactRequestDelivery.Status.PROCESSING,
            attempts=1,
            next_attempt_at=None,
            processing_started_at=timezone.now() - timedelta(minutes=11),
        )
        response = Mock(status_code=200)
        response.json.return_value = {
            'ok': True,
            'result': {'message_id': 654},
        }
        post = session_class.return_value.post
        post.return_value = response

        output = StringIO()
        call_command(
            'process_contact_deliveries',
            stale_after=600,
            stdout=output,
        )

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, ContactRequestDelivery.Status.SENT)
        self.assertEqual(delivery.attempts, 2)
        self.assertIn('восстановлено=1', output.getvalue())

    @override_settings(
        TELEGRAM_PROXY_URL='https://proxy-user:proxy-password@proxy.example:8443'
    )
    @patch('pict.services.contact_delivery.requests.Session')
    def test_configured_proxy_is_used_in_strict_mode(self, session_class):
        self.create_delivery()
        session = session_class.return_value
        response = Mock(status_code=200)
        response.json.return_value = {
            'ok': True,
            'result': {'message_id': 777},
        }
        session.post.return_value = response

        call_command('process_contact_deliveries', stdout=StringIO())

        expected_proxy = 'https://proxy-user:proxy-password@proxy.example:8443'
        self.assertEqual(
            session.post.call_args.kwargs['proxies'],
            {'http': expected_proxy, 'https': expected_proxy},
        )
        self.assertFalse(session.trust_env)

    @override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_CHAT_ID='')
    def test_missing_configuration_keeps_delivery_pending(self):
        delivery = self.create_delivery()

        with self.assertRaises(CommandError):
            call_command('process_contact_deliveries', stdout=StringIO())

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, ContactRequestDelivery.Status.PENDING)
        self.assertEqual(delivery.attempts, 0)

    def test_delivery_model_is_hidden_from_admin_and_retry_action_is_preserved(self):
        delivery = self.create_delivery(
            status=ContactRequestDelivery.Status.FAILED,
            attempts=3,
            next_attempt_at=None,
            last_error='Ошибка доставки',
        )
        request_admin = ContactRequestAdmin(ContactRequest, AdminSite())

        self.assertFalse(admin.site.is_registered(ContactRequestDelivery))
        self.assertIn('retry_failed_telegram_deliveries', request_admin.actions)
        with patch.object(request_admin, 'message_user'):
            request_admin.retry_failed_telegram_deliveries(
                None,
                ContactRequest.objects.filter(pk=delivery.contact_request_id),
            )

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, ContactRequestDelivery.Status.RETRY)
        self.assertEqual(delivery.attempts, 0)
        self.assertIsNotNone(delivery.next_attempt_at)
        self.assertEqual(delivery.last_error, '')


class DesignerPageTests(TestCase):
    def test_designer_page_shows_copyright_terms_and_contact_links(self):
        response = self.client.get(reverse('designer'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Авторское право на изображения')
        self.assertContains(response, 'Покупателям изображений')
        self.assertContains(response, 'Заказчикам скинали')
        self.assertContains(response, 'БЕСПЛАТНО')
        self.assertContains(
            response,
            f'<a class="designer-page__contact-link" href="{reverse("about")}">Напишите нам</a> номер изображения из каталога.',
        )
        self.assertContains(response, 'class="designer-price-card"')
        self.assertContains(
            response,
            '<strong data-price-code="designer-original-image-usd">5</strong>$',
            html=True,
        )
        self.assertNotContains(response, '<strong>30</strong> BYN', html=True)
        self.assertContains(response, 'Эксклюзивное изображение с нуля.')
        self.assertContains(response, 'skinali/images/designer-exclusive-reference.jpg')
        self.assertContains(response, 'Обсудить идею')
        self.assertContains(
            response,
            f'class="designer-exclusive-banner__action designer-page__contact-link" href="{reverse("about")}"',
        )
        self.assertContains(
            response,
            f'class="designer-page__contact-link" href="{reverse("about")}"',
            count=2,
        )


class SessionFavoritesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first_picture = Pict.objects.create(
            name=301,
            alt='Первое описание',
            photo=create_test_image_file('301.jpg'),
        )
        cls.second_picture = Pict.objects.create(
            name=302,
            alt='Второе описание',
            photo=create_test_image_file('302.jpg'),
        )
        cls.favorite_category = Category.objects.create(
            cat='Категория избранного',
            slug='favorite-category',
        )
        cls.favorite_tag = TagPict.objects.create(
            tag='Тег избранного',
            slug='favorite-tag',
        )
        cls.first_picture.cat.add(cls.favorite_category)
        cls.favorite_tag.tags.add(cls.first_picture)

    def test_toggle_adds_and_removes_picture_in_current_session(self):
        url = reverse('favorite_toggle', kwargs={'pict_id': self.first_picture.pk})

        added_response = self.client.post(url)

        self.assertEqual(added_response.status_code, 200)
        self.assertEqual(added_response.json(), {
            'pict_id': self.first_picture.pk,
            'is_favorite': True,
            'favorites_count': 1,
        })
        self.assertEqual(
            self.client.session['favorite_pict_ids'],
            [self.first_picture.pk],
        )

        removed_response = self.client.post(url)

        self.assertEqual(removed_response.status_code, 200)
        self.assertFalse(removed_response.json()['is_favorite'])
        self.assertEqual(self.client.session['favorite_pict_ids'], [])

    @override_settings(PUBLIC_SITE_ORIGIN='https://odium.by')
    def test_favorites_page_is_noindex_with_self_canonical(self):
        response = self.client.get(reverse('favorites'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<meta name="robots" content="noindex,follow">',
            html=True,
        )
        self.assertEqual(
            response.context['canonical_url'],
            f'https://odium.by{reverse("favorites")}',
        )
        self.assertContains(
            response,
            f'<link rel="canonical" '
            f'href="https://odium.by{reverse("favorites")}">',
            html=True,
        )

    def test_favorites_are_isolated_between_browser_sessions(self):
        first_browser = Client()
        second_browser = Client()
        toggle_url = reverse(
            'favorite_toggle',
            kwargs={'pict_id': self.first_picture.pk},
        )

        first_browser.post(toggle_url)

        self.assertContains(
            first_browser.get(reverse('favorites')),
            'Изображение № 301',
        )
        self.assertNotContains(
            second_browser.get(reverse('favorites')),
            'Изображение № 301',
        )

    def test_favorites_page_shows_newest_first_with_description(self):
        self.client.post(reverse(
            'favorite_toggle',
            kwargs={'pict_id': self.first_picture.pk},
        ))
        self.client.post(reverse(
            'favorite_toggle',
            kwargs={'pict_id': self.second_picture.pk},
        ))

        response = self.client.get(reverse('favorites'))
        styles = Path(
            settings.BASE_DIR,
            'pict/static/skinali/css/styles.css',
        ).read_text(encoding='utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['favorite_pictures'],
            [self.second_picture, self.first_picture],
        )
        self.assertContains(response, 'Изображение № 301')
        self.assertContains(response, self.first_picture.alt)
        self.assertContains(response, 'data-favorite-row')
        self.assertContains(response, 'class="catalog-thumbnail favorite-card__preview"')
        self.assertContains(
            response,
            '<span class="catalog-thumbnail__image-number">'
            '<span class="catalog-thumbnail__image-number-text">№ 301</span>'
            '</span>',
            html=True,
        )
        self.assertContains(response, 'data-fancybox="catalog-gallery"')
        self.assertContains(response, 'data-caption-template="catalog-gallery-caption-')
        self.assertContains(response, 'class="catalog-modal__title"')
        self.assertNotContains(response, 'class="catalog-modal__image-number"')
        self.assertContains(response, 'class="catalog-modal__favorite is-active"')
        self.assertContains(response, 'class="catalog-modal__purchase"')
        self.assertContains(response, 'data-image-purchase-open')
        self.assertContains(response, 'data-share-kind="favorites"')
        self.assertContains(response, 'Поделиться изображениями')
        self.assertContains(response, 'data-image-number="302"')
        response_html = response.content.decode()
        self.assertGreater(
            response_html.index('class="favorites-share"'),
            response_html.rindex('class="favorite-card"'),
        )
        self.assertContains(response, '#Тег избранного')
        self.assertContains(response, 'Категория избранного')
        self.assertNotContains(response, 'class="catalog-favorite-toggle')
        self.assertEqual(styles.count('.favorite-card__image {'), 1)
        favorite_image_styles = styles.split(
            '.favorite-card__image {',
            maxsplit=1,
        )[1].split('}', maxsplit=1)[0]
        thumbnail_hover_styles = styles.split(
            '.catalog-thumbnail:hover::after,',
            maxsplit=1,
        )[1].split('}', maxsplit=1)[0]
        self.assertIn('height: auto;', favorite_image_styles)
        self.assertNotIn('object-fit:', favorite_image_styles)
        self.assertNotIn('background:', favorite_image_styles)
        self.assertIn(
            '.catalog-thumbnail:focus-visible::after,',
            thumbnail_hover_styles,
        )
        self.assertIn(
            '.finished-work-card__link:hover::after,',
            thumbnail_hover_styles,
        )
        self.assertIn(
            '.finished-work-card__link:focus-visible::after {',
            thumbnail_hover_styles,
        )
        self.assertIn('opacity: 1;', thumbnail_hover_styles)

    def test_favorites_menu_link_and_modal_button_are_rendered(self):
        empty_response = self.client.get(reverse('skinali'))

        self.assertContains(
            empty_response,
            'class="mainmenu__favorites" data-favorites-menu hidden',
        )
        self.client.post(reverse(
            'favorite_toggle',
            kwargs={'pict_id': self.first_picture.pk},
        ))

        response = self.client.get(reverse('skinali'))
        response_html = response.content.decode()
        styles = Path(
            settings.BASE_DIR,
            'pict/static/skinali/css/styles.css',
        ).read_text(encoding='utf-8')

        self.assertNotContains(response, 'data-favorites-menu hidden')
        self.assertContains(
            response,
            '<span class="mainmenu__favorites-count" data-favorites-count>1</span>',
            count=1,
            html=True,
        )
        self.assertGreater(
            response_html.index('data-favorites-menu'),
            response_html.index('Связаться с нами'),
        )
        self.assertContains(
            response,
            reverse(
                'favorite_toggle',
                kwargs={'pict_id': self.first_picture.pk},
            ),
        )
        self.assertContains(response, 'favorite-toggle__label-add">Добавить в избранное</span>')
        self.assertContains(response, 'class="catalog-favorite-toggle is-active"')
        self.assertContains(response, 'aria-label="Удалить из избранного"')
        self.assertContains(response, 'class="catalog-modal__favorite is-active"')
        self.assertContains(response, "transition: 'fade'")
        self.assertContains(response, 'Navigation: false')
        self.assertContains(response, 'showClass: false')
        self.assertContains(response, 'zoom: false')
        self.assertContains(response, "content.classList.add('is-catalog-ready')")
        self.assertIn(
            '.catalog-gallery-modal .fancybox__slide:not(.is-selected) '
            '> .fancybox__content',
            styles,
        )
        self.assertContains(response, 'enableCatalogCaptionSelection(caption)')
        self.assertContains(response, "caption.addEventListener('mousedown', stopImageNavigation)")
        self.assertContains(response, "event.target.closest('[data-clickable]')")
        self.assertContains(
            response,
            'data-fancybox-prev\n              data-clickable',
            count=2,
        )
        self.assertContains(
            response,
            'data-fancybox-next\n              data-clickable',
            count=2,
        )
        self.assertContains(response, "document.getElementById(templateId)")
        self.assertContains(response, 'updateFavoritesMenu(result.favorites_count)')
        self.assertContains(response, "document.querySelectorAll('[data-favorites-menu]')")
        self.assertContains(response, 'slide.captionEl || fancybox.caption')
        self.assertContains(response, 'if (!slide)')
        self.assertContains(response, 'reveal: (fancybox, slide)')
        self.assertContains(response, "'Carousel.selectSlide': (fancybox, carousel, slide)")
        self.assertContains(response, '!fancybox.isCurrentSlide(slide)')
        self.assertContains(response, 'resize: (fancybox) => prepareGallerySlide')

    def test_toggle_accepts_only_post_and_unknown_picture_returns_404(self):
        valid_url = reverse(
            'favorite_toggle',
            kwargs={'pict_id': self.first_picture.pk},
        )
        missing_url = reverse('favorite_toggle', kwargs={'pict_id': 999999})

        self.assertEqual(self.client.get(valid_url).status_code, 405)
        self.assertEqual(self.client.post(missing_url).status_code, 404)

    def test_unpublished_picture_is_removed_from_favorites_and_cannot_be_added(self):
        for picture in (self.first_picture, self.second_picture):
            self.client.post(reverse(
                'favorite_toggle',
                kwargs={'pict_id': picture.pk},
            ))

        self.first_picture.is_published = False
        self.first_picture.save(update_fields=['is_published'])

        response = self.client.get(reverse('favorites'))

        self.assertEqual(
            response.context['favorite_pictures'],
            [self.second_picture],
        )
        self.assertEqual(
            self.client.session['favorite_pict_ids'],
            [self.second_picture.pk],
        )
        self.assertNotContains(response, 'Изображение № 301')
        self.assertEqual(
            self.client.post(reverse(
                'favorite_toggle',
                kwargs={'pict_id': self.first_picture.pk},
            )).status_code,
            404,
        )


class FinishedWorkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(
            cat='Архитектура',
            slug='architecture',
        )
        cls.catalog_image = Pict.objects.create(
            name=701,
            alt='Каталожное изображение',
            photo=create_test_image_file('701.jpg'),
        )
        cls.catalog_image.cat.add(cls.category)
        cls.work = FinishedWork.objects.create(
            name='Кухонный фартук',
            description='Готовая работа с подсветкой',
            photo=create_test_image_file('finished-kitchen.jpg'),
            catalog_image=cls.catalog_image,
        )

    def test_glass_and_skinali_types_have_safe_defaults(self):
        self.assertEqual(self.work.glass_type, FinishedWork.GlassType.STANDARD)
        self.assertEqual(self.work.get_glass_type_display(), 'Обычное')
        self.assertEqual(self.work.skinali_type, FinishedWork.SkinaliType.PRINT)
        self.assertEqual(self.work.get_skinali_type_display(), 'Печать')
        self.assertEqual(self.work.paint_color, '')

    def test_skinali_type_validates_dependent_fields(self):
        painted_work = FinishedWork(
            name='Покрашенный фартук',
            photo='finished_works/painted.jpg',
            skinali_type=FinishedWork.SkinaliType.PAINT,
        )

        with self.assertRaises(ValidationError) as missing_color_error:
            painted_work.full_clean()
        self.assertIn('paint_color', missing_color_error.exception.message_dict)

        painted_work.paint_color = '  RAL 9000  '
        painted_work.catalog_image = self.catalog_image
        with self.assertRaises(ValidationError) as catalog_image_error:
            painted_work.full_clean()
        self.assertIn('catalog_image', catalog_image_error.exception.message_dict)

        painted_work.catalog_image = None
        painted_work.full_clean()
        painted_work.save()
        painted_work.refresh_from_db()
        self.assertEqual(painted_work.paint_color, 'RAL 9000')

        transparent_work = FinishedWork(
            name='Прозрачный фартук',
            photo='finished_works/transparent.jpg',
            skinali_type=FinishedWork.SkinaliType.TRANSPARENT,
            paint_color='RAL 9000',
            catalog_image=self.catalog_image,
        )
        with self.assertRaises(ValidationError) as transparent_error:
            transparent_work.full_clean()
        self.assertEqual(
            set(transparent_error.exception.message_dict),
            {'paint_color', 'catalog_image'},
        )

        printed_work = FinishedWork(
            name='Фартук с печатью',
            photo='finished_works/printed.jpg',
            skinali_type=FinishedWork.SkinaliType.PRINT,
            paint_color='RAL 9000',
        )
        with self.assertRaises(ValidationError) as print_error:
            printed_work.full_clean()
        self.assertIn('paint_color', print_error.exception.message_dict)

    def test_admin_form_saves_painting_without_catalog_image(self):
        form = FinishedWorkAdminForm(
            data={
                'name': self.work.name,
                'description': self.work.description,
                'is_published': 'on',
                'glass_type': FinishedWork.GlassType.OPTIWHITE,
                'skinali_type': FinishedWork.SkinaliType.PAINT,
                'paint_color': 'RAL 9000',
                'catalog_image': '',
            },
            instance=self.work,
        )

        self.assertTrue(form.is_valid(), form.errors.as_json())
        saved_work = form.save()
        self.assertEqual(saved_work.glass_type, FinishedWork.GlassType.OPTIWHITE)
        self.assertEqual(saved_work.skinali_type, FinishedWork.SkinaliType.PAINT)
        self.assertEqual(saved_work.paint_color, 'RAL 9000')
        self.assertIsNone(saved_work.catalog_image)
        self.assertEqual(
            form.fields['paint_color'].widget.attrs['placeholder'],
            'RAL 9000',
        )

    def test_catalog_relation_is_optional_and_pict_deletion_keeps_work(self):
        self.assertEqual(
            list(self.catalog_image.finished_works.all()),
            [self.work],
        )
        self.assertEqual(
            list(self.work.catalog_image.cat.all()),
            [self.category],
        )

        self.catalog_image.delete()
        self.work.refresh_from_db()

        self.assertIsNone(self.work.catalog_image)
        self.assertTrue(FinishedWork.objects.filter(pk=self.work.pk).exists())

        response = self.client.get(reverse('finished_works'))
        self.assertNotContains(response, 'Номер изображения')
        self.assertNotContains(response, 'finished-work-modal__category')

    def test_public_gallery_shows_modal_fields_and_callback_action(self):
        response = self.client.get(reverse('finished_works'))
        styles = Path(
            settings.BASE_DIR,
            'pict/static/skinali/css/styles.css',
        ).read_text(encoding='utf-8')
        mobile_filters_script = Path(
            settings.BASE_DIR,
            'pict/static/skinali/js/mobile-filters.js',
        ).read_text(encoding='utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['title'], 'Наши работы')
        self.assertContains(response, 'class="finished-works-grid"')
        self.assertContains(response, 'class="finished-work-card__image"')
        self.assertContains(response, 'data-fancybox="finished-works"')
        self.assertContains(response, self.work.photo.url)
        self.assertContains(response, self.work.name)
        self.assertNotContains(response, self.work.description)
        self.assertNotContains(response, 'finished-work-modal__category')
        self.assertContains(response, 'Тип стекла')
        self.assertContains(response, 'Обычное')
        self.assertContains(response, 'Тип скинали')
        self.assertContains(response, 'Печать')
        self.assertContains(response, 'aria-label="Тип скинали"')
        self.assertContains(response, 'src="/static/skinali/js/mobile-filters.js"')
        self.assertIn("'.finished-work-types a'", mobile_filters_script)
        self.assertIn('restoreScrollPosition();', mobile_filters_script)
        self.assertContains(
            response,
            '<li class="page-num page-num-selected" aria-current="page">'
            ' Печать </li>',
            html=True,
        )
        self.assertContains(response, '?skinali_type=paint')
        self.assertContains(response, '?skinali_type=transparent')
        self.assertContains(response, 'aria-label="Категории"')
        self.assertNotContains(response, 'Номер изображения')
        self.assertContains(response, '№ 701')
        self.assertContains(
            response,
            'class="catalog-thumbnail finished-work-modal__catalog-image-link"',
        )
        self.assertContains(
            response,
            f'href="{self.catalog_image.get_absolute_url()}"',
        )
        self.assertContains(response, 'aria-label="Открыть изображение №701"')
        self.assertContains(response, f'alt="{self.catalog_image.alt}"')
        self.assertContains(response, 'class="catalog-favorite-toggle"')
        self.assertContains(
            response,
            f'data-favorite-url="{reverse("favorite_toggle", args=[self.catalog_image.pk])}"',
        )
        self.assertContains(response, 'aria-label="Добавить в избранное"')
        self.assertContains(response, 'Хочу скинали')
        self.assertContains(response, 'data-callback-open')
        self.assertContains(
            response,
            f'data-caption-template="finished-work-caption-{self.work.pk}"',
        )
        self.assertContains(response, 'enableFinishedWorkCallback(slide.contentEl)')
        self.assertNotContains(response, 'class="site-search"')
        self.assertContains(
            response,
            f'href="{reverse("finished_works")}"',
        )
        self.assertIn(
            '.finished-works-grid {\n\tgrid-template-columns: repeat(6, minmax(0, 1fr));',
            styles,
        )
        self.assertIn(
            '.list-pages-color ul .color-option:hover,\n'
            '.list-pages-color ul .color-option:focus-within {\n\tz-index: 10;',
            styles,
        )
        self.assertIn(
            '.finished-work-modal__catalog-preview .catalog-favorite-toggle:hover,\n'
            '.finished-work-modal__catalog-preview '
            '.catalog-favorite-toggle:focus-visible {\n'
            '\tbackground-color: #f2f2f2;',
            styles,
        )
        self.assertIn(
            '.catalog-categories.finished-work-types {\n'
            '\t\tdisplay: block;',
            styles,
        )

    def test_public_gallery_shows_only_the_matching_dependent_field(self):
        painted_work = FinishedWork.objects.create(
            name='Покрашенная кухня',
            photo=create_test_image_file('finished-painted-kitchen.jpg'),
            glass_type=FinishedWork.GlassType.OPTIWHITE,
            skinali_type=FinishedWork.SkinaliType.PAINT,
            paint_color='RAL 9000',
        )
        transparent_work = FinishedWork.objects.create(
            name='Прозрачная кухня',
            photo=create_test_image_file('finished-transparent-kitchen.jpg'),
            glass_type=FinishedWork.GlassType.DIAMANT,
            skinali_type=FinishedWork.SkinaliType.TRANSPARENT,
        )

        printed_response = self.client.get(reverse('finished_works'))
        painted_response = self.client.get(
            reverse('finished_works'),
            {'skinali_type': FinishedWork.SkinaliType.PAINT},
        )
        transparent_response = self.client.get(
            reverse('finished_works'),
            {'skinali_type': FinishedWork.SkinaliType.TRANSPARENT},
        )

        def caption_for(work, response):
            html = response.content.decode()
            start = html.index(f'<template id="finished-work-caption-{work.pk}">')
            end = html.index('</template>', start)
            return html[start:end]

        printed_caption = caption_for(self.work, printed_response)
        painted_caption = caption_for(painted_work, painted_response)
        transparent_caption = caption_for(
            transparent_work,
            transparent_response,
        )

        self.assertNotIn('Номер изображения', printed_caption)
        self.assertIn('finished-work-modal__catalog-image-link', printed_caption)
        self.assertIn('catalog-favorite-toggle', printed_caption)
        self.assertNotIn('Цвет покраски', printed_caption)
        self.assertIn('Optiwhite', painted_caption)
        self.assertIn('Покраска', painted_caption)
        self.assertIn('Цвет покраски', painted_caption)
        self.assertIn('RAL 9000', painted_caption)
        self.assertNotIn('Номер изображения', painted_caption)
        self.assertNotIn('finished-work-modal__catalog-image-link', painted_caption)
        self.assertIn('Diamant', transparent_caption)
        self.assertIn('Прозрачное', transparent_caption)
        self.assertNotIn('Номер изображения', transparent_caption)
        self.assertNotIn('Цвет покраски', transparent_caption)
        self.assertNotIn('finished-work-modal__catalog-image-link', transparent_caption)

    def test_public_gallery_filters_by_skinali_type_and_hides_categories(self):
        painted_works = [
            FinishedWork.objects.create(
                name=f'Покрашенная работа {index}',
                photo=create_test_image_file(
                    f'finished-painted-filter-{index}.jpg'
                ),
                skinali_type=FinishedWork.SkinaliType.PAINT,
                paint_color='RAL 9000',
            )
            for index in range(1, 8)
        ]
        transparent_work = FinishedWork.objects.create(
            name='Прозрачная работа для фильтра',
            photo=create_test_image_file('finished-transparent-filter.jpg'),
            skinali_type=FinishedWork.SkinaliType.TRANSPARENT,
        )

        printed_response = self.client.get(reverse('finished_works'))
        painted_response = self.client.get(
            reverse('finished_works'),
            {'skinali_type': FinishedWork.SkinaliType.PAINT},
        )
        transparent_response = self.client.get(
            reverse('finished_works'),
            {'skinali_type': FinishedWork.SkinaliType.TRANSPARENT},
        )

        self.assertEqual(
            list(printed_response.context['finished_works']),
            [self.work],
        )
        self.assertEqual(
            list(painted_response.context['finished_works']),
            list(reversed(painted_works[-6:])),
        )
        self.assertEqual(
            list(transparent_response.context['finished_works']),
            [transparent_work],
        )
        self.assertEqual(
            painted_response.context['selected_skinali_type'],
            FinishedWork.SkinaliType.PAINT,
        )
        self.assertFalse(
            painted_response.context['show_finished_work_categories']
        )
        self.assertContains(painted_response, 'aria-label="Тип скинали"')
        self.assertContains(
            painted_response,
            '<li class="page-num page-num-selected" aria-current="page">'
            ' Покраска </li>',
            html=True,
        )
        self.assertNotContains(painted_response, 'aria-label="Категории"')
        self.assertNotContains(painted_response, 'mobile-catalog-filters')
        self.assertNotContains(painted_response, 'mobile-filter-dialog')
        self.assertContains(
            painted_response,
            '?page=2&amp;skinali_type=paint',
        )
        self.assertNotContains(transparent_response, 'aria-label="Категории"')
        self.assertNotContains(transparent_response, 'mobile-filter-dialog')

        invalid_response = self.client.get(
            reverse('finished_works'),
            {'skinali_type': 'unknown'},
        )
        self.assertEqual(invalid_response.status_code, 404)

    def test_public_gallery_uses_cached_square_thumbnail(self):
        optimized_work = FinishedWork.objects.create(
            name='Работа с кешированным превью',
            photo=create_test_image_file(
                'finished-work-thumbnail-source.jpg',
                size=(1000, 1000),
            ),
        )

        response = self.client.get(reverse('finished_works'))
        html = response.content.decode()
        thumbnail_url_start = html.index('/media/cache/thumbnails/')
        thumbnail_url_end = html.index('"', thumbnail_url_start)
        thumbnail_url = html[thumbnail_url_start:thumbnail_url_end]
        thumbnail_path = Path(settings.MEDIA_ROOT) / thumbnail_url.removeprefix(
            settings.MEDIA_URL
        )

        self.assertContains(response, f'href="{optimized_work.photo.url}"')
        self.assertContains(response, f'src="{thumbnail_url}"')
        self.assertContains(response, 'width="760"')
        self.assertContains(response, 'height="760"')
        self.assertContains(response, 'loading="lazy"')
        self.assertContains(response, 'decoding="async"')
        self.assertNotEqual(thumbnail_url, optimized_work.photo.url)
        self.assertTrue(thumbnail_path.exists())

        with Image.open(thumbnail_path) as thumbnail:
            self.assertEqual(thumbnail.size, (760, 760))

        initial_mtime = thumbnail_path.stat().st_mtime_ns
        repeated_response = self.client.get(reverse('finished_works'))

        self.assertContains(repeated_response, f'src="{thumbnail_url}"')
        self.assertEqual(thumbnail_path.stat().st_mtime_ns, initial_mtime)

    def test_public_gallery_is_sorted_by_novelty_and_paginated_by_six(self):
        newer_works = [
            FinishedWork.objects.create(
                name=f'Работа {index}',
                photo=create_test_image_file(f'finished-work-{index}.jpg'),
            )
            for index in range(1, 7)
        ]

        first_page = self.client.get(reverse('finished_works'))
        second_page = self.client.get(reverse('finished_works'), {'page': 2})

        self.assertEqual(
            list(first_page.context['finished_works']),
            list(reversed(newer_works)),
        )
        self.assertEqual(
            list(second_page.context['finished_works']),
            [self.work],
        )
        self.assertEqual(first_page.context['paginator'].per_page, 6)
        self.assertContains(first_page, 'class="list-pages catalog-pagination"')
        self.assertContains(first_page, 'aria-current="page"')
        self.assertContains(first_page, '?page=2')

    def test_unpublished_work_is_hidden_from_gallery_and_homepage(self):
        hidden_work = FinishedWork.objects.create(
            name='Скрытая готовая работа',
            photo='finished_works/hidden.jpg',
            is_published=False,
        )

        gallery_response = self.client.get(reverse('finished_works'))
        home_response = self.client.get(reverse('home'))

        self.assertNotIn(hidden_work, gallery_response.context['finished_works'])
        self.assertNotIn(hidden_work, home_response.context['recent_finished_works'])
        self.assertNotContains(gallery_response, hidden_work.photo.url)
        self.assertNotContains(home_response, hidden_work.photo.url)

    def test_public_gallery_filters_by_catalog_category_and_keeps_it_in_pagination(self):
        other_category = Category.objects.create(
            cat='Природа',
            slug='nature',
        )
        other_catalog_image = Pict.objects.create(
            name=703,
            alt='Изображение другой категории',
            photo=create_test_image_file('703.jpg'),
        )
        other_catalog_image.cat.add(other_category)
        other_work = FinishedWork.objects.create(
            name='Работа другой категории',
            photo='finished_works/other-category.jpg',
            catalog_image=other_catalog_image,
        )
        unlinked_work = FinishedWork.objects.create(
            name='Работа без изображения каталога',
            photo='finished_works/unlinked.jpg',
        )
        filtered_works = [
            FinishedWork.objects.create(
                name=f'Архитектурная работа {index}',
                photo=create_test_image_file(
                    f'finished-architecture-{index}.jpg'
                ),
                catalog_image=self.catalog_image,
            )
            for index in range(1, 7)
        ]

        first_page = self.client.get(
            reverse('finished_works'),
            {'category': self.category.slug},
        )
        second_page = self.client.get(
            reverse('finished_works'),
            {'category': self.category.slug, 'page': 2},
        )

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_page.context['selected_category'], self.category)
        self.assertEqual(
            list(first_page.context['finished_works']),
            list(reversed(filtered_works)),
        )
        self.assertEqual(list(second_page.context['finished_works']), [self.work])
        self.assertNotIn(other_work, first_page.context['finished_works'])
        self.assertNotIn(unlinked_work, first_page.context['finished_works'])
        self.assertContains(
            first_page,
            '<li class="page-num page-num-selected">Архитектура</li>',
            html=True,
        )
        self.assertContains(first_page, 'class="mobile-filter-dialog"')
        self.assertContains(
            first_page,
            'src="/static/skinali/js/mobile-filters.js"',
        )
        self.assertContains(first_page, '?page=2&amp;category=architecture')

        missing_category = self.client.get(
            reverse('finished_works'),
            {'category': 'missing-category'},
        )
        self.assertEqual(missing_category.status_code, 404)

    def test_admin_uses_compact_previews_and_shows_linked_works_on_pict(self):
        site = AdminSite()
        finished_work_admin = FinishedWorkAdmin(FinishedWork, site)
        pict_admin = PictAdmin(Pict, site)

        list_preview = str(finished_work_admin.get_html_photo(self.work))
        form_preview = str(finished_work_admin.get_html_photo_fields(self.work))
        linked_works = str(pict_admin.get_finished_works(self.catalog_image))

        self.assertIn('width="80"', list_preview)
        self.assertIn('width="200"', form_preview)
        self.assertIn('data-image-preview', list_preview)
        self.assertIn('data-image-preview', form_preview)
        self.assertEqual(
            finished_work_admin.get_html_photo_fields.short_description,
            'Миниатюра',
        )
        self.assertIs(finished_work_admin.form, FinishedWorkAdminForm)
        self.assertIn('glass_type', finished_work_admin.list_display)
        self.assertIn('skinali_type', finished_work_admin.list_display)
        self.assertNotIn('get_catalog_image_number', finished_work_admin.list_display)
        self.assertNotIn('get_catalog_categories', finished_work_admin.list_display)
        self.assertIn('glass_type', finished_work_admin.list_filter)
        self.assertIn('skinali_type', finished_work_admin.list_filter)
        pict_fields = [
            field
            for _, options in pict_admin.get_fieldsets(None, self.catalog_image)
            for field in options['fields']
        ]
        self.assertIn('get_finished_works', pict_fields)
        self.assertIn('width="160"', linked_works)
        self.assertIn('data-image-preview', linked_works)
        self.assertIn(self.work.photo.url, linked_works)

        image_without_works = Pict.objects.create(
            name=702,
            alt='Изображение без готовых работ',
            photo=create_test_image_file('702.jpg'),
        )
        pict_fields_without_works = [
            field
            for _, options in pict_admin.get_fieldsets(None, image_without_works)
            for field in options['fields']
        ]
        self.assertNotIn('get_finished_works', pict_fields_without_works)

        admin_user = get_user_model().objects.create_superuser(
            username='admin-preview-test',
            email='admin@example.com',
            password='test-password',
        )
        self.client.force_login(admin_user)

        linked_response = self.client.get(reverse(
            'admin:pict_pict_change',
            args=[self.catalog_image.pk],
        ))
        unlinked_response = self.client.get(reverse(
            'admin:pict_pict_change',
            args=[image_without_works.pk],
        ))
        finished_work_response = self.client.get(reverse(
            'admin:pict_finishedwork_change',
            args=[self.work.pk],
        ))

        self.assertEqual(linked_response.status_code, 200)
        self.assertContains(linked_response, 'field-get_finished_works')
        self.assertContains(linked_response, self.work.photo.url)
        self.assertContains(linked_response, 'skinali/js/admin-image-preview.js')
        self.assertContains(linked_response, 'skinali/css/admin-image-preview.css')
        self.assertEqual(unlinked_response.status_code, 200)
        self.assertNotContains(unlinked_response, 'field-get_finished_works')
        self.assertEqual(finished_work_response.status_code, 200)
        self.assertContains(finished_work_response, 'Тип стекла')
        self.assertContains(finished_work_response, 'Тип скинали')
        self.assertContains(finished_work_response, 'Цвет покраски')
        self.assertContains(finished_work_response, 'placeholder="RAL 9000"')
        self.assertContains(
            finished_work_response,
            'skinali/js/admin-finished-work.js',
        )
        self.assertContains(
            finished_work_response,
            'skinali/js/admin-image-preview.js',
        )

        conditional_script = Path(
            settings.BASE_DIR,
            'pict/static/skinali/js/admin-finished-work.js',
        ).read_text(encoding='utf-8')
        self.assertIn("selectedType === 'print'", conditional_script)
        self.assertIn("selectedType === 'paint'", conditional_script)
        self.assertIn('field.disabled = !visible', conditional_script)


class IntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_superuser('integration-owner', password='test-password')
        cls.staff = get_user_model().objects.create_user('integration-staff', is_staff=True)
        cls.staff.user_permissions.set(Permission.objects.filter(content_type__model__in=['integration', 'integrationrevision']))

    def setUp(self):
        self.integration = Integration(name='Метрика', is_enabled=True,
                                       head_html='<script>window.integrationHead = "{{ title }}";</script>',
                                       body_start_html='<div id="integration-start"></div>',
                                       body_end_html='<script>window.integrationEnd = true;</script>')
        self.integration.save_with_revision(self.owner, 'Создание')

    def test_slots_render_raw_code_once_without_evaluating_django_templates(self):
        html = self.client.get(reverse('about')).content.decode()
        head = self.integration.head_html
        start = self.integration.body_start_html
        end = self.integration.body_end_html
        for fragment in (head, start, end):
            self.assertEqual(html.count(fragment), 1)
        self.assertLess(html.index(head), html.index('</head>'))
        self.assertLess(html.index('<body>'), html.index(start))
        self.assertLess(html.index(start), html.index('<header'))
        self.assertLess(html.index(end), html.index('</body>'))
        self.assertGreater(html.index(end), html.index('</footer>'))

    def test_path_scope_query_parameters_and_immediate_disable(self):
        self.integration.page_paths = '/about/'
        self.integration.save_with_revision(self.owner)
        self.assertContains(self.client.get('/about/?source=test'), self.integration.head_html)
        self.assertNotContains(self.client.get('/'), self.integration.head_html)
        self.integration.is_enabled = False
        self.integration.save_with_revision(self.owner)
        self.assertNotContains(self.client.get('/about/'), self.integration.head_html)

    def test_render_uses_one_query_and_stable_order(self):
        Integration.objects.create(name='Раньше', is_enabled=True, position=0, head_html='FIRST')
        self.integration.position = 10
        self.integration.save_with_revision(self.owner)
        request = RequestFactory().get('/about/')
        template = Template('{% load integrations %}{% site_integrations as items %}'
                            '{% for item in items %}{{ item.head_html|safe }}{% endfor %}'
                            '{% for item in items %}{{ item.body_end_html|safe }}{% endfor %}')
        with self.assertNumQueries(1):
            html = template.render(RequestContext(request))
        self.assertTrue(html.startswith('FIRST'))

    def test_form_rejects_invalid_paths_and_empty_enabled_integration(self):
        data = {field: getattr(self.integration, field) for field in Integration.SNAPSHOT_FIELDS}
        for path in ('https://example.com/', '//example.com/', '/about/?q=1', '/about/#x', '/skinali/*', '/bad path'):
            with self.subTest(path=path):
                form = IntegrationAdminForm(data={**data, 'page_paths': path})
                self.assertFalse(form.is_valid())
                self.assertIn('page_paths', form.errors)
        form = IntegrationAdminForm(data={**data, 'page_paths': ' /about/\n/about/\n/designer '})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.instance.page_paths, '/about/\n/designer')
        form = IntegrationAdminForm(data={**data, 'head_html': '', 'body_start_html': '', 'body_end_html': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('is_enabled', form.errors)

    def test_admin_save_records_author_and_escapes_code(self):
        self.client.force_login(self.owner)
        code = '</textarea><script>window.adminInjection = true;</script>'
        data = {field: getattr(self.integration, field) for field in Integration.SNAPSHOT_FIELDS}
        url = reverse('admin:pict_integration_change', args=[self.integration.pk])
        response = self.client.post(url, {**data, 'head_html': code, '_save': 'Сохранить'})
        self.assertEqual(response.status_code, 302)
        revision = self.integration.revisions.first()
        self.assertEqual(revision.author, self.owner)
        self.assertEqual(revision.snapshot['head_html'], code)
        for page in (url, reverse('admin:pict_integrationrevision_change', args=[revision.pk]),
                     reverse('admin:pict_integrationrevision_restore', args=[revision.pk])):
            response = self.client.get(page)
            self.assertContains(response, escape(code))
            self.assertNotContains(response, code)
        self.assertNotContains(self.client.get(reverse('admin:index')), self.integration.body_end_html)
        self.assertEqual(self.client.get(reverse('admin:pict_integrationrevision_changelist') +
                                        f'?integration__id__exact={self.integration.pk}').status_code, 200)

    def test_regular_staff_cannot_read_write_or_restore_even_with_model_permissions(self):
        self.client.force_login(self.staff)
        revision = self.integration.revisions.first()
        urls = [reverse('admin:pict_integration_changelist'), reverse('admin:pict_integration_add'),
                reverse('admin:pict_integration_change', args=[self.integration.pk]),
                reverse('admin:pict_integrationrevision_changelist'),
                reverse('admin:pict_integrationrevision_change', args=[revision.pk]),
                reverse('admin:pict_integrationrevision_restore', args=[revision.pk])]
        for url in urls:
            for method in ('get', 'post'):
                with self.subTest(url=url, method=method):
                    self.assertEqual(getattr(self.client, method)(url).status_code, 403)
        self.assertNotContains(self.client.get(reverse('admin:index')), 'Интеграции')

    def test_restore_requires_csrf_and_post_and_creates_new_revision(self):
        original = self.integration.revisions.first()
        self.integration.name = 'Новая версия'
        self.integration.is_enabled = False
        self.integration.save_with_revision(self.owner)
        secure_client = Client(enforce_csrf_checks=True)
        secure_client.force_login(self.owner)
        url = reverse('admin:pict_integrationrevision_restore', args=[original.pk])
        self.assertEqual(secure_client.get(url).status_code, 200)
        self.assertEqual(self.integration.revisions.count(), 2)
        self.assertEqual(secure_client.post(url).status_code, 403)
        response = secure_client.post(url, {'csrfmiddlewaretoken': secure_client.cookies['csrftoken'].value})
        self.assertEqual(response.status_code, 302)
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.name, 'Метрика')
        self.assertTrue(self.integration.is_enabled)
        self.assertEqual(self.integration.revisions.count(), 3)
        self.assertEqual(self.integration.revisions.first().snapshot, original.snapshot)

    def test_revision_write_failure_rolls_back_settings(self):
        self.integration.name = 'Не должно сохраниться'
        with patch('pict.models.IntegrationRevision.objects.create', side_effect=RuntimeError('failure')):
            with self.assertRaises(RuntimeError):
                self.integration.save_with_revision(self.owner)
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.name, 'Метрика')
        self.assertEqual(self.integration.revisions.count(), 1)
