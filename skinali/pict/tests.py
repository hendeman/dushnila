from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .admin import FinishedWorkAdmin, PictAdmin
from .models import Category, Color, FinishedWork, Pict, TagPict


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
                photo=f'photos/{start_name + offset}.jpg',
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
        self.assertContains(response, 'data-fancybox="gallery"')
        self.assertContains(response, 'gallery-modal__description')
        self.assertContains(response, 'gallery-modal__number')
        self.assertContains(response, 'data-favorite-toggle')
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
        self.assertContains(response, 'skinali/css/styles.css?v=33')
        self.assertContains(response, 'class="site-header__logo-mark"')
        self.assertContains(response, '<strong>ДИУМ</strong>', count=2, html=True)
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
        self.assertContains(response, '<main class="site-content">')
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
        self.assertContains(response, 'skinali/js/site-menu.js?v=2')
        self.assertContains(response, 'data-mobile-filter-open="mobile-category-filter"')
        self.assertContains(response, 'data-mobile-filter-open="mobile-color-filter"')
        self.assertContains(response, 'id="mobile-category-filter"')
        self.assertContains(response, 'id="mobile-color-filter"')
        self.assertContains(response, 'mobile-catalog-filters__chevron')
        self.assertContains(response, 'skinali/js/mobile-filters.js?v=1')
        self.assertContains(response, 'data-catalog-favorite-toggle')
        self.assertContains(response, 'skinali/images/icon-favorite-inactive.png')
        self.assertContains(response, 'skinali/images/icon-favorite-active.png')

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


class SessionFavoritesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first_picture = Pict.objects.create(
            name=301,
            alt='Первое описание',
            photo='photos/301.jpg',
        )
        cls.second_picture = Pict.objects.create(
            name=302,
            alt='Второе описание',
            photo='photos/302.jpg',
        )

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
        self.assertContains(response, 'data-fancybox="gallery"')

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
        self.assertContains(response, 'favorite-toggle__label-add">В избранное</span>')
        self.assertContains(response, 'class="catalog-favorite-toggle is-active"')
        self.assertContains(response, 'aria-label="Удалить из избранного"')
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
            photo='photos/701.jpg',
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
        self.assertNotContains(response, self.category.cat)

    def test_public_gallery_shows_photo_and_linked_catalog_metadata(self):
        response = self.client.get(reverse('finished_works'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['title'], 'Наши работы')
        self.assertContains(response, 'class="finished-works-grid"')
        self.assertContains(response, 'class="finished-work-card__image"')
        self.assertContains(response, 'data-fancybox="finished-works"')
        self.assertContains(response, self.work.photo.url)
        self.assertContains(response, self.work.description)
        self.assertContains(response, self.category.cat)
        self.assertContains(response, 'Изображение № 701')
        self.assertNotContains(response, 'class="site-search"')
        self.assertContains(
            response,
            f'href="{reverse("finished_works")}"',
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
            photo='photos/702.jpg',
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
