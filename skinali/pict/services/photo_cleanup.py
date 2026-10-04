"""Очистка неиспользуемых оригиналов каталога и готовых работ."""

import logging
from pathlib import Path, PurePosixPath

from django.apps import apps
from django.db import DEFAULT_DB_ALIAS, models, transaction
from sorl.thumbnail.images import ImageFile
from sorl.thumbnail.shortcuts import delete as delete_thumbnail


logger = logging.getLogger(__name__)
PHOTO_TABLE_DIRECTORIES = {
    'images': 'photos',
    'finished-works': 'finished_works',
}
PHOTO_DIRECTORIES = tuple(PHOTO_TABLE_DIRECTORIES.values())


def is_safe_photo_path(name, storage):
    """Ограничивает очистку папками оригиналов, без обхода через ссылки."""
    if not name or '\\' in name or ':' in name:
        return False
    parts = name.split('/')
    if (
        len(parts) < 2
        or parts[0] not in PHOTO_DIRECTORIES
        or any(part in ('', '.', '..') for part in parts)
    ):
        return False
    try:
        storage_path = Path(storage.path(name))
    except NotImplementedError:
        # Для удалённого storage граница задаётся относительным ключом.
        return True
    root = Path(storage.path('')).resolve()
    expected_directory = root / parts[0]
    resolved_path = storage_path.resolve()
    if (
        not resolved_path.is_relative_to(expected_directory)
        or resolved_path != root.joinpath(*parts)
    ):
        return False
    return not any(
        root.joinpath(*parts[:index]).is_symlink()
        for index in range(1, len(parts) + 1)
    )


def iter_file_fields():
    """Учитывает также ручные ссылки на оригиналы из других моделей сайта."""
    for model in apps.get_models():
        if model._meta.managed and not model._meta.proxy:
            for field in model._meta.local_fields:
                if isinstance(field, models.FileField):
                    yield model, field


def get_referenced_photo_names(*, using=DEFAULT_DB_ALIAS):
    names = set()
    for model, field in iter_file_fields():
        names.update(
            model._base_manager.using(using)
            .exclude(**{field.attname: ''})
            .exclude(**{f'{field.attname}__isnull': True})
            .values_list(field.attname, flat=True)
            .iterator(chunk_size=1000)
        )
    return names


def is_photo_referenced(name, *, using=DEFAULT_DB_ALIAS):
    # Совпадение пути даже в другом storage трактуем консервативно: не удаляем.
    return any(
        model._base_manager.using(using).filter(**{field.attname: name}).exists()
        for model, field in iter_file_fields()
    )


def remove_unused_photo(name, *, storage, using=DEFAULT_DB_ALIAS, older_than=None):
    """Возвращает результат; ошибки очистки не отменяют сохранённую запись."""
    try:
        if not is_safe_photo_path(name, storage):
            return 'unsafe'
        if is_photo_referenced(name, using=using):
            return 'referenced'
        exists = storage.exists(name)
        if exists and older_than is not None:
            if storage.get_modified_time(name) >= older_than:
                return 'recent'
        # При ошибке миниатюр сохраняем оригинал для повторной попытки очистки.
        delete_thumbnail(ImageFile(name, storage=storage), delete_file=False)
        if exists:
            storage.delete(name)
        return 'deleted' if exists else 'missing'
    except Exception:
        logger.exception('Не удалось очистить неиспользуемую фотографию %s.', name)
        return 'failed'


def schedule_photo_cleanup(name, *, storage, using):
    """Откат любой внешней транзакции отменяет удаление прежнего файла."""
    if name:
        transaction.on_commit(
            lambda: remove_unused_photo(name, storage=storage, using=using),
            using=using,
        )


def iter_stored_photos(storage, *, directories=PHOTO_DIRECTORIES):
    """Обходит выбранные папки оригиналов, не трогая кеш и другие media."""
    directories = tuple(directories)
    if not directories or any(directory not in PHOTO_DIRECTORIES for directory in directories):
        raise ValueError('Для очистки допустимы только папки оригиналов фотографий.')
    pending = list(reversed(directories))
    while pending:
        directory = pending.pop()
        if not is_safe_photo_path(f'{directory}/__scope_check__', storage):
            continue
        try:
            directories, files = storage.listdir(directory)
        except FileNotFoundError:
            continue
        for filename in sorted(files):
            name = str(PurePosixPath(directory) / filename)
            if is_safe_photo_path(name, storage):
                yield name
        for child in sorted(directories, reverse=True):
            pending.append(str(PurePosixPath(directory) / child))
