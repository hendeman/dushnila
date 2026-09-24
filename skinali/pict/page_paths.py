from django.core.exceptions import ValidationError


INVALID_PAGE_PATH_MESSAGE = (
    'Укажите локальные пути с / без домена, параметров и масок.'
)


def normalize_public_page_paths(value):
    """Нормализует точные публичные пути, заданные по одному на строку."""
    paths = list(dict.fromkeys(
        line.strip()
        for line in value.splitlines()
        if line.strip()
    ))
    for path in paths:
        if (
            not path.startswith('/')
            or path.startswith('//')
            or any(character in path for character in '?#*\\')
            or any(character.isspace() or ord(character) < 32 for character in path)
        ):
            raise ValidationError(INVALID_PAGE_PATH_MESSAGE)
    return '\n'.join(paths)


def matches_public_page_path(configured_paths, request_path):
    """Пустой список охватывает все страницы, иначе требуется точное совпадение."""
    return not configured_paths or request_path in configured_paths.splitlines()
