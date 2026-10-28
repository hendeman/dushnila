from decimal import Decimal, localcontext

from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import path, reverse
from django.utils import translation

from .admin import CalculatorServiceAdmin, CalculatorSettingsAdmin, CalculatorTariffsAdmin, MeasurementUnitAdmin, PricedOptionAdmin
from .calculation import (
    CalculationInput, CalculatorConfigurationError, MAX_PANELS, Panel, ServiceSelection, calculate_price,
)
from .forms import CalculationForm, PanelFormSet
from .models import CalculatorService, CalculatorSettings, CalculatorTariffs, DecorationType, GlassType, MeasurementUnit
from .templatetags.calculator_numbers import exact_decimal


class CalculationFixture:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.glass = GlassType.objects.create(name='Обычное', price_per_sqm='100.25')
        cls.decoration = DecorationType.objects.create(name='Печать', price_per_sqm='20.50')
        cls.settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
        cls.settings.default_glass_type = cls.glass
        cls.settings.default_decoration_type = cls.decoration
        cls.settings.show_stair_lifting = True
        cls.settings.stair_lifting_min_price = Decimal('50')
        cls.settings.stair_lifting_price_per_panel_floor = Decimal('6')
        cls.settings.save()
        for code, price in {'backlight': '10.20', 'railing': '4.40', 'sockets': '5.50',
                            'hydrophobic': '3.25', 'delivery': '1.25'}.items():
            cls.settings.services.filter(code=code).update(is_visible=True, price_per_unit=Decimal(price))
        cls.service_ids = dict(cls.settings.services.values_list('code', 'pk'))

    quantity_aliases = {'backlight_length_m': 'backlight', 'railing_length_m': 'railing',
                        'socket_blocks': 'sockets', 'delivery_distance_km': 'delivery'}

    def calculation_input(self, **changes):
        if changes.get('stair_floor') is not None:
            changes = {'stair_panel_count': 2, **changes}
        services = list(changes.pop('services', ()))
        for field, code in self.quantity_aliases.items():
            if field in changes:
                value = changes.pop(field)
                if value != 0:
                    services.append(ServiceSelection(self.service_ids[code], value))
        if changes.pop('hydrophobic', False):
            services.append(ServiceSelection(self.service_ids['hydrophobic']))
        return CalculationInput(**{
            'panels': (Panel(1000, 600), Panel(500, 400)),
            'glass_type_id': self.glass.pk, 'decoration_type_id': self.decoration.pk,
            'services': tuple(services), **changes,
        })

    def post_data(self, **changes):
        for field, code in self.quantity_aliases.items():
            if field not in changes:
                continue
            value = changes.pop(field)
            changes[f'service_quantity_{self.service_ids[code]}'] = value
            toggle = {'backlight': 'use_backlight', 'railing': 'use_railing'}.get(code)
            active = changes.pop(toggle, '') if toggle else bool(value)
            if active:
                changes[f'use_service_{self.service_ids[code]}'] = 'on'
        if changes.pop('hydrophobic', False):
            changes[f"use_service_{self.service_ids['hydrophobic']}"] = 'on'
        for code in ('backlight', 'railing'):
            if changes.pop(f'use_{code}', False):
                changes[f'use_service_{self.service_ids[code]}'] = 'on'
        return {
            'panels-TOTAL_FORMS': '2', 'panels-INITIAL_FORMS': '0',
            'panels-MIN_NUM_FORMS': '1', 'panels-MAX_NUM_FORMS': str(MAX_PANELS),
            'panels-0-width_mm': '1000', 'panels-0-height_mm': '600',
            'panels-1-width_mm': '500', 'panels-1-height_mm': '400',
            'glass_type': str(self.glass.pk), 'decoration_type': str(self.decoration.pk),
            'lifting_type': 'standard', 'stair_panel_count': '2', **changes,
        }


class PriceCalculationTests(CalculationFixture, TestCase):
    def test_complete_quote_has_exact_area_all_rates_and_one_final_rounding(self):
        data = self.calculation_input(
            backlight_length_m=Decimal('1.5'), railing_length_m=Decimal('0.75'),
            socket_blocks=2, hydrophobic=True, delivery_distance_km=Decimal('12.5'), stair_floor=5,
        )
        result = calculate_price(data)
        self.assertEqual(result.panel_count, 2)
        self.assertEqual(result.area_sqm, Decimal('0.8'))
        self.assertEqual({line.code: line.amount for line in result.lines}, {
            'glass': Decimal('80.20'), 'decoration': Decimal('16.40'),
            'backlight': Decimal('15.30'), 'railing': Decimal('3.30'),
            'sockets': Decimal('11'), 'hydrophobic': Decimal('2.60'),
            'delivery': Decimal('15.625'), 'stair_lifting': Decimal('50'),
            'stair_lifting_extra': Decimal('6'),
            'measurement': Decimal('0'), 'installation': Decimal('0'),
        })
        self.assertEqual(result.subtotal, Decimal('200.425'))
        self.assertEqual(result.total, Decimal('201'))
        self.assertEqual(result.rounding_adjustment, Decimal('0.575'))
        self.assertEqual(result.subtotal, sum(line.amount for line in result.lines))

    def test_stair_price_boundaries_for_every_supported_panel_count(self):
        cases = (
            (1, 2, '50'), (1, 9, '50'), (1, 10, '56'), (1, 11, '62'),
            (2, 2, '50'), (2, 4, '50'), (2, 5, '56'), (2, 6, '62'),
            (3, 2, '50'), (3, 3, '50'), (3, 4, '62'), (3, 5, '74'),
            (4, 2, '50'), (4, 3, '62'), (4, 4, '74'),
        )
        for count, floor, expected in cases:
            with self.subTest(panels=count, floor=floor):
                result = calculate_price(self.calculation_input(stair_floor=floor, stair_panel_count=count))
                lines = [line for line in result.lines if line.code.startswith('stair_lifting')]
                self.assertEqual(sum(line.amount for line in lines), Decimal(expected))
                self.assertEqual(lines[0].amount, Decimal('50'))
                self.assertEqual(len(lines), 1 if expected == '50' else 2)

    def test_stair_quantity_is_entered_separately_from_geometry(self):
        for count, expected in ((1, '146.6'), (2, '152.6')):
            with self.subTest(count=count):
                result = calculate_price(self.calculation_input(stair_floor=5, stair_panel_count=count))
                self.assertEqual(result.panel_count, 2)
                self.assertEqual(result.subtotal, Decimal(expected))
                self.assertIn(f'Панелей для подъёма: {count}', result.lines[2].description)

    def test_saved_stair_rules_control_each_column_and_apply_on_next_calculation(self):
        before = calculate_price(self.calculation_input(stair_floor=6, stair_panel_count=2))
        self.assertEqual(before.subtotal, Decimal('158.6'))
        settings = CalculatorTariffs.objects.get(pk=CalculatorTariffs.CODE)
        settings.set_stair_lifting_rules({
            1: (2, Decimal('0.50')), 2: (5, Decimal('1.25')),
            3: (7, Decimal('2.50')), 4: (10, Decimal('3.75')),
        })
        for count, floor, extra_price in ((1, 2, '6'), (2, 5, '15'), (3, 7, '30'), (4, 10, '45')):
            for extra_floors in (0, 2):
                with self.subTest(count=count, extra_floors=extra_floors):
                    result = calculate_price(self.calculation_input(
                        stair_floor=floor + extra_floors, stair_panel_count=count,
                    ))
                    lines = [line for line in result.lines if line.code.startswith('stair_lifting')]
                    expected_extra = Decimal(extra_price) if extra_floors else Decimal('0')
                    self.assertEqual(sum(line.amount for line in lines), Decimal('50') + expected_extra)
                    self.assertEqual(len(lines), 2 if extra_floors else 1)

    def test_stair_fractional_multiplier_keeps_precision_until_total_rounding(self):
        self.settings.stair_lifting_rules.filter(panel_count=2).update(included_floor=5, multiplier=Decimal('1.25'))
        CalculatorTariffs.objects.update(stair_lifting_price_per_panel_floor=Decimal('6.01'))
        result = calculate_price(self.calculation_input(stair_floor=6, stair_panel_count=2))
        line = next(line for line in result.lines if line.code == 'stair_lifting_extra')
        self.assertEqual(line.amount, Decimal('7.5125'))
        self.assertEqual(result.subtotal, Decimal('154.1125'))
        self.assertEqual(result.total, 155)

    def test_zero_included_floor_charges_from_first_floor_and_zero_multiplier_removes_surcharge(self):
        self.settings.stair_lifting_rules.filter(panel_count=1).update(included_floor=0, multiplier=Decimal('0.5'))
        data = self.calculation_input(stair_floor=2, stair_panel_count=1)
        result = calculate_price(data)
        self.assertEqual(result.subtotal, Decimal('152.6'))
        self.assertIn('с первого этажа', result.lines[2].description)
        self.assertEqual(result.lines[3].amount, Decimal('6'))
        self.settings.stair_lifting_rules.filter(panel_count=1).update(multiplier=Decimal('0'))
        self.assertEqual(calculate_price(data).subtotal, Decimal('146.6'))

    def test_stair_panel_count_is_required_and_limited_to_six(self):
        for count in (None, 0, 7, 11, -1, True, 1.5, '2'):
            with self.subTest(count=count), self.assertRaises(ValidationError) as error:
                self.calculation_input(stair_floor=5, stair_panel_count=count)
            self.assertIn('stair_panel_count', error.exception.message_dict)

    def test_stair_limit_follows_saved_rules_in_backend(self):
        self.settings.set_stair_lifting_rules({number: (2, Decimal(number)) for number in range(1, 7)})
        result = calculate_price(self.calculation_input(stair_floor=3, stair_panel_count=6))
        self.assertEqual(result.subtotal, Decimal('182.6'))
        self.settings.set_stair_lifting_rules({1: (2, Decimal('1'))})
        with self.assertRaises(ValidationError) as error:
            calculate_price(self.calculation_input(stair_floor=3, stair_panel_count=2))
        self.assertIn('stair_panel_count', error.exception.message_dict)
        result = calculate_price(self.calculation_input(stair_floor=3, stair_panel_count=1))
        self.assertEqual(result.subtotal, Decimal('152.6'))

    def test_missing_or_noncontiguous_stair_rules_have_controlled_configuration_error(self):
        self.settings.stair_lifting_rules.filter(panel_count=2).delete()
        with self.assertRaises(CalculatorConfigurationError):
            calculate_price(self.calculation_input(stair_floor=3, stair_panel_count=1))
        self.settings.stair_lifting_rules.all().delete()
        with self.assertRaises(CalculatorConfigurationError):
            calculate_price(self.calculation_input(stair_floor=3, stair_panel_count=1))

    def test_stair_base_and_surcharge_keep_full_precision(self):
        CalculatorTariffs.objects.update(
            stair_lifting_min_price=Decimal('50.25'), stair_lifting_price_per_panel_floor=Decimal('6.01'),
        )
        result = calculate_price(self.calculation_input(stair_floor=4, stair_panel_count=3))
        lines = [line for line in result.lines if line.code.startswith('stair_lifting')]
        self.assertEqual(sum(line.amount for line in lines), Decimal('62.27'))
        self.assertEqual(lines[1].quantity, 1)
        self.assertEqual(lines[1].unit_price, Decimal('12.02'))
        self.assertEqual(result.subtotal, Decimal('158.87'))
        self.assertEqual(result.total, 159)

    def test_zero_standard_stair_cost_still_uses_threshold(self):
        CalculatorTariffs.objects.update(stair_lifting_min_price=Decimal('0'))
        for floor, expected in ((9, '0'), (10, '6')):
            result = calculate_price(self.calculation_input(stair_floor=floor, stair_panel_count=1))
            lines = [line for line in result.lines if line.code.startswith('stair_lifting')]
            self.assertEqual(sum(line.amount for line in lines), Decimal(expected))

    def test_standard_lifting_measurement_and_installation_are_included(self):
        result = calculate_price(self.calculation_input())
        included = {line.code for line in result.lines if line.included}
        self.assertEqual(included, {'standard_lifting', 'measurement', 'installation'})
        self.assertEqual(result.subtotal, Decimal('96.6'))
        self.assertEqual(result.total, 97)

    def test_no_minimum_panel_area_or_minimum_order_cost(self):
        result = calculate_price(self.calculation_input(panels=(Panel(1, 1),)))
        self.assertEqual(result.area_sqm, Decimal('0.00'))
        self.assertEqual(result.subtotal, Decimal('0'))
        self.assertEqual(result.total, 0)

    def test_total_is_rounded_once_and_exact_integer_is_not_increased(self):
        for price, expected_subtotal, expected_total in (('1.01', '2.02', 3), ('1.00', '2.00', 2), ('0', '0', 0)):
            with self.subTest(price=price):
                GlassType.objects.filter(pk=self.glass.pk).update(price_per_sqm=Decimal(price))
                DecorationType.objects.filter(pk=self.decoration.pk).update(price_per_sqm=Decimal(price))
                result = calculate_price(self.calculation_input(panels=(Panel(1000, 1000),)))
                self.assertEqual(result.subtotal, Decimal(expected_subtotal))
                self.assertEqual(result.total, expected_total)

    def test_area_is_rounded_before_prices_and_intermediate_amounts_keep_full_precision(self):
        GlassType.objects.filter(pk=self.glass.pk).update(price_per_sqm=Decimal('10.01'))
        DecorationType.objects.filter(pk=self.decoration.pk).update(price_per_sqm=Decimal('0.02'))
        with localcontext() as context:
            context.prec = 8
            result = calculate_price(self.calculation_input(panels=(Panel(333, 333),)))
        self.assertEqual(result.area_sqm, Decimal('0.11'))
        self.assertEqual(result.subtotal, Decimal('1.1033'))
        self.assertEqual(result.total, 2)

    def test_area_rounds_half_up_once_after_summing_and_is_shared_by_area_services(self):
        service = self.settings.services.get(code='hydrophobic')
        for panels, expected_area in (
            ((Panel(1111, 1111),), '1.23'),
            ((Panel(1004, 1000), Panel(999, 1)), '1.00'),
            ((Panel(1005, 1000),), '1.01'),
            ((Panel(1015, 1000),), '1.02'),
            ((Panel(1006, 500), Panel(1006, 500)), '1.01'),
            ((Panel(6, 1000), Panel(6, 1000)), '0.01'),
            ((Panel(1, 1),), '0.00'),
        ):
            with self.subTest(panels=panels):
                result = calculate_price(self.calculation_input(
                    panels=panels, services=(ServiceSelection(service.pk),),
                ))
                area = Decimal(expected_area)
                self.assertEqual(result.area_sqm, area)
                self.assertEqual(result.area_sqm.as_tuple().exponent, -2)
                lines = {line.code: line for line in result.lines}
                for code, price in (('glass', self.glass.price_per_sqm),
                                    ('decoration', self.decoration.price_per_sqm),
                                    ('hydrophobic', service.price_per_unit)):
                    self.assertEqual(lines[code].quantity, area)
                    self.assertEqual(lines[code].amount, area * price)

    def test_hidden_services_are_ignored_even_if_submitted_explicitly(self):
        self.settings.services.exclude(code='installation').update(is_visible=False)
        self.settings.show_stair_lifting = False
        self.settings.save()
        result = calculate_price(self.calculation_input(
            backlight_length_m=Decimal('100'), railing_length_m=Decimal('100'),
            socket_blocks=100, hydrophobic=True, delivery_distance_km=Decimal('100'), stair_floor=12,
        ))
        self.assertEqual({line.code for line in result.lines}, {'glass', 'decoration', 'installation'})
        self.assertEqual(result.subtotal, Decimal('96.6'))

    def test_hidden_selectors_use_defaults_and_ignore_supplied_material_ids(self):
        self.settings.show_glass_type = False
        self.settings.show_decoration_type = False
        self.settings.save()
        for option in (self.glass, self.decoration):
            option.is_visible = False
            option.save()
        result = calculate_price(self.calculation_input(glass_type_id=999999, decoration_type_id=999999))
        self.assertEqual(result.subtotal, Decimal('96.6'))
        self.assertIn('Обычное', result.lines[0].label)
        self.assertIn('Печать', result.lines[1].label)

    def test_visible_selectors_reject_hidden_missing_and_invalid_options(self):
        for field, model in (('glass_type_id', GlassType), ('decoration_type_id', DecorationType)):
            hidden = model.objects.create(name='Скрытый', price_per_sqm=0, is_visible=False)
            for value in (hidden.pk, 999999, 0, -1, True, '1'):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    calculate_price(self.calculation_input(**{field: value}))

    def test_visible_defaults_can_be_used_without_explicit_selection(self):
        result = calculate_price(self.calculation_input(glass_type_id=None, decoration_type_id=None))
        self.assertEqual(result.subtotal, Decimal('96.6'))

    def test_tariff_and_visibility_changes_are_used_on_next_calculation(self):
        data = self.calculation_input(delivery_distance_km=Decimal('10'))
        self.assertEqual(calculate_price(data).subtotal, Decimal('109.1'))
        CalculatorService.objects.filter(code='delivery').update(price_per_unit=Decimal('2'))
        self.assertEqual(calculate_price(data).subtotal, Decimal('116.6'))
        CalculatorService.objects.filter(code='delivery').update(is_visible=False)
        self.assertEqual(calculate_price(data).subtotal, Decimal('96.6'))

    def test_unconfigured_price_and_missing_settings_have_controlled_errors(self):
        CalculatorService.objects.filter(code='delivery').update(price_per_unit=None)
        with self.assertRaises(CalculatorConfigurationError):
            calculate_price(self.calculation_input(delivery_distance_km=Decimal('1')))
        CalculatorTariffs.objects.all().delete()
        with self.assertRaises(CalculatorConfigurationError):
            calculate_price(self.calculation_input())

    def test_hidden_material_without_default_has_configuration_error(self):
        CalculatorTariffs.objects.update(show_glass_type=False, default_glass_type=None)
        with self.assertRaises(CalculatorConfigurationError):
            calculate_price(self.calculation_input())

    def test_free_optional_service_is_still_in_breakdown(self):
        CalculatorService.objects.filter(code='delivery').update(price_per_unit=Decimal('0'))
        result = calculate_price(self.calculation_input(delivery_distance_km=Decimal('10')))
        line = next(line for line in result.lines if line.code == 'delivery')
        self.assertEqual(line.quantity, 10)
        self.assertEqual(line.amount, 0)

    def test_maximum_panel_count_is_supported_and_overflow_is_rejected(self):
        result = calculate_price(self.calculation_input(panels=(Panel(6000, 6000),) * MAX_PANELS))
        self.assertEqual(result.area_sqm, 36 * MAX_PANELS)
        self.assertEqual(result.panel_count, MAX_PANELS)
        for panels in (None, 1, (), (Panel(1, 1),) * (MAX_PANELS + 1), ({'width_mm': 1, 'height_mm': 1},)):
            with self.subTest(panels=type(panels).__name__), self.assertRaises(ValidationError):
                self.calculation_input(panels=panels)

    def test_input_rejects_invalid_counts_dimensions_and_non_finite_quantities(self):
        for width, height in ((0, 1), (1, -1), (True, 1), (1.5, 1), (6001, 1), (1, 6001), (10**10, 1)):
            with self.subTest(width=width, height=height), self.assertRaises(ValidationError):
                Panel(width, height)
        for field in ('backlight_length_m', 'railing_length_m', 'delivery_distance_km'):
            for value in ('-1', 'NaN', 'Infinity', '0.001', '1.005', '0.0001', None, True, 1.5):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    self.calculation_input(**{field: value})
        for field, value in (('socket_blocks', -1), ('socket_blocks', 1.5), ('stair_floor', 0),
                             ('stair_floor', 1), ('stair_floor', True), ('stair_floor', 13)):
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                calculate_price(self.calculation_input(**{field: value}))


class CalculationFormTests(CalculationFixture, TestCase):
    def test_stair_form_has_floor_and_editable_panel_count(self):
        form = CalculationForm(settings=self.settings)
        self.assertEqual(form.fields['stair_floor'].label, 'Этаж')
        self.assertEqual(form.fields['stair_panel_count'].label, 'Панелей')
        self.assertEqual(form.fields['stair_panel_count'].initial, 1)
        self.assertEqual(form.fields['stair_panel_count'].min_value, 1)
        self.assertEqual(form.fields['stair_panel_count'].max_value, 4)
        self.assertEqual(form.fields['stair_floor'].initial, 2)
        self.assertEqual(form.fields['stair_floor'].min_value, 2)
        self.assertEqual(form.fields['stair_floor'].max_value, 12)
        self.assertEqual(form.fields['stair_floor'].help_text, '')

    def test_stair_form_limit_and_help_follow_saved_columns(self):
        for count in (1, 3, 6):
            with self.subTest(count=count):
                self.settings.set_stair_lifting_rules({number: (2, Decimal('1')) for number in range(1, count + 1)})
                form = CalculationForm(settings=self.settings)
                self.assertEqual(form.fields['stair_panel_count'].max_value, count)
                self.assertEqual(form.fields['stair_panel_count'].help_text,
                                 f'Количество панелей более 0,5 м² для подъёма по лестнице: от 1 до {count}.')
                bound = CalculationForm(self.post_data(
                    lifting_type='stairs', stair_floor='2', stair_panel_count=str(count),
                ), settings=self.settings)
                self.assertTrue(bound.is_valid(), bound.errors)
                bound = CalculationForm(self.post_data(
                    lifting_type='stairs', stair_floor='2', stair_panel_count=str(count + 1),
                ), settings=self.settings)
                self.assertFalse(bound.is_valid())
                self.assertIn('stair_panel_count', bound.errors)

    def test_hidden_options_and_services_have_no_editable_fields(self):
        self.settings.show_glass_type = False
        self.settings.show_decoration_type = False
        self.settings.services.update(is_visible=False)
        self.settings.show_stair_lifting = False
        form = CalculationForm(settings=self.settings)
        self.assertEqual(list(form.fields), [])

    def test_selected_lengths_and_stairs_require_their_parameters(self):
        for data, error_field in (
            ({'use_backlight': 'on', 'backlight_length_m': '0'}, 'backlight_length_m'),
            ({'use_railing': 'on'}, 'railing_length_m'),
            ({'lifting_type': 'stairs'}, 'stair_floor'),
            ({'lifting_type': 'stairs', 'stair_floor': '0'}, 'stair_floor'),
            ({'lifting_type': 'stairs', 'stair_floor': '1'}, 'stair_floor'),
            ({'lifting_type': 'stairs', 'stair_floor': '13'}, 'stair_floor'),
            ({'lifting_type': 'stairs', 'stair_floor': '5', 'stair_panel_count': ''}, 'stair_panel_count'),
            ({'lifting_type': 'stairs', 'stair_floor': '5', 'stair_panel_count': '0'}, 'stair_panel_count'),
            ({'lifting_type': 'stairs', 'stair_floor': '5', 'stair_panel_count': '5'}, 'stair_panel_count'),
            ({'lifting_type': 'stairs', 'stair_floor': '5', 'stair_panel_count': '1.5'}, 'stair_panel_count'),
            ({'delivery_distance_km': '-1'}, 'delivery_distance_km'),
        ):
            with self.subTest(data=data):
                form = CalculationForm(self.post_data(**data), settings=self.settings)
                self.assertFalse(form.is_valid())
                actual_field = f'service_quantity_{self.service_ids[self.quantity_aliases[error_field]]}' if error_field in self.quantity_aliases else error_field
                self.assertIn(actual_field, form.errors)

    def test_unselected_lengths_and_standard_floor_do_not_add_to_price(self):
        data = self.post_data(backlight_length_m='10', railing_length_m='10', stair_floor='10')
        form = CalculationForm(data, settings=self.settings)
        panels = PanelFormSet(data, prefix='panels')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(panels.is_valid(), panels.errors)
        result = calculate_price(form.calculation_input(panels))
        self.assertEqual(result.subtotal, Decimal('96.6'))

    def test_standard_lifting_ignores_invalid_hidden_stair_fields(self):
        data = self.post_data(stair_floor='не число', stair_panel_count='999')
        form = CalculationForm(data, settings=self.settings)
        panels = PanelFormSet(data, prefix='panels')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(panels.is_valid(), panels.errors)
        self.assertIsNone(form.calculation_input(panels).stair_floor)
        self.assertIsNone(form.calculation_input(panels).stair_panel_count)
        self.assertEqual(calculate_price(form.calculation_input(panels)).subtotal, Decimal('96.6'))

    def test_empty_additional_and_deleted_panels_are_excluded(self):
        data = self.post_data(**{
            'panels-TOTAL_FORMS': '3', 'panels-0-DELETE': 'on',
            'panels-2-width_mm': '', 'panels-2-height_mm': '',
        })
        form = CalculationForm(data, settings=self.settings)
        panels = PanelFormSet(data, prefix='panels')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(panels.is_valid(), panels.errors)
        result = calculate_price(form.calculation_input(panels))
        self.assertEqual(result.panel_count, 1)
        self.assertEqual(result.area_sqm, Decimal('0.2'))

    def test_missing_partial_and_nonpositive_panel_sizes_are_rejected(self):
        for width, height in (('', ''), ('1', ''), ('', '1'), ('0', '1'), ('-1', '1'), ('6001', '1'), ('1', '6001')):
            data = self.post_data(**{
                'panels-TOTAL_FORMS': '1', 'panels-0-width_mm': width, 'panels-0-height_mm': height,
            })
            with self.subTest(width=width, height=height):
                self.assertFalse(PanelFormSet(data, prefix='panels').is_valid())

    def test_forged_form_counts_and_missing_management_data_are_rejected(self):
        for count in ('0', '1000000'):
            with self.subTest(count=count):
                panels = PanelFormSet(self.post_data(**{'panels-TOTAL_FORMS': count}), prefix='panels')
                self.assertFalse(panels.is_valid())
                self.assertLessEqual(len(panels.forms), MAX_PANELS)
        self.assertFalse(PanelFormSet({}, prefix='panels').is_valid())

    def test_exact_number_output_preserves_fraction_without_trailing_zeros(self):
        with translation.override('ru'):
            self.assertEqual(exact_decimal(Decimal('100.000000')), '100')
            self.assertEqual(exact_decimal(Decimal('0.00000100')), '0,000001')
            self.assertEqual(exact_decimal(Decimal('204.425')), '204,425')


class CalculationAdminTests(CalculationFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = get_user_model().objects.create_superuser('calculation-owner', password=None)
        cls.staff = get_user_model().objects.create_user('calculation-staff', is_staff=True)
        cls.staff.user_permissions.set(Permission.objects.filter(content_type__app_label='calculator'))
        cls.url = reverse('admin:calculator_calculatortariffs_calculate')
        cls.card_url = reverse('admin:calculator_calculatortariffs_change', args=[CalculatorTariffs.CODE])

    def setUp(self):
        self.client.force_login(self.owner)

    def test_settings_card_links_to_form_and_get_does_not_calculate(self):
        self.assertContains(self.client.get(self.card_url), f'href="{self.url}"')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['result'])
        self.assertNotContains(response, 'add-calculation-panel')
        self.assertEqual(response.context['panels'].total_form_count(), 2)
        for index in (0, 1):
            self.assertContains(response, f'name="panels-{index}-width_mm"', count=1)
            self.assertContains(response, f'name="panels-{index}-height_mm"', count=1)
        self.assertContains(response, 'calculator/js/admin-calculation.js')
        self.assertContains(response, 'max="6000"')
        self.assertContains(response, 'csrfmiddlewaretoken')

    def test_auto_added_empty_panels_are_ignored_but_partial_panel_blocks_quote(self):
        data = self.post_data(**{
            'panels-TOTAL_FORMS': '3', 'panels-1-width_mm': '', 'panels-1-height_mm': '',
            'panels-2-width_mm': '', 'panels-2-height_mm': '',
        })
        response = self.client.post(self.url, data)
        self.assertEqual(response.context['panels'].total_form_count(), 3)
        result = response.context['result']
        self.assertEqual(result.panel_count, 1)
        self.assertEqual(result.area_sqm, Decimal('0.6'))
        self.assertEqual(result.subtotal, Decimal('72.45'))
        data['panels-2-width_mm'] = '1000'
        response = self.client.post(self.url, data)
        self.assertIsNone(response.context['result'])
        self.assertIn('height_mm', response.context['panels'].forms[2].errors)

    def test_stair_rows_are_hidden_for_standard_and_visible_for_stairs_including_errors(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'data-stair-field hidden', count=2)
        for data, hidden in (
            (self.post_data(), True),
            (self.post_data(lifting_type='stairs', stair_floor='5'), False),
            (self.post_data(lifting_type='stairs', stair_floor=''), False),
        ):
            with self.subTest(data=data):
                response = self.client.post(self.url, data)
                if hidden:
                    self.assertContains(response, 'data-stair-field hidden', count=2)
                else:
                    self.assertNotContains(response, 'data-stair-field hidden')
                    self.assertContains(response, 'data-stair-field', count=2)

    def test_post_returns_breakdown_using_saved_prices_without_writes(self):
        data = self.post_data(
            use_backlight='on', backlight_length_m='1.5', use_railing='on', railing_length_m='0.75',
            socket_blocks='2', hydrophobic='on', delivery_distance_km='12.5',
            lifting_type='stairs', stair_floor='5',
            panel_count='1000', people='1000', total='0', glass_price='0', delivery_price_per_km='0',
        )
        before = [model.objects.count() for model in (GlassType, DecorationType, CalculatorTariffs, LogEntry)]
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['result'].total, Decimal('201'))
        self.assertEqual(response.context['result'].panel_count, 2)
        self.assertContains(response, '200,425')
        self.assertContains(response, 'Включено в стоимость')
        self.assertContains(response, 'Округление вверх до целого')
        self.assertEqual(before, [model.objects.count() for model in (GlassType, DecorationType, CalculatorTariffs, LogEntry)])
        self.settings.refresh_from_db()
        self.assertEqual(self.settings.services.get(code='delivery').price_per_unit, Decimal('1.25'))

    def test_breakdown_uses_rounded_area_for_prices_and_displays_two_places(self):
        GlassType.objects.filter(pk=self.glass.pk).update(price_per_sqm=Decimal('300'))
        DecorationType.objects.filter(pk=self.decoration.pk).update(price_per_sqm=Decimal('60'))
        for width, height, area, subtotal, total in (
            ('1111', '1111', '1,23', '442.8', 443),
            ('1000', '1200', '1,20', '432', 432),
        ):
            with self.subTest(width=width, height=height):
                response = self.client.post(self.url, self.post_data(**{
                    'panels-TOTAL_FORMS': '1', 'panels-0-width_mm': width, 'panels-0-height_mm': height,
                }))
                self.assertEqual(response.context['result'].subtotal, Decimal(subtotal))
                self.assertEqual(response.context['result'].total, total)
                self.assertContains(response, f'{area} м²', count=3)
                self.assertNotContains(response, '1,234321')
                self.assertContains(response, 'Общая площадь округляется до двух знаков перед расчётом стоимости.')

    def test_standard_stair_cost_and_included_floors_are_explained(self):
        response = self.client.post(self.url, self.post_data(lifting_type='stairs', stair_floor='2'))
        self.assertEqual(response.context['result'].total, 147)
        self.assertContains(response, 'Подъём по лестнице — стандартная стоимость')
        self.assertContains(response, 'Стандартная стоимость действует по 4-й этаж включительно.')
        self.assertNotContains(response, 'Доплата за подъём выше')

    def test_editable_stair_count_controls_tier_in_rendered_breakdown(self):
        response = self.client.post(self.url, self.post_data(
            lifting_type='stairs', stair_floor='3', stair_panel_count='4',
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['result'].total, 159)
        self.assertEqual(response.context['result'].panel_count, 2)
        self.assertContains(response, 'Панелей для подъёма: 4')
        self.assertContains(response, 'Доплата за подъём выше 2-го этажа')
        self.assertContains(response, 'Коэффициент доплаты для выбранного количества панелей: 2.')

    def test_more_than_saved_stair_columns_does_not_produce_a_quote(self):
        response = self.client.post(self.url, self.post_data(
            lifting_type='stairs', stair_floor='3', stair_panel_count='5',
        ))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['result'])
        self.assertIn('stair_panel_count', response.context['form'].errors)

    def test_invalid_panel_and_option_errors_prevent_quote(self):
        for changes in ({'panels-0-height_mm': ''}, {'panels-0-width_mm': '6001'},
                        {'panels-0-height_mm': '6001'}, {'glass_type': '999999'}, {'lifting_type': 'stairs'}):
            with self.subTest(changes=changes):
                response = self.client.post(self.url, self.post_data(**changes))
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.context['result'])
                self.assertTrue(response.context['form'].errors or any(response.context['panels'].errors))

    def test_unconfigured_tariff_is_shown_as_form_error(self):
        CalculatorService.objects.filter(code='delivery').update(price_per_unit=None)
        response = self.client.post(self.url, self.post_data(delivery_distance_km='1'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['result'])
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertContains(response, 'Не задан корректный тариф')

    def test_hidden_fields_cannot_be_forced_by_post(self):
        self.settings.services.update(is_visible=False)
        self.settings.show_stair_lifting = False
        self.settings.show_glass_type = False
        self.settings.show_decoration_type = False
        self.settings.save()
        response = self.client.post(self.url, self.post_data(
            glass_type='99999', decoration_type='99999', use_backlight='on', backlight_length_m='100',
            socket_blocks='100', hydrophobic='on', delivery_distance_km='100', lifting_type='stairs', stair_floor='100',
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['result'].subtotal, Decimal('96.6'))
        self.assertEqual(list(response.context['form'].fields), [])

    def test_anonymous_staff_and_inactive_users_cannot_calculate(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 403)
        self.owner.is_active = False
        self.owner.save()
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(self.url, self.post_data()).status_code, 302)

    def test_csrf_and_http_methods_are_enforced(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post(self.url, self.post_data()).status_code, 403)
        self.assertEqual(self.client.put(self.url).status_code, 405)
        self.assertEqual(self.client.delete(self.url).status_code, 405)

    def test_material_names_are_escaped(self):
        GlassType.objects.filter(pk=self.glass.pk).update(name='<script>alert(1)</script>')
        response = self.client.post(self.url, self.post_data())
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_empty_material_lists_render_without_server_error(self):
        CalculatorTariffs.objects.update(default_glass_type=None, default_decoration_type=None)
        GlassType.objects.all().delete()
        DecorationType.objects.all().delete()
        self.assertEqual(self.client.get(self.url).status_code, 200)
        response = self.client.post(self.url, self.post_data())
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['result'])

    def test_custom_admin_namespace_works_for_form_and_settings_link(self):
        site = admin.AdminSite(name='calculator_test_admin')
        site.register(CalculatorSettings, CalculatorSettingsAdmin)
        site.register(CalculatorTariffs, CalculatorTariffsAdmin)
        site.register(GlassType, PricedOptionAdmin)
        site.register(DecorationType, PricedOptionAdmin)
        site.register(CalculatorService, CalculatorServiceAdmin)
        site.register(MeasurementUnit, MeasurementUnitAdmin)

        class TestUrls:
            urlpatterns = [path('other-admin/', site.urls)]

        with override_settings(ROOT_URLCONF=TestUrls):
            card_url = reverse('calculator_test_admin:calculator_calculatortariffs_change', args=[CalculatorTariffs.CODE])
            card = self.client.get(card_url)
            self.assertEqual(card.status_code, 200)
            self.assertContains(card, '/other-admin/calculator/calculatorservice/add/')
            self.assertContains(card, '/other-admin/calculator/measurementunit/')
            self.assertContains(card, f'/other-admin/calculator/calculatorservice/{self.service_ids["backlight"]}/change/')
            url = reverse('calculator_test_admin:calculator_calculatortariffs_calculate')
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, '/other-admin/calculator/calculatortariffs/skinali/change/')
            response = self.client.post(url, self.post_data())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['result'].total, 97)
            settings_url = reverse('calculator_test_admin:calculator_calculatorsettings_change', args=[CalculatorSettings.CODE])
            self.assertContains(self.client.get(settings_url), '/other-admin/calculator/calculatortariffs/')
            legacy_url = reverse('calculator_test_admin:calculator_calculatorsettings_calculate')
            response = self.client.post(legacy_url, self.post_data())
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['result'].total, 97)
