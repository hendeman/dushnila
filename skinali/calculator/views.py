import json
import logging

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_safe

from pict.services.favorites import get_favorite_ids
from pict.forms import CalculatorOrderContactForm
from pict.views import resolve_site_page_metadata, set_page_metadata
from sitecontent.models import PriceTable, SitePage

from .calculation import CalculatorConfigurationError
from .public import get_public_calculator
from .sharing import (
    INVALID_SHARE_MESSAGE, MAX_SHARE_REQUEST_BYTES, UNAVAILABLE_SHARE_MESSAGE,
    build_calculation_share_url, parse_calculation_input, read_calculation_share_token,
    serialize_calculation_input, validate_shared_calculation,
)


logger = logging.getLogger(__name__)


def _public_calculator():
    try:
        return get_public_calculator()
    except CalculatorConfigurationError:
        logger.warning('Публичный калькулятор недоступен: проверьте тарифы и настройки.', exc_info=True)
        return None, None


@never_cache
@require_safe
def price(request):
    tariffs, configuration = _public_calculator()
    initial_input = None
    share_error = ''
    status = 200
    is_shared = 'calculation' in request.GET
    if is_shared:
        try:
            data = read_calculation_share_token(request.GET.get('calculation'))
        except ValidationError:
            share_error, status = INVALID_SHARE_MESSAGE, 400
        else:
            if configuration:
                try:
                    data = validate_shared_calculation(data, configuration, tariffs)
                    initial_input = serialize_calculation_input(data)
                except (ValidationError, CalculatorConfigurationError):
                    share_error, status = UNAVAILABLE_SHARE_MESSAGE, 409
    context = {
        'title': 'Рассчитайте стоимость скинали', 'calculator_config': configuration,
        'favorites_count': len(get_favorite_ids(request)),
        'calculation_initial_input': initial_input, 'calculation_share_error': share_error,
        'calculator_order_form': CalculatorOrderContactForm(prefix='calculator_order') if configuration else None,
        'price_tables': PriceTable.objects.filter(
            is_published=True, rows__isnull=False,
        ).distinct().prefetch_related('rows'),
    }
    page_title, description = resolve_site_page_metadata(
        SitePage.Code.PRICE, default_page_title='Цена скинали — калькулятор стоимости | ОДИУМ',
        default_meta_description='Рассчитайте стоимость скинали по размерам вашей кухни: стекло, декорирование, услуги и подъём с учётом действующих акций.',
    )
    set_page_metadata(
        context, request, page_title=page_title, meta_description=description,
        canonical_path=reverse('price'),
        breadcrumbs=(('Главная', reverse('home')), ('Цена', None)),
    )
    if is_shared:
        context['meta_robots'] = 'noindex,follow'
    response = render(request, 'calculator/price.html', context, status=status)
    if is_shared:
        response['Referrer-Policy'] = 'no-referrer'
        response['X-Robots-Tag'] = 'noindex, follow'
    return response


@never_cache
@require_POST
def share_calculation(request):
    if request.content_type != 'application/json':
        return JsonResponse({'message': 'Передайте параметры расчёта в формате JSON.'}, status=415)
    if int(request.META.get('CONTENT_LENGTH') or 0) > MAX_SHARE_REQUEST_BYTES:
        return JsonResponse({'message': 'Слишком большой расчёт.'}, status=413)
    body = request.body
    if len(body) > MAX_SHARE_REQUEST_BYTES:
        return JsonResponse({'message': 'Слишком большой расчёт.'}, status=413)
    tariffs, configuration = _public_calculator()
    if not configuration:
        return JsonResponse({'message': 'Калькулятор сейчас недоступен. Попробуйте позже.'}, status=503)
    try:
        raw = json.loads(body)
        data = validate_shared_calculation(parse_calculation_input(raw), configuration, tariffs)
        url = build_calculation_share_url(data)
    except (ValueError, TypeError, ValidationError, RecursionError):
        return JsonResponse({'message': 'Параметры расчёта изменились или заполнены неверно. Обновите страницу и проверьте ввод.'}, status=400)
    return JsonResponse({'url': url})
