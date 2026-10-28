import re
from dataclasses import replace
from urllib.parse import parse_qs, urlencode, urlsplit

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.urls import reverse

from .calculation import CalculationInput, Panel, ServiceSelection, calculate_price
from .models import QUANTITY_DECIMAL_PLACES
from .public import get_public_calculator


SHARE_SALT = 'calculator.shared_calculation.v1'
MAX_SHARE_TOKEN_LENGTH = 4096
MAX_SHARE_REQUEST_BYTES = 16384
MAX_SHARED_SERVICES = 100
INVALID_SHARE_MESSAGE = 'Ссылка на расчёт недействительна. Создайте новую ссылку.'
UNAVAILABLE_SHARE_MESSAGE = 'Некоторые параметры расчёта больше недоступны. Составьте новый расчёт по действующим условиям.'


def _integer(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,19}', value):
        return int(value)
    raise ValidationError('Проверьте числовые параметры расчёта.')


def parse_calculation_input(raw):
    """Проверяет схему ссылки независимо от текущих тарифов."""
    if not isinstance(raw, dict) or set(raw) - {'panels', 'glass_type', 'decoration_type', 'services', 'stairs'}:
        raise ValidationError(INVALID_SHARE_MESSAGE)
    panels = raw.get('panels')
    services = raw.get('services', [])
    if not isinstance(panels, list) or not isinstance(services, list) or len(services) > MAX_SHARED_SERVICES:
        raise ValidationError(INVALID_SHARE_MESSAGE)
    parsed_panels = []
    for panel in panels:
        if not isinstance(panel, dict) or set(panel) != {'width', 'height'}:
            raise ValidationError(INVALID_SHARE_MESSAGE)
        parsed_panels.append(Panel(_integer(panel['width']), _integer(panel['height'])))
    parsed_services = []
    for service in services:
        if not isinstance(service, dict) or set(service) != {'id', 'quantity'}:
            raise ValidationError(INVALID_SHARE_MESSAGE)
        quantity = service['quantity']
        if not isinstance(quantity, str) or not re.fullmatch(
            rf'[0-9]{{1,9}}(?:\.[0-9]{{1,{QUANTITY_DECIMAL_PLACES}}})?', quantity,
        ):
            raise ValidationError(INVALID_SHARE_MESSAGE)
        parsed_services.append(ServiceSelection(_integer(service['id']), quantity))
    option_ids = {}
    for name in ('glass_type', 'decoration_type'):
        value = raw.get(name)
        option_ids[f'{name}_id'] = None if value is None else _integer(value)
        if value is not None and not 0 < option_ids[f'{name}_id'] <= 2**63 - 1:
            raise ValidationError(INVALID_SHARE_MESSAGE)
    stairs = raw.get('stairs')
    floor = count = None
    if stairs is not None:
        if not isinstance(stairs, dict) or set(stairs) != {'floor', 'count'}:
            raise ValidationError(INVALID_SHARE_MESSAGE)
        floor, count = _integer(stairs['floor']), _integer(stairs['count'])
    return CalculationInput(
        tuple(parsed_panels), services=tuple(parsed_services),
        stair_floor=floor, stair_panel_count=count, **option_ids,
    )


def validate_shared_calculation(data, configuration, tariffs):
    """Исключает скрытые параметры и проверяет расчёт общей серверной формулой."""
    selected_options = {}
    for name in ('glass_type', 'decoration_type'):
        option_id = getattr(data, f'{name}_id')
        if option_id is None:
            option_id = configuration[name]['default']
        if option_id not in {item['id'] for item in configuration[name]['options']}:
            raise ValidationError(UNAVAILABLE_SHARE_MESSAGE)
        selected_options[f'{name}_id'] = option_id
    available_services = {item['id'] for item in configuration['services'] if item['has_price']}
    if any(item.service_id not in available_services for item in data.services):
        raise ValidationError(UNAVAILABLE_SHARE_MESSAGE)
    if data.stair_floor is not None and not configuration['stairs']:
        raise ValidationError(UNAVAILABLE_SHARE_MESSAGE)
    data = replace(data, **selected_options)
    calculate_price(data, settings=tariffs)
    return data


def serialize_calculation_input(data):
    return {
        'panels': [{'width': panel.width_mm, 'height': panel.height_mm} for panel in data.panels],
        'glass_type': data.glass_type_id,
        'decoration_type': data.decoration_type_id,
        'services': [{'id': item.service_id, 'quantity': format(item.quantity, 'f')} for item in data.services],
        'stairs': {'floor': data.stair_floor, 'count': data.stair_panel_count} if data.stair_floor is not None else None,
    }


def build_calculation_share_url(data):
    token = signing.Signer(salt=SHARE_SALT).sign_object(
        {'v': 1, 'input': serialize_calculation_input(data)}, compress=True,
    )
    if len(token) > MAX_SHARE_TOKEN_LENGTH:
        raise ValidationError('В расчёте слишком много параметров для одной ссылки.')
    return f'{settings.PUBLIC_SITE_ORIGIN.rstrip("/")}{reverse("price")}?{urlencode({"calculation": token})}'


def read_calculation_share_token(token):
    if not isinstance(token, str) or not 0 < len(token) <= MAX_SHARE_TOKEN_LENGTH:
        raise ValidationError(INVALID_SHARE_MESSAGE)
    try:
        payload = signing.Signer(salt=SHARE_SALT).unsign_object(token)
        if not isinstance(payload, dict) or set(payload) != {'v', 'input'} or type(payload['v']) is not int or payload['v'] != 1:
            raise ValueError
        return parse_calculation_input(payload['input'])
    except (signing.BadSignature, ValueError, TypeError, ValidationError, RecursionError):
        raise ValidationError(INVALID_SHARE_MESSAGE) from None


def validate_calculation_share_url(url):
    """Проверяет свой адрес, подпись и актуальные параметры скрытой ссылки заявки."""
    try:
        parts = urlsplit(url)
        origin = urlsplit(settings.PUBLIC_SITE_ORIGIN)
        if (parts.scheme, parts.netloc, parts.path) != (origin.scheme, origin.netloc, reverse('price')) or parts.fragment:
            raise ValueError
        query = parse_qs(parts.query, keep_blank_values=True, strict_parsing=True, max_num_fields=1)
        if set(query) != {'calculation'} or len(query['calculation']) != 1:
            raise ValueError
        data = read_calculation_share_token(query['calculation'][0])
    except (ValueError, TypeError, ValidationError):
        raise ValidationError(INVALID_SHARE_MESSAGE) from None
    tariffs, configuration = get_public_calculator()
    if not configuration:
        raise ValidationError('Калькулятор сейчас недоступен. Попробуйте позже.')
    try:
        data = validate_shared_calculation(data, configuration, tariffs)
        return build_calculation_share_url(data)
    except ValidationError:
        raise ValidationError(UNAVAILABLE_SHARE_MESSAGE) from None
