from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.urls import reverse

from ..models import Pict


FAVORITES_SESSION_KEY = 'favorite_pict_ids'
FAVORITES_PENDING_IMPORT_SESSION_KEY = 'pending_favorites_share_token'
FAVORITES_PENDING_ADDED_SESSION_KEY = 'pending_favorites_added_ids'
MAX_FAVORITES = 5
FAVORITES_LIMIT_MESSAGE = 'Избранное переполнено. Удалите лишнее'
FAVORITES_IMPORT_LIMIT_MESSAGE = 'Избранное переполнено'
FAVORITES_SHARE_SALT = 'pict.shared_favorites.v1'
MAX_SHARE_TOKEN_LENGTH = 2048
MAX_PICT_ID = 2**63 - 1


def get_published_favorite_ids(raw_ids):
    """Сохраняет порядок уникальных ID доступных изображений."""
    if not isinstance(raw_ids, (list, tuple)):
        return []

    candidates = []
    for raw_id in raw_ids:
        if isinstance(raw_id, bool):
            continue
        try:
            pict_id = int(raw_id)
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 < pict_id <= MAX_PICT_ID and pict_id not in candidates:
            candidates.append(pict_id)

    published_ids = set(
        Pict.objects.published()
        .filter(pk__in=candidates)
        .values_list('pk', flat=True)
    ) if candidates else set()
    return [pict_id for pict_id in candidates if pict_id in published_ids]


def get_favorite_ids(request):
    raw_ids = request.session.get(FAVORITES_SESSION_KEY, [])
    favorite_ids = get_published_favorite_ids(raw_ids)
    if favorite_ids != raw_ids:
        request.session[FAVORITES_SESSION_KEY] = favorite_ids
    return favorite_ids


def build_favorites_share_url(favorite_ids):
    if not favorite_ids or len(favorite_ids) > MAX_FAVORITES:
        return ''
    token = signing.Signer(salt=FAVORITES_SHARE_SALT).sign_object(
        {'v': 1, 'ids': favorite_ids},
        compress=True,
    )
    path = reverse('favorites_shared')
    query = urlencode({'data': token})
    return f'{settings.PUBLIC_SITE_ORIGIN.rstrip("/")}{path}?{query}'


def read_favorites_share_token(token):
    """Проверяет подпись и ограниченную схему ссылки без срока действия."""
    if not isinstance(token, str) or not 0 < len(token) <= MAX_SHARE_TOKEN_LENGTH:
        raise ValueError('Недопустимая ссылка на избранное')
    try:
        payload = signing.Signer(salt=FAVORITES_SHARE_SALT).unsign_object(token)
    except (signing.BadSignature, ValueError, TypeError) as error:
        raise ValueError('Недопустимая ссылка на избранное') from error

    if (
        not isinstance(payload, dict)
        or type(payload.get('v')) is not int
        or payload['v'] != 1
        or not isinstance(payload.get('ids'), list)
        or not 0 < len(payload['ids']) <= MAX_FAVORITES
        or any(type(pict_id) is not int or not 0 < pict_id <= MAX_PICT_ID
               for pict_id in payload['ids'])
    ):
        raise ValueError('Недопустимая ссылка на избранное')
    return payload['ids']


def get_new_favorite_ids(favorite_ids, incoming_ids):
    """Оставляет только новые ID, сохраняя порядок полученной подборки."""
    known_ids = set(favorite_ids)
    new_ids = []
    for pict_id in incoming_ids:
        if pict_id not in known_ids:
            new_ids.append(pict_id)
            known_ids.add(pict_id)
    return new_ids


def get_pending_favorites_import(request, favorite_ids):
    """Возвращает токен, число оставшихся и уже добавленных изображений."""
    token = request.session.get(FAVORITES_PENDING_IMPORT_SESSION_KEY, '')
    if not token:
        return '', 0, 0
    try:
        shared_ids = read_favorites_share_token(token)
    except ValueError:
        shared_ids = []
    available_ids = get_published_favorite_ids(shared_ids)
    remaining_ids = get_new_favorite_ids(favorite_ids, available_ids)
    if not remaining_ids:
        clear_pending_favorites_import(request)
        return '', 0, 0
    added_ids = get_pending_added_favorite_ids(request, token)
    added_count = len(set(added_ids) & set(favorite_ids) & set(available_ids))
    return token, len(remaining_ids), added_count


def get_pending_added_favorite_ids(request, token):
    """Сохраняет историю добавленных ID только при повторе той же подборки."""
    if request.session.get(FAVORITES_PENDING_IMPORT_SESSION_KEY) != token:
        return []
    raw_ids = request.session.get(FAVORITES_PENDING_ADDED_SESSION_KEY, [])
    if not isinstance(raw_ids, list):
        return []
    return get_new_favorite_ids([], [pict_id for pict_id in raw_ids if type(pict_id) is int])


def clear_pending_favorites_import(request):
    request.session.pop(FAVORITES_PENDING_IMPORT_SESSION_KEY, None)
    request.session.pop(FAVORITES_PENDING_ADDED_SESSION_KEY, None)
