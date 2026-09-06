import time
from datetime import timedelta
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import requests
from PIL import Image
from django.conf import settings
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.template import RequestContext, Template
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from .admin import (
    ContactRequestAdmin,
    ContactRequestDeliveryInline,
    FinishedWorkAdmin,
    PictAdmin,
)
from .forms import (
    CONTACT_FORM_TOKEN_SALT,
    BaseContactForm,
    CallbackContactForm,
    EmailCommentContactForm,
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
    TagPict,
)


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


class PopularTagsByCategoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first_category = Category.objects.create(cat='Первая', slug='first')
        cls.second_category = Category.objects.create(cat='Вторая', slug='second')
        cls.selected_color = Color.objects.create(color='Красный', slug_color='red')

        cls.first_tag = TagPict.objects.create(tag='Первый тег', slug='first-tag')
        cls.second_tag = TagPict.objects.create(tag='Второй тег', slug='second-tag')
        cls.cross_category_tag = TagPict.objects.create(tag='Общий тег', slug='cross-category-tag')

        first_category_pictures = cls.create_pictures(cls.first_category, 100, 3)
        second_category_pictures = cls.create_pictures(cls.second_category, 200, 3)

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

    def test_category_contains_only_its_tags_sorted_and_limited_to_ten(self):
        response = self.client.get(
            reverse('skinali', kwargs={'slug_cat': self.first_category.slug})
        )

        tags = list(response.context['list_tag'])
        totals = [tag.total for tag in tags]

        self.assertEqual(len(tags), 10)
        self.assertEqual(totals, sorted(totals, reverse=True))
        self.assertEqual(tags[0].slug, self.first_tag.slug)
        self.assertEqual(tags[0].total, 3)
        self.assertEqual(tags[1].slug, self.cross_category_tag.slug)
        self.assertEqual(tags[1].total, 2)
        self.assertTrue(any(tag.total == 1 for tag in tags))
        self.assertNotIn(self.second_tag.slug, {tag.slug for tag in tags})
        self.assertContains(response, f'>{self.first_tag.tag}</a>', html=False)
        self.assertNotContains(response, f'{self.first_tag.tag} ({tags[0].total})')
        self.assertContains(response, 'data-fancybox="catalog-gallery"')
        self.assertContains(response, 'data-caption-template="catalog-gallery-caption-')
        self.assertContains(response, 'class="catalog-modal__title"')
        self.assertContains(response, 'Описание изображения 100')
        self.assertContains(response, '<span>#Первый тег</span>', html=True)
        self.assertContains(response, '<dd>№100</dd>', html=True)
        self.assertContains(response, self.first_category.cat)
        self.assertContains(response, 'class="catalog-modal__nav catalog-modal__nav--prev"')
        self.assertContains(response, 'class="catalog-modal__nav catalog-modal__nav--next"')
        self.assertNotContains(response, 'catalog-modal__counter')
        self.assertContains(response, 'data-favorite-toggle')
        self.assertContains(response, 'class="catalog-modal__purchase"')
        self.assertContains(response, 'data-image-purchase-open')
        self.assertContains(response, 'data-image-number="100"')
        self.assertContains(
            response,
            f'<a href="{reverse("skinali")}">Все</a>',
            html=True,
        )

    def test_all_catalog_keeps_global_counts_and_ten_tag_limit(self):
        response = self.client.get(reverse('skinali'))

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
        self.assertNotContains(response, 'Сбросить цвет')
        self.assertContains(response, 'placeholder="Поиск, например море"')
        self.assertContains(response, 'skinali/css/styles.css?v=61')
        self.assertContains(response, 'skinali/images/logo_skinali.png', count=2)
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
        self.assertContains(response, 'Популярные запросы:')
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
        self.assertContains(response, 'skinali/js/site-menu.js?v=3')
        self.assertContains(response, 'data-mobile-filter-open="mobile-category-filter"')
        self.assertContains(response, 'data-mobile-filter-open="mobile-color-filter"')
        self.assertContains(response, 'id="mobile-category-filter"')
        self.assertContains(response, 'id="mobile-color-filter"')
        self.assertContains(response, 'mobile-catalog-filters__chevron')
        self.assertContains(response, 'skinali/js/mobile-filters.js?v=1')
        self.assertContains(response, 'data-catalog-favorite-toggle')
        self.assertContains(response, 'skinali/images/icon-favorite-inactive.png')
        self.assertContains(response, 'skinali/images/icon-favorite-active.png')

    def test_homepage_shows_hero_and_search_results_replace_it(self):
        finished_works = [
            FinishedWork.objects.create(
                name=f'Готовая работа {index}',
                description=f'Описание готовой работы {index}',
                photo=f'finished_works/home-work-{index}.jpg',
            )
            for index in range(1, 5)
        ]
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="home-hero"')
        self.assertContains(response, 'Скинали из')
        self.assertContains(response, 'Заказать скинали')
        self.assertContains(response, 'Выбрать изображение')
        self.assertContains(response, 'skinali/images/odium-hero-glass-v2.jpg')
        self.assertContains(response, 'class="home-offers"')
        self.assertContains(response, 'Больше возможностей')
        self.assertContains(response, 'class="home-offer-card"', count=3)
        self.assertContains(response, 'skinali/images/home-offer-designer.jpg')
        self.assertContains(response, 'skinali/images/home-offer-hood.jpg')
        self.assertContains(response, 'skinali/images/home-offer-lighting.jpg')
        self.assertContains(response, 'class="home-benefits"')
        self.assertContains(response, 'Почему стекло')
        self.assertContains(response, 'class="home-benefit-card"', count=6)
        self.assertContains(response, 'skinali/images/home-benefit-strength.jpg')
        self.assertContains(response, 'skinali/images/home-benefit-variants.jpg')
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
        search_response = self.client.get(
            reverse('home'),
            {'product-number': picture.name},
        )

        self.assertEqual(search_response.status_code, 200)
        self.assertNotContains(search_response, 'class="home-hero"')
        self.assertNotContains(search_response, 'class="home-offers"')
        self.assertNotContains(search_response, 'class="home-benefits"')
        self.assertNotContains(search_response, 'class="home-recent-works"')
        self.assertContains(search_response, f'Введенные слова: {picture.name}')
        self.assertContains(search_response, '<h1>Результаты поиска</h1>')
        self.assertContains(search_response, 'data-search-back')
        self.assertContains(search_response, 'data-fancybox="catalog-gallery"')

        # Пустая выдача должна работать и для короткого текстового запроса.
        for query in ('я', 'несуществующий-запрос-xyz'):
            with self.subTest(query=query):
                response = self.client.get(reverse('home'), {'product-number': query})
                self.assertContains(response, '<p>По запросу ничего не найдено</p>')
                self.assertContains(response, f'Введенные слова: {query}')
                self.assertNotContains(response, '<div class="container')

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
        self.assertContains(response, 'mobile-filter-dialog__item is-selected')
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
        self.assertContains(response, 'Сбросить цвет')
        self.assertNotContains(response, 'сброс цветов')
        self.assertNotContains(
            response,
            'class="page-num page-num-selected" style="background-color: red;"',
        )

    def test_category_links_have_no_color_parameter_when_color_is_not_selected(self):
        response = self.client.get(
            reverse('skinali', kwargs={'slug_cat': self.first_category.slug})
        )

        self.assertContains(
            response,
            f'<a href="{self.second_category.get_absolute_url()}">{self.second_category.cat}</a>',
            html=True,
        )


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
        self.assertIn('is_published', pict_admin.fields)
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
            reverse('home'),
            {'product-number': self.hidden_picture.name},
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

    def test_menu_modal_and_contact_page_form_use_shared_markup(self):
        home_response = self.client.get(reverse('home'))
        contact_response = self.client.get(reverse('about'))

        self.assertContains(home_response, 'class="mainmenu__callback-button"')
        self.assertContains(home_response, 'Перезвоните мне')
        self.assertContains(home_response, 'id="callback-dialog"')
        self.assertContains(home_response, 'id="image-purchase-dialog"')
        self.assertContains(home_response, 'Купить изображение №')
        self.assertContains(home_response, 'name="image_purchase-pict_id"')
        self.assertContains(home_response, 'data-image-purchase-pict')
        self.assertContains(home_response, 'name="image_purchase-email"')
        self.assertContains(home_response, 'maxlength="50"')
        self.assertContains(home_response, 'id="contact-success-dialog"')
        self.assertContains(home_response, 'skinali/js/contact-forms.js?v=2')
        self.assertLess(
            home_response.content.find(b'mainmenu__favorites'),
            home_response.content.find(b'mainmenu__callback'),
        )
        self.assertContains(contact_response, 'class="contact-request-card"')
        self.assertContains(contact_response, 'Остались вопросы?')
        self.assertContains(contact_response, 'name="question-question"')
        self.assertContains(contact_response, 'maxlength="250"')
        self.assertContains(contact_response, 'name="question-website"')
        self.assertContains(contact_response, 'id="email-message-title"')
        self.assertContains(contact_response, 'name="email_message-email"')
        self.assertContains(contact_response, 'type="email"')
        self.assertContains(contact_response, 'name="email_message-comment"')
        self.assertContains(contact_response, 'name="email_message-website"')

    def test_valid_ajax_post_saves_callback_request(self):
        response = self.client.post(
            reverse('contact_submit'),
            self.callback_data(),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'ok': True,
            'message': 'Спасибо! Мы получили заявку и скоро свяжемся с вами',
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
            'message': 'Спасибо! Заявка на покупку изображения принята',
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
        self.assertIn(f'Новая заявка № {delivery.contact_request_id}', request_payload['text'])
        self.assertIn('Телефон: +375 29 111-22-33', request_payload['text'])
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
        self.assertIn('Тип: Сообщение по email', message)
        self.assertIn('Email: elena@example.com', message)
        self.assertIn('Комментарий: Хочу уточнить стоимость.', message)
        self.assertNotIn('Телефон:', message)

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
        self.assertIn('Тип: Покупка изображения', message)
        self.assertIn('Email: buyer@example.com', message)
        self.assertIn('Комментарий: Хочу купить оригинал.', message)
        self.assertIn('Изображение: №127', message)

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
        self.assertContains(response, '<strong>30</strong> BYN', html=True)
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

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['favorite_pictures'],
            [self.second_picture, self.first_picture],
        )
        self.assertContains(response, 'Изображение № 301')
        self.assertContains(response, self.first_picture.alt)
        self.assertContains(response, 'data-favorite-row')
        self.assertContains(response, 'class="favorite-card__preview"')
        self.assertContains(response, 'data-fancybox="catalog-gallery"')
        self.assertContains(response, 'data-caption-template="catalog-gallery-caption-')
        self.assertContains(response, 'class="catalog-modal__title"')
        self.assertContains(response, 'class="catalog-modal__favorite is-active"')
        self.assertContains(response, 'class="catalog-modal__purchase"')
        self.assertContains(response, 'data-image-purchase-open')
        self.assertContains(response, '#Тег избранного')
        self.assertContains(response, 'Категория избранного')
        self.assertNotContains(response, 'class="catalog-favorite-toggle')

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
        self.assertContains(response, 'enableCatalogCaptionSelection(caption)')
        self.assertContains(response, "caption.addEventListener('mousedown', stopImageNavigation)")
        self.assertContains(response, "document.getElementById(templateId)")
        self.assertContains(response, 'updateFavoritesMenu(result.favorites_count)')
        self.assertContains(response, "document.querySelectorAll('[data-favorites-menu]')")
        self.assertContains(response, 'slide.captionEl || fancybox.caption')
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
            photo='finished_works/kitchen.jpg',
            catalog_image=cls.catalog_image,
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
        self.assertNotContains(response, 'Изображение №')
        self.assertNotContains(response, 'finished-work-modal__category')

    def test_public_gallery_shows_name_and_linked_catalog_number(self):
        response = self.client.get(reverse('finished_works'))
        styles = Path(
            settings.BASE_DIR,
            'pict/static/skinali/css/styles.css',
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
        self.assertContains(response, 'Изображение № 701')
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

    def test_public_gallery_is_sorted_by_novelty_and_paginated_by_six(self):
        newer_works = [
            FinishedWork.objects.create(
                name=f'Работа {index}',
                photo=f'finished_works/work-{index}.jpg',
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
                photo=f'finished_works/architecture-{index}.jpg',
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
        self.assertContains(first_page, 'skinali/js/mobile-filters.js?v=1')
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
        self.assertIn('get_finished_works', pict_admin.get_fields(None, self.catalog_image))
        self.assertIn('width="160"', linked_works)
        self.assertIn('data-image-preview', linked_works)
        self.assertIn(self.work.photo.url, linked_works)

        image_without_works = Pict.objects.create(
            name=702,
            photo=create_test_image_file('702.jpg'),
        )
        self.assertNotIn(
            'get_finished_works',
            pict_admin.get_fields(None, image_without_works),
        )

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

        self.assertEqual(linked_response.status_code, 200)
        self.assertContains(linked_response, 'field-get_finished_works')
        self.assertContains(linked_response, self.work.photo.url)
        self.assertContains(linked_response, 'skinali/js/admin-image-preview.js')
        self.assertContains(linked_response, 'skinali/css/admin-image-preview.css')
        self.assertEqual(unlinked_response.status_code, 200)
        self.assertNotContains(unlinked_response, 'field-get_finished_works')


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
