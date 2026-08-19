from django.test import Client, TestCase
from django.urls import reverse

from .models import Category, Color, Pict, TagPict


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
        self.assertContains(response, 'skinali/css/styles.css?v=20')
        self.assertContains(response, 'skinali/images/odium_logo.png')
        self.assertContains(
            response,
            'Режим работы: пн-вс 10.00 - 21.00 (прием заказов)',
        )
        self.assertContains(response, 'class="site-topbar"')
        self.assertContains(response, 'href="tel:+375291498838"')
        self.assertContains(response, 'data-mobile-menu-open')
        self.assertContains(response, 'id="mobile-site-menu"')
        self.assertContains(response, 'data-mobile-menu-close')
        self.assertContains(response, 'skinali/images/menu.png')
        self.assertContains(response, 'skinali/js/site-menu.js?v=1')
        self.assertContains(response, 'data-mobile-filter-open="mobile-category-filter"')
        self.assertContains(response, 'data-mobile-filter-open="mobile-color-filter"')
        self.assertContains(response, 'id="mobile-category-filter"')
        self.assertContains(response, 'id="mobile-color-filter"')
        self.assertContains(response, 'mobile-catalog-filters__chevron')
        self.assertContains(response, 'skinali/js/mobile-filters.js?v=1')

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
            count=2,
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
