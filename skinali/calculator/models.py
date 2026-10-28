from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinValueValidator
from django.db import models, transaction


STAIR_PRICE_FIELDS = ('stair_lifting_min_price', 'stair_lifting_price_per_panel_floor')
MIN_STAIR_PANELS = 1
MAX_STAIR_PANELS = 6
MAX_STAIR_INCLUDED_FLOOR = 999_999_999
TARIFF_HINT_FIELDS = ('panels_hint', 'glass_type_hint', 'decoration_type_hint', 'stair_lifting_hint')
QUANTITY_DECIMAL_PLACES = 2
QUANTITY_MAX_DIGITS = 11
QUANTITY_STEP = Decimal('0.01')


def validate_stair_rule_counts(rules):
    count = len(rules)
    if (
        not MIN_STAIR_PANELS <= count <= MAX_STAIR_PANELS
        or any(type(key) is not int for key in rules)
        or set(rules) != set(range(1, count + 1))
    ):
        raise ValidationError(
            f'Таблица подъёма должна содержать последовательные столбцы от 1 до {MAX_STAIR_PANELS} панелей.'
        )


def price_field(label, *, optional=False, help_text=''):
    """Денежные значения хранятся точно; пустой тариф отличается от бесплатного."""
    return models.DecimalField(
        label, max_digits=10, decimal_places=2,
        null=optional, blank=optional,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text=help_text or (
            'Пустое поле — тариф не задан. Укажите 0 для бесплатной услуги.'
            if optional else 'Неотрицательная сумма с точностью до двух знаков после запятой.'
        ),
    )


def service_code():
    return uuid4().hex


def hint_field(label='Подсказка на сайте'):
    return models.TextField(
        label, max_length=2000, blank=True, default='', validators=[MaxLengthValidator(2000)],
        help_text='Обычный текст без HTML. Оставьте пустым, чтобы скрыть значок «?» на сайте.',
    )


class ValidatedCalculatorModel(models.Model):
    """Настройки проверяются также при обычном сохранении через ORM."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PricedOption(ValidatedCalculatorModel):
    name = models.CharField('Название', max_length=100, unique=True)
    price_per_sqm = price_field('Цена за 1 м²')
    position = models.PositiveIntegerField('Порядок', default=0)
    is_visible = models.BooleanField('Показывать в калькуляторе', default=True)

    class Meta:
        abstract = True
        ordering = ('position', 'pk')
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price_per_sqm__gte=0),
                name='calc_%(class)s_price_gte0',
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.name = (self.name or '').strip()
        if not self.name:
            raise ValidationError({'name': 'Укажите название.'})
        if self.pk and not self.is_visible and self.default_for_settings.filter(
            **{self.visibility_setting: True},
        ).exists():
            raise ValidationError({
                'is_visible': (
                    'Этот вариант выбран по умолчанию. Сначала выберите другой вариант '
                    'или скройте весь раздел в настройках калькулятора.'
                ),
            })


class GlassType(PricedOption):
    visibility_setting = 'show_glass_type'

    class Meta(PricedOption.Meta):
        abstract = False
        verbose_name = 'Тип стекла'
        verbose_name_plural = 'Типы стекла'


class DecorationType(PricedOption):
    visibility_setting = 'show_decoration_type'
    price_per_sqm = price_field('Доплата за 1 м²')

    class Meta(PricedOption.Meta):
        abstract = False
        verbose_name = 'Декорирование'
        verbose_name_plural = 'Декорирование'


class CalculatorSettings(ValidatedCalculatorModel):
    CODE = 'skinali'

    code = models.CharField(max_length=20, primary_key=True, default=CODE, editable=False)
    is_enabled = models.BooleanField(
        'Показывать калькулятор на сайте', default=False,
        help_text='Выключите, чтобы полностью скрыть калькулятор на сайте. Проверочный расчёт в админке остаётся доступным.',
    )
    area_discount_percent = models.DecimalField(
        'Скидка за каждый следующий м², %', max_digits=5, decimal_places=2, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))],
        help_text=(
            'Скидка действует только при общей площади больше 2 м². '
            'Тогда первый м² — по полной цене, каждый следующий дешевле предыдущего на указанный процент. '
            'Неполный метр считается пропорционально. Только для стекла и декорирования; 0 — без скидки.'
        ),
    )
    marketing_discount_percent = models.DecimalField(
        'Маркетинговая скидка, %', max_digits=5, decimal_places=2, default=Decimal('0'),
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('99.99'))],
        help_text='Скидка относительно зачёркнутой цены. При 20% итог 800 соответствует зачёркнутой цене 1000. 0 — без скидки.',
    )
    marketing_discount_description = models.TextField(
        'Описание маркетинговой скидки', max_length=2000, blank=True, default='',
        validators=[MaxLengthValidator(2000)],
        help_text='Необязательный текст с описанием условий акции. До 2000 символов.',
    )

    class Meta:
        verbose_name = 'Настройки калькулятора'
        verbose_name_plural = 'Настройки калькулятора'
        constraints = [
            models.CheckConstraint(condition=models.Q(code='skinali'), name='calculator_settings_singleton'),
            models.CheckConstraint(
                condition=models.Q(area_discount_percent__gte=0, area_discount_percent__lte=100),
                name='calc_area_discount_percent_range',
            ),
            models.CheckConstraint(
                condition=models.Q(marketing_discount_percent__gte=0, marketing_discount_percent__lt=100),
                name='calc_marketing_discount_range',
            ),
        ]

    def __str__(self):
        return str(self._meta.verbose_name)


class CalculatorTariffs(ValidatedCalculatorModel):
    CODE = 'skinali'
    INCLUDED_SERVICE_LABEL = 'Включено в стоимость'

    code = models.CharField(max_length=20, primary_key=True, default=CODE, editable=False)
    panels_hint = hint_field('Подсказка к размерам панелей')
    glass_type_hint = hint_field('Подсказка к выбору стекла')
    decoration_type_hint = hint_field('Подсказка к декорированию')
    stair_lifting_hint = hint_field('Подсказка к подъёму')
    show_glass_type = models.BooleanField('Показывать выбор стекла', default=True)
    default_glass_type = models.ForeignKey(
        GlassType, on_delete=models.PROTECT, null=True, blank=True,
        related_name='default_for_settings', verbose_name='Стекло по умолчанию',
        help_text='Применяется также при скрытом выборе стекла. Сначала добавьте варианты стекла.',
    )
    show_decoration_type = models.BooleanField('Показывать выбор декорирования', default=True)
    default_decoration_type = models.ForeignKey(
        DecorationType, on_delete=models.PROTECT, null=True, blank=True,
        related_name='default_for_settings', verbose_name='Декорирование по умолчанию',
        help_text='Применяется также при скрытом выборе. Для варианта без доплаты укажите цену 0.',
    )

    show_stair_lifting = models.BooleanField('Показывать подъём по лестнице', default=False)
    stair_lifting_min_price = price_field(
        'Стандартная стоимость подъёма', optional=True,
        help_text='Базовая стоимость подъёма в пределах включённых этажей. Пустое поле — тариф не задан.',
    )
    stair_lifting_price_per_panel_floor = price_field(
        'Подъём одной панели на один этаж', optional=True,
        help_text=(
            'Доплата за каждый этаж сверх порога из таблицы с выбранным коэффициентом сложности. '
            'Пустое поле — тариф не задан.'
        ),
    )

    class Meta:
        verbose_name = 'Тарифы и услуги'
        verbose_name_plural = 'Тарифы и услуги'
        constraints = [
            models.CheckConstraint(condition=models.Q(code='skinali'), name='calculator_tariffs_singleton'),
            *[
                models.CheckConstraint(
                    condition=models.Q(**{f'{field}__gte': 0}) | models.Q(**{f'{field}__isnull': True}),
                    name=f'calc_{field}_gte0',
                )
                for field in STAIR_PRICE_FIELDS
            ],
        ]

    def __str__(self):
        return str(self._meta.verbose_name)

    def get_stair_lifting_rules(self):
        return {rule.panel_count: (rule.included_floor, rule.multiplier)
                for rule in self.stair_lifting_rules.all()}

    def set_stair_lifting_rules(self, rules):
        validate_stair_rule_counts(rules)
        rows = [StairLiftingRule(settings=self, panel_count=count, included_floor=floor, multiplier=multiplier)
                for count, (floor, multiplier) in sorted(rules.items())]
        for row in rows:
            row.clean_fields(exclude=('settings',))
        with transaction.atomic(using=self._state.db):
            self.stair_lifting_rules.all().delete()
            StairLiftingRule.objects.using(self._state.db).bulk_create(rows)
        getattr(self, '_prefetched_objects_cache', {}).pop('stair_lifting_rules', None)

    def clean(self):
        super().clean()
        errors = {}
        if self.show_stair_lifting:
            for field in STAIR_PRICE_FIELDS:
                if getattr(self, field) is None:
                    errors[field] = 'Укажите тариф перед включением услуги. Для бесплатной услуги введите 0.'
        for field, visibility, option_model in (
            ('default_glass_type', 'show_glass_type', GlassType),
            ('default_decoration_type', 'show_decoration_type', DecorationType),
        ):
            option_id = getattr(self, f'{field}_id')
            if not getattr(self, visibility) and not option_id:
                errors[field] = 'Выберите вариант по умолчанию перед скрытием этого раздела.'
            elif getattr(self, visibility) and option_id and option_model.objects.filter(
                pk=option_id, is_visible=False,
            ).exists():
                errors[field] = 'При видимом выборе вариант по умолчанию тоже должен быть видимым.'
        if errors:
            raise ValidationError(errors)


class MeasurementUnit(ValidatedCalculatorModel):
    name = models.CharField('Название', max_length=100, unique=True)
    symbol = models.CharField('Обозначение', max_length=30, unique=True)
    position = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        ordering = ('position', 'pk')
        verbose_name = 'Единица измерения'
        verbose_name_plural = 'Единицы измерения'

    def __str__(self):
        return f'{self.name} ({self.symbol})'

    def clean(self):
        super().clean()
        errors = {}
        for field in ('name', 'symbol'):
            value = (getattr(self, field) or '').strip()
            setattr(self, field, value)
            if not value:
                errors[field] = 'Заполните поле.'
        if errors:
            raise ValidationError(errors)


class CalculatorService(ValidatedCalculatorModel):
    settings = models.ForeignKey(CalculatorTariffs, on_delete=models.CASCADE, related_name='services')
    code = models.SlugField(max_length=32, unique=True, default=service_code, editable=False)
    name = models.CharField('Название услуги', max_length=100)
    hint = hint_field()
    visibility_label = models.CharField('Подпись чекбокса показа', max_length=180, blank=True)
    price_label = models.CharField('Описание тарифа', max_length=200, blank=True)
    is_visible = models.BooleanField('Показывать услугу', default=False)
    has_price = models.BooleanField('Указывать стоимость', default=True,
                                   help_text='Выключите, если услуга включена в стоимость.')
    fixed_price = models.BooleanField(
        'Фиксированная стоимость на весь заказ', default=False,
        help_text='При выборе услуги сумма начисляется один раз, без ввода количества.',
    )
    price_per_unit = price_field('Цена за одну единицу', optional=True)
    quantity_label = models.CharField('Название поля количества', max_length=100, default='Количество')
    unit = models.ForeignKey(
        MeasurementUnit, on_delete=models.PROTECT, related_name='services',
        verbose_name='Единица измерения', null=True, blank=True,
        help_text='Выберите единицу из справочника. На формулу стоимости обозначение не влияет.',
    )
    max_quantity = models.DecimalField(
        'Максимальное количество', max_digits=QUANTITY_MAX_DIGITS, decimal_places=QUANTITY_DECIMAL_PLACES, null=True, blank=True,
        validators=[MinValueValidator(QUANTITY_STEP)],
        help_text='Необязательный предел ручного ввода. Для целого количества укажите целое число. Пустое поле — отдельный предел не задан.',
    )
    use_panel_area = models.BooleanField('Количество по площади панелей', default=False,
                                        help_text='Общая площадь вместо ручного ввода количества.')
    whole_quantity = models.BooleanField('Только целое количество', default=False)
    position = models.PositiveIntegerField('Порядок', default=0)

    class Meta:
        ordering = ('position', 'pk')
        verbose_name = 'Услуга калькулятора'
        verbose_name_plural = 'Дополнительные услуги'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price_per_unit__gte=0) | models.Q(price_per_unit__isnull=True),
                name='calc_service_price_gte0',
            ),
            models.CheckConstraint(
                condition=models.Q(max_quantity__isnull=True) | models.Q(max_quantity__gte=QUANTITY_STEP),
                name='calc_service_max_quantity_positive',
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def requires_manual_quantity(self):
        return self.has_price and not self.fixed_price and not self.use_panel_area

    def clean(self):
        super().clean()
        self.name = (self.name or '').strip()
        self.visibility_label = (self.visibility_label or '').strip() or f'Показать: {self.name}'
        self.price_label = (self.price_label or '').strip() or self.name
        if not self.name:
            raise ValidationError({'name': 'Укажите название услуги.'})
        if self.is_visible and self.has_price and self.price_per_unit is None:
            raise ValidationError({'price_per_unit': 'Укажите стоимость перед показом платной услуги.'})
        if self.requires_manual_quantity and self.whole_quantity and isinstance(self.max_quantity, Decimal):
            if self.max_quantity.is_finite() and self.max_quantity != self.max_quantity.to_integral_value():
                raise ValidationError({'max_quantity': 'Для целого количества укажите целое максимальное значение.'})


class StairLiftingRule(ValidatedCalculatorModel):
    settings = models.ForeignKey(
        CalculatorTariffs, on_delete=models.CASCADE, related_name='stair_lifting_rules',
        verbose_name='Тарифы и услуги',
    )
    panel_count = models.PositiveSmallIntegerField(
        'Панелей', validators=[MinValueValidator(MIN_STAIR_PANELS), MaxValueValidator(MAX_STAIR_PANELS)],
    )
    included_floor = models.PositiveIntegerField(
        'Этаж', validators=[MaxValueValidator(MAX_STAIR_INCLUDED_FLOOR)],
    )
    multiplier = models.DecimalField(
        'Коэффициент сложности', max_digits=6, decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))],
    )

    class Meta:
        ordering = ('panel_count',)
        verbose_name = 'Правило подъёма по лестнице'
        verbose_name_plural = 'Правила подъёма по лестнице'
        constraints = [
            models.UniqueConstraint(fields=('settings', 'panel_count'), name='calc_stair_unique_panel_count'),
            models.CheckConstraint(
                condition=models.Q(panel_count__gte=MIN_STAIR_PANELS, panel_count__lte=MAX_STAIR_PANELS),
                name='calc_stair_panel_count_range',
            ),
            models.CheckConstraint(condition=models.Q(multiplier__gte=0), name='calc_stair_multiplier_gte0'),
        ]
