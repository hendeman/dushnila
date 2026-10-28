from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms import formset_factory

from .calculation import CalculationInput, DEFAULT_STAIR_FLOOR, MAX_INTEGER, MAX_PANELS, MAX_PANEL_DIMENSION_MM, MAX_STAIR_FLOOR, MIN_STAIR_FLOOR, Panel, ServiceSelection, service_quantity_limit
from .models import CalculatorService, CalculatorSettings, CalculatorTariffs, DecorationType, GlassType, MAX_STAIR_PANELS, MeasurementUnit, MIN_STAIR_PANELS, QUANTITY_DECIMAL_PLACES, QUANTITY_MAX_DIGITS, QUANTITY_STEP, StairLiftingRule, TARIFF_HINT_FIELDS
from .widgets import QuantityLimitWidget, StairLiftingRulesWidget


HINT_WIDGET = forms.Textarea(attrs={'rows': 3, 'cols': 60})


class StairLiftingRulesField(forms.Field):
    def __init__(self, **kwargs):
        super().__init__(
            widget=StairLiftingRulesWidget(),
            label='Правила подъёма',
            help_text=(
                '«Этаж» — последний этаж со стандартной стоимостью; 0 — без включённых этажей. '
                'Коэффициент сложности применяется к доплате за каждый следующий этаж. '
                'Можно задать дробный коэффициент или 0 для отсутствия доплаты.'
            ),
            **kwargs,
        )

    def clean(self, value):
        value = super().clean(value)
        count = forms.IntegerField(min_value=MIN_STAIR_PANELS, max_value=MAX_STAIR_PANELS).clean(value['count'])
        rules, errors = {}, []
        for number in range(1, count + 1):
            values = []
            for index, name in enumerate(('included_floor', 'multiplier')):
                model_field = StairLiftingRule._meta.get_field(name)
                field = model_field.formfield(validators=model_field.validators)
                try:
                    values.append(field.clean(value['rules'][number][index]))
                except ValidationError as error:
                    errors.extend(f'Панелей {number}, {model_field.verbose_name.lower()}: {message}'
                                  for message in error.messages)
            rules[number] = tuple(values)
        if errors:
            raise ValidationError(errors)
        return rules

    def has_changed(self, initial, data):
        if self.disabled:
            return False
        try:
            return (initial or {}) != self.clean(data)
        except ValidationError:
            return True


class CalculatorSettingsAdminForm(forms.ModelForm):
    class Meta:
        model = CalculatorSettings
        fields = '__all__'
        widgets = {'marketing_discount_description': forms.Textarea(attrs={'rows': 3, 'cols': 80})}


class CalculatorTariffsAdminForm(forms.ModelForm):
    stair_lifting_rules = StairLiftingRulesField()

    class Meta:
        model = CalculatorTariffs
        fields = '__all__'
        widgets = dict.fromkeys(TARIFF_HINT_FIELDS, HINT_WIDGET)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial.setdefault('stair_lifting_rules', self.instance.get_stair_lifting_rules())

    def save(self, commit=True):
        with transaction.atomic(using=self.instance._state.db):
            instance = super().save(commit=commit)
        return instance

    def _save_m2m(self):
        super()._save_m2m()
        self.instance.set_stair_lifting_rules(self.cleaned_data['stair_lifting_rules'])


class PanelForm(forms.Form):
    width_mm = forms.IntegerField(label='Ширина, мм', min_value=1, max_value=MAX_PANEL_DIMENSION_MM)
    height_mm = forms.IntegerField(label='Высота, мм', min_value=1, max_value=MAX_PANEL_DIMENSION_MM)


PanelFormSet = formset_factory(
    PanelForm, extra=1, min_num=1, validate_min=True,
    max_num=MAX_PANELS, validate_max=True, absolute_max=MAX_PANELS, can_delete=True,
)


class CalculatorServiceForm(forms.ModelForm):
    class Meta:
        model = CalculatorService
        exclude = ('settings', 'position')
        widgets = {'hint': HINT_WIDGET, 'max_quantity': QuantityLimitWidget()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.settings_id = CalculatorTariffs.CODE
        self.fields['unit'].empty_label = 'Без обозначения'
        if not self.instance.pk and not self.is_bound and not self.initial.get('unit'):
            self.initial['unit'] = MeasurementUnit.objects.filter(symbol='ед.').values_list('pk', flat=True).first()
        self.fields['is_visible'].label = self.instance.visibility_label or 'Показывать услугу'
        self.fields['price_per_unit'].label = self.instance.price_label or 'Цена за одну единицу'
        has_price = forms.BooleanField(required=False).to_python(self['has_price'].value())
        fixed_price = forms.BooleanField(required=False).to_python(self['fixed_price'].value())
        use_panel_area = forms.BooleanField(required=False).to_python(self['use_panel_area'].value())
        whole_quantity = forms.BooleanField(required=False).to_python(self['whole_quantity'].value())
        if not has_price:
            self.fields['price_per_unit'].disabled = True
        if not has_price or fixed_price:
            for name in ('quantity_label', 'unit', 'use_panel_area', 'whole_quantity'):
                self.fields[name].disabled = True
        self.fields['max_quantity'].disabled = not has_price or fixed_price or use_panel_area
        self.fields['max_quantity'].widget.attrs.update(
            min=1 if whole_quantity else str(QUANTITY_STEP), step=1 if whole_quantity else str(QUANTITY_STEP),
        )
        self.fields['max_quantity'].widget.attrs['data-quantity-step'] = str(QUANTITY_STEP)

    class Media:
        js = ('calculator/js/admin-services.js',)


class CalculatorServiceInlineForm(forms.ModelForm):
    class Meta:
        model = CalculatorService
        fields = ('is_visible', 'price_per_unit', 'position')
        widgets = {'position': forms.HiddenInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['is_visible'].label = self.instance.visibility_label
        self.fields['price_per_unit'].label = self.instance.price_label
        if not self.instance.has_price:
            self.fields['price_per_unit'].disabled = True

    def _post_clean(self):
        if not self.instance.pk:
            self.add_error(None, 'Услуга не найдена. Обновите настройки перед сохранением.')
            return
        super()._post_clean()


class CalculationForm(forms.Form):
    """Поля строятся из настроек; скрытые опции не принимаются из запроса."""

    def __init__(self, *args, settings, **kwargs):
        super().__init__(*args, **kwargs)
        self.field_groups = []
        self.services = list(settings.services.filter(is_visible=True).select_related('unit'))
        for field, model, label in (
            ('glass_type', GlassType, 'Тип стекла'),
            ('decoration_type', DecorationType, 'Декорирование'),
        ):
            if getattr(settings, f'show_{field}'):
                self.fields[field] = forms.ModelChoiceField(
                    label=label, queryset=model.objects.filter(is_visible=True),
                    initial=getattr(settings, f'default_{field}_id'), empty_label='Выберите вариант',
                )
                self.field_groups.append((label, (field,)))
        for service in self.services:
            if not service.has_price:
                continue
            selected = f'use_service_{service.pk}'
            self.fields[selected] = forms.BooleanField(label=service.name, required=False)
            if service.requires_manual_quantity:
                quantity = f'service_quantity_{service.pk}'
                limit = service_quantity_limit(service)
                field = (forms.IntegerField(min_value=1, max_value=limit) if service.whole_quantity
                         else self.quantity_field(service.quantity_label, max_value=limit))
                field.label, field.initial, field.required = service.quantity_label, min(Decimal('1'), limit), False
                field.disabled = self.is_bound and not forms.BooleanField(required=False).to_python(self[selected].value())
                self.fields[quantity] = field
        if settings.show_stair_lifting:
            self.fields['lifting_type'] = forms.ChoiceField(
                label='Способ подъёма', choices=(('standard', 'Стандартный'), ('stairs', 'По лестнице')),
                initial='standard',
            )
            self.fields['stair_floor'] = forms.IntegerField(
                label='Этаж', min_value=MIN_STAIR_FLOOR, max_value=MAX_STAIR_FLOOR, required=False, initial=DEFAULT_STAIR_FLOOR,
                widget=forms.NumberInput(attrs={'data-initial-value': DEFAULT_STAIR_FLOOR}),
            )
            max_panels = max(MIN_STAIR_PANELS, len(settings.get_stair_lifting_rules()))
            self.fields['stair_panel_count'] = forms.IntegerField(
                label='Панелей', min_value=1, max_value=max_panels, required=False, initial=1,
                help_text=f'Количество панелей более 0,5 м² для подъёма по лестнице: от 1 до {max_panels}.',
            )
            if self.is_bound and self.data.get(self.add_prefix('lifting_type')) == 'standard':
                for name in ('stair_floor', 'stair_panel_count'):
                    self.fields[name].disabled = True
            self.field_groups.append(('Подъём', ('lifting_type', 'stair_floor', 'stair_panel_count')))

    @staticmethod
    def quantity_field(label, *, max_value=None):
        return forms.DecimalField(
            label=label, required=False, min_value=Decimal('0'), max_digits=QUANTITY_MAX_DIGITS,
            decimal_places=QUANTITY_DECIMAL_PLACES, initial=0, max_value=max_value, widget=QuantityLimitWidget(),
        )

    def clean(self):
        cleaned = super().clean()
        for service in self.services:
            quantity = f'service_quantity_{service.pk}'
            if service.requires_manual_quantity and cleaned.get(f'use_service_{service.pk}'):
                if not cleaned.get(quantity) and quantity not in self.errors:
                    self.add_error(quantity, 'Укажите количество больше нуля.')
        if cleaned.get('lifting_type') == 'stairs':
            for field, message in (
                ('stair_floor', 'Укажите этаж для подъёма по лестнице.'),
                ('stair_panel_count', 'Укажите количество панелей для подъёма по лестнице.'),
            ):
                if not cleaned.get(field) and field not in self.errors:
                    self.add_error(field, message)
        return cleaned

    @property
    def service_rows(self):
        return [{
            'service': service,
            'selected': self[f'use_service_{service.pk}'] if service.has_price else None,
            'quantity': self[f'service_quantity_{service.pk}'] if service.requires_manual_quantity else None,
            'enabled': forms.BooleanField(required=False).to_python(self[f'use_service_{service.pk}'].value()) if service.has_price else False,
        } for service in self.services]

    def calculation_input(self, panel_forms):
        cleaned = self.cleaned_data
        return CalculationInput(
            panels=tuple(Panel(row['width_mm'], row['height_mm']) for row in panel_forms.cleaned_data
                         if row and not row.get('DELETE')),
            glass_type_id=cleaned['glass_type'].pk if cleaned.get('glass_type') else None,
            decoration_type_id=cleaned['decoration_type'].pk if cleaned.get('decoration_type') else None,
            services=tuple(ServiceSelection(service.pk, Decimal(cleaned[f'service_quantity_{service.pk}']) if service.requires_manual_quantity else Decimal('1'))
                           for service in self.services if service.has_price and cleaned.get(f'use_service_{service.pk}')),
            stair_floor=cleaned.get('stair_floor') if cleaned.get('lifting_type') == 'stairs' else None,
            stair_panel_count=cleaned.get('stair_panel_count') if cleaned.get('lifting_type') == 'stairs' else None,
        )
