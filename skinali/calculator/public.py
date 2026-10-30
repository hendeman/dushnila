from django.core.exceptions import ValidationError

from .calculation import (
    AREA_DECIMAL_PLACES, CalculatorConfigurationError, DEFAULT_STAIR_FLOOR, MAX_INTEGER, MAX_PANELS,
    MAX_PANEL_DIMENSION_MM, MAX_QUANTITY, MAX_STAIR_FLOOR, MIN_STAIR_FLOOR, configured_discount_percent, configured_price, material_discount_configuration, service_quantity_limit,
)
from .models import CalculatorSettings, CalculatorTariffs, DecorationType, GlassType, QUANTITY_DECIMAL_PLACES, QUANTITY_STEP, validate_stair_rule_counts


def get_public_calculator():
    """Загружает действующие публичные тарифы для страницы, ссылок и заявок."""
    settings = CalculatorSettings.objects.filter(pk=CalculatorSettings.CODE).first()
    if not settings or not settings.is_enabled:
        return None, None
    tariffs = CalculatorTariffs.objects.select_related(
        'default_glass_type', 'default_decoration_type',
    ).filter(pk=CalculatorTariffs.CODE).first()
    if tariffs is None:
        raise CalculatorConfigurationError('Не найдены тарифы калькулятора.')
    return tariffs, public_configuration(tariffs, settings)


def public_configuration(tariffs, settings):
    """Передаёт браузеру только публичные варианты и необходимые для расчёта тарифы."""
    result = {'max_panels': MAX_PANELS, 'max_integer': MAX_INTEGER, 'max_quantity': str(MAX_QUANTITY)}
    result['quantity_step'] = str(QUANTITY_STEP)
    result['quantity_decimal_places'] = QUANTITY_DECIMAL_PLACES
    result['area_decimal_places'] = AREA_DECIMAL_PLACES
    result['minimum_order_area_sqm'] = str(configured_price(settings.minimum_order_area_sqm, 'Минимальный заказ'))
    result['max_panel_dimension_mm'] = MAX_PANEL_DIMENSION_MM
    result['max_stair_floor'] = MAX_STAIR_FLOOR
    result['min_stair_floor'] = MIN_STAIR_FLOOR
    result['initial_stair_floor'] = DEFAULT_STAIR_FLOOR
    result['panels_hint'] = tariffs.panels_hint.strip()
    for field, model in (('glass_type', GlassType), ('decoration_type', DecorationType)):
        visible = getattr(tariffs, f'show_{field}')
        default = getattr(tariffs, f'default_{field}')
        options = list(model.objects.filter(is_visible=True)) if visible else [default]
        if not options or any(option is None for option in options):
            raise CalculatorConfigurationError('Не настроены материалы калькулятора.')
        if default is not None and visible and default.pk not in {option.pk for option in options}:
            raise CalculatorConfigurationError('Материал по умолчанию недоступен.')
        result[field] = {
            'visible': visible, 'default': default.pk if default else None,
            'hint': getattr(tariffs, f'{field}_hint').strip(),
            'options': [{'id': option.pk, 'name': option.name,
                         'price': str(configured_price(option.price_per_sqm, option.name))}
                        for option in options],
        }
    result['services'] = []
    for service in tariffs.services.filter(is_visible=True).select_related('unit'):
        limit = service_quantity_limit(service)
        if limit is not None and service.whole_quantity:
            limit = int(limit)
        result['services'].append({
            'id': service.pk, 'name': service.name, 'has_price': service.has_price, 'hint': service.hint.strip(),
            'calculation_type': service.calculation_type, 'selectable': service.is_selectable,
            'requires_manual_quantity': service.requires_manual_quantity,
            'discount_percent': str(configured_discount_percent(service.discount_percent, service.name)) if service.is_order_discount else '0',
            'fixed_price': service.fixed_price, 'use_panel_area': service.use_panel_area,
            'whole_quantity': service.whole_quantity, 'quantity_label': service.quantity_label,
            'max_quantity': str(limit) if limit is not None else None,
            'initial_quantity': (str(min(1, limit)) if service.whole_quantity
                                 else f'{min(1, limit):.{QUANTITY_DECIMAL_PLACES}f}') if limit is not None else '1',
            'unit': service.unit.symbol if service.unit_id else '',
            'price': str(configured_price(service.price_per_unit, service.name)) if service.has_price and not service.is_order_discount else '0',
        })
    result['stairs'] = None
    if tariffs.show_stair_lifting:
        rules = tariffs.get_stair_lifting_rules()
        try:
            validate_stair_rule_counts(rules)
        except ValidationError as error:
            raise CalculatorConfigurationError(error.messages)
        result['stairs'] = {
            'hint': tariffs.stair_lifting_hint.strip(),
            'base': str(configured_price(tariffs.stair_lifting_min_price, 'Подъём')),
            'per_floor': str(configured_price(tariffs.stair_lifting_price_per_panel_floor, 'Дополнительный этаж')),
            'rules': [{'count': count, 'floor': floor, 'multiplier': str(multiplier)}
                      for count, (floor, multiplier) in sorted(rules.items())],
        }
    result['material_discount'] = material_discount_configuration(settings)
    result['marketing_discount_percent'] = str(settings.marketing_discount_percent)
    result['marketing_discount_description'] = settings.marketing_discount_description.strip()
    return result
