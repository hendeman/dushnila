from django.core.exceptions import ValidationError


INVALID_PAGE_PATH_MESSAGE = (
    'Укажите локальные пути с / без домена, параметров и масок.'
)
INVALID_PAGE_PATH_MASK_MESSAGE = (
    'Укажите локальные пути с / без домена и параметров. '
    'Маска разрешена только в конце пути: /polezno-znat/*.'
)


def normalize_public_page_paths(value, *, allow_subpaths=False):
    """Нормализует пути; при allow_subpaths разрешает конечную маску /*."""
    paths = list(dict.fromkeys(
        '/designer/' if path == '/designer' else path
        for path in (line.strip() for line in value.splitlines())
        if path
    ))
    invalid_path_message = (
        INVALID_PAGE_PATH_MASK_MESSAGE if allow_subpaths else INVALID_PAGE_PATH_MESSAGE
    )
    for path in paths:
        if (
            not path.startswith('/')
            or path.startswith('//')
            or any(character in path for character in '?#\\')
            or any(character.isspace() or ord(character) < 32 for character in path)
            or (
                '*' in path
                and not (allow_subpaths and path.endswith('/*') and path.count('*') == 1)
            )
        ):
            raise ValidationError(invalid_path_message)
    return '\n'.join(paths)


def matches_public_page_path(configured_paths, request_path, *, allow_subpaths=False):
    """Пустой список охватывает все страницы; маска /* включает раздел и вложенность."""
    if not configured_paths:
        return True
    for path in configured_paths.splitlines():
        if request_path == path:
            return True
        if allow_subpaths and path.endswith('/*') and request_path.startswith(path[:-1]):
            return True
    return False
