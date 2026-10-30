from decimal import Decimal
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.forms.models import model_to_dict
from django.test import TestCase
from django.urls import reverse

from .calculation import Panel, ServiceSelection, calculate_price
from .models import CalculatorService, CalculatorSettings
from .public import public_configuration
from .test_calculation import CalculationFixture
from .test_public import NODE, browser_results


class MinimumOrderTests(CalculationFixture, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = get_user_model().objects.create_superuser('minimum-order-owner', password=None)

    def setUp(self):
        self.general = CalculatorSettings.objects.get(pk=CalculatorSettings.CODE)
        self.general.is_enabled = True
        self.general.minimum_order_area_sqm = Decimal('1.25')
        self.general.save()
        self.glass.price_per_sqm = Decimal('100')
        self.glass.save()
        self.decoration.price_per_sqm = Decimal('0')
        self.decoration.save()

    def test_minimum_applies_to_rounded_total_without_changing_geometry(self):
        for panels, area, billable, expected in (
            ((Panel(1, 1),), '0', '1.25', '125'),
            ((Panel(800, 1000),), '0.8', '1.25', '125'),
            ((Panel(1250, 1000),), '1.25', '1.25', '125'),
            ((Panel(1254, 1000),), '1.25', '1.25', '125'),
            ((Panel(1255, 1000),), '1.26', '1.26', '126'),
            ((Panel(800, 1000), Panel(800, 1000)), '1.6', '1.6', '160'),
        ):
            with self.subTest(panels=panels):
                result = calculate_price(self.calculation_input(panels=panels))
                self.assertEqual(result.panels, panels)
                self.assertEqual(result.area_sqm, Decimal(area))
                self.assertEqual(result.billable_area_sqm, Decimal(billable))
                self.assertEqual(result.subtotal, Decimal(expected))
                self.assertEqual(result.total, Decimal(expected))
                self.assertEqual(result.lines[0].quantity, Decimal(billable))
                self.assertEqual(result.lines[1].quantity, Decimal(billable))

    def test_zero_disables_minimum(self):
        self.general.minimum_order_area_sqm = 0
        self.general.save()
        result = calculate_price(self.calculation_input())
        self.assertEqual(result.area_sqm, result.billable_area_sqm)
        self.assertEqual(result.subtotal, Decimal('80'))
        self.assertEqual(CalculatorSettings._meta.get_field('minimum_order_area_sqm').get_default(), Decimal('0'))

    def test_area_services_use_minimum_while_manual_fixed_and_stairs_keep_their_quantities(self):
        fixed = self.settings.services.get(code='backlight')
        fixed.fixed_price = True
        fixed.price_per_unit = Decimal('17.30')
        fixed.save()
        result = calculate_price(self.calculation_input(
            hydrophobic=True, delivery_distance_km=10, stair_floor=5,
            services=(ServiceSelection(fixed.pk, '999'),),
        ))
        lines = {line.code: line for line in result.lines}
        self.assertEqual(lines['hydrophobic'].quantity, Decimal('1.25'))
        self.assertEqual(lines['hydrophobic'].amount, Decimal('4.0625'))
        self.assertEqual(lines['delivery'].quantity, 10)
        self.assertEqual(lines['delivery'].amount, Decimal('12.5'))
        self.assertEqual(lines['backlight'].quantity, 1)
        self.assertEqual(lines['backlight'].amount, Decimal('17.30'))
        self.assertEqual(lines['stair_lifting'].amount + lines['stair_lifting_extra'].amount, 56)
        self.assertEqual(result.subtotal, Decimal('214.8625'))
        self.assertEqual(result.total, 215)

    def test_material_discounts_use_billable_area_in_both_modes(self):
        self.general.minimum_order_area_sqm = Decimal('2.50')
        self.general.save()
        for mode, expected in (('stepped', '225'), ('progressive', '235')):
            with self.subTest(mode=mode):
                self.set_material_discount(mode, (('2', '10'),))
                result = calculate_price(self.calculation_input())
                self.assertEqual(result.area_sqm, Decimal('0.8'))
                self.assertEqual(result.billable_area_sqm, Decimal('2.5'))
                self.assertEqual(result.subtotal, Decimal(expected))
                self.assertEqual(result.materials_discount, Decimal('250') - Decimal(expected))

    def test_order_discounts_apply_after_minimum_before_rounding_and_marketing(self):
        selections = []
        for name, percent in (('Фотоотзыв', '3'), ('Повторный заказ', '2')):
            service = CalculatorService.objects.create(
                settings=self.settings, name=name, calculation_type='order_discount',
                discount_percent=percent, is_visible=True,
            )
            selections.append(ServiceSelection(service.pk))
        self.general.marketing_discount_percent = Decimal('20')
        self.general.save()
        result = calculate_price(self.calculation_input(services=selections, delivery_distance_km=10))
        self.assertEqual(result.order_discount_percent, 5)
        self.assertEqual(result.order_discount, Decimal('6.875'))
        self.assertEqual(result.subtotal, Decimal('130.625'))
        self.assertEqual(result.total, 131)
        self.assertEqual(result.comparison_total, 164)

    def test_model_and_database_reject_negative_minimum_and_excess_precision(self):
        for value in ('-0.01', '1.234'):
            with self.subTest(value=value), self.assertRaises(ValidationError) as error:
                self.general.minimum_order_area_sqm = Decimal(value)
                self.general.save()
            self.assertIn('minimum_order_area_sqm', error.exception.message_dict)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CalculatorSettings.objects.update(minimum_order_area_sqm=Decimal('-0.01'))

    def test_admin_saves_fractional_minimum_and_keeps_discount_tables_under_mode(self):
        self.client.force_login(self.owner)
        url = reverse('admin:calculator_calculatorsettings_change', args=[CalculatorSettings.CODE])
        card = self.client.get(url)
        self.assertContains(card, 'Минимальный заказ')
        self.assertContains(card, 'Общая площадь панелей, м²')
        self.assertEqual(str(card.context['adminform'].form.fields['minimum_order_area_sqm'].widget.attrs['step']), '0.01')
        content = card.content.decode()
        self.assertLess(content.index('id_minimum_order_area_sqm'), content.index('id_material_discount_mode'))
        self.assertLess(content.index('id_material_discount_mode'), content.index('id_stepped_discounts-TOTAL_FORMS'))
        self.assertLess(content.index('id_progressive_discounts-TOTAL_FORMS'), content.index('id_marketing_discount_percent'))
        data = {
            **model_to_dict(self.general), 'minimum_order_area_sqm': '1.75',
            **{f'{mode}_discounts-{key}': '0' for mode in ('stepped', 'progressive') for key in ('TOTAL_FORMS', 'INITIAL_FORMS')},
        }
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.general.refresh_from_db()
        self.assertEqual(self.general.minimum_order_area_sqm, Decimal('1.75'))
        invalid = self.client.post(url, {**data, 'minimum_order_area_sqm': '-1'})
        self.assertIn('minimum_order_area_sqm', invalid.context['adminform'].form.errors)
        self.general.refresh_from_db()
        self.assertEqual(self.general.minimum_order_area_sqm, Decimal('1.75'))
        preview = self.client.post(reverse('admin:calculator_calculatortariffs_calculate'), self.post_data())
        self.assertContains(preview, 'Расчётная площадь с учётом минимального заказа:')
        self.assertEqual(preview.context['result'].total, 175)

    def test_intro_formats_minimum_without_trailing_zeroes_and_hides_disabled_minimum(self):
        for value, label in (('1.00', '1'), ('1.20', '1,2'), ('1.25', '1,25')):
            with self.subTest(value=value):
                self.general.minimum_order_area_sqm = Decimal(value)
                self.general.save()
                page = self.client.get(reverse('price'))
                self.assertContains(page, f'Минимальный заказ {label}м².')
                self.assertEqual(page.context['calculator_config']['minimum_order_area_sqm'], value)
        self.general.minimum_order_area_sqm = 0
        self.general.save()
        self.assertNotContains(self.client.get(reverse('price')), 'Минимальный заказ ')
        self.general.minimum_order_area_sqm = Decimal('1')
        self.general.is_enabled = False
        self.general.save()
        self.assertNotContains(self.client.get(reverse('price')), 'Минимальный заказ ')

    @skipUnless(NODE, 'Для проверки браузерной арифметики нужен Node.js.')
    def test_browser_matches_server_for_minimum_discounts_and_service_types(self):
        cases, expected = [], []
        discount_service = CalculatorService.objects.create(
            settings=self.settings, name='Фотоотзыв', calculation_type='order_discount',
            discount_percent='3', is_visible=True,
        )
        self.general.marketing_discount_percent = Decimal('10')
        for minimum in ('0', '0.01', '1.25', '2.50'):
            self.general.minimum_order_area_sqm = Decimal(minimum)
            self.general.save()
            for mode in ('none', 'stepped', 'progressive'):
                self.set_material_discount(mode, () if mode == 'none' else (('2', '10'), ('3', '20')))
                config = public_configuration(self.settings, self.general)
                for panels in ((Panel(1, 1),), (Panel(800, 1000),), (Panel(1255, 1000),),
                               (Panel(1500, 1000), Panel(1500, 1000))):
                    data = self.calculation_input(
                        panels=panels, hydrophobic=True, delivery_distance_km=10,
                        stair_floor=5, services=(ServiceSelection(discount_service.pk),),
                    )
                    expected.append(calculate_price(data))
                    cases.append({'config': config, 'input': {
                        'panels': [{'width': panel.width_mm, 'height': panel.height_mm} for panel in panels],
                        'glass_type': self.glass.pk, 'decoration_type': self.decoration.pk,
                        'services': [{'id': item.service_id, 'quantity': str(item.quantity)} for item in data.services],
                        'stairs': {'floor': 5, 'count': 2},
                    }})
        for index, (actual, server) in enumerate(zip(browser_results(cases), expected)):
            with self.subTest(index=index):
                self.assertNotIn('error', actual)
                for key, value in (
                    ('area', server.area_sqm), ('billable_area', server.billable_area_sqm),
                    ('total', server.total), ('subtotal', server.subtotal), ('comparison', server.comparison_total),
                    ('materials_discount', server.materials_discount), ('order_discount', server.order_discount),
                ):
                    self.assertEqual(Decimal(actual[key]), value)
