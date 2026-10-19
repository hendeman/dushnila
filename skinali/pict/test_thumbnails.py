"""Проверки нумерованных превью, перехода со старого кеша и его очистки."""

from io import StringIO
from pathlib import PurePosixPath
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from sorl.thumbnail import default
from sorl.thumbnail.base import ThumbnailBackend
from sorl.thumbnail.images import ImageFile
from sorl.thumbnail.shortcuts import get_thumbnail

from .models import FinishedWork, Pict
from .tests import create_test_image_file


class NumberedThumbnailTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        media_settings = override_settings(MEDIA_ROOT=directory.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        cache.clear()
        self.addCleanup(cache.clear)
        self.picture = Pict.objects.create(
            name=275,
            alt=self._testMethodName,
            photo=create_test_image_file('source.jpg', size=(3000, 500)),
        )

    def test_existing_cache_is_preserved_and_new_sizes_are_cached(self):
        original_name = self.picture.photo.name
        for geometry, options, size in (
            ('760', {}, (760, 127)),
            ('1920', {'quality': 90}, (1920, 320)),
            ('100', {'format': 'PNG'}, (100, 17)),
        ):
            with self.subTest(geometry=geometry, options=options):
                old_thumbnail = ThumbnailBackend().get_thumbnail(
                    self.picture.photo, geometry, **options,
                )
                thumbnail = get_thumbnail(self.picture.photo, geometry, **options)
                old_path = PurePosixPath(old_thumbnail.name)
                self.assertEqual(
                    thumbnail.name,
                    str(old_path.with_name(f'{old_path.stem}-275{old_path.suffix}')),
                )
                self.assertTrue(old_thumbnail.exists())
                self.assertTrue(thumbnail.exists())
                with thumbnail.storage.open(thumbnail.name, 'rb') as image_file:
                    with Image.open(image_file) as image:
                        self.assertEqual(image.size, size)

                with patch.object(default.engine, 'get_image') as decode:
                    with self.assertNumQueries(0):
                        repeated = get_thumbnail(self.picture.photo, geometry, **options)
                    decode.assert_not_called()
                self.assertEqual(repeated.name, thumbnail.name)

        self.picture.refresh_from_db()
        self.assertEqual(self.picture.photo.name, original_name)
        self.assertTrue(self.picture.photo.storage.exists(original_name))

    def test_legacy_filename_and_renumbering_use_current_catalog_number(self):
        legacy_name = default_storage.save(
            'photos/legacy-17_X7YzA12.jpg', create_test_image_file('legacy.jpg'),
        )
        self.picture.photo = legacy_name
        self.picture.save(update_fields=['photo'])
        old_thumbnail = get_thumbnail(self.picture.photo, '760')
        self.assertTrue(old_thumbnail.name.endswith('-275.jpg'))

        self.picture.name = 276
        self.picture.save(update_fields=['name'])
        thumbnail = get_thumbnail(self.picture.photo, '760')
        self.assertTrue(thumbnail.name.endswith('-276.jpg'))
        self.assertNotEqual(thumbnail.name, old_thumbnail.name)
        self.assertTrue(old_thumbnail.exists())
        self.assertTrue(thumbnail.exists())
        self.picture.refresh_from_db()
        self.assertEqual(self.picture.photo.name, legacy_name)

    def test_finished_work_and_plain_paths_keep_standard_cache_names(self):
        work = FinishedWork.objects.create(
            name='Готовая кухня',
            photo=create_test_image_file('kitchen.jpg'),
            catalog_image=self.picture,
        )
        for source, geometry in (
            (work.photo, '760x760'),
            (self.picture.photo.name, '760'),
        ):
            with self.subTest(source=str(source)):
                expected = ThumbnailBackend().get_thumbnail(source, geometry)
                thumbnail = get_thumbnail(source, geometry)
                self.assertEqual(thumbnail.name, expected.name)
                self.assertRegex(PurePosixPath(thumbnail.name).name, r'^[a-f0-9]{32}\.jpg$')

    def test_explicit_number_overrides_instance_and_supports_plain_paths(self):
        thumbnail = get_thumbnail(self.picture.photo, '760', catalog_image_number=0)
        self.assertTrue(thumbnail.name.endswith('-0.jpg'))
        self.assertEqual(
            get_thumbnail(self.picture.photo.name, '760', catalog_image_number=0).url,
            thumbnail.url,
        )

    def test_explicit_number_cannot_change_storage_path(self):
        with self.assertRaises(ValueError):
            get_thumbnail(self.picture.photo, '760', catalog_image_number='../275')

    def test_deleting_image_cleans_old_and_numbered_thumbnails(self):
        old_thumbnail = ThumbnailBackend().get_thumbnail(self.picture.photo, '760')
        thumbnail = get_thumbnail(self.picture.photo, '760')
        original = self.picture.photo.name

        with self.captureOnCommitCallbacks(execute=True):
            self.picture.delete()

        self.assertFalse(default_storage.exists(original))
        for cached in (old_thumbnail, thumbnail):
            with self.subTest(name=cached.name):
                self.assertFalse(cached.exists())
                self.assertIsNone(default.kvstore.get(cached))

    def test_public_pages_use_numbered_catalog_previews(self):
        work = FinishedWork.objects.create(
            name='Кухня с изображением',
            photo=create_test_image_file('interior.jpg'),
            catalog_image=self.picture,
        )
        self.client.post(reverse('favorite_toggle', args=[self.picture.pk]))
        small = get_thumbnail(self.picture.photo, '760')
        large = get_thumbnail(self.picture.photo, '1920', quality=90)
        self.assertTrue(small.name.endswith('-275.jpg'))
        self.assertTrue(large.name.endswith('-275.jpg'))

        for url, thumbnail in (
            (reverse('skinali'), small),
            (reverse('favorites'), small),
            (self.picture.get_absolute_url(), large),
            (reverse('finished_works'), small),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, f'src="{thumbnail.url}"')
        self.assertNotIn('-275.', get_thumbnail(work.photo, '760x760', crop='center').name)

    def test_large_preview_loads_number_without_additional_model_query(self):
        thumbnail = get_thumbnail(self.picture.photo, '1920', quality=90)
        with self.assertNumQueries(1):
            response = self.client.get(reverse(
                'pict_large_preview', kwargs={'slug': self.picture.slug},
            ))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], thumbnail.url)

    def test_external_cache_clear_recovers_files_and_persistent_metadata(self):
        thumbnail = get_thumbnail(self.picture.photo, '760')
        # У отдельного процесса команды свой LocMemCache; память web-процесса остаётся.
        command_caches = {
            'default': {
                'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                'LOCATION': self._testMethodName,
            },
        }
        with override_settings(CACHES=command_caches):
            call_command('thumbnail', 'clear_delete_all', stdout=StringIO())

        self.assertFalse(thumbnail.exists())
        self.assertIsNotNone(default.kvstore.get(thumbnail))
        response = self.client.get(reverse('skinali'))
        self.assertContains(response, f'src="{thumbnail.url}"')
        self.assertTrue(thumbnail.exists())

        # Новый worker должен найти также восстановленный источник и связь с превью.
        cache.clear()
        source = ImageFile(self.picture.photo)
        self.assertIsNotNone(default.kvstore.get(source))
        self.assertIsNotNone(default.kvstore.get(thumbnail))
        self.assertEqual(default.kvstore.get(source).size, [3000, 500])
        self.assertEqual(default.kvstore.get(thumbnail).size, [760, 127])
        with self.captureOnCommitCallbacks(execute=True):
            self.picture.delete()
        self.assertFalse(thumbnail.exists())

    def test_missing_cached_file_is_rebuilt_without_deleting_other_sizes(self):
        work = FinishedWork.objects.create(
            name='Кухня для восстановления кеша',
            photo=create_test_image_file('cache-recovery-work.jpg'),
        )
        for photo in (self.picture.photo, work.photo):
            with self.subTest(photo=photo.name):
                thumbnail = get_thumbnail(photo, '760')
                other_size = get_thumbnail(photo, '1920')
                other_mtime = other_size.storage.get_modified_time(other_size.name)
                thumbnail.storage.delete(thumbnail.name)

                with patch.object(
                    default.engine, 'get_image', wraps=default.engine.get_image,
                ) as decode:
                    restored = get_thumbnail(photo, '760')
                self.assertEqual(decode.call_count, 1)
                self.assertEqual(restored.url, thumbnail.url)
                self.assertTrue(restored.exists())
                self.assertTrue(other_size.exists())
                self.assertEqual(
                    other_size.storage.get_modified_time(other_size.name), other_mtime,
                )

    def test_source_read_error_does_not_repeat_generation(self):
        with self.assertLogs('sorl.thumbnail.base', level='ERROR'):
            with patch.object(
                default.engine, 'get_image', side_effect=OSError('unreadable source'),
            ) as decode:
                thumbnail = get_thumbnail(self.picture.photo, '760')
        decode.assert_called_once()
        self.assertFalse(thumbnail.exists())
