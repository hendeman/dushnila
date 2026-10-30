from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP, localcontext

from django.core.exceptions import ValidationError

from .models import CalculatorSettings, CalculatorTariffs, DecorationType, GlassType, MaterialDiscountMode, MIN_DISCOUNT_RULE_START, MAX_DISCOUNT_RULES, MAX_STAIR_PANELS, QUANTITY_STEP, validate_stair_rule_counts


ZERO = Decimal('0')
AREA_DECIMAL_PLACES = 2
MAX_PANELS = 10
MAX_PANEL_DIMENSION_MM = 6000
MIN_STAIR_FLOOR = 2
MAX_STAIR_FLOOR = 12
DEFAULT_STAIR_FLOOR = MIN_STAIR_FLOOR
MAX_INTEGER = 999_999_999
MAX_QUANTITY = Decimal(MAX_INTEGER) + 1 - QUANTITY_STEP


class CalculatorConfigurationError(ValidationError):
    """Сохранённых настроек недостаточно для достоверного расчёта."""


def validate_integer(value, *, minimum=0, maximum=MAX_INTEGER):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValidationError('Укажите допустимое целое число.')


@dataclass(frozen=True)
class Panel:
    width_mm: int
    height_mm: int

    def __post_init__(self):
        validate_integer(self.width_mm, minimum=1, maximum=MAX_PANEL_DIMENSION_MM)
        validate_integer(self.height_mm, minimum=1, maximum=MAX_PANEL_DIMENSION_MM)

    @property
    def area_sqm(self):
        return Decimal(self.width_mm) * Decimal(self.height_mm) / Decimal('1000000')


@dataclass(frozen=True)
class ServiceSelection:
    service_id: int
    quantity: Decimal = Decimal('1')

    def __post_init__(self):
        validate_integer(self.service_id, minimum=1)
        try:
            if isinstance(self.quantity, (bool, float)):
                raise InvalidOperation
            value = Decimal(self.quantity)
            if not value.is_finite() or not ZERO <= value <= MAX_QUANTITY or value != value.quantize(QUANTITY_STEP):
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            raise ValidationError('Укажите неотрицательное количество с точностью до двух знаков.')
        object.__setattr__(self, 'quantity', value)


@dataclass(frozen=True)
class CalculationInput:
    panels: tuple[Panel, ...]
    glass_type_id: int | None = None
    decoration_type_id: int | None = None
    services: tuple[ServiceSelection, ...] = ()
    stair_floor: int | None = None
    stair_panel_count: int | None = None

    def __post_init__(self):
        if (
            not isinstance(self.panels, (tuple, list))
            or not 1 <= len(self.panels) <= MAX_PANELS
            or not all(isinstance(panel, Panel) for panel in self.panels)
        ):
            raise ValidationError(f'Добавьте от 1 до {MAX_PANELS} заполненных панелей.')
        object.__setattr__(self, 'panels', tuple(self.panels))
        if not isinstance(self.services, (tuple, list)) or not all(isinstance(item, ServiceSelection) for item in self.services):
            raise ValidationError('Передайте выбранные услуги с количеством.')
        if len({item.service_id for item in self.services}) != len(self.services):
            raise ValidationError('Каждая услуга должна быть выбрана один раз.')
        object.__setattr__(self, 'services', tuple(self.services))
        if self.stair_floor is not None:
            try:
                validate_integer(self.stair_floor, minimum=MIN_STAIR_FLOOR, maximum=MAX_STAIR_FLOOR)
            except ValidationError:
                raise ValidationError({'stair_floor': f'Укажите этаж от {MIN_STAIR_FLOOR} до {MAX_STAIR_FLOOR}.'})
            if self.stair_panel_count is None:
                raise ValidationError({'stair_panel_count': 'Укажите количество панелей для подъёма.'})
        if self.stair_panel_count is not None:
            try:
                validate_integer(self.stair_panel_count, minimum=1, maximum=MAX_STAIR_PANELS)
            except ValidationError:
                raise ValidationError({'stair_panel_count': f'Для подъёма по лестнице укажите от 1 до {MAX_STAIR_PANELS} панелей.'})


@dataclass(frozen=True)
class PriceLine:
    code: str
    label: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    amount: Decimal
    included: bool = False
    description: str = ''


@dataclass(frozen=True)
class CalculationResult:
    panels: tuple[Panel, ...]
    area_sqm: Decimal
    lines: tuple[PriceLine, ...]
    subtotal: Decimal
    total: Decimal
    rounding_adjustment: Decimal
    material_discount_mode: str
    materials_discount: Decimal
    marketing_discount_percent: Decimal
    comparison_total: Decimal
    order_discount_percent: Decimal
    order_discount: Decimal

    @property
    def panel_count(self):
        return len(self.panels)


def resolve_option(settings, model, field, selected_id):
    if not getattr(settings, f'show_{field}'):
        option = getattr(settings, f'default_{field}')
        if option is None:
            raise CalculatorConfigurationError('Выберите материалы по умолчанию в настройках калькулятора.')
        return option
    if selected_id is None:
        selected_id = getattr(settings, f'default_{field}_id')
    if isinstance(selected_id, bool) or not isinstance(selected_id, int) or selected_id <= 0:
        raise ValidationError({field: 'Выберите доступный вариант.'})
    option = model.objects.filter(pk=selected_id, is_visible=True).first()
    if option is None:
        raise ValidationError({field: 'Этот вариант больше недоступен. Выберите другой.'})
    return option


def configured_price(value, label):
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise CalculatorConfigurationError(f'Не задан корректный тариф: {label}. Проверьте настройки калькулятора.')
    return value


def configured_discount_percent(value, label):
    value = configured_price(value, label)
    if value > 100:
        raise CalculatorConfigurationError(f'Скидка «{label}» должна быть от 0 до 100%.')
    return value


def service_quantity_limit(service):
    """Единый предел ручного ввода для формы, расчёта и публичной конфигурации."""
    if not service.requires_manual_quantity:
        return None
    if service.max_quantity is not None:
        return service.max_quantity
    return Decimal(MAX_INTEGER) if service.whole_quantity else MAX_QUANTITY


def material_discount_configuration(settings):
    """Единые проверенные правила для серверного расчёта и браузера."""
    mode = settings.material_discount_mode
    if mode not in MaterialDiscountMode.values:
        raise CalculatorConfigurationError('Выберите допустимый вид скидки.')
    rules = []
    if mode != MaterialDiscountMode.NONE:
        previous = None
        for rule in settings.discount_rules.filter(mode=mode).order_by('area_from'):
            start = configured_price(rule.area_from, 'Порог площади скидки')
            percent = configured_discount_percent(rule.discount_percent, 'Процент скидки')
            if start < MIN_DISCOUNT_RULE_START or start == previous:
                raise CalculatorConfigurationError('Проверьте пороги и проценты скидки.')
            rules.append({'area_from': str(start), 'percent': str(percent)})
            previous = start
        if not 1 <= len(rules) <= MAX_DISCOUNT_RULES:
            raise CalculatorConfigurationError(f'Добавьте от 1 до {MAX_DISCOUNT_RULES} ступеней для выбранной скидки.')
    return {'mode': mode, 'minimum_area': rules[0]['area_from'] if rules else None, 'rules': rules}


def material_discount_amount(area, price_per_sqm, configuration):
    """Разовая скидка на весь объём либо отдельные ставки на участки площади."""
    mode = configuration['mode']
    if mode == MaterialDiscountMode.NONE or area < Decimal(configuration['minimum_area']):
        return ZERO
    rules = [(Decimal(rule['area_from']), Decimal(rule['percent'])) for rule in configuration['rules']]
    if mode == MaterialDiscountMode.STEPPED:
        percent = next((percent for start, percent in reversed(rules) if area >= start), ZERO)
        return area * price_per_sqm * percent / Decimal('100')
    # В прогрессивной таблице 2 означает второй метр — участок от 1 до 2 м².
    rules = [(number - Decimal('1'), percent) for number, percent in rules]
    discount_area = ZERO
    for index, (start, percent) in enumerate(rules):
        end = min(area, rules[index + 1][0]) if index + 1 < len(rules) else area
        discount_area += max(ZERO, end - start) * percent / Decimal('100')
    return discount_area * price_per_sqm


def calculate_price(data, *, settings=None):
    """Общий серверный расчёт по сохранённым тарифам без промежуточного округления."""
    if not isinstance(data, CalculationInput):
        raise TypeError('Ожидается CalculationInput.')
    if settings is None:
        settings = CalculatorTariffs.objects.select_related(
            'default_glass_type', 'default_decoration_type',
        ).filter(pk=CalculatorTariffs.CODE).first()
    if settings is None:
        raise CalculatorConfigurationError('Сначала создайте настройки калькулятора штатной миграцией.')
    glass = resolve_option(settings, GlassType, 'glass_type', data.glass_type_id)
    decoration = resolve_option(settings, DecorationType, 'decoration_type', data.decoration_type_id)
    general_settings = CalculatorSettings.objects.filter(pk=CalculatorSettings.CODE).first()
    if general_settings is None:
        raise CalculatorConfigurationError('Не найдены общие настройки калькулятора.')
    discount_configuration = material_discount_configuration(general_settings)
    marketing_discount_percent = configured_price(general_settings.marketing_discount_percent, 'Маркетинговая скидка')
    if marketing_discount_percent >= 100:
        raise CalculatorConfigurationError('Маркетинговая скидка должна быть от 0 до 99,99%.')

    with localcontext() as context:
        context.prec = 50
        area = sum((panel.area_sqm for panel in data.panels), ZERO).quantize(
            Decimal('1').scaleb(-AREA_DECIMAL_PLACES), rounding=ROUND_HALF_UP,
        )
        lines = []

        def add_line(code, label, quantity, unit, price, *, description=''):
            price = configured_price(price, label)
            lines.append(PriceLine(code, label, quantity, unit, price, quantity * price, description=description))

        add_line('glass', f'Стекло: {glass.name}', area, 'м²', glass.price_per_sqm)
        add_line('decoration', f'Декорирование: {decoration.name}', area, 'м²', decoration.price_per_sqm)
        materials_discount = material_discount_amount(
            area, lines[0].unit_price + lines[1].unit_price, discount_configuration,
        )
        if materials_discount:
            lines.append(PriceLine(
                'materials_discount', 'Скидка на стекло и декорирование', Decimal('1'), 'заказ',
                -materials_discount, -materials_discount,
                description=MaterialDiscountMode(discount_configuration['mode']).label,
            ))
        if settings.show_stair_lifting:
            if data.stair_floor is not None:
                rules = settings.get_stair_lifting_rules()
                try:
                    validate_stair_rule_counts(rules)
                except ValidationError:
                    raise CalculatorConfigurationError('Заполните таблицу правил подъёма в настройках калькулятора.')
                if data.stair_panel_count not in rules:
                    raise ValidationError({
                        'stair_panel_count': f'Для подъёма по лестнице укажите от 1 до {len(rules)} панелей.',
                    })
                included_floor, multiplier = rules[data.stair_panel_count]
                try:
                    validate_integer(included_floor)
                except ValidationError:
                    raise CalculatorConfigurationError('Проверьте включённые этажи в таблице правил подъёма.')
                multiplier = configured_price(multiplier, 'Коэффициент сложности подъёма')
                extra_floors = max(0, data.stair_floor - included_floor)
                tariff = configured_price(settings.stair_lifting_price_per_panel_floor, 'Подъём по лестнице')
                add_line(
                    'stair_lifting', 'Подъём по лестнице — стандартная стоимость', Decimal('1'),
                    'заказ', settings.stair_lifting_min_price,
                    description=(f'Панелей для подъёма: {data.stair_panel_count}. ' + (
                        f'Стандартная стоимость действует по {included_floor}-й этаж включительно.'
                        if included_floor else 'Доплата начисляется с первого этажа.'
                    )),
                )
                if extra_floors:
                    add_line(
                        'stair_lifting_extra', (
                            f'Доплата за подъём выше {included_floor}-го этажа'
                            if included_floor else 'Доплата за подъём с первого этажа'
                        ),
                        Decimal(extra_floors), 'доп. этаж', tariff * multiplier,
                        description=f'Коэффициент доплаты для выбранного количества панелей: {multiplier.normalize():f}.',
                    )
            else:
                lines.append(PriceLine('standard_lifting', 'Стандартный подъём', Decimal('1'), 'заказ', ZERO, ZERO, included=True))
        selected = {item.service_id: item.quantity for item in data.services}
        order_discounts = []
        for service in settings.services.filter(is_visible=True).select_related('unit'):
            unit = service.unit.symbol if service.unit_id else ''
            if service.is_order_discount:
                if service.pk in selected:
                    order_discounts.append((service.name, configured_discount_percent(service.discount_percent, service.name)))
            elif not service.has_price:
                lines.append(PriceLine(service.code, service.name, Decimal('1'), unit, ZERO, ZERO, included=True))
            elif service.pk in selected:
                if service.fixed_price:
                    quantity, unit = Decimal('1'), 'заказ'
                elif service.use_panel_area:
                    quantity = area
                else:
                    quantity = selected[service.pk]
                if service.requires_manual_quantity and (
                    quantity <= 0 or (service.whole_quantity and quantity != quantity.to_integral_value())
                ):
                    raise ValidationError({f'service_quantity_{service.pk}': 'Укажите допустимое количество больше нуля.'})
                limit = service_quantity_limit(service)
                if limit is not None and quantity > limit:
                    raise ValidationError({f'service_quantity_{service.pk}': f'Укажите количество не больше {limit:f}.'})
                add_line(service.code, service.name, quantity, unit, service.price_per_unit)

        subtotal = sum((line.amount for line in lines), ZERO)
        requested_discount = sum((percent for _, percent in order_discounts), ZERO)
        order_discount_percent = min(Decimal('100'), requested_discount)
        order_discount = subtotal * order_discount_percent / Decimal('100')
        if order_discounts:
            description = '; '.join(f'{name} — {percent.normalize():f}%' for name, percent in order_discounts)
            if requested_discount > 100:
                description += '. Общая скидка ограничена 100%.'
            lines.append(PriceLine(
                'order_discount', order_discounts[0][0] if len(order_discounts) == 1 else 'Скидки на весь заказ',
                order_discount_percent, '%', -subtotal / Decimal('100') if subtotal else ZERO,
                -order_discount if order_discount else ZERO,
                description=description,
            ))
        subtotal -= order_discount
        total = subtotal.quantize(Decimal('1'), rounding=ROUND_CEILING)
        comparison_total = (total * Decimal('100') / (Decimal('100') - marketing_discount_percent)).quantize(
            Decimal('1'), rounding=ROUND_CEILING,
        )
        return CalculationResult(
            data.panels, area, tuple(lines), subtotal, total, total - subtotal,
            discount_configuration['mode'], materials_discount, marketing_discount_percent, comparison_total,
            order_discount_percent, order_discount,
        )
