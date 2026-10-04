import os
from datetime import timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.storage import default_storage
from django.core.management import CommandError, call_command
from django.contrib.admin.sites import AdminSite
from django.db import transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from quiz.models import Quiz
from sorl.thumbnail.shortcuts import get_thumbnail

from .admin import PictAdmin
from .models import FinishedWork, Pict
from .services.photo_cleanup import is_safe_photo_path, iter_stored_photos, remove_unused_photo
from .tests import create_test_image_file


class PhotoStorageMixin:
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.media_settings = override_settings(MEDIA_ROOT=directory.name)
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)
        self.storage = default_storage

    def create_record(self, model=Pict):
        values = {'photo': create_test_image_file('original.jpg')}
        if model is Pict:
            values.update(name=321, alt=self._testMethodName)
        else:
            values['name'] = self._testMethodName
        return model.objects.create(**values)

    def store_file(self, directory='photos', *, filename=None, old=True):
        name = self.storage.save(
            f'{directory}/{filename or self._testMethodName + ".jpg"}',
            create_test_image_file('file.jpg'),
        )
        if old:
            self.age_file(name)
        return name

    def age_file(self, name):
        timestamp = (timezone.now() - timedelta(days=2)).timestamp()
        os.utime(self.storage.path(name), (timestamp, timestamp))


class PhotoCleanupTests(PhotoStorageMixin, TestCase):
    def test_replacement_cleans_both_models_only_after_commit(self):
        for model in (Pict, FinishedWork):
            with self.subTest(model=model.__name__):
                record = self.create_record(model)
                old_name = record.photo.name
                thumbnail = get_thumbnail(record.photo, '100')
                with self.captureOnCommitCallbacks(execute=True) as callbacks:
                    record.photo = create_test_image_file('replacement.jpg')
                    record.save(update_fields=['photo'])
                    self.assertNotEqual(record.photo.name, old_name)
                    self.assertTrue(self.storage.exists(old_name))
                    self.assertTrue(thumbnail.storage.exists(thumbnail.name))
                self.assertEqual(len(callbacks), 1)
                self.assertFalse(self.storage.exists(old_name))
                self.assertFalse(thumbnail.storage.exists(thumbnail.name))
                self.assertTrue(self.storage.exists(record.photo.name))

    def test_model_and_bulk_deletion_clean_both_models(self):
        for model in (Pict, FinishedWork):
            for bulk in (False, True):
                with self.subTest(model=model.__name__, bulk=bulk):
                    record = self.create_record(model)
                    old_name = record.photo.name
                    thumbnail = get_thumbnail(record.photo, '101')
                    with self.captureOnCommitCallbacks(execute=True):
                        if bulk:
                            model.objects.filter(pk=record.pk).delete()
                        else:
                            record.delete()
                        self.assertTrue(self.storage.exists(old_name))
                    self.assertFalse(self.storage.exists(old_name))
                    self.assertFalse(thumbnail.storage.exists(thumbnail.name))

    def test_clearing_photo_cleans_previous_file(self):
        record = self.create_record()
        old_name = record.photo.name
        with self.captureOnCommitCallbacks(execute=True):
            record.photo = ''
            record.save(update_fields=['photo'])
        self.assertFalse(self.storage.exists(old_name))

    def test_unchanged_file_is_not_scheduled_for_cleanup(self):
        record = self.create_record()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            record.alt = 'Другое описание'
            record.save()
        self.assertEqual(callbacks, [])
        self.assertTrue(self.storage.exists(record.photo.name))

    def test_update_fields_without_photo_keeps_actual_database_file(self):
        record = self.create_record()
        old_name = record.photo.name
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            record.photo = create_test_image_file('not-saved.jpg')
            record.alt = 'Новое описание'
            record.save(update_fields=['alt'])
        record.refresh_from_db()
        self.assertEqual(callbacks, [])
        self.assertEqual(record.photo.name, old_name)
        self.assertTrue(self.storage.exists(old_name))

    def test_replacement_rollback_preserves_previous_original_and_thumbnail(self):
        record = self.create_record()
        old_name = record.photo.name
        thumbnail = get_thumbnail(record.photo, '102')
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError), transaction.atomic():
                record.photo = create_test_image_file('rolled-back.jpg')
                record.save(update_fields=['photo'])
                uploaded_name = record.photo.name
                raise RuntimeError('Откат сохранения')
        record.refresh_from_db()
        self.assertEqual(callbacks, [])
        self.assertEqual(record.photo.name, old_name)
        self.assertTrue(self.storage.exists(old_name))
        self.assertTrue(thumbnail.storage.exists(thumbnail.name))
        # Файловый storage не транзакционный: новую копию найдёт отдельная команда.
        self.assertTrue(self.storage.exists(uploaded_name))

    def test_deletion_rollback_preserves_file(self):
        record = self.create_record()
        old_name = record.photo.name
        pk = record.pk
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaises(RuntimeError), transaction.atomic():
                record.delete()
                raise RuntimeError('Откат удаления')
        self.assertEqual(callbacks, [])
        self.assertTrue(Pict.objects.filter(pk=pk).exists())
        self.assertTrue(self.storage.exists(old_name))

    def test_shared_unpublished_file_is_preserved_until_last_reference_deleted(self):
        record = self.create_record()
        old_name = record.photo.name
        work = FinishedWork.objects.create(name='Общая фотография', photo=old_name, is_published=False)
        thumbnail = get_thumbnail(record.photo, '103')
        with self.captureOnCommitCallbacks(execute=True):
            record.delete()
        self.assertTrue(self.storage.exists(old_name))
        self.assertTrue(thumbnail.storage.exists(thumbnail.name))
        with self.captureOnCommitCallbacks(execute=True):
            work.delete()
        self.assertFalse(self.storage.exists(old_name))
        self.assertFalse(thumbnail.storage.exists(thumbnail.name))

    def test_other_app_file_reference_prevents_cleanup(self):
        record = self.create_record()
        old_name = record.photo.name
        Quiz.objects.update_or_create(
            trigger_key='shared-photo',
            defaults={'name': 'Общий файл', 'title': 'Квиз', 'launcher_icon': old_name},
        )
        with self.captureOnCommitCallbacks(execute=True):
            record.delete()
        self.assertTrue(self.storage.exists(old_name))

    def test_reference_created_before_callback_is_respected(self):
        record = self.create_record()
        old_name = record.photo.name
        with self.captureOnCommitCallbacks(execute=True):
            record.photo = create_test_image_file('new.jpg')
            record.save(update_fields=['photo'])
            FinishedWork.objects.create(name='Сохраняем старый файл', photo=old_name)
        self.assertTrue(self.storage.exists(old_name))

    def test_multiple_replacements_clean_all_but_final_file(self):
        record = self.create_record()
        obsolete_names = [record.photo.name]
        with self.captureOnCommitCallbacks(execute=True):
            for index in range(2):
                record.photo = create_test_image_file(f'new-{index}.jpg')
                record.save(update_fields=['photo'])
                if index == 0:
                    obsolete_names.append(record.photo.name)
        self.assertTrue(self.storage.exists(record.photo.name))
        for name in obsolete_names:
            self.assertFalse(self.storage.exists(name))

    def test_thumbnail_failure_keeps_original_for_retry_without_breaking_save(self):
        record = self.create_record()
        old_name = record.photo.name
        with self.assertLogs('pict.services.photo_cleanup', level='ERROR'), patch(
            'pict.services.photo_cleanup.delete_thumbnail', side_effect=OSError('Ошибка кеша'),
        ), self.captureOnCommitCallbacks(execute=True):
            record.photo = create_test_image_file('new.jpg')
            record.save(update_fields=['photo'])
        record.refresh_from_db()
        self.assertNotEqual(record.photo.name, old_name)
        self.assertTrue(self.storage.exists(old_name))
        self.assertEqual(remove_unused_photo(old_name, storage=self.storage), 'deleted')

    def test_database_failure_does_not_delete_file(self):
        name = self.store_file()
        with self.assertLogs('pict.services.photo_cleanup', level='ERROR'), patch(
            'pict.services.photo_cleanup.is_photo_referenced', side_effect=RuntimeError('БД недоступна'),
        ):
            self.assertEqual(remove_unused_photo(name, storage=self.storage), 'failed')
        self.assertTrue(self.storage.exists(name))

    def test_missing_original_still_cleans_thumbnail(self):
        record = self.create_record()
        name = record.photo.name
        thumbnail = get_thumbnail(record.photo, '104')
        self.storage.delete(name)
        with self.captureOnCommitCallbacks(execute=True):
            record.delete()
        self.assertFalse(thumbnail.storage.exists(thumbnail.name))

    def test_cleanup_is_idempotent(self):
        name = self.store_file()
        self.assertEqual(remove_unused_photo(name, storage=self.storage), 'deleted')
        self.assertEqual(remove_unused_photo(name, storage=self.storage), 'missing')

    def test_unsafe_paths_are_rejected(self):
        for name in ('', '/photos/a.jpg', '../photos/a.jpg', 'photos/../a.jpg',
                     'photos//a.jpg', 'photos/./a.jpg', 'photos\\a.jpg',
                     'photos/C:/a.jpg', 'quiz/a.jpg', 'cache/thumbnails/a.jpg'):
            with self.subTest(name=name):
                self.assertFalse(is_safe_photo_path(name, self.storage))
                self.assertEqual(remove_unused_photo(name, storage=self.storage), 'unsafe')

    def test_internal_symlink_or_junction_resolution_is_rejected(self):
        root = Path(self.storage.path('')).resolve()
        with patch('pict.services.photo_cleanup.Path.resolve', side_effect=[root, root / 'photos/target.jpg']):
            self.assertFalse(is_safe_photo_path('photos/alias.jpg', self.storage))

    def test_scanner_rejects_directories_outside_supported_roots(self):
        for directories in ((), ('quiz',), ('photos/..',), ('photos', 'cache/thumbnails')):
            with self.subTest(directories=directories), self.assertRaises(ValueError):
                list(iter_stored_photos(self.storage, directories=directories))


class PhotoCleanupCommitTests(PhotoStorageMixin, TransactionTestCase):
    def test_real_commit_cleans_previous_file_without_manual_callback_execution(self):
        record = self.create_record()
        old_name = record.photo.name
        with transaction.atomic():
            record.photo = create_test_image_file('new.jpg')
            record.save(update_fields=['photo'])
            self.assertTrue(self.storage.exists(old_name))
        self.assertFalse(self.storage.exists(old_name))
        self.assertTrue(self.storage.exists(record.photo.name))

    def test_admin_rename_rollback_keeps_old_file_and_database_reference(self):
        old_name = self.store_file(filename='legacy.jpg')
        record = Pict.objects.create(name=123, alt='Описание', photo=old_name)
        model_admin = PictAdmin(Pict, AdminSite())
        request = RequestFactory().post('/admin/pict/pict/')
        with self.assertRaises(RuntimeError), transaction.atomic():
            with patch.object(model_admin, 'message_user'):
                model_admin.rename_photos_from_description(request, Pict.objects.filter(pk=record.pk))
            record.refresh_from_db()
            renamed_name = record.photo.name
            self.assertNotEqual(renamed_name, old_name)
            self.assertTrue(self.storage.exists(old_name))
            raise RuntimeError('Откат внешней транзакции')
        record.refresh_from_db()
        self.assertEqual(record.photo.name, old_name)
        self.assertTrue(self.storage.exists(old_name))
        self.assertTrue(self.storage.exists(renamed_name))

    def test_storage_failure_does_not_turn_committed_save_into_error(self):
        record = self.create_record()
        old_name = record.photo.name
        with self.assertLogs('pict.services.photo_cleanup', level='ERROR'), patch.object(
            self.storage, 'delete', side_effect=OSError('Ошибка удаления оригинала'),
        ), transaction.atomic():
            record.photo = create_test_image_file('new.jpg')
            record.save(update_fields=['photo'])
        record.refresh_from_db()
        self.assertNotEqual(record.photo.name, old_name)
        self.assertTrue(self.storage.exists(old_name))
        self.assertTrue(self.storage.exists(record.photo.name))


class UnusedPhotoCommandTests(PhotoStorageMixin, TestCase):
    def run_command(self, **options):
        output = StringIO()
        call_command('cleanup_unused_photos', stdout=output, **options)
        return output.getvalue()

    def test_default_report_does_not_delete_originals_or_thumbnails(self):
        name = self.store_file()
        thumbnail = get_thumbnail(name, '105')
        output = self.run_command()
        self.assertIn('Режим отчёта', output)
        self.assertIn(name, output)
        self.assertIn('Неиспользуемых файлов: 1', output)
        self.assertIn(f'объём оригиналов: {self.storage.size(name)} байт', output)
        self.assertTrue(self.storage.exists(name))
        self.assertTrue(thumbnail.storage.exists(thumbnail.name))

    def test_table_selection_limits_report_and_directory_scan(self):
        names = {
            'images': self.store_file('photos'),
            'finished-works': self.store_file('finished_works'),
        }
        for table, selected_name in names.items():
            with self.subTest(table=table), patch.object(
                self.storage, 'listdir', wraps=self.storage.listdir,
            ) as listdir:
                output = self.run_command(table=table)
                self.assertIn(selected_name, output)
                self.assertIn('Неиспользуемых файлов: 1', output)
                listdir.assert_called_once_with(selected_name.split('/')[0])
                for other_table, other_name in names.items():
                    if other_table != table:
                        self.assertNotIn(other_name, output)
        for name in names.values():
            self.assertTrue(self.storage.exists(name))

    def assert_selected_table_deletion(self, table, selected_directory, other_directory):
        selected = self.store_file(f'{selected_directory}/nested')
        other = self.store_file(other_directory)
        selected_thumbnail = get_thumbnail(selected, '107')
        other_thumbnail = get_thumbnail(other, '107')
        output = self.run_command(table=table, delete=True)
        self.assertIn('удалено: 1', output)
        self.assertFalse(self.storage.exists(selected))
        self.assertFalse(selected_thumbnail.storage.exists(selected_thumbnail.name))
        self.assertTrue(self.storage.exists(other))
        self.assertTrue(other_thumbnail.storage.exists(other_thumbnail.name))

    def test_images_selection_deletes_only_catalog_originals_and_thumbnails(self):
        self.assert_selected_table_deletion('images', 'photos', 'finished_works')

    def test_finished_works_selection_deletes_only_work_originals_and_thumbnails(self):
        self.assert_selected_table_deletion('finished-works', 'finished_works', 'photos')

    def test_explicit_all_is_equivalent_to_default_scope(self):
        self.store_file('photos')
        self.store_file('finished_works')
        self.assertEqual(self.run_command(), self.run_command(table='all'))

    def test_selected_catalog_directory_keeps_references_from_finished_works(self):
        name = self.store_file('photos')
        FinishedWork.objects.create(name='Общий файл', photo=name, is_published=False)
        thumbnail = get_thumbnail(name, '108')
        self.assertNotIn(name, self.run_command(table='images', delete=True))
        self.assertTrue(self.storage.exists(name))
        self.assertTrue(thumbnail.storage.exists(thumbnail.name))

    def test_selected_work_directory_rechecks_references_from_catalog(self):
        name = self.store_file('finished_works')
        Pict.objects.create(name=123, alt='Общий файл', photo=name)
        with patch('pict.management.commands.cleanup_unused_photos.get_referenced_photo_names', return_value=set()):
            output = self.run_command(table='finished-works', delete=True)
        self.assertIn('referenced:', output)
        self.assertTrue(self.storage.exists(name))

    def test_invalid_table_is_rejected_before_scanning(self):
        with patch('pict.management.commands.cleanup_unused_photos.iter_stored_photos') as scan:
            with self.assertRaises(CommandError):
                self.run_command(table='unknown')
            with self.assertRaises(CommandError):
                call_command('cleanup_unused_photos', '--table', 'unknown', stdout=StringIO())
            scan.assert_not_called()

    def test_delete_removes_only_old_unused_originals_and_their_thumbnails(self):
        picture = self.create_record()
        picture.is_published = False
        picture.save(update_fields=['is_published'])
        self.age_file(picture.photo.name)
        work = self.create_record(FinishedWork)
        self.age_file(work.photo.name)
        orphan_names = [self.store_file(directory) for directory in ('photos', 'finished_works/nested')]
        thumbnails = [get_thumbnail(name, '106') for name in orphan_names]
        fresh = self.store_file(old=False, filename='fresh.jpg')
        unrelated = [self.store_file(directory) for directory in ('quiz', 'cache/thumbnails')]
        output = self.run_command(delete=True)
        self.assertIn('удалено: 2', output)
        self.assertIn('свежих файлов пропущено: 1', output)
        for name in orphan_names:
            self.assertFalse(self.storage.exists(name))
        for thumbnail in thumbnails:
            self.assertFalse(thumbnail.storage.exists(thumbnail.name))
        for name in [picture.photo.name, work.photo.name, fresh, *unrelated]:
            self.assertTrue(self.storage.exists(name))

    def test_delete_rechecks_database_instead_of_trusting_initial_snapshot(self):
        picture = self.create_record()
        self.age_file(picture.photo.name)
        with patch('pict.management.commands.cleanup_unused_photos.get_referenced_photo_names', return_value=set()):
            output = self.run_command(delete=True)
        self.assertIn('referenced:', output)
        self.assertTrue(self.storage.exists(picture.photo.name))

    def test_delete_rechecks_file_age(self):
        name = self.store_file()
        old_time = timezone.now() - timedelta(days=2)
        with patch.object(self.storage, 'get_modified_time', side_effect=[old_time, timezone.now()]):
            output = self.run_command(delete=True)
        self.assertIn('recent:', output)
        self.assertTrue(self.storage.exists(name))

    def test_custom_age_and_explicit_dry_run(self):
        name = self.store_file(old=False)
        timestamp = (timezone.now() - timedelta(hours=2)).timestamp()
        os.utime(self.storage.path(name), (timestamp, timestamp))
        self.assertNotIn(name, self.run_command())
        self.assertIn(name, self.run_command(min_age_hours=1, dry_run=True))
        self.assertTrue(self.storage.exists(name))

    def test_invalid_age_is_rejected(self):
        for hours in (0, -1, 10 ** 20):
            with self.subTest(hours=hours), self.assertRaises(CommandError):
                self.run_command(min_age_hours=hours)

    def test_cleanup_failure_has_nonzero_exit_and_preserves_original(self):
        name = self.store_file()
        with patch('pict.services.photo_cleanup.delete_thumbnail', side_effect=OSError('Ошибка кеша')):
            with self.assertLogs('pict.services.photo_cleanup', level='ERROR'), self.assertRaises(CommandError):
                self.run_command(delete=True)
        self.assertTrue(self.storage.exists(name))

    def test_empty_directories_are_safe(self):
        self.assertIn('Неиспользуемых файлов: 0', self.run_command(delete=True))

    def test_symlink_is_not_followed_or_deleted(self):
        with TemporaryDirectory() as outside:
            target = Path(outside) / 'keep.jpg'
            # Сам оригинал создаётся через отдельный storage вне проверяемого media.
            from django.core.files.storage import FileSystemStorage
            FileSystemStorage(location=outside).save('keep.jpg', create_test_image_file('keep.jpg'))
            link = Path(self.storage.path('photos/link.jpg'))
            link.parent.mkdir(parents=True, exist_ok=True)
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest('Создание символических ссылок недоступно в этой среде.')
            self.assertFalse(is_safe_photo_path('photos/link.jpg', self.storage))
            self.assertIn('Неиспользуемых файлов: 0', self.run_command(delete=True))
            self.assertTrue(link.is_symlink())
            self.assertTrue(target.exists())
