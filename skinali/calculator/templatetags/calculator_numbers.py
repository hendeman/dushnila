from decimal import Decimal

from django import template
from django.utils import formats

from ..calculation import AREA_DECIMAL_PLACES


register = template.Library()


@register.filter
def area_decimal(value):
    """Выводит расчётную площадь с фиксированным числом десятичных знаков."""
    return formats.number_format(value, decimal_pos=AREA_DECIMAL_PLACES)


@register.filter
def exact_decimal(value):
    """Показывает точную сумму без лишних нулей и промежуточного округления."""
    if isinstance(value, Decimal):
        text = format(value, 'f')
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        return formats.number_format(Decimal(text))
    return formats.localize(value)
