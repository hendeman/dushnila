from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib.messages import get_messages
from django.core import signing
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Pict
from .services.favorites import (
    FAVORITES_IMPORT_LIMIT_MESSAGE,
    FAVORITES_LIMIT_MESSAGE,
    FAVORITES_PENDING_ADDED_SESSION_KEY,
    FAVORITES_PENDING_IMPORT_SESSION_KEY,
    FAVORITES_SESSION_KEY,
    FAVORITES_SHARE_SALT,
    MAX_FAVORITES,
    MAX_SHARE_TOKEN_LENGTH,
    build_favorites_share_url,
    read_favorites_share_token,
)
from .tests import create_test_image_file


class FavoritesSharingTests(TestCase):
    @classmethod
    def setUpClass(cls):
        media = TemporaryDirectory()
        cls.addClassCleanup(media.cleanup)
        media_settings = override_settings(MEDIA_ROOT=media.name)
        media_settings.enable()
        cls.addClassCleanup(media_settings.disable)
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        cls.pictures = [
            Pict.objects.create(
                name=8000 + index,
                alt=f'Изображение подборки {index}',
                photo=create_test_image_file(f'favorite-{index}.jpg'),
            )
            for index in range(MAX_FAVORITES + 5)
        ]
        cls.picture_ids = [picture.pk for picture in cls.pictures]

    def seed_favorites(self, ids, client=None):
        client = client or self.client
        session = client.session
        session[FAVORITES_SESSION_KEY] = ids
        session.save()
        client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

    def share_token(self, ids):
        return parse_qs(urlparse(build_favorites_share_url(ids)).query)['data'][0]

    def signed_payload(self, payload, salt=FAVORITES_SHARE_SALT):
        return signing.Signer(salt=salt).sign_object(payload, compress=True)

    def toggle(self, pict_id):
        return self.client.post(reverse('favorite_toggle', args=[pict_id]))

    def import_ids(self, ids, client=None):
        return (client or self.client).post(
            reverse('favorites_shared'), {'data': self.share_token(ids)},
        )

    def test_last_allowed_image_and_first_over_limit(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 1])
        self.assertEqual(self.toggle(self.picture_ids[MAX_FAVORITES - 1]).status_code, 200)

        response = self.toggle(self.picture_ids[MAX_FAVORITES])

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['message'], FAVORITES_LIMIT_MESSAGE)
        self.assertEqual(response.json()['code'], 'favorites_full')
        self.assertFalse(response.json()['is_favorite'])
        self.assertEqual(response.json()['favorites_count'], MAX_FAVORITES)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[:MAX_FAVORITES])

    def test_full_favorites_allow_removing_then_adding(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES])
        self.assertEqual(self.toggle(self.picture_ids[0]).status_code, 200)
        response = self.toggle(self.picture_ids[MAX_FAVORITES])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['favorites_count'], MAX_FAVORITES)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[1:MAX_FAVORITES + 1])

    def test_unpublished_favorite_does_not_take_a_slot(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES])
        Pict.objects.filter(pk=self.picture_ids[0]).update(is_published=False)
        response = self.toggle(self.picture_ids[MAX_FAVORITES])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[1:MAX_FAVORITES + 1])

    def test_old_oversized_session_preserves_selection_and_allows_removal(self):
        self.seed_favorites(self.picture_ids)
        response = self.client.get(reverse('favorites'))
        self.assertEqual(response.context['favorite_ids'], self.picture_ids)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids)
        self.assertEqual(response.context['favorites_share_url'], '')
        self.assertContains(response, FAVORITES_IMPORT_LIMIT_MESSAGE)
        for pict_id in self.picture_ids[:-MAX_FAVORITES]:
            removed = self.toggle(pict_id)
            self.assertEqual(removed.status_code, 200)
        self.assertTrue(removed.json()['favorites_share_url'])
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[-MAX_FAVORITES:])

    def test_session_normalization_ignores_invalid_and_duplicate_ids(self):
        self.seed_favorites([
            str(self.picture_ids[0]), self.picture_ids[0], None, 'bad',
            -1, True, 2**100, self.picture_ids[1],
        ])
        response = self.client.get(reverse('favorites'))
        self.assertEqual(response.context['favorite_ids'], self.picture_ids[:2])

    def test_summary_shows_limit_and_current_count(self):
        for count in [0, 1]:
            with self.subTest(count=count):
                self.seed_favorites(self.picture_ids[:count])
                page = self.client.get(reverse('favorites'))
                self.assertContains(page,
                    f'<p class="favorites-notice">В избранное можно добавить не более {MAX_FAVORITES} изображений. '
                    f'Всего добавлено изображений: <span data-favorites-current-count>{count}</span></p>',
                    html=True,
                )

    @override_settings(
        PUBLIC_SITE_ORIGIN='https://odium.by',
        ALLOWED_HOSTS=['testserver', 'other.example'],
    )
    def test_share_url_is_signed_snapshot_using_configured_origin(self):
        self.seed_favorites(self.picture_ids[:2])
        response = self.client.get(reverse('favorites'), HTTP_HOST='other.example')
        share_url = response.context['favorites_share_url']
        self.assertTrue(share_url.startswith('https://odium.by/favorites/shared/?data='))
        token = parse_qs(urlparse(share_url).query)['data'][0]
        self.assertEqual(read_favorites_share_token(token), self.picture_ids[:2])
        self.assertContains(response, 'data-share-url=')

    def test_share_url_updates_after_each_toggle_and_is_empty_after_last_removal(self):
        first = self.toggle(self.picture_ids[0]).json()
        second = self.toggle(self.picture_ids[1]).json()
        self.assertNotEqual(first['favorites_share_url'], second['favorites_share_url'])
        token = parse_qs(urlparse(second['favorites_share_url']).query)['data'][0]
        self.assertEqual(read_favorites_share_token(token), self.picture_ids[:2])
        self.toggle(self.picture_ids[0])
        self.assertEqual(self.toggle(self.picture_ids[1]).json()['favorites_share_url'], '')

    def test_share_get_does_not_import_and_contains_automatic_csrf_form(self):
        self.seed_favorites(self.picture_ids[:1])
        response = self.client.get(reverse('favorites_shared'), {
            'data': self.share_token(self.picture_ids[1:3]),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[:1])
        self.assertContains(response, 'data-favorites-import-form hidden')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, '/static/skinali/js/favorites-import.js')
        self.assertNotContains(response, 'data-favorites-import-retry')
        self.assertContains(response, '<meta name="robots" content="noindex,follow">', html=True)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')

    def test_import_merges_without_duplicates_and_preserves_selection_order(self):
        self.seed_favorites(self.picture_ids[:2])
        response = self.import_ids([self.picture_ids[1], self.picture_ids[2], self.picture_ids[2]])
        self.assertRedirects(response, reverse('favorites'), fetch_redirect_response=False)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[:3])
        page = self.client.get(reverse('favorites'))
        self.assertEqual(page.context['favorite_pictures'], list(reversed(self.pictures[:3])))
        self.assertContains(page, 'Подборка сохранена в избранном')

    def test_import_works_in_another_browser_after_sender_clears_cookies(self):
        self.seed_favorites(self.picture_ids[:2])
        token = self.share_token(self.picture_ids[:2])
        self.client.cookies.clear()
        recipient = Client()
        recipient.post(reverse('favorites_shared'), {'data': token})
        self.assertEqual(recipient.session[FAVORITES_SESSION_KEY], self.picture_ids[:2])
        self.assertNotIn(FAVORITES_SESSION_KEY, self.client.session)

    def test_import_skips_deleted_and_unpublished_images(self):
        token = self.share_token(self.picture_ids[:3])
        Pict.objects.filter(pk=self.picture_ids[1]).update(is_published=False)
        self.pictures[2].delete()
        self.client.post(reverse('favorites_shared'), {'data': token})
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[:1])

    def test_unavailable_shared_images_do_not_change_existing_selection(self):
        self.seed_favorites(self.picture_ids[:1])
        token = self.share_token(self.picture_ids[1:3])
        Pict.objects.filter(pk__in=self.picture_ids[1:3]).update(is_published=False)
        self.client.post(reverse('favorites_shared'), {'data': token})
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[:1])
        page = self.client.get(reverse('favorites'))
        self.assertContains(page, 'В подборке нет доступных изображений')

    def test_repeated_import_does_not_duplicate_or_reorder_existing_favorites(self):
        self.seed_favorites(list(reversed(self.picture_ids[:2])))
        self.import_ids(self.picture_ids[:2])
        self.import_ids(self.picture_ids[:2])
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], list(reversed(self.picture_ids[:2])))

    def test_overflow_import_adds_until_limit_and_shows_warning_after_redirect(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 1])
        response = self.import_ids(self.picture_ids[MAX_FAVORITES - 1:MAX_FAVORITES + 1])
        self.assertRedirects(response, reverse('favorites'), fetch_redirect_response=False)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[:MAX_FAVORITES])
        page = self.client.get(reverse('favorites'))
        self.assertEqual(page.context['pending_favorites_added_count'], 1)
        self.assertEqual(page.context['pending_favorites_count'], 1)
        self.assertContains(page, FAVORITES_IMPORT_LIMIT_MESSAGE)
        self.assertContains(page, 'data-site-toast-kind="warning"')

    def test_import_allows_exact_limit_including_existing_duplicates(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 1])
        response = self.import_ids(self.picture_ids[MAX_FAVORITES - 2:MAX_FAVORITES])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[:MAX_FAVORITES])

    def test_import_of_four_images_with_three_matches_adds_only_one(self):
        self.seed_favorites(self.picture_ids[:4])
        response = self.import_ids(self.picture_ids[1:5])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[:5])
        self.assertNotIn(FAVORITES_PENDING_IMPORT_SESSION_KEY, self.client.session)

    def test_pending_summary_counts_only_new_unique_available_images(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES])
        shared_ids = [
            self.picture_ids[1], self.picture_ids[2],
            self.picture_ids[MAX_FAVORITES],
            self.picture_ids[MAX_FAVORITES],
            self.picture_ids[MAX_FAVORITES + 1],
        ]
        self.import_ids(shared_ids)
        Pict.objects.filter(pk=self.picture_ids[MAX_FAVORITES + 1]).update(is_published=False)
        page = self.client.get(reverse('favorites'))
        self.assertEqual(page.context['pending_favorites_count'], 1)
        self.assertEqual(page.context['pending_favorites_added_count'], 0)
        self.assertContains(page,
            '<p class="favorites-notice favorites-notice--warning">Подборка не добавлена. Удалите лишние изображения и повторите добавление.<br>'
            'Добавлено новых изображений: <span data-favorites-imported-count>0</span><br>'
            'Осталось добавить изображений: <span data-favorites-pending-count>1</span></p>',
            html=True,
        )
        self.assertContains(page, 'Избранное переполнено')
        self.assertNotContains(page, 'В избранном должно быть не более')

    def test_pending_counters_recalculate_when_removing_an_existing_shared_image(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 1])
        self.import_ids(self.picture_ids[MAX_FAVORITES - 3:MAX_FAVORITES + 1])

        result = self.toggle(self.picture_ids[MAX_FAVORITES - 2]).json()

        self.assertEqual(result['favorites_count'], MAX_FAVORITES - 1)
        self.assertEqual(result['pending_favorites_count'], 2)
        self.assertEqual(result['pending_favorites_added_count'], 1)
        self.assertTrue(result['has_pending_favorites'])
        page = self.client.get(reverse('favorites'))
        self.assertEqual(page.context['pending_favorites_count'], 2)

    def test_toggle_clears_unavailable_pending_selection_in_its_response(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 1])
        shared_ids = self.picture_ids[MAX_FAVORITES - 1:MAX_FAVORITES + 1]
        self.import_ids(shared_ids)
        Pict.objects.filter(pk__in=shared_ids).update(is_published=False)

        result = self.toggle(self.picture_ids[0]).json()

        self.assertEqual(result['pending_favorites_count'], 0)
        self.assertFalse(result['has_pending_favorites'])
        self.assertNotIn(FAVORITES_PENDING_IMPORT_SESSION_KEY, self.client.session)

    def test_retry_button_appears_only_after_overflow(self):
        self.assertNotContains(self.client.get(reverse('favorites')), 'data-favorites-import-retry')
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 1])
        shared_ids = self.picture_ids[MAX_FAVORITES - 1:MAX_FAVORITES + 1]
        self.import_ids(shared_ids)

        page = self.client.get(reverse('favorites'))

        self.assertContains(page, 'data-favorites-import-retry')
        self.assertContains(page, 'Добавить всё в моё избранное')
        self.assertContains(page, 'name="csrfmiddlewaretoken"')
        self.assertEqual(read_favorites_share_token(page.context['pending_favorites_token']), shared_ids)
        self.assertNotContains(page, '/static/skinali/js/favorites-import.js')

    def test_retry_preserves_shared_selection_after_removal_and_reload(self):
        own_ids = self.picture_ids[:MAX_FAVORITES - 1]
        shared_ids = self.picture_ids[MAX_FAVORITES - 1:MAX_FAVORITES + 1]
        self.seed_favorites(own_ids)
        self.import_ids(shared_ids)
        token = self.client.session[FAVORITES_PENDING_IMPORT_SESSION_KEY]
        self.toggle(own_ids[0])
        page = self.client.get(reverse('favorites'))
        self.assertEqual(page.context['pending_favorites_token'], token)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], own_ids[1:] + shared_ids[:1])

        response = self.client.post(reverse('favorites_shared'), {'data': token})

        self.assertRedirects(response, reverse('favorites'), fetch_redirect_response=False)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], own_ids[1:] + shared_ids)
        self.assertNotIn(FAVORITES_PENDING_IMPORT_SESSION_KEY, self.client.session)
        self.assertNotIn(FAVORITES_PENDING_ADDED_SESSION_KEY, self.client.session)
        self.assertNotContains(self.client.get(reverse('favorites')), 'data-favorites-import-retry')

    def test_retry_with_insufficient_space_keeps_selection_and_button(self):
        own_ids = self.picture_ids[:MAX_FAVORITES - 1]
        self.seed_favorites(own_ids)
        self.import_ids(self.picture_ids[MAX_FAVORITES - 1:MAX_FAVORITES + 1])
        token = self.client.session[FAVORITES_PENDING_IMPORT_SESSION_KEY]

        self.client.post(reverse('favorites_shared'), {'data': token})

        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], own_ids + self.picture_ids[MAX_FAVORITES - 1:MAX_FAVORITES])
        self.assertEqual(self.client.session[FAVORITES_PENDING_IMPORT_SESSION_KEY], token)
        page = self.client.get(reverse('favorites'))
        self.assertContains(page, FAVORITES_IMPORT_LIMIT_MESSAGE)
        self.assertContains(page, 'data-favorites-import-retry')

    def test_partial_import_shows_three_added_and_one_remaining(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 3])
        shared_ids = self.picture_ids[MAX_FAVORITES - 3:MAX_FAVORITES + 1]
        self.import_ids(shared_ids)

        page = self.client.get(reverse('favorites'))

        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[:MAX_FAVORITES])
        self.assertEqual(page.context['pending_favorites_added_count'], 3)
        self.assertEqual(page.context['pending_favorites_count'], 1)
        self.assertContains(page,
            '<p class="favorites-notice favorites-notice--warning">Подборка не добавлена. Удалите лишние изображения и повторите добавление.<br>'
            'Добавлено новых изображений: <span data-favorites-imported-count>3</span><br>'
            'Осталось добавить изображений: <span data-favorites-pending-count>1</span></p>',
            html=True,
        )

    def test_removing_imported_image_updates_added_and_remaining_counters(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 3])
        self.import_ids(self.picture_ids[MAX_FAVORITES - 3:MAX_FAVORITES + 1])

        result = self.toggle(self.picture_ids[MAX_FAVORITES - 3]).json()

        self.assertEqual(result['favorites_count'], MAX_FAVORITES - 1)
        self.assertEqual(result['pending_favorites_added_count'], 2)
        self.assertEqual(result['pending_favorites_count'], 2)

    def test_repeated_partial_import_preserves_progress_without_counting_duplicates(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 2])
        shared_ids = self.picture_ids[MAX_FAVORITES - 2:MAX_FAVORITES + 2]
        self.import_ids(shared_ids)
        self.toggle(self.picture_ids[0])
        self.import_ids(shared_ids)

        page = self.client.get(reverse('favorites'))

        self.assertEqual(page.context['pending_favorites_added_count'], 3)
        self.assertEqual(page.context['pending_favorites_count'], 1)
        self.assertEqual(len(self.client.session[FAVORITES_SESSION_KEY]), MAX_FAVORITES)

    def test_new_pending_selection_resets_previous_added_counter(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 1])
        self.import_ids(self.picture_ids[MAX_FAVORITES - 1:MAX_FAVORITES + 1])
        self.import_ids(self.picture_ids[MAX_FAVORITES + 1:MAX_FAVORITES + 2])

        page = self.client.get(reverse('favorites'))

        self.assertEqual(page.context['pending_favorites_added_count'], 0)
        self.assertEqual(page.context['pending_favorites_count'], 1)

    def test_pending_state_is_cleared_when_all_remaining_images_become_unavailable(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 1])
        self.import_ids(self.picture_ids[MAX_FAVORITES - 1:MAX_FAVORITES + 1])
        Pict.objects.filter(pk=self.picture_ids[MAX_FAVORITES]).update(is_published=False)

        page = self.client.get(reverse('favorites'))

        self.assertNotContains(page, 'data-favorites-import-retry')
        self.assertNotIn(FAVORITES_PENDING_IMPORT_SESSION_KEY, self.client.session)
        self.assertNotIn(FAVORITES_PENDING_ADDED_SESSION_KEY, self.client.session)

    def test_retry_is_isolated_between_browsers(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 1])
        self.import_ids(self.picture_ids[MAX_FAVORITES - 1:MAX_FAVORITES + 1])
        self.assertNotContains(Client().get(reverse('favorites')), 'data-favorites-import-retry')

    def test_invalid_or_unavailable_pending_selection_is_cleared(self):
        for token in ['invalid', self.share_token(self.picture_ids[:2])]:
            with self.subTest(token=token):
                Pict.objects.filter(pk__in=self.picture_ids[:2]).update(is_published=False)
                session = self.client.session
                session[FAVORITES_PENDING_IMPORT_SESSION_KEY] = token
                session.save()
                self.client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
                page = self.client.get(reverse('favorites'))
                self.assertNotContains(page, 'data-favorites-import-retry')
                self.assertNotIn(FAVORITES_PENDING_IMPORT_SESSION_KEY, self.client.session)

    def test_latest_failed_import_replaces_previous_pending_selection(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES])
        self.import_ids(self.picture_ids[MAX_FAVORITES:MAX_FAVORITES + 1])
        latest_ids = self.picture_ids[MAX_FAVORITES + 1:MAX_FAVORITES + 2]
        self.import_ids(latest_ids)
        token = self.client.session[FAVORITES_PENDING_IMPORT_SESSION_KEY]
        self.assertEqual(read_favorites_share_token(token), latest_ids)

    def test_overflow_and_retry_do_not_write_database_rows(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 1])
        token = self.share_token(self.picture_ids[MAX_FAVORITES - 1:MAX_FAVORITES + 1])
        with CaptureQueriesContext(connection) as queries:
            self.client.post(reverse('favorites_shared'), {'data': token})
            self.toggle(self.picture_ids[0])
            self.client.post(reverse('favorites_shared'), {'data': token})
        writes = [query['sql'] for query in queries if query['sql'].lstrip().upper().startswith(
            ('INSERT', 'UPDATE', 'DELETE', 'REPLACE'),
        )]
        self.assertEqual(writes, [])
        self.assertNotIn(FAVORITES_PENDING_IMPORT_SESSION_KEY, self.client.session)

    def test_clear_removes_only_current_browser_favorites_without_database_writes(self):
        other_browser = Client()
        self.seed_favorites(self.picture_ids[:2])
        self.seed_favorites(self.picture_ids[2:4], client=other_browser)
        session = self.client.session
        session['other_session_data'] = 'keep'
        session.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(reverse('favorites_clear'))
        self.assertRedirects(response, reverse('favorites'), fetch_redirect_response=False)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], [])
        self.assertEqual(self.client.session['other_session_data'], 'keep')
        self.assertEqual(other_browser.session[FAVORITES_SESSION_KEY], self.picture_ids[2:4])
        self.assertEqual(Pict.objects.count(), len(self.picture_ids))
        writes = [query['sql'] for query in queries if query['sql'].lstrip().upper().startswith(
            ('INSERT', 'UPDATE', 'DELETE', 'REPLACE'),
        )]
        self.assertEqual(writes, [])

    def test_clear_preserves_pending_selection_for_retry(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 3])
        shared_ids = self.picture_ids[MAX_FAVORITES - 3:MAX_FAVORITES + 1]
        self.import_ids(shared_ids)
        token = self.client.session[FAVORITES_PENDING_IMPORT_SESSION_KEY]

        self.client.post(reverse('favorites_clear'))
        page = self.client.get(reverse('favorites'))

        self.assertEqual(page.context['favorites_count'], 0)
        self.assertEqual(page.context['pending_favorites_added_count'], 0)
        self.assertEqual(page.context['pending_favorites_count'], len(shared_ids))
        self.assertEqual(page.context['pending_favorites_token'], token)
        self.assertContains(page, 'Избранное очищено')
        self.assertContains(page, 'data-favorites-clear disabled')
        self.client.post(reverse('favorites_shared'), {'data': token})
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], shared_ids)
        self.assertNotIn(FAVORITES_PENDING_IMPORT_SESSION_KEY, self.client.session)

    def test_retry_and_clear_forms_share_actions_container_and_have_csrf_tokens(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES - 1])
        self.import_ids(self.picture_ids[MAX_FAVORITES - 1:MAX_FAVORITES + 1])
        page = self.client.get(reverse('favorites'))
        actions = page.content.decode().split('<div class="favorites-actions"', 1)[1].split('</div>', 1)[0]
        self.assertIn('Добавить всё в моё избранное', actions)
        self.assertIn('Удалить все из избранного', actions)
        self.assertIn(f'action="{reverse("favorites_shared")}"', actions)
        self.assertIn(f'action="{reverse("favorites_clear")}"', actions)
        self.assertEqual(actions.count('name="csrfmiddlewaretoken"'), 2)

    def test_clear_button_is_available_without_pending_import_and_hidden_when_empty(self):
        self.seed_favorites(self.picture_ids[:1])
        page = self.client.get(reverse('favorites'))
        self.assertContains(page, 'class="favorites-clear__submit is-active"')
        self.assertNotContains(page, 'data-favorites-import-retry')
        self.client.post(reverse('favorites_clear'))
        empty_page = self.client.get(reverse('favorites'))
        self.assertNotContains(empty_page, 'class="favorites-actions"')

    def test_clear_requires_post_and_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        self.seed_favorites(self.picture_ids[:2], client=browser)
        url = reverse('favorites_clear')
        self.assertEqual(browser.get(url).status_code, 405)
        self.assertEqual(browser.post(url).status_code, 403)
        self.assertEqual(browser.session[FAVORITES_SESSION_KEY], self.picture_ids[:2])
        browser.get(reverse('favorites'))
        csrf_token = browser.cookies[settings.CSRF_COOKIE_NAME].value
        self.assertEqual(browser.post(url, {'csrfmiddlewaretoken': csrf_token}).status_code, 302)
        self.assertEqual(browser.session[FAVORITES_SESSION_KEY], [])

    def test_clearing_empty_favorites_is_idempotent(self):
        for _ in range(2):
            response = self.client.post(reverse('favorites_clear'))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], [])

    def test_full_favorites_allow_import_containing_only_existing_images(self):
        self.seed_favorites(self.picture_ids[:MAX_FAVORITES])
        self.assertEqual(self.import_ids(self.picture_ids[:3]).status_code, 302)
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[:MAX_FAVORITES])

    def test_tampered_and_foreign_signatures_do_not_change_favorites(self):
        self.seed_favorites(self.picture_ids[:1])
        valid = self.share_token(self.picture_ids[1:3])
        invalid_tokens = [
            'A' + valid[1:],
            self.signed_payload({'v': 1, 'ids': self.picture_ids[1:3]}, salt='another.purpose'),
        ]
        for token in invalid_tokens:
            with self.subTest(token=token):
                page = self.client.get(reverse('favorites_shared'), {'data': token})
                self.assertEqual(page.status_code, 400)
                self.assertContains(page, 'Ссылка на избранное недействительна', status_code=400)
                self.assertNotContains(page, 'data-favorites-import-form', status_code=400)
                self.client.post(reverse('favorites_shared'), {'data': token})
                self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[:1])

    def test_invalid_signed_payloads_are_rejected(self):
        payloads = [
            [], {}, {'v': 2, 'ids': self.picture_ids[:1]},
            {'v': True, 'ids': self.picture_ids[:1]},
            {'v': 1, 'ids': []}, {'v': 1, 'ids': self.picture_ids[:MAX_FAVORITES + 1]},
            {'v': 1, 'ids': '123'}, {'v': 1, 'ids': ['123']},
            {'v': 1, 'ids': [True]}, {'v': 1, 'ids': [0]},
            {'v': 1, 'ids': [-1]}, {'v': 1, 'ids': [2**100]},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    read_favorites_share_token(self.signed_payload(payload))

    def test_oversized_tokens_are_rejected_before_signature_processing(self):
        with patch.object(signing.Signer, 'unsign_object') as decode:
            with self.assertRaises(ValueError):
                read_favorites_share_token('x' * (MAX_SHARE_TOKEN_LENGTH + 1))
            decode.assert_not_called()

    def test_links_have_no_time_limit(self):
        token = self.share_token(self.picture_ids[:2])
        with patch('time.time', return_value=10**12):
            self.assertEqual(read_favorites_share_token(token), self.picture_ids[:2])

    def test_import_requires_csrf_token_and_accepts_automatic_form_token(self):
        browser = Client(enforce_csrf_checks=True)
        token = self.share_token(self.picture_ids[:2])
        url = reverse('favorites_shared')
        self.assertEqual(browser.post(url, {'data': token}).status_code, 403)
        page = browser.get(url, {'data': token})
        self.assertEqual(page.status_code, 200)
        csrf_token = browser.cookies[settings.CSRF_COOKIE_NAME].value
        response = browser.post(url, {'data': token, 'csrfmiddlewaretoken': csrf_token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(browser.session[FAVORITES_SESSION_KEY], self.picture_ids[:2])

    def test_automatic_import_returns_clean_redirect_for_browser(self):
        response = self.client.post(
            reverse('favorites_shared'),
            {'data': self.share_token(self.picture_ids[:2])},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'redirect_url': reverse('favorites')})
        self.assertEqual(self.client.session[FAVORITES_SESSION_KEY], self.picture_ids[:2])

    def test_toggle_requires_csrf_token(self):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.post(reverse('favorite_toggle', args=[self.picture_ids[0]])).status_code, 403)

    def test_sharing_and_import_do_not_write_database_rows(self):
        with CaptureQueriesContext(connection) as queries:
            token = self.share_token(self.picture_ids[:2])
            self.client.get(reverse('favorites_shared'), {'data': token})
            response = self.client.post(reverse('favorites_shared'), {'data': token})
        writes = [query['sql'] for query in queries if query['sql'].lstrip().upper().startswith(
            ('INSERT', 'UPDATE', 'DELETE', 'REPLACE'),
        )]
        self.assertEqual(response.status_code, 302)
        self.assertEqual(writes, [])

    def test_invalid_post_redirects_with_error_message(self):
        response = self.client.post(reverse('favorites_shared'), {'data': 'invalid'})
        self.assertRedirects(response, reverse('favorites'), fetch_redirect_response=False)
        notice = list(get_messages(response.wsgi_request))[0]
        self.assertEqual(notice.level_tag, 'error')

    def test_missing_token_and_unsupported_method_are_rejected(self):
        self.assertEqual(self.client.get(reverse('favorites_shared')).status_code, 400)
        self.assertEqual(self.client.put(reverse('favorites_shared')).status_code, 405)
